#!/usr/bin/env python3
"""
Render-Engine für Hermes-Dataviz.

Baut aus EINER JSON-Config ein 9:16-Social-Video (TikTok/Reels).
Deterministisch, headless (Agg-Backend), Proxmox-tauglich.

Unterstützte chart_type-Werte:
  - "stacked_area"  : Zusammensetzung über Zeit (z.B. Benzinpreis-Bestandteile)
  - "line_race"     : mehrere Serien als Linien, Kamera fährt durch die Zeit
  - "bar_race"      : klassisches Balken-Rennen (Ranking ändert sich über Zeit)

Aufruf:
    python render_engine.py config.json
    python render_engine.py config.json --out mein_video.mp4

Die Config-Struktur ist in references/config_schema.md dokumentiert und wird
von DeepSeek befüllt. validate_config() prüft alles vor dem Rendern.
"""
import argparse
import json
import subprocess
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# ------------------------------------------------------------------ Theme
THEMES = {
    "dark": dict(bg="#0d1117", fg="#e6edf3", muted="#8b949e", grid="#21262d"),
    "light": dict(bg="#ffffff", fg="#1b1f24", muted="#6a737d", grid="#e1e4e8"),
}
# Kategorie-Farben für Meilensteine
CAT_COLOR = {"krise": "#e5534b", "krieg": "#e5534b", "geopolitik": "#e5534b",
             "politik": "#58a6ff", "markt": "#d29922", "sonstiges": "#8b949e"}
# Standard-Farbpalette für Serien/Komponenten (überschreibbar per Config)
PALETTE = ["#f0883e", "#3b5bdb", "#2f9e44", "#868e96", "#a371f7",
           "#e5534b", "#58a6ff", "#d29922", "#3fb950", "#db61a2",
           "#ec775c", "#6e7681", "#bf8700", "#1f6feb"]


# ------------------------------------------------------------------ Config
def validate_config(cfg: dict) -> list:
    """Gibt eine Liste von Fehlern zurück (leer = alles ok)."""
    errs = []
    req = ["chart_type", "data_file", "title"]
    for k in req:
        if k not in cfg:
            errs.append(f"Pflichtfeld fehlt: '{k}'")
    ct = cfg.get("chart_type")
    if ct not in ("stacked_area", "line_race", "bar_race"):
        errs.append(f"chart_type '{ct}' unbekannt "
                    f"(erlaubt: stacked_area, line_race, bar_race)")
    fps = cfg.get("fps", 30)
    if not (10 <= fps <= 60):
        errs.append(f"fps {fps} außerhalb 10–60")
    dur = cfg.get("duration_sec", 40)
    if not (5 <= dur <= 180):
        errs.append(f"duration_sec {dur} außerhalb 5–180")
    if cfg.get("theme", "dark") not in THEMES:
        errs.append(f"theme '{cfg.get('theme')}' unbekannt (dark|light)")
    return errs


def load_data(cfg):
    """Liest die Datendatei. Erwartet Wide-Format:
       erste Spalte = Serien-/Komponentenname, restliche Spalten = Zeitpunkte.
       'orientation':'long' schaltet auf Langformat mit
       date_col/series_col/value_col um."""
    path = cfg["data_file"]
    if cfg.get("orientation") == "long":
        df = pd.read_csv(path, sep=cfg.get("sep", ","))
        dc, sc, vc = cfg["date_col"], cfg["series_col"], cfg["value_col"]
        wide = df.pivot_table(index=sc, columns=dc, values=vc)
        series = wide.index.tolist()
        dates = pd.to_datetime(wide.columns)
        vals = wide.to_numpy(dtype=float)
    else:
        df = pd.read_csv(path, sep=cfg.get("sep", ","))
        series = df.iloc[:, 0].tolist()
        dates = pd.to_datetime(df.columns[1:])
        vals = df.iloc[:, 1:].to_numpy(dtype=float)
    # optionale Serien-Auswahl / Reihenfolge
    if cfg.get("series"):
        idx = [series.index(s) for s in cfg["series"] if s in series]
        series = [series[i] for i in idx]
        vals = vals[idx, :]
    order = np.argsort(dates)
    return series, dates[order], vals[:, order]


