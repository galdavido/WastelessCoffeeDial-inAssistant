# Tailscale setup for the friends instance

The prod stack is multi-user: each caller's beans, shots, setups and settings are
scoped to the `Tailscale-User-Login` header that `tailscale serve` injects (see
`src/core/auth.py`). That header is *trusted*, which is only safe while the app is
unreachable except through Serve — hence the loopback bind in `compose.prod.yaml`.

This file is the host-side half, which lives outside the repo's control: the daemon,
Serve, and the tailnet policy.

## 1. Install and join (once, needs sudo + a browser)

```sh
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up          # prints an auth URL to open and approve
```

## 2. Enable MagicDNS and HTTPS certificates

In the [admin console](https://login.tailscale.com/admin/dns), turn on **MagicDNS**
and **HTTPS Certificates**. Serve cannot obtain a TLS certificate without both, and
`tailscale serve` will fail at step 3 if they are off.

## 3. Put Serve in front of the app

```sh
sudo tailscale serve --bg --https=443 http://127.0.0.1:8081
tailscale serve status     # confirm the mapping
```

Read back the tailnet name and your own login — the login is what owns your existing
data (see step 5):

```sh
tailscale status --json | grep -iE '"(DNSName|LoginName)"' | head
```

The app is then at `https://<machine>.<tailnet>.ts.net`. Because that is real HTTPS,
it is a *secure context*, so the service worker finally registers and the PWA works
offline — something the plain-HTTP LAN deployment never did.

### Turn off key expiry on this machine

By default a node key expires after ~6 months. When it does, the machine drops off the
tailnet and **the app goes dark for everyone** until somebody with shell access runs
`sudo tailscale up` and completes a browser login. On a personal laptop or phone that is
a minor annoyance and worth keeping. On an always-on server that other people depend on
it is an outage with a long fuse, scheduled for a date nobody remembers.

Admin console → **Machines** → this machine → **⋯** → **Disable key expiry**.

Check where it stands:

```sh
curl -s -H "Authorization: Bearer $TOK" \
  https://api.tailscale.com/api/v2/tailnet/-/devices \
  | python3 -c 'import json,sys; [print(d["name"], d["keyExpiryDisabled"], d["expires"]) for d in json.load(sys.stdin)["devices"]]'
```

Want `True` for this host. Leave the phone alone — reauthenticating a phone is easy, and
key expiry on a personal device is a feature. Note the read-only `devices:core:read`
scope can *see* this but not change it; flipping it needs the console or a token with
device write.

## 4. Lock down what shared friends can reach

**This matters on this host.** It also runs Jellyfin (`8096`), qBittorrent (`8080`),
Portainer (`9000`/`9443`), Sonarr (`8989`), Radarr (`7878`), Jackett (`9117`) and
Jellyseerr (`5055`). A node share grants a friend network reach to the **machine**,
not to one service — so with the stock policy, an invite to the coffee app is also an
invite to all of that.

### Why the rule is about port 443, not 8081

Friends never address `8081`. Serve terminates TLS on port **443 of the tailnet IP**
and proxies to `127.0.0.1:8081` locally, so from the tailnet the app *is* port 443 and
nothing else. That is what makes the lockdown a one-port rule.

It also means `http://<machine>.<tailnet>.ts.net` will not work — Serve is only
listening on 443 and there is no redirect from 80. Always hand out the `https://` URL.

### The trap: the default policy is allow-all

A new tailnet ships with an explicit allow-everything rule:

```json
{ "action": "accept", "src": ["*"], "dst": ["*:*"] }
```

Access rules are **additive** — traffic is permitted if *any* rule allows it. So adding
a restrictive rule for `autogroup:shared` while that allow-all is still in the file
achieves exactly nothing. The job is to **replace** the default, not append to it.

Two related gotchas:

- Tailscale's docs state that *omitting* the `acls` field is equivalent to the default
  allow-all. Do not rely on removing it; write an explicit rule set.

  **Settled by measurement (2026-09-06):** with the `grants` policy below live and no
  `acls` field present, an identity that matches no grant is dropped on *every* port,
  443 included — so a `grants`-only file is **not** an implicit allow-all. Verified with
  the ACL-test method below; see the "unknown identity" test. This is reassuring, but
  keep writing the explicit rule set anyway: the guarantee that matters is that no
  allow-all rule survives, not that omission happens to be safe.
- The docs do not clearly specify how a file containing **both** `acls` and `grants`
  is evaluated. Don't find out the hard way — keep the policy in **one** style, with no
  allow-all rule left in either block.

### Paste one of these whole

Use the style your tailnet is already on. Replace the entire policy file rather than
merging, so no permissive rule survives by accident.

`grants` (current style, recommended for a new tailnet):

```jsonc
{
  "grants": [
    // You, and anyone who is a full member of your tailnet, are unrestricted.
    // This is the rule that stops you locking yourself out.
    {
      "src": ["autogroup:member"],
      "dst": ["*"],
      "ip":  ["*"]
    },
    // Friends who accepted a node share reach the coffee app over HTTPS and
    // nothing else on the box. Widening or deleting this exposes Jellyfin,
    // Portainer, qBittorrent and the rest to them.
    {
      "src": ["autogroup:shared"],
      "dst": ["*"],
      "ip":  ["tcp:443"]
    }
  ]
}
```

`acls` (older style — use only if your file already looks like this):

```jsonc
{
  "acls": [
    { "action": "accept", "src": ["autogroup:member"], "dst": ["*:*"] },
    { "action": "accept", "src": ["autogroup:shared"], "dst": ["*:443"] }
  ]
}
```

`autogroup:shared` covers everyone you invite, now and later, so no email addresses
need listing in advance. `autogroup:member` is authenticated members of your own
tailnet — you — and shared-in friends are deliberately *not* members.

### Verify it, three ways

The admin console's policy editor previews rule matches before you save — use it, and
confirm your own account still matches the unrestricted rule *before* saving.

**Then assert the rules, don't eyeball them.** Tailscale evaluates `tests` in the policy
file server-side, so the whole rule set can be checked without touching a device. This
needs an OAuth client with **write** on the `acl` scope (admin console → Settings → OAuth
clients); it can read and rewrite the policy file and nothing else, and posting to
`/acl/validate` only checks — it never saves.

```sh
TOK=$(curl -s -d "client_id=$ID" -d "client_secret=$SECRET" \
  https://api.tailscale.com/api/v2/oauth/token | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')

curl -s -X POST -H "Authorization: Bearer $TOK" -H "Content-Type: application/hujson" \
  --data-binary @policy.hujson \
  https://api.tailscale.com/api/v2/tailnet/-/acl/validate
```

`{}` means every test passed. Put these three in the `tests` array, substituting this
machine's tailnet IP:

| src | assertion | proves |
|---|---|---|
| your own login | `accept` 443, 8096, 9000 | you are not locked out of your own box |
| your own login | `deny` 8096 — **must fail** | the tests are really being evaluated |
| an address in no share | `deny` 443, 8096, 9000 | nothing is reachable by default |

The middle row is the one people skip. Run it and confirm it *fails* with
`want: Drop, got: Accept` — a suite where a false claim passes is proving nothing, and
that is exactly the failure mode of a policy that silently isn't applying.

Finally, test from a friend's device (or a second account of your own that you invite as
a share), because none of the above checks Serve:

