"""
Bootlegger Book Club Tracker
A small self-hosted hub for tracking books across multiple book clubs.

- Public, read-only pages for everyone (home, club pages, calendar, /display signage)
- One admin login (ADMIN_PASSWORD env var) for clubs, books, people, dates
- SQLite database stored in ./data/bootlegger.db (migrations run automatically)
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
                   request, send_from_directory, session, url_for)
from PIL import Image, UnidentifiedImageError

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "bootlegger.db")
COVERS_DIR = os.path.join(DATA_DIR, "covers")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(COVERS_DIR, exist_ok=True)

# Uploaded covers are resized to fit this box (2:3 portrait, the standard
# book-cover shape) — large enough for the signage view on a TV, small on disk.
COVER_MAX = (600, 900)

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
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024  # 15 MB upload ceiling

# Calendar accent colors cycled across clubs (index = club id % len)
CLUB_ACCENTS = ["#B08D3E", "#7A2E2A", "#3E5F4B", "#5B4A78", "#8C6239", "#2F5D6B"]

# --------------------------------------------------------------------------
# Database helpers + migrations
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
    meeting_date TEXT,                -- ISO date; NULL when book is split into sections
    portion      TEXT NOT NULL DEFAULT '',  -- e.g. "Chapters 1-10"; empty = whole book
    status       TEXT NOT NULL DEFAULT 'upcoming'
                 CHECK (status IN ('current', 'upcoming', 'past')),
    queue_pos    INTEGER NOT NULL DEFAULT 0,
    finished_at  TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_books_club_status ON books (club_id, status, queue_pos);

-- People who belong to clubs (names only — no accounts, no logins)
CREATE TABLE IF NOT EXISTS people (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS club_people (
    club_id   INTEGER NOT NULL REFERENCES clubs(id) ON DELETE CASCADE,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    PRIMARY KEY (club_id, person_id)
);

-- For books read across several meetings: one row per section
CREATE TABLE IF NOT EXISTS book_sections (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id   INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    meet_date TEXT NOT NULL,          -- ISO date for this section's meeting
    portion   TEXT NOT NULL DEFAULT '',  -- e.g. "Chapters 1-5"
    position  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sections_book ON book_sections (book_id, meet_date);
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

    # Migration: earlier versions had a separate due_date on books.
    # Meeting date is now the only date; keep whichever value exists.
    cols = [r[1] for r in conn.execute("PRAGMA table_info(books)").fetchall()]
    if "due_date" in cols:
        conn.execute("UPDATE books SET meeting_date = COALESCE(meeting_date, due_date)")
        try:
            conn.execute("ALTER TABLE books DROP COLUMN due_date")
        except sqlite3.OperationalError:
            pass  # very old SQLite: the column simply goes unused

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


def book_sections_for(book_id: int) -> list[dict]:
    rows = get_db().execute(
        "SELECT * FROM book_sections WHERE book_id = ? ORDER BY meet_date, position",
        (book_id,)).fetchall()
    return [dict(r) for r in rows]


def enrich_book(row) -> dict | None:
    """Turn a book row into a dict with its sections, the next section that
    hasn't been discussed yet, and a single 'next_date' used for sorting
    and display everywhere."""
    if row is None:
        return None
    book = dict(row)
    sections = book_sections_for(book["id"])
    book["sections"] = sections
    today_iso = date.today().isoformat()
    nxt = next((s for s in sections if s["meet_date"] >= today_iso), None)
    book["next_section"] = nxt
    if sections:
        book["next_date"] = nxt["meet_date"] if nxt else sections[-1]["meet_date"]
        book["all_sections_done"] = nxt is None
    else:
        book["next_date"] = book["meeting_date"]
        book["all_sections_done"] = False
    return book


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
    return (enrich_book(current),
            [enrich_book(b) for b in upcoming],
            [enrich_book(b) for b in past])


def club_members(club_id: int) -> list[dict]:
    rows = get_db().execute(
        """SELECT p.* FROM people p
           JOIN club_people cp ON cp.person_id = p.id
           WHERE cp.club_id = ? ORDER BY p.name""", (club_id,)).fetchall()
    return [dict(r) for r in rows]


def all_people() -> list[dict]:
    return [dict(r) for r in
            get_db().execute("SELECT * FROM people ORDER BY name").fetchall()]


def person_or_none(person_id) -> dict | None:
    if not person_id:
        return None
    row = get_db().execute("SELECT * FROM people WHERE id = ?", (person_id,)).fetchone()
    return dict(row) if row else None


def clubs_query(person_id=None):
    db = get_db()
    if person_id:
        return db.execute(
            """SELECT c.* FROM clubs c
               JOIN club_people cp ON cp.club_id = c.id
               WHERE cp.person_id = ? ORDER BY c.name""", (person_id,)).fetchall()
    return db.execute("SELECT * FROM clubs ORDER BY name").fetchall()


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


def _club_cards(person_id=None):
    cards = []
    for club in clubs_query(person_id):
        current, upcoming, _past = club_books(club["id"])
        cards.append({
            "club": club,
            "accent": club_accent(club["id"]),
            "current": current,
            "next_up": upcoming[0] if upcoming else None,
            "queue_len": len(upcoming),
            "members": club_members(club["id"]),
        })
    return cards


@app.route("/")
def home():
    person_id = request.args.get("person", type=int)
    person = person_or_none(person_id)
    return render_template("index.html",
                           cards=_club_cards(person["id"] if person else None),
                           people=all_people(), person=person)


@app.route("/club/<int:club_id>")
def club_detail(club_id: int):
    club = fetch_club_or_404(club_id)
    current, upcoming, past = club_books(club_id)
    return render_template("club.html", club=club, accent=club_accent(club_id),
                           current=current, upcoming=upcoming, past=past,
                           members=club_members(club_id))


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
    month_prefix = f"{year:04d}-{month:02d}"

    db = get_db()
    rows = db.execute(
        """SELECT b.*, c.name AS club_name FROM books b
           JOIN clubs c ON c.id = b.club_id
           WHERE b.status IN ('current', 'upcoming')""").fetchall()

    events_by_day: dict[str, list] = {}

    def add_event(iso, club_id, club_name, label):
        if iso and iso[:7] == month_prefix:
            events_by_day.setdefault(iso, []).append({
                "club": club_name,
                "club_id": club_id,
                "accent": club_accent(club_id),
                "title": label,
            })

    for b in rows:
        sections = book_sections_for(b["id"])
        if sections:
            for s in sections:
                label = b["title"] + (f" — {s['portion']}" if s["portion"] else "")
                add_event(s["meet_date"], b["club_id"], b["club_name"], label)
        else:
            add_event(b["meeting_date"], b["club_id"], b["club_name"], b["title"])

    for day_events in events_by_day.values():
        day_events.sort(key=lambda e: e["club"])

    # Build week rows (Sunday-first grid)
    start_pad = (first.weekday() + 1) % 7
    days_in_month = (next_month - timedelta(days=1)).day
    cells: list[dict | None] = [None] * start_pad
    for d in range(1, days_in_month + 1):
        iso = f"{month_prefix}-{d:02d}"
        cells.append({"day": d, "iso": iso, "events": events_by_day.get(iso, [])})
    while len(cells) % 7:
        cells.append(None)
    weeks = [cells[i:i + 7] for i in range(0, len(cells), 7)]

    month_events = sorted(
        ((iso, ev) for iso, evs in events_by_day.items() for ev in evs),
        key=lambda pair: pair[0])

    clubs = [{"name": c["name"], "accent": club_accent(c["id"])}
             for c in clubs_query()]

    return render_template("calendar.html", weeks=weeks,
                           month_label=first.strftime("%B %Y"),
                           prev_y=prev_month.year, prev_m=prev_month.month,
                           next_y=next_month.year, next_m=next_month.month,
                           month_events=month_events, club_legend=clubs)


@app.route("/display")
@app.route("/signage")
def signage():
    person_id = request.args.get("person", type=int)
    person = person_or_none(person_id)
    boards = []
    for club in clubs_query(person["id"] if person else None):
        current, upcoming, _past = club_books(club["id"])
        boards.append({
            "club": club,
            "accent": club_accent(club["id"]),
            "current": current,
            "next_up": upcoming[0] if upcoming else None,
            "members": club_members(club["id"]),
        })
    # Soonest meeting first; clubs with no scheduled date sink to the end
    boards.sort(key=lambda b: (b["current"] is None,
                               (b["current"] or {}).get("next_date") is None,
                               (b["current"] or {}).get("next_date") or "9999"))
    return render_template("signage.html", boards=boards, people=all_people(),
                           person=person,
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
# Admin: people
# --------------------------------------------------------------------------


@app.route("/admin/people", methods=["GET", "POST"])
@admin_required
def people_admin():
    db = get_db()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("The person needs a name.", "error")
        else:
            db.execute("INSERT INTO people (name) VALUES (?)", (name,))
            db.commit()
            flash(f"Added {name}.", "ok")
        return redirect(url_for("people_admin"))
    people = all_people()
    memberships = {}
    for p in people:
        rows = db.execute(
            """SELECT c.name FROM clubs c JOIN club_people cp ON cp.club_id = c.id
               WHERE cp.person_id = ? ORDER BY c.name""", (p["id"],)).fetchall()
        memberships[p["id"]] = [r["name"] for r in rows]
    return render_template("people.html", people=people, memberships=memberships)


@app.route("/admin/people/<int:person_id>/delete", methods=["POST"])
@admin_required
def person_delete(person_id: int):
    db = get_db()
    person = db.execute("SELECT * FROM people WHERE id = ?", (person_id,)).fetchone()
    if person is None:
        abort(404)
    db.execute("DELETE FROM people WHERE id = ?", (person_id,))
    db.commit()
    flash(f"Removed {person['name']}.", "ok")
    return redirect(url_for("people_admin"))


@app.route("/admin/people/<int:person_id>/rename", methods=["POST"])
@admin_required
def person_rename(person_id: int):
    name = (request.form.get("name") or "").strip()
    if name:
        db = get_db()
        db.execute("UPDATE people SET name = ? WHERE id = ?", (name, person_id))
        db.commit()
        flash("Name updated.", "ok")
    return redirect(url_for("people_admin"))

# --------------------------------------------------------------------------
# Admin: clubs
# --------------------------------------------------------------------------


def _save_club_members(db, club_id: int):
    picked = request.form.getlist("member_ids")
    db.execute("DELETE FROM club_people WHERE club_id = ?", (club_id,))
    for pid in picked:
        try:
            db.execute("INSERT OR IGNORE INTO club_people (club_id, person_id) "
                       "VALUES (?, ?)", (club_id, int(pid)))
        except ValueError:
            pass


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
            _save_club_members(db, cur.lastrowid)
            db.commit()
            flash(f"Club “{name}” created.", "ok")
            return redirect(url_for("club_detail", club_id=cur.lastrowid))
    return render_template("club_form.html", club=None, people=all_people(),
                           member_ids=set())


@app.route("/admin/club/<int:club_id>/edit", methods=["GET", "POST"])
@admin_required
def club_edit(club_id: int):
    club = fetch_club_or_404(club_id)
    db = get_db()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("The club needs a name.", "error")
        else:
            db.execute("UPDATE clubs SET name = ?, description = ? WHERE id = ?",
                       (name, (request.form.get("description") or "").strip(), club_id))
            _save_club_members(db, club_id)
            db.commit()
            flash("Club updated.", "ok")
            return redirect(url_for("club_detail", club_id=club_id))
    member_ids = {m["id"] for m in club_members(club_id)}
    return render_template("club_form.html", club=club, people=all_people(),
                           member_ids=member_ids)


@app.route("/admin/club/<int:club_id>/delete", methods=["POST"])
@admin_required
def club_delete(club_id: int):
    club = fetch_club_or_404(club_id)
    db = get_db()
    covers = [r["cover_url"] for r in db.execute(
        "SELECT cover_url FROM books WHERE club_id = ?", (club_id,)).fetchall()]
    db.execute("DELETE FROM clubs WHERE id = ?", (club_id,))
    db.commit()
    for url in covers:
        cleanup_cover(db, url)
    flash(f"Club “{club['name']}” and its books were removed.", "ok")
    return redirect(url_for("home"))

# --------------------------------------------------------------------------
# Uploaded book covers
# --------------------------------------------------------------------------


@app.route("/covers/<path:filename>")
def cover_file(filename):
    resp = send_from_directory(COVERS_DIR, filename)
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp


def save_uploaded_cover(file_storage) -> str | None:
    """Validate and store an uploaded cover image. Anything Pillow can read
    is accepted; it's resized to fit COVER_MAX and saved as JPEG. Returns
    the /covers/... URL, or None if the file wasn't a usable image."""
    try:
        img = Image.open(file_storage.stream)
        img.load()
    except (UnidentifiedImageError, OSError):
        return None
    if img.mode in ("RGBA", "P", "LA"):
        # Flatten transparency onto paper-white so JPEG doesn't go black
        img = img.convert("RGBA")
        flat = Image.new("RGB", img.size, (244, 238, 225))
        flat.paste(img, mask=img.split()[-1])
        img = flat
    elif img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail(COVER_MAX, Image.LANCZOS)
    name = f"{secrets.token_hex(8)}.jpg"
    img.save(os.path.join(COVERS_DIR, name), "JPEG", quality=85, optimize=True)
    return f"/covers/{name}"