def load_milestones(cfg, dmin, dmax):
    mf = cfg.get("milestones_file")
    inline = cfg.get("milestones")
    if inline:
        m = pd.DataFrame(inline)
    elif mf:
        m = pd.read_csv(mf, sep=cfg.get("milestones_sep", ";"),
                        usecols=range(4),
                        names=["date", "end", "label", "category"],
                        header=0, engine="python", on_bad_lines="skip")
    else:
        return pd.DataFrame(columns=["date", "label", "category"])
    m = m.rename(columns={c: c.lower() for c in m.columns})
    m["date"] = pd.to_datetime(m["date"])
    m = m[(m["date"] >= dmin) & (m["date"] <= dmax)].copy()
    if cfg.get("milestone_labels"):  # nur bestimmte Labels zeigen
        keep = set(cfg["milestone_labels"])
        m = m[m["label"].isin(keep)]
    m["category"] = m.get("category", "sonstiges").fillna("sonstiges").str.lower()
    return m.reset_index(drop=True)


# ------------------------------------------------------------------ Setup
def sanity_check(series, vals, cfg):
    """Warnt bei verdächtigen Daten (typische Ursache: Währungs-/Einheitenfehler,
    z.B. HUF/CZK nicht umgerechnet). Blockt nicht, gibt Warnungen zurück."""
    warns = []
    finite = vals[np.isfinite(vals)]
    if finite.size == 0:
        return ["Alle Werte sind NaN/inf — Datei/Spalten prüfen."]
    med = np.nanmedian(finite)
    for i, s in enumerate(series):
        row = vals[i][np.isfinite(vals[i])]
        if row.size and med > 0 and (np.nanmedian(row) > med * 20 or
                                     np.nanmedian(row) < med / 20):
            warns.append(f"Serie '{s}' weicht stark ab "
                         f"(Median {np.nanmedian(row):.2f} vs. Gesamt {med:.2f}) "
                         f"— Einheit/Währung prüfen.")
    if cfg.get("expected_max") is not None and np.nanmax(finite) > cfg["expected_max"]:
        warns.append(f"Maximalwert {np.nanmax(finite):.2f} über expected_max "
                     f"{cfg['expected_max']} — Ausreißer oder falsche Einheit?")
    return warns


def setup_style(theme, font_path=None):
    t = THEMES[theme]
    if font_path:
        try:
            font_manager.fontManager.addfont(font_path)
            fam = font_manager.FontProperties(fname=font_path).get_name()
        except Exception as e:
            print(f"  Font '{font_path}' nicht ladbar: {e}", file=sys.stderr)
            fam = "DejaVu Sans"
    else:
        fam = "DejaVu Sans"
    plt.rcParams.update({
        "font.family": fam, "text.color": t["fg"],
        "axes.edgecolor": t["grid"], "xtick.color": t["muted"],
        "ytick.color": t["muted"],
    })
    return t, fam


def colors_for(series, cfg):
    override = cfg.get("colors", {})
    return [override.get(s, PALETTE[i % len(PALETTE)]) for i, s in enumerate(series)]


def year_ticks(dates):
    yrs = pd.date_range(dates.min(), dates.max(), freq="YS")
    return ([int(np.searchsorted(dates, y)) for y in yrs], [y.year for y in yrs])


def make_progress(N, fps, dur, hold_sec):
    fs = int(dur * fps)
    fh = int(hold_sec * fps)
    p = np.linspace(0, N - 1, fs)
    return np.concatenate([p, np.full(fh, N - 1)])


# ------------------------------------------------------------------ Renderers
def draw_stacked_area(ax, fig, series, dates, vals, cols, t, cfg, k, ms, tick):
    xk = np.arange(k)
    ax.stackplot(xk, vals[:, :k], colors=cols, edgecolor="none", zorder=2)
    _time_axis(ax, len(dates), vals, t, tick, cfg)
    total = vals.sum(axis=0)
    ci = min(k - 1, len(dates) - 1)
    _milestones(ax, ms, dates, ci, vals.sum(axis=0).max() * 1.18, t)
    _running_value(ax, ci, total[ci], total, len(dates), t, cfg)
    _legend(fig, series, cols, vals, ci, t, cfg, value_fmt="{:.0f} ct")


