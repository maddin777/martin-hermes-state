#!/usr/bin/env python3
"""
dq_alarm.py — Signal-Degradierungs-Alarm für die Watchlist.

Zählt (a) .L-Microcaps OHNE Tech-Score in der Conviction-Watchlist (≥76%
oder gekauft) — also die Einträge, die der UK-Liquidity-Gate blockt — und
(b) Einträge in watching/bought, deren EINZIGE Quelle deaktiviert ist
(enabled=0) — die Deaktivierungs-Verifikation (seit 24.08.2026).

Verhalten (Watchdog-Pattern):
- Count < SCHWELLE  → SILENT (kein Output, kein Alert)
- Count >= SCHWELLE → Telegram-Alert im Trading-Channel

Läuft als no_agent Hermes-Cron (Mo–Fr nach dem Export, 22:40).
Cron-ID: 37d505cbc47b

SCHWELLE: 10 (Insight 16.08.: DQ explodierte 1→8→14 in 3 Nächten —
           >10 ist eine klare Signal-Degradierung und muss alarmiert werden).

Deaktivierungs-Verifikation (Teil b, seit 24.08.2026):
- Wertet aus `source_registry` die Menge deaktivierter Quellen aus (enabled=0).
- Wertet aus `watchlist.channels` (JSON-Array) aus, ob ein Eintrag NUR aus
  deaktivierten Quellen besteht. Solche Einträge (z.B. .L-Microcaps, die zu
  100% aus rss:share talk stammen) sind komplett tot und beweisen, dass eine
  Deaktivierung nicht gegriffen hat → Meldung + Alarm.
- Ein Eintrag, der AUCH aus aktiven Quellen gespeist wird (z.B. AAPL mit
  mehreren aktiven YouTube-Kanälen), zählt NICHT — nur exklusiv-deaktiviert.
"""
import json
import os
import sys

sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401
from datetime import datetime
from config import db_connect

# Schwellenwert: Anzahl DQ-Microcaps (>=0.76 Conviction oder bought) bevor Alarm.
SCHWELLE = 10
# State-File: speichert letzten Count, um NUR Regressionen zu melden
# (kein Daily-Spam bei stabilem hohen Niveau). Liegt im Trading-data/-Ordner.
TRADING_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(TRADING_ROOT, "data", "dq_alarm_state.txt")


def count_dq_microcaps(con):
    """Zählt .L-Einträge ohne tech_score, die als Signale zählen würden."""
    row = con.execute("""
        SELECT COUNT(*)
        FROM watchlist w
        WHERE w.status IN ('watching','bought')
          AND w.ticker LIKE '%.L'
          AND w.ticker IS NOT NULL
          AND w.tech_score IS NULL
          AND (w.conviction_score >= 0.76 OR w.status = 'bought')
    """).fetchone()
    return row[0] if row else 0


def _deactivated_channels(con):
    """Menge der deaktivierten Quellen (enabled=0) als lowercase-Set.

    channels-Strings sind entweder "rss:<lower display_name>" (für RSS-Quellen)
    oder reine Channel-Namen (YouTube etc.). Wir normalisieren beides:
    strip "rss:"-Präfix + lowercase + Vergleich gegen die enabled=0-Menge.
    """
    rows = con.execute(
        "SELECT display_name FROM source_registry WHERE enabled=0"
    ).fetchall()
    return {"rss:" + str(r[0]).strip().lower() for r in rows} | {
        str(r[0]).strip().lower() for r in rows
    }


def _parse_channels(channels_val):
    """Parsed watchlist.channels (JSON-Array string) zu einer Liste."""
    if not channels_val:
        return []
    try:
        return json.loads(channels_val)
    except Exception:
        return []


