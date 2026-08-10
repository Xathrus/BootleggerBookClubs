"""Fetches the secret iCal (.ics) feeds for each configured Google Calendar,
expands recurring events, and buckets everything into Today / Tomorrow /
This Week. Results are cached in memory for a few minutes so the phone app
feels instant and Google isn't polled on every tap."""
import logging
import threading
import time
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import requests
import icalendar
import recurring_ical_events

log = logging.getLogger("hub.feeds")

CACHE_TTL_SECONDS = 300  # re-fetch calendars at most every 5 minutes

_lock = threading.Lock()
_cache = {"fetched_at": 0.0, "payload": None}


def _fetch_ics(url: str) -> bytes:
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    return resp.content


def _fmt_time(dt: datetime) -> str:
    # 9:00 AM style, no leading zero, portable across platforms
    return dt.strftime("%I:%M %p").lstrip("0")


def _extract_events(cal_cfg: dict, raw: bytes, tz: ZoneInfo, window_start: date, window_end: date) -> list:
    cal = icalendar.Calendar.from_ical(raw)
    occurrences = recurring_ical_events.of(cal).between(window_start, window_end)
    events = []
    for ev in occurrences:
        summary = str(ev.get("SUMMARY", "(untitled)"))
        location = str(ev.get("LOCATION", "") or "")
        dtstart = ev.get("DTSTART").dt
        dtend_prop = ev.get("DTEND")
        dtend = dtend_prop.dt if dtend_prop is not None else None

        if isinstance(dtstart, datetime):
            start_local = dtstart.astimezone(tz) if dtstart.tzinfo else dtstart.replace(tzinfo=tz)
            end_local = None
            if isinstance(dtend, datetime):
                end_local = dtend.astimezone(tz) if dtend.tzinfo else dtend.replace(tzinfo=tz)
            time_label = _fmt_time(start_local)
            if end_local is not None and end_local != start_local:
                time_label += f" – {_fmt_time(end_local)}"
            events.append(
                {
                    "title": summary,
                    "location": location,
                    "calendar": cal_cfg["name"],
                    "color": cal_cfg["color"],
                    "all_day": False,
                    "date": start_local.date().isoformat(),
                    "sort_key": start_local.isoformat(),
                    "time_label": time_label,
                }
            )
        else:
            # All-day event: DTSTART is a date; DTEND is exclusive per RFC 5545.
            start_d = dtstart
            end_d_exclusive = dtend if isinstance(dtend, date) else start_d + timedelta(days=1)
            last_day = end_d_exclusive - timedelta(days=1)
            display_date = start_d
            today = datetime.now(tz).date()
            if start_d < today <= last_day:
                display_date = today  # ongoing multi-day event surfaces under Today
            label = "All day"
            if last_day > start_d:
                label = f"All day (through {last_day.strftime('%a %b')} {last_day.day})"
            events.append(
                {
                    "title": summary,
                    "location": location,
                    "calendar": cal_cfg["name"],
                    "color": cal_cfg["color"],
                    "all_day": True,
                    "date": display_date.isoformat(),
                    "sort_key": display_date.isoformat(),  # sorts before timed events that day
                    "time_label": label,
                }
            )
    return events


def _build_sections(events: list, tz: ZoneInfo) -> list:
    today = datetime.now(tz).date()
    tomorrow = today + timedelta(days=1)
    week_end = today + timedelta(days=7)

    def day_label(d: date) -> str:
        return f"{d.strftime('%A')} · {d.strftime('%b')} {d.day}"

    buckets = {
        "today": {"id": "today", "heading": "Today", "sub": day_label(today), "events": []},
        "tomorrow": {"id": "tomorrow", "heading": "Tomorrow", "sub": day_label(tomorrow), "events": []},
        "week": {
            "id": "week",
            "heading": "This week",
            "sub": f"{(tomorrow + timedelta(days=1)).strftime('%a %b')} {(tomorrow + timedelta(days=1)).day} – {week_end.strftime('%a %b')} {week_end.day}",
            "events": [],
        },
    }

    for ev in sorted(events, key=lambda e: e["sort_key"]):
        d = date.fromisoformat(ev["date"])
        if d == today:
            buckets["today"]["events"].append(ev)
        elif d == tomorrow:
            buckets["tomorrow"]["events"].append(ev)
        elif tomorrow < d <= week_end:
            ev = dict(ev)
            ev["day_label"] = f"{d.strftime('%a')} {d.day}"
            buckets["week"]["events"].append(ev)

    return [buckets["today"], buckets["tomorrow"], buckets["week"]]


_meals_lock = threading.Lock()
_meals_cache = {"fetched_at": 0.0, "payload": None}


def get_meals(meals_cfg, tz_name: str):
    """Parses the AnyList meal-plan ICS feed into one row per day for the next
    7 days (today included). Returns (days, error)."""
    if not meals_cfg or not meals_cfg.get("ics_url"):
        return [], None

    now = time.time()
    with _meals_lock:
        if _meals_cache["payload"] is not None and now - _meals_cache["fetched_at"] < CACHE_TTL_SECONDS:
            return _meals_cache["payload"]

    tz = ZoneInfo(tz_name)
    today = datetime.now(tz).date()
    window_end = today + timedelta(days=7)

    by_day = {}
    error = None
    try:
        raw = _fetch_ics(meals_cfg["ics_url"])
        cal = icalendar.Calendar.from_ical(raw)
        occurrences = recurring_ical_events.of(cal).between(today, window_end)
        for ev in occurrences:
            dtstart = ev.get("DTSTART").dt
            d = dtstart.astimezone(tz).date() if isinstance(dtstart, datetime) else dtstart
            if not (today <= d < window_end):
                continue
            title = str(ev.get("SUMMARY", "")).strip()
            if title:
                by_day.setdefault(d, []).append(title)
    except Exception as exc:
        log.warning("Failed to load meals feed: %s", exc)
        error = str(exc)

    days = []
    for i in range(7):
        d = today + timedelta(days=i)
        items = by_day.get(d, [])
        if i == 0:
            label = "Today"
        elif i == 1:
            label = "Tomorrow"
        else:
            label = f"{d.strftime('%a')} {d.day}"
        days.append({"date": d.isoformat(), "label": label, "items": items})

    payload = (days, error)
    with _meals_lock:
        _meals_cache.update(fetched_at=now, payload=payload)
    return payload


def get_agenda(calendars: list, tz_name: str) -> dict:
    now = time.time()
    with _lock:
        if _cache["payload"] is not None and now - _cache["fetched_at"] < CACHE_TTL_SECONDS:
            return _cache["payload"]

    tz = ZoneInfo(tz_name)
    today = datetime.now(tz).date()
    window_start = today - timedelta(days=14)  # catch ongoing multi-day events
    window_end = today + timedelta(days=8)

    events, errors = [], []
    for cal_cfg in calendars:
        try:
            raw = _fetch_ics(cal_cfg["ics_url"])
            events.extend(_extract_events(cal_cfg, raw, tz, window_start, window_end))
        except Exception as exc:  # keep the app up even if one feed is down
            log.warning("Failed to load calendar %s: %s", cal_cfg.get("name"), exc)
            errors.append({"calendar": cal_cfg.get("name", "?"), "error": str(exc)})

    payload = {
        "generated_at": datetime.now(tz).isoformat(),
        "sections": _build_sections(events, tz),
        "errors": errors,
    }
    with _lock:
        _cache.update(fetched_at=now, payload=payload)
    return payload
