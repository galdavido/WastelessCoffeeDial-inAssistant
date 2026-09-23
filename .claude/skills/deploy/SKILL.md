---
name: deploy
description: Build and redeploy the prod web container, then verify it is serving the new code. Use when asked to deploy, ship, redeploy, or push a frontend/backend change to the running friends app (Tailscale-only, loopback 127.0.0.1:8081 on the prod host).
---

# Deploy to prod

The prod stack is `compose.prod.yaml` (project `wcda-prod`). Only the `web`
service is rebuilt here; `db` and `db-backup` are left running.

Prod is the multi-user **friends** instance: `WCDA_AUTH_MODE=tailscale`, bound
to **loopback only** (`127.0.0.1:8081`) and fronted by `tailscale serve` on the
host. Verify against `http://127.0.0.1:8081` from the prod host — the old LAN
address `192.168.50.202:8081` is the dev instance now. API routes require the
`Tailscale-User-Login` header; `tailscale serve` supplies it in normal use, and
the smoke check below sends a throwaway value directly to loopback.

## Steps

1. **If any file under `src/web/static/` changed**, bump the service-worker
   cache in `src/web/static/sw.js`: `const CACHE = 'wcda-vN'` → next `N`, and
   the `?v=N` on the CSS/JS tags in `index.html` and `admin.html` to match
   (`tests/test_web_app.py` fails if they disagree). Skipping this leaves
   clients on the old bundle.

2. **If backend/test files changed**, run checks first (in a throwaway
   container so no host env is needed):
   ```
   docker run --rm -v "$PWD":/w -w /w -e DATABASE_URL=postgresql+psycopg2://t:t@localhost/t \
     -e GEMINI_API_KEY=x python:3.14-slim bash -c \
     'pip install -q -e ".[dev]" && ruff check src tests && ruff format --check src tests && mypy src && pytest -q'
   ```
   Without a reachable database the API-flow tests skip; CI runs them against
   Postgres, so a green CI run on the branch is the real gate.

   **New migrations run on startup.** If `migrations/versions/` changed, the
   restart in step 3 applies them to the friends database — take a fresh dump
   first so the change can be rolled back:
   ```
   docker compose -f compose.prod.yaml exec db-backup /backup.sh
   ls -t backups/db/last/ | head -1        # the dump just written
   ```

3. **Rebuild + restart the web container:**
   ```
   docker compose -f compose.prod.yaml up -d --build web
   ```

   Naming `web` starts only `web` and its `depends_on` — **not `db-backup`**.
   That is how the nightly backup silently went unstarted for a week. Bring the
   whole stack up so every service is running, then confirm:
   ```
   docker compose -f compose.prod.yaml up -d
   docker compose -f compose.prod.yaml ps --services --filter status=running
   ```
   Expect `db`, `db-backup` and `web`. If `db-backup` is missing, nothing is
   being backed up.

4. **Wait for health** (retry a few times, ~3s apart):
   ```
   docker inspect -f '{{.State.Health.Status}}' wcda-prod-web-1   # want: healthy
   ```

5. **Confirm the container serves the local code** — for each changed static
   file, the served bytes must match the working tree:
   ```
   for f in index.html app.js style.css sw.js; do
     a=$(sha256sum "src/web/static/$f" | cut -d' ' -f1)
     b=$(curl -sS "http://127.0.0.1:8081/static/$f" | sha256sum | cut -d' ' -f1)
     [ "$a" = "$b" ] && echo "$f MATCH" || echo "$f DIFF"
   done
   ```

6. **Smoke-check the API** (multi-user: the identity header is required):
   ```
   curl -fsS http://127.0.0.1:8081/healthz                       # {"status":"ok"}
   curl -sS -o /dev/null -w '%{http_code}\n' 'http://127.0.0.1:8081/api/logs?limit=1'   # 401 (no header)
   curl -fsS -o /dev/null -w '%{http_code}\n' -H 'Tailscale-User-Login: deploy-check@example.com' \
     'http://127.0.0.1:8081/api/logs?limit=1'                    # 200
   ```

7. **Report**: the new `sw.js` cache version, health status, any file DIFF, and
   the smoke-check results. Remind the user to reload once on the phone to pick
   up the new service worker.
