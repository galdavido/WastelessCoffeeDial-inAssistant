# The public instance

A deployment a native client can reach from anywhere. Strangers can reach
it too, which is the only thing that really separates it from the other two
stacks — and it is why almost everything below exists.

|                        | identity                | reachable from        | port |
| ---------------------- | ----------------------- | --------------------- | ---- |
| `compose.yaml`         | implicit single user    | your LAN              | 8082 |
| `compose.prod.yaml`    | Tailscale header        | your tailnet          | 8081 |
| `compose.public.yaml`  | Sign in with Apple      | the internet, via TLS | 8083 |

The first two trust the network boundary. This one cannot: there is no
boundary. Identity rests on a signature instead — the app signs in with
Apple, the server verifies Apple's token against Apple's published keys, and
issues its own session token from it (`src/core/apple_auth.py`).

**Keep your home instance exactly as it is.** This is a separate deployment
with its own database. Nothing here touches the dev or friends stacks, and
they should not be migrated into it.

## What you need

- A small VPS. The stack idles comfortably in under 1 GB; €4–5/month is
  enough. It must run Docker.
- A domain name pointed at it. Sign in with Apple requires real TLS, and
  Let's Encrypt wants a name to issue against.
- The Apple side: an App ID with the **Sign in with Apple** capability
  enabled, matching `WCDA_APPLE_BUNDLE_ID`. That is a checkbox in the
  Certificates, Identifiers & Profiles section of the developer portal.

## Configure

Use a *separate* env file. Sharing `.env` with the other stacks is how a
value meant for one of them ends up overriding another — the existing
`.env.example` says the same thing about `WCDA_AUTH_MODE`.

```sh
cp .env.example .env.public
```

Then set, at minimum:

```sh
POSTGRES_PASSWORD=<a long random string>
GEMINI_API_KEY=<your key>
WCDA_APPLE_BUNDLE_ID=com.galdavido.dialin
WCDA_SESSION_SECRET=<a long random string, see below>
```

The session secret signs every session token. Anyone who has it can mint a
session for any user, so generate it properly and never reuse the database
password for it:

```sh
openssl rand -base64 48
```

Rotating it signs everyone out, which is the correct behaviour if you ever
think it leaked.

The app **refuses to start** in this mode without both `WCDA_SESSION_SECRET`
and `WCDA_APPLE_BUNDLE_ID`. That is deliberate: without the secret every
token would be forgeable, and without the bundle id an identity token from
*any* app would be accepted. An instance that starts anyway is an open
instance that looks authenticated.

## Bring it up

```sh
docker compose -f compose.public.yaml --env-file .env.public up -d --build
```

Without naming a service — `up -d --build web` starts only `web` and its
`depends_on`, and the nightly dump quietly never runs.

Migrations run on startup. Check what it bound to:

```sh
docker compose -f compose.public.yaml --env-file .env.public logs web | head -40
```

The startup log names the database it connected to and the audience it will
accept tokens for. Read both — a wrong database looks like an empty app, not
like an error.

## TLS

The container binds to `127.0.0.1:8083` only. Terminate TLS on the host;
Caddy is the least work, because it gets and renews the certificate itself:

```caddy
dialin.example.com {
    reverse_proxy 127.0.0.1:8083
}
```

Do not publish the container on `0.0.0.0` instead. It speaks plain HTTP, and
session tokens travel in the `Authorization` header on every request.

## Backups

Nightly `pg_dump` into `./backups/public-db/` with the same rotation as the
other stacks. **Despite the `.sql.gz` name these dumps are plain,
uncompressed SQL**, so a restore is a straight redirect and piping through
`gunzip` fails with "not in gzip format":

```sh
docker compose -f compose.public.yaml --env-file .env.public exec -T db \
  psql -U barista -d barista_db < backups/public-db/last/<file>.sql.gz
```

## Spending

This instance is reachable by anyone with the app, so the AI quota is not a
nicety — it is what stands between one enthusiastic user and an exhausted
Gemini key. Defaults are 5 bag scans a month on the free tier and 100 on the
paid one; prose falls back to the deterministic template for free users, with
identical numbers. `src/core/quota.py` and the `AI spending limits` block in
`.env.example` have the detail.

Until real subscriptions exist, the paid tier is the `WCDA_ENTITLED_OWNERS`
allowlist. Owners here look like `apple:001234.abcdef….0001` — the `sub`
claim Apple issues, which is stable per user and per developer team. Read one
off `GET /api/whoami` while signed in rather than trying to construct it.

## Deleting an account

`DELETE /api/account` erases every row belonging to the caller and unlinks
their bag photos from disk. Anywhere real accounts exist, people are
entitled to remove them. It is refused in `single` mode, where "the
account" would mean the whole instance.

## Tiers

The paid tier is whatever `core.quota.is_entitled` says it is, and right now
that is an env allowlist. It is deliberately one function, so a real
entitlement source — a billing system, a licence server, an internal group
— can replace it without anything above needing to know.
