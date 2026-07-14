# Deploying Bootlegger — a complete walkthrough

This guide assumes zero prior experience with Docker, Git, or Cloudflare Tunnel. Follow it top to bottom. Anything you type is shown in code blocks; type it exactly and press Enter.

By the end you'll have the app running in a container on your Proxmox server, reachable from anywhere at your own address like `https://books.yourdomain.com`, with no ports opened on your router.

**The five stages:**

1. Put the code in a GitHub repository
2. Prepare an LXC container on Proxmox
3. Install Docker inside the LXC
4. Pull the code and start the app
5. Point a Cloudflare Tunnel at it

---

## Stage 1 — Put the code on GitHub

GitHub is where the code will live so your server can download ("clone") it, and so you have a copy if the server ever dies.

1. Sign in at [github.com](https://github.com) (create a free account if needed).
2. Click the **+** in the top-right → **New repository**.
3. Name it `bootlegger` (or anything you like). Choose **Private** unless you want the code public. Do **not** tick "Add a README" — you already have one. Click **Create repository**.
4. On the new empty repo page, click the **"uploading an existing file"** link.
5. Unzip the project folder on your computer, then drag **all the files and folders inside it** (`app.py`, `templates/`, `static/`, `Dockerfile`, etc.) into the upload box. Make sure folders came along — after uploading, you should see `templates` and `static` listed in the repo.
6. Click **Commit changes**.

> **Note:** the `.env.example` file uploads; the real `.env` (with your password) never should — and the included `.gitignore` file prevents that automatically if you ever use git commands later.

---

## Stage 2 — Prepare an LXC container on Proxmox

An LXC container is a lightweight virtual machine. We'll make a small Ubuntu one dedicated to this app. (If you'd rather reuse an existing Docker-capable LXC you already have, skip to Stage 3.)

1. In the Proxmox web interface, click **Create CT** (top right).
2. **General:** pick a free ID (e.g. `211`), hostname `bootlegger`, and set a root password you'll remember. Leave "Unprivileged container" **checked**.
3. **Template:** choose an Ubuntu 24.04 (or 22.04) standard template. If none is listed, go to your storage → **CT Templates** → **Templates** button and download one first.
4. **Disks:** 8 GB is plenty.
5. **CPU:** 1 core. **Memory:** 1024 MB.
6. **Network:** leave the defaults, set IPv4 to **DHCP** (or a static IP if you prefer).
7. Finish the wizard but **don't start it yet**.
8. Select the new container → **Options** → **Features** → **Edit**. Tick **Nesting** and **keyctl**, click OK. *(Docker won't run inside an LXC without these.)*
9. Now click **Start**, then open the **Console** and log in as `root` with the password you set.

Everything from here on is typed into that console (or an SSH session to the container).

---

## Stage 3 — Install Docker inside the LXC

Docker packages the app and everything it needs into one "container" so you never have to install Python or fiddle with dependencies. Two commands:

```bash
apt update && apt install -y curl git
curl -fsSL https://get.docker.com | sh
```

That second command takes a minute. Verify it worked:

```bash
docker --version
```

You should see something like `Docker version 27.x.x`. If you get an error mentioning permissions or overlay, double-check Stage 2 step 8 (Nesting + keyctl), then reboot the container (`reboot`) and try again.

---

## Stage 4 — Pull the code and start the app

**1. Download the code from GitHub:**

If your repo is **public**:

```bash
cd /opt
git clone https://github.com/YOUR-USERNAME/bootlegger.git
cd bootlegger
```

If your repo is **private**, GitHub will ask for a username and password — the "password" must be a *personal access token*, not your real password. Make one at GitHub → your avatar → **Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)** → Generate new token, tick the `repo` box, and copy it. Then run the same `git clone` command and paste the token when asked for a password.

**2. Set your admin password:**

```bash
cp .env.example .env
nano .env
```

`nano` is a simple text editor. Change the line to a real password, e.g.:

```
ADMIN_PASSWORD=a-long-phrase-only-you-know
```

Press **Ctrl+O**, **Enter** to save, then **Ctrl+X** to exit.

