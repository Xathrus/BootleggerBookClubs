# Bootlegger Book Club Tracker

A small, self-hosted hub for tracking what several book clubs are reading — who's on what book, when it's due, and when each club meets. Built for family and friends: everyone can view everything with just the link; one admin password controls the content.

## Features

- **Multiple clubs**, each with its own name, description, current book, queue of upcoming books, and reading history.
- **Books** carry a title, author, cover image, a meeting date, and an optional "portion" note like *Chapters 1–10* when the club isn't reading the whole book.
- **Split books**: a book can be read across several meetings — give each section its own date and chapter note, and every view highlights the *next* section due.
- **People**: add family and friends by name and check them off per club. Names show on club cards and the display, and clicking a name filters everything down to that person's clubs. (No accounts, ratings, or RSVPs — just names.)
- **Book search** against the Open Library API (free, no API key needed) that auto-fills title, author, and cover art. Manual entry always works as a fallback.
- **Calendar view** showing every meeting (including each section of a split book) across all clubs, color-coded per club.
- **Digital signage** at `/display` (or `/signage`) — a dark, high-contrast board sorted soonest-meeting-first, designed to be readable from across the room on a TV or tablet. It refreshes itself every 5 minutes with no page flash.
- **One admin login** (password set via environment variable). Everyone else browses freely.
- **Installable PWA**: add it to an iPhone home screen and it opens full-screen like a native app, with offline fallback to the last-seen schedule.

## Tech stack, in plain terms

- **Flask (Python)** — a small, boring, reliable web framework. One file of application code you can actually read.
- **SQLite** — the database is a single file in the `data/` folder. Nothing to install, nothing to administer, trivially easy to back up (copy the folder).
- **One Docker container** — the whole app builds and runs with two commands. No separate database server, no reverse proxy inside, no message queues. Cloudflare Tunnel handles HTTPS and exposure to the internet, so the container just serves plain HTTP on port 8080.
- **Open Library** for book search, because it's free and needs no API key or signup — there is nothing to configure or pay for.

Member logins, ratings, and RSVPs remain out of scope, but the `people` table gives them a natural home if they're ever wanted.

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
