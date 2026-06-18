import json
import sys
from pathlib import Path

import pytest

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from presets import (
    SCHEMA_VERSION,
    _store_path,
    delete_preset,
    load_store,
    save_store,
    set_last_used,
    upsert_preset,
)


@pytest.fixture
def isolate_presets(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    # Also override Path.home() just in case APPDATA is empty or on non-Windows
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path

def test_load_store_not_exist(isolate_presets):
    store = load_store()
    assert store == {"version": SCHEMA_VERSION, "last_used": {}, "presets": {}}

def test_load_store_broken_json(isolate_presets):
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("invalid json {", encoding="utf-8")

    store = load_store()
    assert store == {"version": SCHEMA_VERSION, "last_used": {}, "presets": {}}

def test_load_store_not_dict(isolate_presets):
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("[]", encoding="utf-8")

    store = load_store()
    assert store == {"version": SCHEMA_VERSION, "last_used": {}, "presets": {}}

def test_upsert_and_save_roundtrip(isolate_presets):
    store = load_store()
    settings = {
        "margin": 0.25,
        "threshold": 4.5,
        "export": "premiere",
        "srt": True,
        "model": "base",
        "output_dir": "C:/some/path",
        "gpu": True,
        "ignored_key": "some_value" # should be filtered out
    }

    upsert_preset(store, "テストプリセット", settings)
    save_store(store)

    # Check that file exists and encoding is correct (no escape sequences)
    p = _store_path()
    assert p.exists()
    content = p.read_text(encoding="utf-8")
    assert "テストプリセット" in content

    data = json.loads(content)
    assert "テストプリセット" in data["presets"]

    loaded = load_store()
    assert "テストプリセット" in loaded["presets"]
    loaded_preset = loaded["presets"]["テストプリセット"]
    assert loaded_preset["margin"] == 0.25
    assert loaded_preset["threshold"] == 4.5
    assert loaded_preset["export"] == "premiere"
    assert loaded_preset["srt"] is True
    assert loaded_preset["model"] == "base"
    assert loaded_preset["output_dir"] == "C:/some/path"
    assert loaded_preset["gpu"] is True
    assert "ignored_key" not in loaded_preset

def test_delete_preset(isolate_presets):
    store = load_store()
    settings = {
        "margin": 0.2,
        "threshold": 4.0,
        "export": "resolve",
        "srt": False,
        "model": "tiny",
        "output_dir": "",
        "gpu": False
    }

    upsert_preset(store, "to_delete", settings)
    upsert_preset(store, "keep_me", settings)
    save_store(store)

    # delete non-existent name (no-op)
    delete_preset(store, "non_existent")

    # delete existent name
    delete_preset(store, "to_delete")
    save_store(store)

    loaded = load_store()
    assert "to_delete" not in loaded["presets"]
    assert "keep_me" in loaded["presets"]

def test_set_last_used(isolate_presets):
    store = load_store()
    settings = {
        "margin": 0.35,
        "threshold": 5.0,
        "export": "final-cut-pro",
        "srt": True,
        "model": "medium",
        "output_dir": "D:/out",
        "gpu": True
    }
    set_last_used(store, settings)
    save_store(store)

    loaded = load_store()
    assert loaded["last_used"] == settings
