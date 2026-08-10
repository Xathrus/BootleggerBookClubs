"""Loads and lightly validates config.yml. Cached with a short TTL so you can
edit the file without restarting the container."""
import time
import yaml

_cache = {"loaded_at": 0.0, "cfg": None, "path": None}
_TTL = 30  # seconds


def load_config(path: str) -> dict:
    now = time.time()
    if _cache["cfg"] is not None and _cache["path"] == path and now - _cache["loaded_at"] < _TTL:
        return _cache["cfg"]

    with open(path, "r") as f:
        cfg = yaml.safe_load(f) or {}

    cfg.setdefault("title", "Household Hub")
    cfg.setdefault("timezone", "America/Chicago")
    cfg.setdefault("calendars", [])

    for i, cal in enumerate(cfg["calendars"]):
        if "ics_url" not in cal:
            raise ValueError(f"Calendar entry {i + 1} is missing 'ics_url' in {path}")
        cal.setdefault("name", f"Calendar {i + 1}")
        cal.setdefault("color", "#4A6FA5")

    _cache.update(loaded_at=now, cfg=cfg, path=path)
    return cfg