def draw_line_race(ax, fig, series, dates, vals, cols, t, cfg, k, ms, tick):
    xk = np.arange(k)
    ymax = np.nanmax(vals) * 1.15
    for i, s in enumerate(series):
        ax.plot(xk, vals[i, :k], color=cols[i], lw=2.4, zorder=3,
                solid_capstyle="round")
        if k > 0 and not np.isnan(vals[i, k - 1]):
            ax.scatter([k - 1], [vals[i, k - 1]], color=cols[i], s=28, zorder=4)
    ax.set_ylim(0, ymax)
    _time_axis(ax, len(dates), vals, t, tick, cfg, set_ylim=False)
    ci = min(k - 1, len(dates) - 1)
    _milestones(ax, ms, dates, ci, ymax, t)
    _legend(fig, series, cols, vals, ci, t, cfg,
            value_fmt=cfg.get("value_fmt", "{:.2f}"))


def draw_bar_race(ax, fig, series, dates, vals, cols, t, cfg, k, ms, tick):
    ci = min(k - 1, len(dates) - 1)
    cur = vals[:, ci].copy()
    order = np.argsort(cur)
    top_n = cfg.get("top_n", min(10, len(series)))
    order = order[-top_n:]
    ypos = np.arange(len(order))
    cmap = {s: cols[i] for i, s in enumerate(series)}
    ax.barh(ypos, cur[order], color=[cmap[series[o]] for o in order],
            zorder=2, height=0.78)
    ax.set_yticks(ypos)
    ax.set_yticklabels([series[o] for o in order], fontsize=15, color=t["fg"])
    ax.set_xlim(0, np.nanmax(vals) * 1.12)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    ax.grid(axis="x", color=t["grid"], lw=0.8, zorder=1)
    for yp, o in zip(ypos, order):
        ax.text(cur[o], yp, f"  {cur[o]:{cfg.get('bar_value_fmt','.1f')}}",
                va="center", ha="left", fontsize=14,
                color=t["fg"], fontweight="bold", zorder=3)
    fig.text(0.94, 0.24, pd.Timestamp(dates[ci]).strftime(cfg.get("date_fmt", "%b %Y")),
             fontsize=40, color=t["muted"], ha="right", fontweight="bold", alpha=0.5)


# ------------------------------------------------------------------ Shared helpers
def _time_axis(ax, N, vals, t, tick, cfg, set_ylim=True):
    ax.set_xlim(0, N - 1)
    if set_ylim:
        ax.set_ylim(0, vals.sum(axis=0).max() * 1.18)
    ax.set_xticks(tick[0])
    ax.set_xticklabels(tick[1], fontsize=13)
    ax.grid(axis="y", color=t["grid"], lw=0.8, zorder=1)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    if cfg.get("y_label"):
        ax.set_ylabel(cfg["y_label"], fontsize=13, color=t["muted"])


def _milestones(ax, ms, dates, ci, ytop, t):
    for _, r in ms.iterrows():
        mi = int(np.searchsorted(dates, r["date"]))
        if mi <= ci:
            col = CAT_COLOR.get(r["category"], t["muted"])
            ax.axvline(mi, color=col, lw=1.4, alpha=0.55, zorder=3)
            alpha = min(1.0, (ci - mi) / 8.0)
            ax.text(mi, ytop * 0.99, " " + str(r["label"]), rotation=90,
                    va="top", ha="left", fontsize=11.5, color=col,
                    alpha=alpha, zorder=4, fontweight="bold")


def _running_value(ax, ci, val, series_total, N, t, cfg):
    ha = "left" if ci < N * 0.82 else "right"
    div = cfg.get("running_divisor", 1)
    unit = cfg.get("running_unit", "")
    txt = f"{val/div:{cfg.get('running_fmt','.2f')}}{unit}"
    ax.annotate((" " if ha == "left" else "") + txt,
                xy=(ci, series_total[ci]), xytext=(0, 8),
                textcoords="offset points", va="bottom", ha=ha,
                fontsize=15, fontweight="bold", color=t["fg"], zorder=5)


