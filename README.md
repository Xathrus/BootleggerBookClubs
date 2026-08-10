# Household Hub

A small self-hosted, mobile-friendly web app you can pin to your phone's home screen like an app. It shows:

- **Today** — everything on the household's Google Calendars today
- **Tomorrow** — same, for tomorrow
- **This week** — the rest of the next 7 days
- **Books due** — upcoming book club due dates for the people you choose, pulled from your Bootlegger Book Club Tracker

It runs as a single Docker container on a Proxmox LXC, following the same pattern as your other apps (Flask + Docker + Cloudflare Tunnel). There is no database — it just reads your calendar feeds and the book tracker's API, with a short in-memory cache so it stays fast and doesn't hammer Google.

---

## How it gets your calendar data

It uses each Google Calendar's **secret iCal address** — a private, read-only URL Google provides for every calendar. No Google Cloud project, no OAuth, no API keys. The trade-off: **anyone who has the URL can read that calendar**, so the URLs live only in `config.yml` on your server. Treat them like passwords.

### Getting the secret address for each calendar

1. Open [Google Calendar on the web](https://calendar.google.com) (desktop browser).
2. In the left sidebar under "My calendars," hover over the calendar → three dots → **Settings and sharing**.
3. Scroll to **Integrate calendar**.
4. Copy **Secret address in iCal format** (ends in `basic.ics`). *Not* the public address — the secret one.
5. Repeat for each household calendar.

If you ever suspect a URL leaked, the same settings page has a **Reset** button that invalidates the old URL.

---

## Step 1 — Create the LXC (same as your other apps)

Any Debian 12 / Ubuntu 22.04+ LXC with Docker works. If you already have a container running Docker (like the one hosting the book tracker), you can deploy this alongside it and skip to Step 2 — just make sure port 8080 is free, or change the port in `docker-compose.yml`.

Fresh LXC quick version:

```bash
# On the LXC (Debian 12), as root:
apt update && apt install -y ca-certificates curl
curl -fsSL https://get.docker.com | sh
```

For an unprivileged LXC, make sure `nesting=1` is set (Proxmox → container → Options → Features → Nesting), as with your other Docker containers.

## Step 2 — Put the app on the server

Copy the `household-hub` folder to the LXC (e.g. `scp -r household-hub root@<lxc-ip>:/opt/`), or push it to your Forgejo instance and clone it:

```bash
cd /opt/household-hub
```

## Step 3 — Configure

```bash
cp config.example.yml config.yml
nano config.yml
```

Fill in:

- One `calendars:` entry per Google Calendar — a display name, a color (shown as the bar/dot on each event), and its secret iCal URL.
- The `bookclub:` section — the tracker's base URL, a shared token (see Step 5), and the list of people whose books should appear. Delete the section if you want to launch without it and add it later; the app re-reads `config.yml` every 30 seconds, so no restart is needed for config changes.
- `timezone:` is already set to `America/Chicago`.

## Step 4 — Build and run

```bash
docker compose up -d --build
```

Check it: open `http://<lxc-ip>:8080` from a browser on your LAN. You should see today's events within a couple of seconds. Logs if anything looks off:

```bash
docker logs -f household-hub
```

## Step 5 — Connect the book tracker

The hub expects your Bootlegger Book Club Tracker to expose one new read-only endpoint:

```
GET /api/upcoming-books?days=7
Header: Authorization: Bearer <token>

Response:
{"books": [
  {"person": "Eric", "title": "...", "club": "...", "due_date": "YYYY-MM-DD"}
]}
```

Use the prompt in `BOOKCLUB_PROMPT.md` (in this folder) in your book tracker development conversation — it specifies the exact contract, auth, and deployment notes so the endpoint comes out compatible on the first try.

Generate a token to share between the two apps:

```bash
openssl rand -hex 32
```

Put the same value in the tracker's environment (`HUB_API_TOKEN`) and in this app's `config.yml` (`api_token`).

Since both apps live on your Proxmox network, point `api_url` at the tracker's **internal** address (e.g. `http://192.168.x.x:5000`) rather than its public Cloudflare hostname — faster, and the endpoint never needs to be exposed to the internet.

## Step 6 — Expose it through Cloudflare Tunnel

Add a public hostname to your existing tunnel, the same way as your other apps:

1. Cloudflare Zero Trust → Networks → Tunnels → your tunnel → **Public Hostname** → Add.
2. Subdomain: `hub` (or whatever you like), Service: `http://<lxc-ip>:8080`.

**Strongly recommended:** since this shows your family's schedule, put a Cloudflare Access policy in front of it (Zero Trust → Access → Applications → Add → Self-hosted, matching `hub.yourdomain.com`, allow by email with One-Time PIN). Each family member authenticates once per device and the app works normally afterward — including as a pinned PWA.

> Note: the service worker and "Add to Home Screen" require HTTPS, which the Cloudflare hostname gives you automatically. On plain LAN HTTP the site still works; it just won't install as an app or cache offline.

## Step 7 — Pin it as an app

- **iPhone/iPad (Safari):** open the site → Share button → **Add to Home Screen**. It launches full-screen with the house icon.
- **Android (Chrome):** open the site → you'll usually get an "Add Hub to Home screen" banner, or menu (⋮) → **Add to Home screen** → Install.

The last-loaded schedule stays visible even if the tunnel blips; it refreshes automatically whenever the app is opened or brought to the foreground, every 5 minutes while open, and on the ↻ button.

---

## Day-2 operations

**Update after changing code:**
```bash
cd /opt/household-hub
docker compose up -d --build
```

**Rollback:** the app is stateless, so rollback is just checking out the previous commit in Forgejo and rebuilding. `config.yml` is the only file with your data — keep it out of the repo (it contains secret URLs and the API token).

**Changing calendars, colors, or people:** edit `config.yml`; changes apply within 30 seconds, no restart.

**Calendar shows stale data:** Google refreshes secret iCal feeds on its own schedule (typically minutes, occasionally a few hours for newly-added events). The hub also caches feeds for 5 minutes. Both are normal.

**A calendar or the book tracker is unreachable:** the app stays up and shows a small notice at the top naming which feed failed, instead of erroring out.
