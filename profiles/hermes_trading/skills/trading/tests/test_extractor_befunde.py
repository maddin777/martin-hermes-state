"""Extraktor-Befunde M13, M14, N5, N6 (Code-Pruefung 30.09.2026). Alle Aufrufe gemockt, keine Live-Pfade."""
import json
import sqlite3
from datetime import date

import pytest

from scripts import signal_extractor as extractor


# ── M13: Listen-Antworten und abgeschnittenes JSON ───────────────────────────────────────────────
def test_truncated_json_keeps_only_the_complete_company_objects():
    frag = '{"companies":[{"name":"Nike","context_snippet":"x","rough_sentiment":"bearish"},{"name":"Adi'
    parsed = extractor._try_parse(frag)
    assert [c["name"] for c in parsed["companies"]] == ["Nike"]
    merged = extractor.merge_scout_results([parsed])
    assert [c["name"] for c in merged["companies"]] == ["Nike"]


def test_truncated_json_without_any_complete_object_is_still_a_parse_error():
    with pytest.raises(json.JSONDecodeError):
        extractor._try_parse('{"companies":[{"name":"Ni')


def test_lone_company_object_is_not_mistaken_for_a_result():
    with pytest.raises(json.JSONDecodeError):
        extractor._try_parse('Text {"name": "Nike", "context_snippet": "x"} und kaputt {"companies": [')


def test_complete_wrapped_json_keeps_market_outlook_and_themes():
    raw = 'Hier: {"companies":[{"name":"Nike"}],"market_outlook":"bullish","key_themes":["Zinsen"]} Ende'
    parsed = extractor._try_parse(raw)
    assert parsed["market_outlook"] == "bullish" and parsed["key_themes"] == ["Zinsen"]


@pytest.mark.parametrize("scout_answer", [[], [{"name": "Nike", "rough_sentiment": "bullish"}], None, "text"])
def test_merge_scout_results_accepts_list_and_odd_answers(scout_answer):
    good = {"companies": [{"name": "Adidas", "context_snippet": "gut"}], "market_outlook": "neutral"}
    merged = extractor.merge_scout_results([good, scout_answer])
    names = [c["name"] for c in merged["companies"]]
    assert "Adidas" in names
    if isinstance(scout_answer, list) and scout_answer:
        assert "Nike" in names


def test_call_analyst_accepts_a_list_answer(monkeypatch):
    import roles.budget as budget
    from thematic.lib import llm_client
    monkeypatch.setattr(budget, "check_and_reserve", lambda *a, **k: True)
    monkeypatch.setattr(budget, "record_spend", lambda *a, **k: None)
    monkeypatch.setattr(llm_client, "get_model", lambda role: extractor.MODEL)
    monkeypatch.setattr(extractor, "_call_cascade",
                        lambda *a, **k: ([{"name": "Nike", "sentiment": "bullish", "strength": "strong"}], 1, 1))
    out = extractor.call_analyst(None, [{"name": "Nike", "snippets": ["x"], "rough_sentiment": "neutral"}],
                                 "kanal", "titel", "20260930")
    assert out[0]["name"] == "Nike" and out[0]["sentiment"] == "bullish"


# ── M14: Rolling-Filter ────────────────────────────────────────────────────────────────────────
def _sig(d, vid="v"):
    return {"companies": [], "source": {"date": d, "video_id": vid}}


def test_rolling_filter_handles_compact_dates_and_normalizes():
    today = date(2026, 9, 30)
    signals = [_sig("20260801", "old"), _sig("2026-09-20", "new"), _sig("20260925", "compact_new")]
    kept = extractor._rolling_filter(signals, 30, today=today)
    ids = {s["source"]["video_id"] for s in kept}
    assert ids == {"new", "compact_new"}
    assert {s["source"]["date"] for s in kept} == {"2026-09-20", "2026-09-25"}


def test_rolling_filter_keeps_entries_without_a_date_like_before():
    kept = extractor._rolling_filter([{"companies": []}, _sig("kaputt")], 30, today=date(2026, 9, 30))
    assert len(kept) == 2


# ── N6: Chunks und Fallback-Sentiment ───────────────────────────────────────────────────────────
def test_short_remainder_does_not_create_a_redundant_chunk():
    chunks = extractor._chunk_transcript("x" * 15500)
    assert [len(c) for c in chunks] == [15500]
    assert [len(c) for c in extractor._chunk_transcript("x" * 16000)] == [16000]


