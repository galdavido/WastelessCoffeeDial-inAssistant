# Open decisions

What the streamline and review (branch `claude/app-streamline-code-review-oiy7c2`)
left for the owner to decide. Each item says where things stand now, the
options, a recommendation, and what happens if nothing is decided. When one is
settled, record the answer here and delete it once the work lands.

## At a glance

| # | Decision | Recommendation | Blocks deploy? |
|---|---|---|---|
| 1 | Who can edit the seeded K6 / AVX once they turn read-only | Fill the K6's documented specs in a migration; keep both shared | No, but decide before friends notice |
| 2 | Gemini explanation on every dose change | Only on the first recipe for a coffee | No |
| 3 | Roast-based starting dose uses one person's basket | Scale it from the brewer's basket size when known | No |
| 4 | Unused database columns | Drop `llm_note`, `burr_size_mm`, the grind-offset rows; keep `tds_pct` | No |
| 5 | Add a dose term to the grind law | Yes, as the next engine change | No |
| 6 | Build the "use less coffee" (Cameron) suggestion | After #5 | No |
| 7 | HEIC photos | Keep refusing them | No |
| 8 | Rename `/api/logs/*` to `/api/beans/*` | Leave as is | No |
| 9 | alembic version differs between CI and the Docker image | Bump `requirements.txt`, then keep both in step | No |
| 10 | `pip-audit` is advisory in CI | Keep advisory; review its output on dependency bumps | No |

The things that need host access rather than a decision are listed at the end
under [Before and after deploying](#before-and-after-deploying).

---

## 1. Seeded equipment turns read-only

**Now.** Migration 0007 records who added each equipment entry. Only that
person can edit or delete it, and an entry with no owner is shared and
read-only. The backfill gives an existing row to the one owner whose setups or
shots use it. The seeded Kingrinder K6 and AVX Hero Plus 2024 are used by
every friend's default setup, so on prod they become shared and read-only.

The seed (`db_bootstrap.seed_baseline_equipment`) stores only brand and model,
with no capabilities. Unless someone filled them in by hand, the K6 has no
microns per click, so the engine can't name a starting grind for anyone on
it: they get the "log one shot" instructions instead. After this deploy,
nobody can fix that in the app.

**Options.**
- a. Leave both shared and read-only. Fix their specs in SQL when needed
  (`docs/tailscale-setup.md` shows how).
- b. Give both entries to your login, so you can edit them in the app.
- c. A data migration that fills in the K6's documented specs where they are
  still empty: 16 µm per click, lower number is finer, and a `spec_source`
  pointing at `docs/science.md#k6-caps`. Both entries stay shared.

**Recommendation.** c, plus a for anything later. Every friend on a default
setup then gets a real starting grind, and nobody can change it for everyone.

**If undecided.** Friends on the default K6 keep getting instructions instead
of a number until they add their own grinder with its specs.

## 2. Gemini writes the explanation on every dose change

**Now.** Each `/api/recommendation` call, including every "Update recipe" tap,
waits for a Gemini call to write the explanation. It tries up to six models in
turn before falling back to the built-in template. The engine has already
fixed every number by then, so the call only changes the wording.

**Options.**
- a. Keep it on every refresh (current).
- b. Use Gemini for the first recipe on a coffee (scan, or opening it), and the
  template for dose changes and setup switches.
- c. Template only: no Gemini call for explanations at all.

**Recommendation.** b. The template already covers every case, and dose
changes are when waiting is most annoying. It is a small change in
`core/routes/recipe.py`.

**If undecided.** Stays as a: slower refreshes and more quota used.

## 3. The roast-based starting dose uses one person's basket

**Now.** A coffee with no shots starts at 18.5 g (light or medium-light),
17.5 g (medium), 17 g (medium-dark) or 16.5 g (dark), shown with a hint to
adjust it (`web_helpers._STARTING_DOSE_BY_ROAST`). These are midpoints for one
18 g basket, and they apply to every friend. The basket guardrail still clamps
the dose when a brewer has `basket_size_g` set. Unlike every other number the
engine uses, the table has no entry in `brewing.CONSTANTS` or
`docs/science.md`.

**Options.**
- a. Keep the table.
- b. Scale it from the brewer's `basket_size_g` when known (light ≈ 1.03×,
  dark ≈ 0.92× of the basket), and fall back to the table otherwise.
- c. Apply it as offsets from each user's own default dose.
- d. Drop it and start every coffee at the user's default dose.

**Recommendation.** b. Whichever you choose, move the numbers into
`brewing.CONSTANTS` as `HEURISTIC` entries with a `docs/science.md` section,
like every other constant.

