"""Household Hub — a small self-hosted PWA that shows what's happening
today, tomorrow, and this week across the family's Google Calendars,
plus upcoming book club due dates from the Bootlegger Book Club Tracker.

Configuration lives in config.yml (see config.example.yml).
"""
import os
import logging
from flask import Flask, jsonify, render_template, send_from_directory

from hub_config import load_config
from feeds import get_agenda, get_meals
from bookclub import get_upcoming_books

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("hub")

app = Flask(__name__)
CONFIG_PATH = os.environ.get("HUB_CONFIG", "config.yml")


@app.route("/")
def index():
    cfg = load_config(CONFIG_PATH)
    return render_template("index.html", title=cfg.get("title", "Household Hub"))


@app.route("/api/agenda")
def api_agenda():
    cfg = load_config(CONFIG_PATH)
    agenda = get_agenda(cfg["calendars"], cfg.get("timezone", "America/Chicago"))
    books, book_error = get_upcoming_books(cfg.get("bookclub"))
    meals, meal_error = get_meals(cfg.get("meals"), cfg.get("timezone", "America/Chicago"))
    return jsonify(
        {
            "generated_at": agenda["generated_at"],
            "timezone": cfg.get("timezone", "America/Chicago"),
            "sections": agenda["sections"],
            "calendar_errors": agenda["errors"],
            "books": books,
            "book_error": book_error,
            "meals": meals,
            "meal_error": meal_error,
        }
    )


# --- PWA plumbing -----------------------------------------------------------

@app.route("/manifest.webmanifest")
def manifest():
    return send_from_directory("static", "manifest.webmanifest", mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
    # Served from the root scope so the service worker can control the whole app.
    return send_from_directory("static", "sw.js", mimetype="application/javascript")


@app.route("/healthz")
def healthz():
    return {"ok": True}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
