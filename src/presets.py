# src/presets.py
import json
import os
from pathlib import Path

SCHEMA_VERSION = 1
SETTING_KEYS = ("margin", "threshold", "export", "srt", "model", "output_dir", "gpu")

def _store_path() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) / "SnipSync" if base else Path.home() / ".snipsync"
    return (root / "presets.json").resolve()

def load_store() -> dict:
    """Load settings store. Returns default structure if not found or corrupted."""
    p = _store_path()
    default_structure = {"version": SCHEMA_VERSION, "last_used": {}, "presets": {}}
    if not p.exists():
        return default_structure
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return default_structure
        data.setdefault("version", SCHEMA_VERSION)
        data.setdefault("last_used", {})
        data.setdefault("presets", {})
        return data
    except Exception:
        return default_structure

def save_store(store: dict) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")

def upsert_preset(store: dict, name: str, settings: dict) -> None:
    store.setdefault("presets", {})
    filtered = {k: v for k, v in settings.items() if k in SETTING_KEYS}
    store["presets"][name] = filtered

def delete_preset(store: dict, name: str) -> None:
    store.setdefault("presets", {})
    store["presets"].pop(name, None)

def set_last_used(store: dict, settings: dict) -> None:
    filtered = {k: v for k, v in settings.items() if k in SETTING_KEYS}
    store["last_used"] = filtered
