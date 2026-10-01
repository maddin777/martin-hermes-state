"""N3: JSON-Zustandsdateien werden atomar geschrieben (Config, Quellen, Makro, Optimizer)."""
import json
import os
import stat
import threading

import pytest

import utils
from scripts import signal_manager as sm

ROOT = os.path.dirname(os.path.dirname(__file__))


def test_writes_valid_json_and_leaves_no_temp_files(tmp_path):
    p = tmp_path / "cfg.json"
    utils.atomic_write_json(str(p), {"a": 1, "ä": "ü"}, indent=2, ensure_ascii=False)
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1, "ä": "ü"}
    assert [f.name for f in tmp_path.iterdir()] == ["cfg.json"]


def test_existing_file_permissions_are_kept_and_new_files_get_0644(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text("{}")
    os.chmod(p, 0o666)
    utils.atomic_write_json(str(p), {"x": 1})
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o666
    q = tmp_path / "new.json"
    utils.atomic_write_json(str(q), {"x": 1})
    assert stat.S_IMODE(os.stat(q).st_mode) == 0o644


def test_serialization_error_keeps_the_old_file_and_cleans_up(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text('{"old": true}')
    with pytest.raises(TypeError):
        utils.atomic_write_json(str(p), {"bad": object()})
    assert json.loads(p.read_text()) == {"old": True}
    assert [f.name for f in tmp_path.iterdir()] == ["cfg.json"]


def test_failing_replace_keeps_the_old_file(tmp_path, monkeypatch):
    p = tmp_path / "cfg.json"
    p.write_text('{"old": true}')
    monkeypatch.setattr(utils._os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        utils.atomic_write_json(str(p), {"new": True})
    assert json.loads(p.read_text()) == {"old": True}
    assert [f.name for f in tmp_path.iterdir()] == ["cfg.json"]


def test_a_parallel_reader_never_sees_a_partial_file(tmp_path):
    p = tmp_path / "cfg.json"
    utils.atomic_write_json(str(p), {"n": 0, "pad": "x" * 200_000})
    stop, errors = threading.Event(), []

    def reader():
        while not stop.is_set():
            try:
                json.loads(p.read_text())
            except Exception as e:                      # halbe Datei -> JSONDecodeError
                errors.append(e)

    t = threading.Thread(target=reader)
    t.start()
    for i in range(150):
        utils.atomic_write_json(str(p), {"n": i, "pad": "x" * 200_000})
    stop.set()
    t.join()
    assert errors == []


def test_save_config_uses_the_atomic_writer(tmp_path, monkeypatch):
    p = tmp_path / "data" / "strategy_config.json"
    monkeypatch.setattr(sm, "CONFIG_PATH", str(p))
    sm.save_config({"time_stop_trading_days": 5})
    assert json.loads(p.read_text()) == {"time_stop_trading_days": 5}


@pytest.mark.parametrize(("rel", "raw_pattern"), [
    ("scripts/signal_manager.py", 'open(CONFIG_PATH, "w")'),
    ("scripts/dashboard.py", 'open(SOURCES_PATH, "w"'),
    ("dashboard_thematic.py", 'open(CONFIG_PATH, "w")'),
    ("scripts/fundamental_data.py", 'open(macro_file, "w")'),
    ("scripts/strategy_optimizer.py", 'open(STRATEGY_CONFIG_PATH, "w")'),
    ("scripts/strategy_optimizer.py", 'open(SOURCES_PATH, "w")'),
    ("scripts/watchlist_manager.py", 'open(STRATEGY_CONFIG_PATH, "w")'),
    ("scripts/technical_validator.py", 'open(OUTPUT_PATH, "w"'),
    ("thematic/universe_manager.py", 'open(UNIVERSE_PATH, "w")'),
])
def test_state_files_are_no_longer_written_in_place(rel, raw_pattern):
    src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
    assert raw_pattern not in src and "atomic_write_json" in src