@pytest.mark.parametrize("n", [1, 999, 15000, 16000, 16001, 30000, 31000, 45500])
def test_chunks_cover_the_whole_text_and_none_is_contained_in_the_previous(n):
    text = "".join(f"{i:07d}" for i in range(n // 7 + 1))[:n]      # nicht periodisch
    chunks = extractor._chunk_transcript(text)
    covered = 0
    start = 0
    for c in chunks:
        assert text[start:start + len(c)] == c
        covered = max(covered, start + len(c))
        start += extractor.CHUNK_SIZE
    assert covered == n
    for prev, cur in zip(chunks, chunks[1:]):
        assert cur not in prev


@pytest.mark.parametrize(("raw", "expected"), [("Positive", "neutral"), ("BULLISH", "bullish"),
                                               (None, "neutral"), ("bearish", "bearish")])
def test_scout_fallback_normalizes_sentiment(raw, expected):
    out = extractor._scout_fallback([{"name": "X", "snippets": ["s"], "rough_sentiment": raw}])
    assert out[0]["sentiment"] == expected


# ── N5: Durability ────────────────────────────────────────────────────────────────────────────
def _make_videos_db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE videos (video_id TEXT PRIMARY KEY, channel TEXT, title TEXT, upload_date TEXT, "
                "transcript TEXT, status TEXT, error_count INTEGER DEFAULT 0, analyzed_at TEXT)")
    for i, vid in enumerate(["v1", "v2", "v3"]):
        con.execute("INSERT INTO videos (video_id, channel, title, upload_date, transcript, status) "
                    "VALUES (?,?,?,?,?, 'pending')", (vid, "K", f"T{i}", f"2026092{8 - i}", "text"))
    con.commit()
    return con


def test_abort_after_a_video_keeps_its_result_and_only_finished_videos_are_done(monkeypatch, tmp_path):
    calls = []

    def fake_analyze(transcript, channel, title, date_str, con=None):
        calls.append(title)
        if len(calls) == 2:
            raise SystemExit("Abbruch")          # Prozess stirbt mitten im Lauf (kein Exception-Handler greift)
        return {"companies": [{"name": "A"}], "market_outlook": "neutral", "key_themes": []}

    con = _make_videos_db()

    class Conn:                                   # main() ruft con.close() am Ende
        def __getattr__(self, name):
            return getattr(con, name)

        def close(self):
            pass

    monkeypatch.setattr(extractor, "db_connect", lambda: Conn())
    monkeypatch.setattr(extractor, "SIGNALS_PATH", str(tmp_path / "signals.json"))
    monkeypatch.setattr(extractor, "analyze", fake_analyze)
    with pytest.raises(SystemExit):
        extractor.main()
    saved = json.load(open(tmp_path / "signals.json", encoding="utf-8"))
    done = {r[0] for r in con.execute("SELECT video_id FROM videos WHERE status='done'")}
    saved_ids = {s["source"]["video_id"] for s in saved}
    assert done == saved_ids and len(done) == 1


def test_failed_json_write_marks_the_video_as_error_not_done(monkeypatch, tmp_path):
    con = _make_videos_db()

    class Conn:
        def __getattr__(self, name):
            return getattr(con, name)

        def close(self):
            pass

    monkeypatch.setattr(extractor, "db_connect", lambda: Conn())
    monkeypatch.setattr(extractor, "SIGNALS_PATH", str(tmp_path / "signals.json"))
    monkeypatch.setattr(extractor, "analyze",
                        lambda *a, **k: {"companies": [], "market_outlook": "neutral", "key_themes": []})
    monkeypatch.setattr(extractor.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("Platte voll")))
    with pytest.raises(OSError):        # der abschliessende Write scheitert ebenfalls -> Lauf bricht laut ab
        extractor.main()
    assert con.execute("SELECT COUNT(*) FROM videos WHERE status='done'").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM videos WHERE status='error'").fetchone()[0] >= 1
    assert not (tmp_path / "signals.json").exists()


def test_atomic_write_leaves_the_old_file_intact_on_failure(monkeypatch, tmp_path):
    target = tmp_path / "signals.json"
    target.write_text('[{"old": true}]', encoding="utf-8")
    monkeypatch.setattr(extractor.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        extractor._write_signals_atomic(str(target), [{"new": True}])
    assert json.loads(target.read_text(encoding="utf-8")) == [{"old": True}]


def test_rerun_after_json_write_but_before_status_does_not_duplicate_entries(monkeypatch, tmp_path):
    con = _make_videos_db()
    con.execute("DELETE FROM videos WHERE video_id != 'v1'")
    con.commit()
    (tmp_path / "signals.json").write_text(json.dumps(
        [{"companies": [{"name": "Alt"}], "source": {"video_id": "v1", "date": "2026-09-28"}}]), encoding="utf-8")

    class Conn:
        def __getattr__(self, name):
            return getattr(con, name)

        def close(self):
            pass

    monkeypatch.setattr(extractor, "db_connect", lambda: Conn())
    monkeypatch.setattr(extractor, "SIGNALS_PATH", str(tmp_path / "signals.json"))
    monkeypatch.setattr(extractor, "analyze",
                        lambda *a, **k: {"companies": [{"name": "Neu"}], "market_outlook": "neutral", "key_themes": []})
    extractor.main()
    saved = json.load(open(tmp_path / "signals.json", encoding="utf-8"))
    assert [s["source"]["video_id"] for s in saved] == ["v1"]
    assert saved[0]["companies"][0]["name"] == "Neu"