def cleanup_cover(db, url: str | None):
    """Remove an uploaded cover file once no book references it anymore.
    External URLs (Open Library etc.) are left alone."""
    if not url or not url.startswith("/covers/"):
        return
    still_used = db.execute("SELECT COUNT(*) AS n FROM books WHERE cover_url = ?",
                            (url,)).fetchone()["n"]
    if still_used:
        return
    path = os.path.join(COVERS_DIR, os.path.basename(url))
    try:
        os.remove(path)
    except OSError:
        pass


# --------------------------------------------------------------------------
# Admin: books
# --------------------------------------------------------------------------


def _book_form_values():
    v = {
        "title": (request.form.get("title") or "").strip(),
        "author": (request.form.get("author") or "").strip(),
        "cover_url": (request.form.get("cover_url") or "").strip(),
        "meeting_date": request.form.get("meeting_date") or None,
        "portion": (request.form.get("portion") or "").strip(),
        "status": request.form.get("status") or "upcoming",
        "sectioned": request.form.get("sectioned") == "on",
        "cover_error": False,
    }
    upload = request.files.get("cover_file")
    if upload and upload.filename:
        saved = save_uploaded_cover(upload)
        if saved:
            v["cover_url"] = saved  # an upload wins over the URL field
        else:
            v["cover_error"] = True
    return v