def _legend(fig, series, cols, vals, ci, t, cfg, value_fmt="{:.0f}"):
    if not cfg.get("show_legend", True):
        return
    ybase = 0.145
    for i, s in enumerate(series):
        yy = ybase - i * 0.032
        if yy < 0.03:
            break
        fig.patches.append(plt.Rectangle((0.10, yy), 0.028, 0.020,
                           transform=fig.transFigure, color=cols[i], zorder=10))
        fig.text(0.145, yy + 0.004, s, fontsize=14, color=t["fg"], ha="left")
        v = vals[i, ci]
        if not np.isnan(v):
            fig.text(0.90, yy + 0.004, value_fmt.format(v),
                     fontsize=14, color=t["muted"], ha="right")


def _header(fig, cfg, t, cur_date):
    title = cfg["title"]
    accent = cfg.get("title_accent", "")
    fig.text(0.10, 0.94, title, fontsize=30, color=t["fg"],
             fontweight="bold", ha="left")
    yb = 0.895
    if accent:
        fig.text(0.10, yb, accent, fontsize=30,
                 color=cfg.get("accent_color", "#f0883e"),
                 fontweight="bold", ha="left")
        yb -= 0.04
    if cfg.get("subtitle"):
        fig.text(0.10, yb, cfg["subtitle"], fontsize=15, color=t["muted"], ha="left")
    fig.text(0.96, 0.94, pd.Timestamp(cur_date).strftime(cfg.get("date_fmt", "%b %Y")),
             fontsize=22, color=t["fg"], ha="right", fontweight="bold")
    if cfg.get("source"):
        fig.text(0.10, 0.02, cfg["source"], fontsize=10.5, color=t["muted"], ha="left")


DRAWERS = {"stacked_area": draw_stacked_area,
           "line_race": draw_line_race,
           "bar_race": draw_bar_race}


# ------------------------------------------------------------------ Main render
def render(cfg, out=None):
    errs = validate_config(cfg)
    if errs:
        raise ValueError("Config-Fehler:\n  - " + "\n  - ".join(errs))

    W, H, DPI = 1080, 1920, 100
    fps = cfg.get("fps", 30)
    dur = cfg.get("duration_sec", 40)
    hold = cfg.get("hold_end_sec", 2.0)
    out = out or cfg.get("out", "hermes_dataviz.mp4")
    theme = cfg.get("theme", "dark")
    t, _ = setup_style(theme, cfg.get("font_path"))

    series, dates, vals = load_data(cfg)
    for w in sanity_check(series, vals, cfg):
        print("  ⚠ WARNUNG:", w, file=sys.stderr)
    vals = np.nan_to_num(vals, nan=0.0) if cfg["chart_type"] != "line_race" else vals
    N = len(dates)
    cols = colors_for(series, cfg)
    ms = load_milestones(cfg, dates.min(), dates.max())
    tick = year_ticks(dates)
    progress = make_progress(N, fps, dur, hold)

    fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI)
    fig.patch.set_facecolor(t["bg"])
    axbox = [0.10, 0.19, 0.86, 0.62] if cfg["chart_type"] != "bar_race" \
        else [0.30, 0.30, 0.62, 0.50]
    ax = fig.add_axes(axbox)
    ax.set_facecolor(t["bg"])

    cmd = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgba",
           "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
           "-c:v", "libx264", "-crf", str(cfg.get("crf", 18)),
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    pipe = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    drawer = DRAWERS[cfg["chart_type"]]

    for fi, p in enumerate(progress):
        k = int(np.floor(p)) + 1
        ci = min(k - 1, N - 1)
        ax.clear()
        ax.set_facecolor(t["bg"])
        for tx in list(fig.texts):
            tx.remove()
        fig.patches.clear()
        drawer(ax, fig, series, dates, vals, cols, t, cfg, k, ms, tick)
        _header(fig, cfg, t, dates[ci])
        fig.canvas.draw()
        pipe.stdin.write(np.asarray(fig.canvas.buffer_rgba()).tobytes())
        if fi % 60 == 0:
            print(f"  frame {fi}/{len(progress)}", file=sys.stderr)

    pipe.stdin.close()
    pipe.wait()
    print("fertig:", out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    with open(a.config, encoding="utf-8") as f:
        render(json.load(f), a.out)