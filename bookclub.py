"""Pulls upcoming book due dates from the Bootlegger Book Club Tracker.

Expects that app to expose:
    GET {api_url}/api/upcoming-books?days=7
    Header: Authorization: Bearer <token>
    Response: {"books": [{"person": "...", "title": "...", "club": "...",
                          "due_date": "YYYY-MM-DD"}, ...]}

If `people` is set in config.yml, results are filtered to those names
(case-insensitive). Failures never take down the hub — they surface as a
small notice in the UI instead."""
import logging
import threading
import time

import requests

log = logging.getLogger("hub.bookclub")

CACHE_TTL_SECONDS = 600

_lock = threading.Lock()
_cache = {"fetched_at": 0.0, "books": None, "error": None}


def get_upcoming_books(bc_cfg):
    if not bc_cfg or not bc_cfg.get("api_url"):
        return [], None

    now = time.time()
    with _lock:
        if _cache["books"] is not None and now - _cache["fetched_at"] < CACHE_TTL_SECONDS:
            return _cache["books"], _cache["error"]

    books, error = [], None
    try:
        headers = {}
        if bc_cfg.get("api_token"):
            headers["Authorization"] = f"Bearer {bc_cfg['api_token']}"
        url = bc_cfg["api_url"].rstrip("/") + "/api/upcoming-books"
        resp = requests.get(url, params={"days": bc_cfg.get("days", 7)}, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        books = data.get("books", [])

        people = [p.strip().lower() for p in bc_cfg.get("people", []) if p.strip()]
        if people:
            books = [b for b in books if str(b.get("person", "")).strip().lower() in people]
        books.sort(key=lambda b: (b.get("due_date", ""), b.get("person", "")))
    except Exception as exc:
        log.warning("Book club fetch failed: %s", exc)
        error = str(exc)

    with _lock:
        _cache.update(fetched_at=now, books=books, error=error)
    return books, error
