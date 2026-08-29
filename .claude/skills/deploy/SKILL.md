---
name: deploy
description: Build and redeploy the prod web container, then verify it is serving the new code. Use when asked to deploy, ship, redeploy, or push a frontend/backend change to the running app at 192.168.50.202:8081.
---

# Deploy to prod

The prod stack is `compose.prod.yaml` (project `wcda-prod`). Only the `web`
service is rebuilt here; `db` and `db-backup` are left running.

## Steps

1. **If any file under `src/web/static/` changed**, bump the service-worker
   cache in `src/web/static/sw.js`: `const CACHE = 'wcda-vN'` → next `N`.
   Skipping this leaves clients on the old bundle.

2. **If backend/test files changed**, run checks first (in a throwaway
   container so no host env is needed):
   ```
   docker run --rm -v "$PWD":/w -w /w -e DATABASE_URL=postgresql+psycopg2://t:t@localhost/t \
     -e GEMINI_API_KEY=x python:3.14-slim bash -c \
     'pip install -q -e ".[dev]" && ruff check src tests && ruff format --check src tests && pytest -q tests/test_web_app.py'
   ```

3. **Rebuild + restart the web container:**
   ```
   docker compose -f compose.prod.yaml up -d --build web
   ```

4. **Wait for health** (retry a few times, ~3s apart):
   ```
   docker inspect -f '{{.State.Health.Status}}' wcda-prod-web-1   # want: healthy
   ```

5. **Confirm the container serves the local code** — for each changed static
   file, the served bytes must match the working tree:
   ```
   for f in index.html app.js style.css sw.js; do
     a=$(sha256sum "src/web/static/$f" | cut -d' ' -f1)
     b=$(curl -sS "http://192.168.50.202:8081/static/$f" | sha256sum | cut -d' ' -f1)
     [ "$a" = "$b" ] && echo "$f MATCH" || echo "$f DIFF"
   done
   ```

6. **Smoke-check the API:**
   ```
   curl -fsS http://192.168.50.202:8081/healthz                 # {"status":"ok"}
   curl -fsS -o /dev/null -w '%{http_code}\n' 'http://192.168.50.202:8081/api/logs?limit=1'   # 200
   ```

7. **Report**: the new `sw.js` cache version, health status, any file DIFF, and
   the smoke-check results. Remind the user to reload once on the phone to pick
   up the new service worker.
