# Bootlegger Book Club Tracker

A small, self-hosted hub for tracking what several book clubs are reading — who's on what book, when it's due, and when each club meets. Built for family and friends: everyone can view everything with just the link; one admin password controls the content.

## Features

- **Multiple clubs**, each with its own name, description, current book, queue of upcoming books, and reading history.
- **Books** carry a title, author, cover image, a meeting date, and an optional "portion" note like *Chapters 1–10* when the club isn't reading the whole book.
- **Split books**: a book can be read across several meetings — give each section its own date and chapter note, and every view highlights the *next* section due.
- **People**: add family and friends by name and check them off per club. Names show on club cards and the display, and clicking names filters everything down to those people's clubs — the display supports selecting several people at once. (No accounts, ratings, or RSVPs — just names.)
- **Cover uploads**: search auto-fills covers from Open Library, paste any image URL, or upload your own file — uploads are resized to 600 × 900 automatically and stored alongside the database.
- **Book search** against the Open Library API (free, no API key needed) that auto-fills title, author, and cover art. Manual entry always works as a fallback.
- **Calendar view** showing every meeting (including each section of a split book) across all clubs, color-coded per club.
- **Digital signage** at `/display` (or `/signage`) — a dark, high-contrast board sorted soonest-meeting-first, designed to be readable from across the room on a TV or tablet. It refreshes itself every 5 minutes with no page flash.
- **Auto-finish**: when a whole-book read's meeting date passes (or a split book's final section passes), it moves to history automatically and the next queued book is promoted. Books with a partial-read note are left for a human to decide.
- **Member logins**: the admin can give any person a username and password. Logged-in members can manage the books of clubs they belong to and change their own password; the admin (username `admin`, password from the environment variable) manages everything — clubs, people, credentials, and all books. Browsing never requires a login.
- **Installable PWA**: add it to an iPhone home screen and it opens full-screen like a native app, with offline fallback to the last-seen schedule.

## Tech stack, in plain terms

- **Flask (Python)** — a small, boring, reliable web framework. One file of application code you can actually read.
- **SQLite** — the database is a single file in the `data/` folder. Nothing to install, nothing to administer, trivially easy to back up (copy the folder).
- **One Docker container** — the whole app builds and runs with two commands. No separate database server, no reverse proxy inside, no message queues. Cloudflare Tunnel handles HTTPS and exposure to the internet, so the container just serves plain HTTP on port 8080.
- **Open Library** for book search, because it's free and needs no API key or signup — there is nothing to configure or pay for.

Ratings and RSVPs remain out of scope, but the `people` table gives a natural home for more if it's ever wanted.

## Household Hub API

An optional read-only endpoint feeds upcoming book dates to a companion dashboard:

```
GET /api/upcoming-books?days=7
Authorization: Bearer <token>
```

It returns `{"books": [{"person", "title", "club", "due_date"}]}` — one entry per club member per book whose next meeting falls within the next `days` days (default 7, capped at 60, past dates excluded), sorted by date. For split books the next section's meeting date is used. The app doesn't track per-person completion, so every member of the club is listed for each book.

**To enable it:** set `HUB_API_TOKEN` in `.env` (generate one with `openssl rand -hex 32`) and restart. While the variable is unset the endpoint answers 503 and the feature is off; a missing or wrong token gets 401. Authentication is the bearer token only — no login cookie — so another container on the LAN can call it server-to-server.

## Running it

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for the full beginner-friendly walkthrough (Proxmox LXC → Docker → Cloudflare Tunnel).

The short version:

```bash
cp .env.example .env        # then edit .env and set a real ADMIN_PASSWORD
docker compose up -d --build
```

The app is now on port 8080. The database and secret key live in `./data/` — back that folder up and you've backed up everything.

## Project layout

```
app.py                  # all server code: routes, database, auth, Open Library proxy
templates/              # HTML pages (Jinja2)
static/css/style.css    # all styling, including the signage view
static/js/booksearch.js # the admin book-search box
static/sw.js            # PWA service worker
static/manifest.webmanifest
static/icons/           # app icons
Dockerfile
docker-compose.yml
.env.example            # copy to .env, set ADMIN_PASSWORD
data/                   # created at runtime: bootlegger.db + secret_key (gitignored)
```
