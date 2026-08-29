# Security Policy

## Reporting a Vulnerability

Please do not open a public issue for security problems. Use GitHub's
["Report a vulnerability"](../../security/advisories/new) private advisory flow,
or contact the maintainer privately. Include a description, reproduction steps,
and impact. We aim to acknowledge within 72 hours.

## Threat model / assumptions

- **No built-in authentication.** Every `/api/*` endpoint is unauthenticated by
  design - WCDA is meant to run for a single user on `localhost` or a trusted
  LAN. Do not expose it directly to the internet. Put a reverse proxy in front
  that terminates TLS and enforces auth if you need remote access.
- Both compose stacks bind the web app and PostgreSQL to `127.0.0.1` only.
- The app trusts its database and the Gemini API; it does not trust uploaded
  files. Uploads are size-capped (8 MB) and restricted to common image types.

## Handling secrets

- `.env` is git-ignored and listed in `.dockerignore`, so it is never committed
  or baked into an image layer. `.env.example` contains placeholders only.
- Rotate any key that has been shared, logged, or committed. Gemini keys are
  rotated in Google AI Studio.
- Server-side errors are logged with detail but returned to clients as generic
  messages.

## Dependencies

- Runtime versions are pinned in `requirements.txt` (mirrored by
  `pyproject.toml`). `pip-audit` runs in CI.
- Base images (`python:3.14-slim-bookworm`, `postgres:16-alpine`) should be
  rebuilt regularly to pick up upstream patches.