def _form_sections() -> list[tuple[str, str]]:
    dates = request.form.getlist("section_date")
    portions = request.form.getlist("section_portion")
    pairs = [(d, (p or "").strip()) for d, p in zip(dates, portions) if d]
    pairs.sort(key=lambda pair: pair[0])
    return pairs


def _save_sections(db, book_id: int, values: dict):
    """Replace a book's sections from the form. When sectioned, the
    book-level meeting date is cleared — the sections carry the dates."""
    db.execute("DELETE FROM book_sections WHERE book_id = ?", (book_id,))
    if values["sectioned"]:
        pairs = _form_sections()
        for pos, (d, portion) in enumerate(pairs):
            db.execute("INSERT INTO book_sections (book_id, meet_date, portion, "
                       "position) VALUES (?, ?, ?, ?)", (book_id, d, portion, pos))
        if pairs:
            db.execute("UPDATE books SET meeting_date = NULL WHERE id = ?", (book_id,))


def _make_current(db, club_id: int, book_id: int):
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
        elif v["cover_error"]:
            flash("That cover file couldn't be read as an image — try a JPG or PNG.", "error")
        else:
            db = get_db()
            next_pos = db.execute(
                "SELECT COALESCE(MAX(queue_pos), -1) + 1 AS p FROM books "
                "WHERE club_id = ? AND status = 'upcoming'", (club_id,)).fetchone()["p"]
            cur = db.execute(
                """INSERT INTO books (club_id, title, author, cover_url,
                                      meeting_date, portion, status, queue_pos)
                   VALUES (?, ?, ?, ?, ?, ?, 'upcoming', ?)""",
                (club_id, v["title"], v["author"], v["cover_url"],
                 v["meeting_date"], v["portion"], next_pos))
            _save_sections(db, cur.lastrowid, v)
            if v["status"] == "current":
                _make_current(db, club_id, cur.lastrowid)
            db.commit()
            flash(f"Added “{v['title']}”.", "ok")
            return redirect(url_for("club_detail", club_id=club_id))
    return render_template("book_form.html", club=club, book=None, sections=[])


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
        elif v["cover_error"]:
            flash("That cover file couldn't be read as an image — try a JPG or PNG.", "error")
        else:
            old_cover = book["cover_url"]
            db.execute(
                """UPDATE books SET title = ?, author = ?, cover_url = ?,
                       meeting_date = ?, portion = ? WHERE id = ?""",
                (v["title"], v["author"], v["cover_url"],
                 v["meeting_date"], v["portion"], book_id))
            _save_sections(db, book_id, v)
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
            if old_cover != v["cover_url"]:
                cleanup_cover(db, old_cover)
            flash("Book updated.", "ok")
            return redirect(url_for("club_detail", club_id=club["id"]))
    return render_template("book_form.html", club=club, book=book,
                           sections=book_sections_for(book_id))


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
    if action == "delete":
        cleanup_cover(db, book["cover_url"])
    return redirect(request.form.get("back") or url_for("club_detail", club_id=club_id))

# --------------------------------------------------------------------------
# PWA service worker (served from root scope)
# --------------------------------------------------------------------------


@app.route("/sw.js")
def service_worker():
    resp = app.send_static_file("sw.js")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.errorhandler(413)
def too_large(_e):
    flash("That file is over the 15 MB upload limit — please use a smaller image.", "error")
    return redirect(request.referrer or url_for("home"))


@app.errorhandler(404)
def not_found(_e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
