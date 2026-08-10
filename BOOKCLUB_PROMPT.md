# Prompt to paste into your Bootlegger Book Club Tracker conversation

Copy everything below the line into the conversation where you develop the book tracker.

---

I'm adding a companion app — a self-hosted "Household Hub" dashboard on my Proxmox — that needs to pull upcoming book due dates from this tracker. Please add a small read-only JSON API endpoint to this app. The hub is already built and expects this exact contract, so please match it precisely:

**Endpoint**

```
GET /api/upcoming-books?days=7
```

- `days` is optional, defaults to 7, and means "books whose due date is within the next N days, including today." Cap it at 60.
- Past-due books should NOT be included.

**Authentication**

- Require the header `Authorization: Bearer <token>`.
- The expected token comes from an environment variable named `HUB_API_TOKEN`.
- If `HUB_API_TOKEN` is unset or empty, the endpoint should return 503 with `{"error": "API not configured"}` (so the feature is off by default).
- On a missing or wrong token, return 401 with `{"error": "unauthorized"}`.
- This endpoint must never require a session/login cookie — it will be called server-to-server from another container on my LAN.

**Response format (200)**

```json
{
  "books": [
    {
      "person": "Eric",
      "title": "The Warrior: En Garde",
      "club": "Bootleggers",
      "due_date": "2026-08-12"
    }
  ]
}
```

- `person`: the member's display name exactly as it appears in this app (the hub filters by these names, case-insensitively).
- `club`: the book club / group name the book belongs to.
- `due_date`: ISO date, YYYY-MM-DD.
- One entry per person per book. If a book is due for the whole club, emit one entry per member who hasn't finished it — or, if the data model doesn't track per-person completion, one entry per member of that club. Tell me which of those the data model supports and implement the best available.
- Sort by `due_date` ascending. Empty list is fine: `{"books": []}`.

**Implementation notes**

- Read-only: no writes, no side effects.
- Add `HUB_API_TOKEN` to the docker-compose environment section and to the `.env.example`, with a comment that it's generated via `openssl rand -hex 32`.
- Update the README with a short section describing the endpoint and how to enable it.
- Give me the complete updated files (not diffs) and the exact commands to redeploy the container safely, consistent with how this app is currently deployed.

After implementing, show me a sample `curl` command I can run from another machine on my LAN to verify the endpoint works, e.g.:

```bash
curl -H "Authorization: Bearer <token>" "http://<tracker-ip>:5000/api/upcoming-books?days=7"
```