```sh
curl -fsS  https://<machine>.<tailnet>.ts.net/api/whoami          # 200, their login
curl -m 5  http://<machine>.<tailnet>.ts.net:8096/                # must time out
curl -m 5  http://<machine>.<tailnet>.ts.net:9000/                # must time out
```

The two timeouts are the actual result you are looking for. A 200 or a connection
refused from either means the rule is not doing its job — refused still proves the
packet reached the host.

### What this does and does not cover

- It is a **network** control: it stops friends reaching other ports on this machine.
- It is *not* what keeps their coffee data separate. That is the app's own per-owner
  scoping in `src/core/auth.py`, which works off the identity header independently.
- It does not constrain anyone you make a full tailnet **member** — members match the
  first rule and are unrestricted. Invite friends by **sharing the machine**, never by
  adding them to the tailnet.

## 5. Cut prod over — before anyone is invited

> **Order matters.** Serve being up does not mean the app is multi-user. Until this
> step lands, the app is still in `single` mode, where *every* visitor is mapped to the
> one owner `owner`. Invite a friend before cutting over and they arrive inside your
> library, seeing and able to delete your coffees and shots. Cut over first, verify
> identity, and only then share the machine.

Delete `WCDA_PROD_BIND` and `WCDA_AUTH_MODE` from `.env` so the compose defaults
(`127.0.0.1` and `tailscale`) apply, then redeploy:

