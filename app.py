"""
Bootlegger Book Club Tracker
A small self-hosted hub for tracking books across multiple book clubs.

- Public, read-only pages for everyone (home, club pages, calendar, /display signage)
- One admin login (ADMIN_PASSWORD env var) for creating clubs, adding books, setting dates
- SQLite database stored in ./data/bootlegger.db
- Book search powered by the Open Library API (free, no API key)
"""

import hmac
import os
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps

import requests
from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "bootlegger.db")

os.makedirs(DATA_DIR, exist_ok=True)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


def _load_secret_key() -> str:
    """Use SECRET_KEY from the environment, or generate one once and keep it
    in the data folder so logins survive restarts."""
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key
    key_file = os.path.join(DATA_DIR, "secret_key")
    if os.path.exists(key_file):
        with open(key_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(key_file, "w", encoding="utf-8") as f:
        f.write(key)
    return key


app = Flask(__name__)
app.config["SECRET_KEY"] = _load_secret_key()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

# Calendar accent colors cycled across clubs (index = club id % len)
CLUB_ACCENTS = ["#B08D3E", "#7A2E2A", "#3E5F4B", "#5B4A78", "#8C6239", "#2F5D6B"]

# --------------------------------------------------------------------------
# Database helpers
# --------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS clubs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS books (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    club_id      INTEGER NOT NULL REFERENCES clubs(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    author       TEXT NOT NULL DEFAULT '',
    cover_url    TEXT NOT NULL DEFAULT '',
    due_date     TEXT,                -- ISO date: finish reading by
    meeting_date TEXT,                -- ISO date: club discussion
    portion      TEXT NOT NULL DEFAULT '',  -- e.g. "Chapters 1-10"; empty = whole book
    status       TEXT NOT NULL DEFAULT 'upcoming'
                 CHECK (status IN ('current', 'upcoming', 'past')),
    queue_pos    INTEGER NOT NULL DEFAULT 0,
    finished_at  TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_books_club_status ON books (club_id, status, queue_pos);
"""


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


init_db()

# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------


def is_admin() -> bool:
    return bool(session.get("admin"))


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_admin():
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_globals():
    return {"is_admin": is_admin(), "today": date.today().isoformat()}


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        supplied = request.form.get("password", "")
        if not ADMIN_PASSWORD:
            flash("No admin password is configured. Set the ADMIN_PASSWORD "
                  "environment variable and restart the app.", "error")
        elif hmac.compare_digest(supplied, ADMIN_PASSWORD):
            session.permanent = True
            session["admin"] = True
            target = request.args.get("next") or url_for("home")
            if not target.startswith("/"):
                target = url_for("home")
            return redirect(target)
        else:
            flash("That password didn't match.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

# --------------------------------------------------------------------------
# Shared queries / formatting
# --------------------------------------------------------------------------


def club_accent(club_id: int) -> str:
    return CLUB_ACCENTS[club_id % len(CLUB_ACCENTS)]


def fetch_club_or_404(club_id: int) -> sqlite3.Row:
    club = get_db().execute("SELECT * FROM clubs WHERE id = ?", (club_id,)).fetchone()
    if club is None:
        abort(404)
    return club


def club_books(club_id: int):
    db = get_db()
    current = db.execute(
        "SELECT * FROM books WHERE club_id = ? AND status = 'current' "
        "ORDER BY queue_pos, id LIMIT 1", (club_id,)).fetchone()
    upcoming = db.execute(
        "SELECT * FROM books WHERE club_id = ? AND status = 'upcoming' "
        "ORDER BY queue_pos, id", (club_id,)).fetchall()
    past = db.execute(
        "SELECT * FROM books WHERE club_id = ? AND status = 'past' "
        "ORDER BY COALESCE(finished_at, created_at) DESC, id DESC",
        (club_id,)).fetchall()
    return current, upcoming, past


def pretty_date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%a, %b %-d, %Y")
    except ValueError:
        return iso


def short_date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%b %-d")
    except ValueError:
        return iso


app.jinja_env.filters["pretty_date"] = pretty_date
app.jinja_env.filters["short_date"] = short_date

# --------------------------------------------------------------------------
# Public pages
# --------------------------------------------------------------------------


@app.route("/")
def home():
    db = get_db()
    clubs = db.execute("SELECT * FROM clubs ORDER BY name").fetchall()
    cards = []
    for club in clubs:
        current, upcoming, _past = club_books(club["id"])
        cards.append({
            "club": club,
            "accent": club_accent(club["id"]),
            "current": current,
            "next_up": upcoming[0] if upcoming else None,
            "queue_len": len(upcoming),
        })
    return render_template("index.html", cards=cards)


@app.route("/club/<int:club_id>")
def club_detail(club_id: int):
    club = fetch_club_or_404(club_id)
    current, upcoming, past = club_books(club_id)
    return render_template("club.html", club=club, accent=club_accent(club_id),
                           current=current, upcoming=upcoming, past=past)


@app.route("/calendar")
def calendar_view():
    try:
        year = int(request.args.get("y", date.today().year))
        month = int(request.args.get("m", date.today().month))
        first = date(year, month, 1)
    except ValueError:
        first = date.today().replace(day=1)
        year, month = first.year, first.month

    prev_month = (first - timedelta(days=1)).replace(day=1)
    next_month = (first + timedelta(days=32)).replace(day=1)

    db = get_db()
    rows = db.execute(
        """SELECT b.*, c.name AS club_name FROM books b
           JOIN clubs c ON c.id = b.club_id
           WHERE b.status IN ('current', 'upcoming')
             AND (b.due_date IS NOT NULL OR b.meeting_date IS NOT NULL)""").fetchall()

    events_by_day: dict[str, list] = {}
    for b in rows:
        for kind, iso in (("due", b["due_date"]), ("meeting", b["meeting_date"])):
            if iso and iso[:7] == f"{year:04d}-{month:02d}":
                events_by_day.setdefault(iso, []).append({
                    "kind": kind,
                    "club": b["club_name"],
                    "club_id": b["club_id"],
                    "accent": club_accent(b["club_id"]),
                    "title": b["title"],
                })
    for day_events in events_by_day.values():
        day_events.sort(key=lambda e: (e["kind"], e["club"]))

    # Build week rows (Sunday-first grid)
    start_pad = (first.weekday() + 1) % 7  # Monday=0 ... Sunday=6 -> Sunday-first
    days_in_month = ((next_month - timedelta(days=1)).day)
    cells: list[dict | None] = [None] * start_pad
    for d in range(1, days_in_month + 1):
        iso = f"{year:04d}-{month:02d}-{d:02d}"
        cells.append({"day": d, "iso": iso, "events": events_by_day.get(iso, [])})
    while len(cells) % 7:
        cells.append(None)
    weeks = [cells[i:i + 7] for i in range(0, len(cells), 7)]

    month_events = sorted(
        ((iso, ev) for iso, evs in events_by_day.items() for ev in evs),
        key=lambda pair: pair[0])

    return render_template("calendar.html", weeks=weeks,
                           month_label=first.strftime("%B %Y"),
                           prev_y=prev_month.year, prev_m=prev_month.month,
                           next_y=next_month.year, next_m=next_month.month,
                           month_events=month_events)


def _signage_payload():
    db = get_db()
    clubs = db.execute("SELECT * FROM clubs ORDER BY name").fetchall()
    boards = []
    for club in clubs:
        current, upcoming, _past = club_books(club["id"])
        boards.append({
            "club": club,
            "accent": club_accent(club["id"]),
            "current": current,
            "next_up": upcoming[0] if upcoming else None,
        })
    return boards


@app.route("/display")
@app.route("/signage")
def signage():
    return render_template("signage.html", boards=_signage_payload(),
                           now=datetime.now().strftime("%A, %B %-d"))

# --------------------------------------------------------------------------
# Book search proxy (Open Library — free, no API key)
# --------------------------------------------------------------------------


@app.route("/api/book-search")
@admin_required
def book_search():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"results": []})
    try:
        resp = requests.get(
            "https://openlibrary.org/search.json",
            params={"q": q, "limit": 8,
                    "fields": "title,author_name,cover_i,first_publish_year"},
            timeout=8,
            headers={"User-Agent": "BootleggerBookClubTracker/1.0"})
        resp.raise_for_status()
        docs = resp.json().get("docs", [])
    except requests.RequestException:
        return jsonify({"error": "Book search is unreachable right now. "
                                 "You can still type the details in manually."}), 502
    results = []
    for d in docs:
        cover_i = d.get("cover_i")
        results.append({
            "title": d.get("title", ""),
            "author": ", ".join(d.get("author_name", [])[:2]),
            "year": d.get("first_publish_year"),
            "thumb": f"https://covers.openlibrary.org/b/id/{cover_i}-M.jpg" if cover_i else "",
            "cover": f"https://covers.openlibrary.org/b/id/{cover_i}-L.jpg" if cover_i else "",
        })
    return jsonify({"results": results})

# --------------------------------------------------------------------------
# Admin: clubs
# --------------------------------------------------------------------------


@app.route("/admin/club/new", methods=["GET", "POST"])
@admin_required
def club_new():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("The club needs a name.", "error")
        else:
            db = get_db()
            cur = db.execute(
                "INSERT INTO clubs (name, description) VALUES (?, ?)",
                (name, (request.form.get("description") or "").strip()))
            db.commit()
            flash(f"Club “{name}” created.", "ok")
            return redirect(url_for("club_detail", club_id=cur.lastrowid))
    return render_template("club_form.html", club=None)


@app.route("/admin/club/<int:club_id>/edit", methods=["GET", "POST"])
@admin_required
def club_edit(club_id: int):
    club = fetch_club_or_404(club_id)
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("The club needs a name.", "error")
        else:
            db = get_db()
            db.execute("UPDATE clubs SET name = ?, description = ? WHERE id = ?",
                       (name, (request.form.get("description") or "").strip(), club_id))
            db.commit()
            flash("Club updated.", "ok")
            return redirect(url_for("club_detail", club_id=club_id))
    return render_template("club_form.html", club=club)


@app.route("/admin/club/<int:club_id>/delete", methods=["POST"])
@admin_required
def club_delete(club_id: int):
    club = fetch_club_or_404(club_id)
    db = get_db()
    db.execute("DELETE FROM clubs WHERE id = ?", (club_id,))
    db.commit()
    flash(f"Club “{club['name']}” and its books were removed.", "ok")
    return redirect(url_for("home"))

# --------------------------------------------------------------------------
# Admin: books
# --------------------------------------------------------------------------


def _book_form_values():
    return {
        "title": (request.form.get("title") or "").strip(),
        "author": (request.form.get("author") or "").strip(),
        "cover_url": (request.form.get("cover_url") or "").strip(),
        "due_date": request.form.get("due_date") or None,
        "meeting_date": request.form.get("meeting_date") or None,
        "portion": (request.form.get("portion") or "").strip(),
        "status": request.form.get("status") or "upcoming",
    }


def _make_current(db, club_id: int, book_id: int):
    """Promote a book to current; any existing current book goes to the
    front of the upcoming queue."""
    db.execute(
        "UPDATE books SET status = 'upcoming', queue_pos = -1 "
        "WHERE club_id = ? AND status = 'current' AND id != ?",
        (club_id, book_id))
    db.execute("UPDATE books SET status = 'current', queue_pos = 0, finished_at = NULL "
               "WHERE id = ?", (book_id,))
    _renumber_queue(db, club_id)


def _renumber_queue(db, club_id: int):
    rows = db.execute(
        "SELECT id FROM books WHERE club_id = ? AND status = 'upcoming' "
        "ORDER BY queue_pos, id", (club_id,)).fetchall()
    for pos, row in enumerate(rows):
        db.execute("UPDATE books SET queue_pos = ? WHERE id = ?", (pos, row["id"]))


@app.route("/admin/club/<int:club_id>/book/new", methods=["GET", "POST"])
@admin_required
def book_new(club_id: int):
    club = fetch_club_or_404(club_id)
    if request.method == "POST":
        v = _book_form_values()
        if not v["title"]:
            flash("The book needs a title.", "error")
        else:
            db = get_db()
            next_pos = db.execute(
                "SELECT COALESCE(MAX(queue_pos), -1) + 1 AS p FROM books "
                "WHERE club_id = ? AND status = 'upcoming'", (club_id,)).fetchone()["p"]
            cur = db.execute(
                """INSERT INTO books (club_id, title, author, cover_url, due_date,
                                      meeting_date, portion, status, queue_pos)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'upcoming', ?)""",
                (club_id, v["title"], v["author"], v["cover_url"], v["due_date"],
                 v["meeting_date"], v["portion"], next_pos))
            if v["status"] == "current":
                _make_current(db, club_id, cur.lastrowid)
            db.commit()
            flash(f"Added “{v['title']}”.", "ok")
            return redirect(url_for("club_detail", club_id=club_id))
    return render_template("book_form.html", club=club, book=None)


@app.route("/admin/book/<int:book_id>/edit", methods=["GET", "POST"])
@admin_required
def book_edit(book_id: int):
    db = get_db()
    book = db.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if book is None:
        abort(404)
    club = fetch_club_or_404(book["club_id"])
    if request.method == "POST":
        v = _book_form_values()
        if not v["title"]:
            flash("The book needs a title.", "error")
        else:
            db.execute(
                """UPDATE books SET title = ?, author = ?, cover_url = ?,
                       due_date = ?, meeting_date = ?, portion = ? WHERE id = ?""",
                (v["title"], v["author"], v["cover_url"], v["due_date"],
                 v["meeting_date"], v["portion"], book_id))
            if v["status"] != book["status"]:
                if v["status"] == "current":
                    _make_current(db, club["id"], book_id)
                elif v["status"] == "past":
                    db.execute("UPDATE books SET status = 'past', "
                               "finished_at = datetime('now') WHERE id = ?", (book_id,))
                else:
                    next_pos = db.execute(
                        "SELECT COALESCE(MAX(queue_pos), -1) + 1 AS p FROM books "
                        "WHERE club_id = ? AND status = 'upcoming'",
                        (club["id"],)).fetchone()["p"]
                    db.execute("UPDATE books SET status = 'upcoming', queue_pos = ?, "
                               "finished_at = NULL WHERE id = ?", (next_pos, book_id))
                _renumber_queue(db, club["id"])
            db.commit()
            flash("Book updated.", "ok")
            return redirect(url_for("club_detail", club_id=club["id"]))
    return render_template("book_form.html", club=club, book=book)


@app.route("/admin/book/<int:book_id>/action", methods=["POST"])
@admin_required
def book_action(book_id: int):
    db = get_db()
    book = db.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if book is None:
        abort(404)
    club_id = book["club_id"]
    action = request.form.get("action")

    if action == "finish":
        db.execute("UPDATE books SET status = 'past', finished_at = datetime('now') "
                   "WHERE id = ?", (book_id,))
        # Promote the next book in the queue, if any
        nxt = db.execute(
            "SELECT id FROM books WHERE club_id = ? AND status = 'upcoming' "
            "ORDER BY queue_pos, id LIMIT 1", (club_id,)).fetchone()
        if nxt:
            _make_current(db, club_id, nxt["id"])
        flash(f"“{book['title']}” moved to history.", "ok")
    elif action == "make_current":
        _make_current(db, club_id, book_id)
        flash(f"“{book['title']}” is now the current book.", "ok")
    elif action in ("up", "down") and book["status"] == "upcoming":
        delta = -1 if action == "up" else 1
        _renumber_queue(db, club_id)
        book = db.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        swap = db.execute(
            "SELECT id, queue_pos FROM books WHERE club_id = ? AND status = 'upcoming' "
            "AND queue_pos = ?", (club_id, book["queue_pos"] + delta)).fetchone()
        if swap:
            db.execute("UPDATE books SET queue_pos = ? WHERE id = ?",
                       (swap["queue_pos"], book_id))
            db.execute("UPDATE books SET queue_pos = ? WHERE id = ?",
                       (book["queue_pos"], swap["id"]))
    elif action == "requeue" and book["status"] == "past":
        next_pos = db.execute(
            "SELECT COALESCE(MAX(queue_pos), -1) + 1 AS p FROM books "
            "WHERE club_id = ? AND status = 'upcoming'", (club_id,)).fetchone()["p"]
        db.execute("UPDATE books SET status = 'upcoming', queue_pos = ?, "
                   "finished_at = NULL WHERE id = ?", (next_pos, book_id))
        flash(f"“{book['title']}” is back in the queue.", "ok")
    elif action == "delete":
        db.execute("DELETE FROM books WHERE id = ?", (book_id,))
        flash(f"“{book['title']}” removed.", "ok")

    db.commit()
    return redirect(request.form.get("back") or url_for("club_detail", club_id=club_id))

# --------------------------------------------------------------------------
# PWA service worker (served from root scope)
# --------------------------------------------------------------------------


@app.route("/sw.js")
def service_worker():
    resp = app.send_static_file("sw.js")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.errorhandler(404)
def not_found(_e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