def count_deactivated_only(con):
    """Zählt .L-Microcaps in watching/bought, deren EINZIGE Quelle deaktiviert ist.

    Das ist die DQ-Restbestand-Verifikation: Wenn ein `.L`-Ticker (mit ODER
    ohne tech_score) zu 100% aus einer deaktivierten Quelle stammt (z.B.
    rss:share talk), ist er komplett tot. Wenn er nach der Deaktivierung
    stehen bleibt (statt gecleant zu werden), ist die Deaktivierung nicht
    gegriffen.

    Bewusst NUR auf `.L`-Ticker begrenzt — das ist die DQ-Flut-Quelle. Ein
    Large-Cap wie STLA (aus `patrick boyle`) oder AEM (aus `urban jäkle`)
    zählt NICHT, selbst wenn sein einziger Kanal inzwischen deaktiviert ist:
    solch ein Eintrag ist eine historische Bestands-Position, keine signifikante
    Signal-Degradierung, und würde sonst falsch-alarmen.
    """
    deactivated = _deactivated_channels(con)
    if not deactivated:
        return 0, []
    rows = con.execute(
        "SELECT ticker, name, channels, status FROM watchlist "
        "WHERE status IN ('watching','bought') AND ticker LIKE '%.L'"
    ).fetchall()
    count = 0
    subjects = []
    for r in rows:
        chans = [c.strip() for c in _parse_channels(r["channels"]) if c.strip()]
        if not chans:
            continue
        # Nur wenn der Eintrag ZU 100% aus deaktivierten Quellen besteht.
        if all(c in deactivated for c in chans):
            count += 1
            subjects.append(r["ticker"])
    return count, subjects[:12]