```sh
docker compose -f compose.prod.yaml up -d --build web
```

Verify **through the ts.net URL**, not loopback — that is the only check that proves
Serve is actually injecting the header:

```sh
curl -fsS https://<machine>.<tailnet>.ts.net/api/whoami   # your login, auth_mode tailscale
```

`auth_mode` must read `tailscale` and `owner` must be your login, not `owner`. Confirm
the LAN address is gone too (`curl -m 5 http://<host-ip>:8081/healthz` should fail to
connect) — if it still answers, the bind did not move and the header is forgeable.

## 6. Move pre-multi-user data to your identity

Migration `0005` backfilled every row that existed before multi-user to the placeholder
owner `owner`. To claim it as yourself, with `<login>` from step 3:

```sh
docker compose -f compose.prod.yaml exec -T db \
  psql -U barista -d barista_db -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
UPDATE beans           SET owner = '<login>' WHERE owner = 'owner';
UPDATE dial_in_logs    SET owner = '<login>' WHERE owner = 'owner';
UPDATE brew_setups     SET owner = '<login>' WHERE owner = 'owner';
UPDATE recommendations SET owner = '<login>' WHERE owner = 'owner';
UPDATE app_settings    SET owner = '<login>' WHERE owner = 'owner';
UPDATE equipment       SET owner = '<login>' WHERE owner = 'owner';
COMMIT;
SQL
```

Safe as a plain `UPDATE` only while no rows exist under `<login>` yet — otherwise
`uq_app_settings_owner_key` will collide on `app_settings`. Check first with
`SELECT owner, count(*) FROM app_settings GROUP BY owner;`.

### Equipment is shared, but only its creator can edit it

Everyone picks from one equipment list, but an entry's click range and microns per
click bound every recommendation made on it, so only the login in `equipment.owner`
may edit or delete it. Rows with no owner — the seeded baseline hardware, and any
pre-`0007` row several people used — are read-only in the app. To correct one, edit
it in SQL, or hand it to someone so they can edit it in the app:

```sql
SELECT id, owner, type, brand, model FROM equipment ORDER BY id;
UPDATE equipment SET owner = '<login>' WHERE id = <id>;
```

## 7. Invite a friend

Only once step 5 is verified. Admin console → **Machines** → this machine → **Share**.
Copy the invite link and send it with the setup guide written for them. Reusable links
work up to 1,000 times; a single-use link is safer if you are sending one per person.

Share the machine — do **not** add friends as tailnet members. Members match the
unrestricted rule in step 4 and would reach every other service on this host.

## Troubleshooting

- **401 from a device that is plainly on the tailnet.** Identity headers are populated
  for users, including external users who accepted a share, but *never* for **tagged**
  devices. A tagged machine cannot sign in here.
- **401 for everyone after a restart.** Serve config does not always survive a daemon
  reinstall — re-run step 3 and check `tailscale serve status`.
- **Everything 401s and the log warns about spoofing.** `warn_if_misconfigured()` fires
  at startup whenever `WCDA_AUTH_MODE=tailscale`; if the port is not on loopback, fix
  the bind before anything else.