**If undecided.** Friends with a different basket get a starting dose that is
wrong for them until their first shot.

## 4. Unused database columns

**Now.** Nothing reads these, and they were left in place because dropping a
column deletes live data and cannot be undone:

- `dial_in_logs.llm_note`: the old prose each shot was logged with. No longer
  written.
- `equipment.burr_size_mm`: never written or read.
- `app_settings` rows with key `default_grind_offset_clicks`: from the removed
  grind-offset setting.
- `dial_in_logs.tds_pct`: never written. It is reserved for a refractometer
  reading, and `docs/science.md` keeps it deliberately.

**Options.** Keep all of them, or add a migration 0009 that drops the first
two and deletes the grind-offset rows.

**Recommendation.** Migration 0009 for the first three, taken right after a
fresh dump. Keep `tds_pct`.

**If undecided.** No harm; a little clutter.

## 5. A dose term in the grind law

**Now.** The grind law has no dose term (`docs/science.md#beta-law`, "Missing
term: dose"). A dose you ask for is now honoured, but the grind is still worked
out at the last shot's dose, and the recipe tells you so. The per-coffee
offset also absorbs dose differences, so two coffees brewed at different
doses look like two coffees that grind differently.

**Options.** Add `+ γ·ln(dose)` to the law and re-fit it (engine change plus
tests and a science.md update), or leave the limitation documented.

**Recommendation.** Do it next. It unblocks #6 and makes dose changes adjust
the grind properly.

## 6. The "use less coffee" (Cameron) suggestion

**Now.** `docs/science.md#cameron-reproducibility` describes the app's
namesake move: when a shot keeps channeling, use about 20% less coffee and
grind coarser. No code suggests it. The old helper was never called and has
been removed.

**Options.** Build it, with a trigger for "channeling keeps coming back at
this dose", or leave it documented only.

**Recommendation.** Build it after #5, because the trigger needs the dose
term to tell dose effects apart from grind effects.

## 7. HEIC photos

**Now.** Uploads must be JPEG, PNG or WebP. HEIC was accepted before, but
Pillow has no HEIF decoder installed, so those uploads always failed. Phones
convert HEIC to JPEG when a web page asks for an image, so this rarely comes
up.

**Options.** Keep refusing HEIC, or add the `pillow-heif` dependency and
accept it.

**Recommendation.** Keep refusing. One more native dependency in a read-only
container isn't worth it for an upload the phone already converts.

## 8. `/api/logs/*` is keyed by coffee, not by shot

**Now.** `GET /api/logs`, `POST /api/logs/manual` and `PUT`/`DELETE
/api/logs/{bean_id}` manage coffees. The name predates that.

**Options.** Rename them to `/api/beans/*` and keep the old paths for one
release, or leave them.

**Recommendation.** Leave them. A rename breaks cached clients and fixes only
a name; `core/routes/coffees.py` explains it in its first lines.

## 9. alembic version differs between CI and the Docker image

**Now.** `pyproject.toml` allows `alembic>=1.13,<2.0`, while `requirements.txt`
(what the Docker image installs) pins `1.14.1`. CI installs from
`pyproject.toml`, so it tests a newer alembic than prod runs. Every other
runtime dependency is pinned identically in both files.

**Options.** Bump `requirements.txt` to the version CI resolves, or pin
`pyproject.toml` to `==1.14.1`. Either way, extend
`test_requirements_lock_mirrors_pyproject_packages` to compare versions as
well as names.

**Recommendation.** Bump `requirements.txt`, so prod runs what CI tests, and
extend the test.

## 10. `pip-audit` is advisory in CI

**Now.** The dependency audit runs with `continue-on-error: true`, so a known
vulnerability never turns CI red. mypy, which used to be advisory too, is now
blocking.

**Recommendation.** Keep it advisory, because advisories arrive without any
code change and would redden unrelated PRs. Read its output whenever
dependencies are bumped.

---

## Before and after deploying

These need the host rather than a decision:

1. **Take a fresh dump of prod first.** The deploy runs migrations 0007
   (equipment ownership) and 0008 (`data_quality` default) on startup. Use
   `docker compose -f compose.prod.yaml exec db-backup /backup.sh`, which is
   also step 2 of the deploy skill.
2. **Check that pgvector is really unused.** On both databases, run `\dx` and
   `\dt scraped_equipment` in `psql`. If `scraped_equipment` exists, CLAUDE.md's
   note needs correcting before anything else changes.
3. **After the deploy, see who owns what:**
   `SELECT id, owner, type, brand, model FROM equipment ORDER BY id;`. Rows
   with an empty owner are the shared, read-only ones (see #1).
4. **Tell friends to reload the app once**, so the new service worker takes
   over.