def send_telegram_alert(msg: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass


def _read_last() -> int:
    try:
        with open(STATE_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return -1


def _write_last(val: int) -> None:
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            f.write(str(val))
    except Exception:
        pass


FEEDER_STATE_FILE = os.path.join(os.path.dirname(STATE_FILE), "dq_feeder_alarm_state.txt")
FEEDER_ALERT_EVERY_DAYS = 7


def _feeder_alert_due(signature: str) -> bool:
    """True, wenn zu DIESEM Befund seit FEEDER_ALERT_EVERY_DAYS nichts ging.

    Eine tote Tabelle bleibt tot — ohne Sperre wuerde der Alarm jeden Tag
    erneut feuern und sich damit selbst abstumpfen. Aendert sich der Befund
    (andere Tabelle betroffen), wird sofort wieder gemeldet.
    """
    try:
        with open(FEEDER_STATE_FILE) as fh:
            last_sig, last_day = fh.read().strip().split("|", 1)
    except Exception:
        last_sig, last_day = "", ""
    if last_sig == signature and last_day:
        try:
            age = (datetime.now().date()
                   - datetime.strptime(last_day, "%Y-%m-%d").date()).days
            if age < FEEDER_ALERT_EVERY_DAYS:
                return False
        except Exception:
            pass
    try:
        os.makedirs(os.path.dirname(FEEDER_STATE_FILE), exist_ok=True)
        with open(FEEDER_STATE_FILE, "w") as fh:
            fh.write(f"{signature}|{datetime.now().strftime('%Y-%m-%d')}")
    except Exception:
        pass
    return True


def stale_feeder_tables(con, max_age_days=7):
    """Meldet Tabellen, die eine Pipeline-Stufe befuellen SOLLTE, aber nicht mehr tut.

    Anlass (18.09.2026): factor_scores wurde zuletzt am 13.07.2026 beschrieben.
    Geschrieben wird sie von thematic/factor_ranker.py — das Skript existiert,
    aber die thematic/-Pipeline hat seit dem 13.07. keinen Cron-Eintrag mehr
    (KORREKTUR 19.09., vorher stand hier faelschlich "existiert nicht"). Die
    Hypothese h1_momentum in shadow_selection liefert deshalb seit ueber zwei
    Monaten 0 Kandidaten. Im Bericht sah das aus wie "noch keine Daten", also wie
    ein Reifeproblem statt wie ein Defekt. Ein stiller Ausfall ueber Monate ist
    genau die Sorte Fehler, die ein Alarm abfangen muss.
    """
    # (Tabelle, Zeitstempel-Spalte, Label) — die Spalte heisst nicht ueberall
    # gleich: factor_scores hat `date`, pead_cache `fetched_at`.
    FEEDERS = (
        ("factor_scores", "date",       "Faktor-Ranking (h1_momentum)"),
        ("pead_cache",    "fetched_at", "PEAD-Cache (h2_pead)"),
    )
    stale = []
    for table, col, label in FEEDERS:
        try:
            row = con.execute(f"SELECT MAX({col}) d FROM {table}").fetchone()
        except Exception as exc:
            # Fehlende Tabelle/Spalte ist ein Konfigurationsfehler, kein toter
            # Feeder — laut protokollieren, aber keinen Alarm ausloesen.
            print(f"  ⚠ dq_alarm: {table}.{col} nicht lesbar ({exc})", flush=True)
            continue
        last = row["d"] if row else None
        if not last:
            stale.append((table, label, None))
            continue
        try:
            age = (datetime.now().date()
                   - datetime.strptime(str(last)[:10], "%Y-%m-%d").date()).days
        except Exception:
            print(f"  ⚠ dq_alarm: {table}.{col} unlesbares Datum ({last!r})",
                  flush=True)
            continue
        if age > max_age_days:
            stale.append((table, label, (str(last)[:10], age)))
    return stale


def main():
    con = db_connect()
    dq = count_dq_microcaps(con)
    deact_count, deact_subj = count_deactivated_only(con)
    stale = stale_feeder_tables(con)
    con.close()
    last = _read_last()
    _write_last(dq)

    combined = dq + deact_count
    print(
        f"DQ-Microcap-Check: {dq} (Schwelle {SCHWELLE}, vorher {last})\n"
        f"Deaktivierungs-Check: {deact_count} exklusiv-deaktivierte Einträge",
        flush=True,
    )
    if deact_count:
        print(f"  ↳ aus deaktivierten Quellen: {', '.join(deact_subj)}", flush=True)

    # Alarm bei REGRESSION auf der kombinierten Kennzahl:
    if stale:
        for table, label, info in stale:
            detail = f"leer" if info is None else f"Stand {info[0]}, {info[1]}d alt"
            print(f"⛔ Feeder-Tabelle tot: {table} ({label}) — {detail}", flush=True)
        lines = "".join(
            f"• <code>{t}</code> ({lbl}): "
            f"{'leer' if i is None else f'Stand {i[0]}, {i[1]}d alt'}" + "\n"
            for t, lbl, i in stale)
        signature = ",".join(sorted(t for t, _, _ in stale))
        if not _feeder_alert_due(signature):
            print("  → Feeder-Alarm unterdrueckt (bereits gemeldet, "
                  f"Wiederholung alle {FEEDER_ALERT_EVERY_DAYS}d)", flush=True)
        else:
            send_telegram_alert(
                "⛔ <b>Feeder-Tabelle wird nicht mehr befuellt</b>" + "\n" + "\n"
                + lines + "\n"
                + "<i>Die daran haengende Hypothese sammelt NICHT still weiter — "
                "sie liefert 0 Kandidaten. Quelle reparieren oder Hypothese "
                "streichen.</i>")

    regression = (combined >= SCHWELLE) and (last < SCHWELLE or combined > last)
    if not regression:
        print("→ silent (keine Regression)", flush=True)
        return

    msg = (
        "🚨 <b>Signal-Degradierung: Watchlist wächst als Rauschen</b>\n"
        f"DQ-Microcaps (`.L` ohne Tech-Score, ≥76% Conviction): <b>{dq}</b>\n"
        f"Exklusiv-deaktivierte Einträge (erledigte Quellen bleiben stehen): "
        f"<b>{deact_count}</b>\n\n"
    )
    if dq:
        msg += (
            "`.L`-Microcaps spülen AIM/Nano-Caps in die Conviction-Watchlist. "
            "Sie verzerren Sektor-Verteilung, SHORT-Anteil und das "
            "max-3-pro-Sektor-Constraint.\n"
        )
    if deact_count:
        msg += (
            f"⚠️ <b>Deaktivierung nicht gegriffen:</b> Diese Einträge stammen "
            f"ausschließlich aus deaktivierten Quellen und bleiben trotzdem in "
            f"watching/bought:\n{', '.join(deact_subj)}\n"
        )
    msg += (
        "<i>Export (22:15) lagert `.L`-Microcaps in den DQ-Block aus — hier "
        "wird nur die Regression gemeldet.</i>"
    )
    send_telegram_alert(msg)
    print(f"🚨 DQ-Regressions-Alarm gesendet (kombiniert {combined} >= {SCHWELLE})", flush=True)


if __name__ == "__main__":
    main()