> This is the only secret the app needs. There's **no book-API key** — Open Library is free and keyless.

**3. Build and start it:**

```bash
docker compose up -d --build
```

The first build takes a couple of minutes. When it finishes, check it's alive:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/
```

If that prints `200`, the app is running. You can also browse to `http://<the-LXC's-IP>:8080` from any computer on your home network right now (find the IP with `ip addr` — it's the one under `eth0`).

The database lives in `/opt/bootlegger/data/bootlegger.db`. **Backing up = copying that `data` folder.**

---

## Stage 5 — Expose it with Cloudflare Tunnel

A Cloudflare Tunnel makes an *outbound* connection from your LXC to Cloudflare, and Cloudflare forwards visitors down that connection — so you never open a port on your router, and you get free HTTPS. You need a domain that's already added to your (free) Cloudflare account.

The easiest method is the dashboard-managed tunnel:

1. Go to [one.dash.cloudflare.com](https://one.dash.cloudflare.com) → **Networks** → **Tunnels** → **Create a tunnel**.
2. Choose **Cloudflared**, name it `bootlegger`, click **Save tunnel**.
3. On the "Install connector" step, pick **Debian**, **64-bit**. Cloudflare shows you a single long command starting with `curl -L ... && sudo dpkg -i ... && sudo cloudflared service install eyJ...`. Copy it, paste it into your LXC console, press Enter. (You can drop the `sudo`s — you're already root.) It installs `cloudflared` and connects. The dashboard should show the connector as **Connected**.
4. Click **Next** to reach **Public Hostnames** → **Add a public hostname**:
   - **Subdomain:** `books` (or whatever you like)
   - **Domain:** your domain
   - **Service Type:** `HTTP`
   - **URL:** `localhost:8080`
5. Save. Give it a minute, then open `https://books.yourdomain.com` from your phone (on cellular, to prove it works from outside). Done.

> If you already run a tunnel on another LXC (e.g. with a locally managed `config.yml`), you can instead add a second `ingress` rule pointing at this container's IP and port 8080 — both approaches work; the dashboard method above is the least fiddly for a fresh setup.

**Optional but recommended:** protect the login page. In Cloudflare Zero Trust → **Access** → **Applications**, you could gate `/login` behind an email one-time-PIN. Not required — the app's own password is the real lock — but it adds a second layer.

---

## Day-2 stuff

**Add it to an iPhone home screen (PWA):** open the site in Safari → Share button → **Add to Home Screen**. It gets its own icon and opens full-screen like an app. The `/display` page can be added the same way on a wall-mounted tablet.

**Set up the signage TV:** browse to `https://books.yourdomain.com/display` and leave it. It refreshes itself every 5 minutes.

**Update the app after code changes:**

```bash
cd /opt/bootlegger
git pull
docker compose up -d --build
```

**View logs** (if something misbehaves):

```bash
docker compose logs --tail 100
```

**Restart / stop:**

```bash
docker compose restart
docker compose down        # stop entirely; data is safe in ./data
```

**Back up:** copy `/opt/bootlegger/data/` somewhere safe (Proxmox's own LXC backups also cover it).

**Change the admin password:** edit `.env`, then `docker compose up -d` (it restarts with the new value). Existing logins stay valid until their cookie expires; to force everyone out immediately, also delete `data/secret_key` before restarting.

---

## Troubleshooting quick hits

| Symptom | Likely fix |
|---|---|
| `docker: command not found` | Stage 3 didn't finish — rerun the install script. |
| Docker install errors about `overlay` or permissions | Enable **Nesting** + **keyctl** in the LXC's Options → Features, then `reboot`. |
| `curl http://localhost:8080` prints `000` or connection refused | `docker compose logs` — most often a typo in `.env`. |
| Login says "No admin password is configured" | The `.env` file is missing or `ADMIN_PASSWORD` is blank; fix and `docker compose up -d`. |
| Book search says "unreachable" | The LXC can't reach the internet, or Open Library is having a moment. Manual entry still works. |
| Site works on home Wi-Fi but not outside | The tunnel isn't connected — check the Cloudflare dashboard shows the connector as healthy. |
