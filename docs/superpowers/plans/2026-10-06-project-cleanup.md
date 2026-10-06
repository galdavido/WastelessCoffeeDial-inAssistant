# Project Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Leave the repo so a developer opening it cold tomorrow finds one
obvious place for each thing: no duplicated logic, tests named after what they
test, docs that agree with the code, and no stray files on disk.

**Architecture:** No behaviour changes. Every task is a refactor, rename,
deletion, added test or doc edit, and the existing 335 tests must survive
unchanged in result.

**Tech Stack:** Python 3.12+ / FastAPI / SQLAlchemy 2.0 / Alembic / pytest
(unittest-style), vanilla-JS PWA.

**Spec:** the owner's request of 2026-10-06: "Deduplicate things, delete
unnecessary folders and files, review the tests, update .md files … streamline
the whole thing." This plan is the spec's expansion; the audit below is its
evidence.

## Audit (2026-10-06, `main` @ `9a79912`)

What is already healthy, so nobody spends tomorrow re-checking it:

- `ruff check`, `ruff format --check`, `mypy src`: all clean.
- `pytest` against a disposable Postgres with `CI=1`: exits 0, 335 tests,
  **85 % line coverage**.
- Frontend: no unused JS functions, CSS classes or ids in `app.js` /
  `admin.js` / `style.css` / `admin.css`; no `console.log`, no TODO/FIXME
  anywhere in the repo.
- `requirements.txt` duplicates `pyproject.toml` on purpose (Docker layer
  cache), and `tests/test_project_conventions.py` already pins the two
  together. **Keep both.**

What needs work:

| # | Finding | Where |
| --- | --- | --- |
| A | The name-match-then-build-a-`Bean` logic exists twice, nearly line for line (the recommendation route resolves `bean_id` itself, before it gets here) | `routes/recipe.py:50` `_bean_for`, `web_helpers.py:476` `_bean_for_shot` |
| B | `web_helpers.py` (587 lines) is a grab bag: text parsing, settings, setups, equipment, serialisers and shot saving | `src/core/web_helpers.py` |
| C | Dead code: `BacktestReport.any_sufficient`, `Target.source_anchor` (set but never read), `_sim.BedParams.particle_um` | `eval_harness.py:86`, `brewing.py:382`, `tests/_sim.py:68` |
| D | The same `K6 = GrinderCaps(...)` / `MachineCaps(...)` fixture is copy-pasted into 8 test files | `tests/test_*.py` |
| E | Test files are named after the change that added them, not the code they cover (`test_ai_refactors`, `test_recents_photo`, `test_use_less_coffee`, `test_data_integrity`) | `tests/` |
| F | Coverage holes: `backtest_cli.py` 0 %, `admin_stats.py` 28 %, `ai/vision.py` 57 %, `ai/rationale.py` 58 % | coverage report |
| G | CLAUDE.md says bag OCR is budgeted 20 s; the code says `VISION_BUDGET_S = 45.0` | `CLAUDE.md` "Gotchas", `ai/model_selection.py:54` |
| H | CLAUDE.md says to commit `docs/SESSION-STATE.md`; `.gitignore` excludes it (local-only by design) | `CLAUDE.md:28-30`, `.gitignore` |
| I | README and CLAUDE.md both carry the run/DB/test instructions, in slightly different words | `README.md`, `CLAUDE.md` "Running it", "Database" |
| J | `docs/open-decisions.md` now holds only settled "keep as is" decisions | `docs/open-decisions.md` |
| K | Three orphaned worktree dirs (~58 MB, root-owned caches inside); git has no record of them | `.claude/worktrees/bridge-cse_*` |
| L | `wcda-v48` (`c531e07`, `9a79912`) is pushed but deployed to neither stack | `docs/SESSION-STATE.md` |

## Global Constraints

- **Test count never drops.** Record `pytest --collect-only -q | tail -1` before
  Task 1; every later task ends at that number or higher.
- **No migrations, no schema changes.** `tds_pct`, `inputs_json` and the other
  columns vulture flags are written by the engine or reserved (see migration
  0009); they stay.
- **No route paths change**, including the misnamed `/api/logs/*`
  (open decision #8).
- Renames use `git mv` so history follows the file.
- A static asset change bumps `CACHE` in `sw.js` and every `?v=` (CLAUDE.md
  "Frontend conventions"). No task here should touch static assets; if one
  does, that rule applies.
- Run the full check before each commit:
  `ruff check . && ruff format --check . && mypy src && pytest` with
  `DATABASE_URL` set to a **disposable** Postgres, never `wcda-dev-db` and never
  the prod database.
- Commit trailer per CLAUDE.md.

## Review Focus

1. **A first scan of a coffee never brewed before.** After Task 2 the transient
   stand-in must still carry `roast_level_ord` and `roast_date`, or retrieval
   and the roast-level temperature band silently go blind. Test lives in
   Task 2.
2. **A shot logged with a `bean_id` from another user's library.** Expect:
   the id is ignored, and the shot lands on the caller's own coffee (today's
   behaviour). Nothing tests this yet; the test lives in Task 2.
3. **Import paths after the `web_helpers` split.** Expect: every
   `from core.web_helpers import X` in `src/` and `tests/` is updated, and no
   compatibility shim is left behind. Task 3's step 4 greps for it.
4. **A renamed test file whose name collides in pytest's rootdir import mode**
   (two `test_brewing.py` files, say). Expect: collection succeeds with the same
   count. Task 5 checks the count.
5. **Deleting a worktree dir that is still in use.** Expect: only dirs absent
   from `git worktree list` are removed. Task 0 checks that first.

---

### Task 0: Host housekeeping and the pending deploy (no code)

**Files:** none in git.

- [ ] **Step 1: Deploy `wcda-v48`** with the `deploy` skill (prod, then dev), so
  the cleanup is not stacked on top of two undeployed fixes. Expected: both
  `/api/version` report asset version 48.
- [ ] **Step 2: Remove orphaned worktrees.** For each `.claude/worktrees/*` dir
  **not** listed by `git worktree list`, remove it. The caches inside are
  root-owned, so run
  `docker run --rm -v "$PWD/.claude/worktrees:/w" alpine rm -rf /w/<name>`.
  Then `git worktree prune`. Expected: `ls .claude/worktrees` shows only
  registered worktrees.
- [ ] **Step 3: Clear stale local caches** in the main checkout
  (`.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `src/wcda.egg-info`,
  `__pycache__`; all gitignored, some root-owned) the same way. Leave `data/`,
  `backups/` and `.env` alone.

### Task 1: Delete dead code

**Files:**

- Modify: `src/core/eval_harness.py:86-88` (drop `any_sufficient`)
- Modify: `src/core/brewing.py:382` and every `Target(...)` construction (drop
  `source_anchor`, unless `test_science_doc.py` turns out to read it, in which
  case keep it and note why in a comment)
- Modify: `tests/_sim.py:68,178` (drop `particle_um`)

- [ ] **Step 1:** Record the baseline: `pytest --collect-only -q | tail -1`
  (expected `335 tests collected`).
- [ ] **Step 2:** Remove the three members. `grep -rn "any_sufficient\|source_anchor\|particle_um" src tests`
  returns nothing.
- [ ] **Step 3:** Full check passes, same count.
- [ ] **Step 4:** Commit `chore: drop three unused members`.

### Task 2: One bean lookup (finding A)

**Files:**

- Modify: `src/core/web_helpers.py` (`_bean_for_shot`; the new helpers live
  here until Task 3 moves them to `core/beans.py`)
- Modify: `src/core/routes/recipe.py:50-78` (delete `_bean_for`)
- Test: `tests/test_data_integrity.py` (renamed in Task 5), `tests/test_api_flows.py`

**Interfaces:**

- Produces:
  - `transient_bean(owner: str, coffee_data: dict[str, Any]) -> Bean`: an
    unsaved `Bean` from the five text fields, `roast_date` and
    `roast_level_ord`.
  - `match_bean(db: Session, owner: str, coffee_data: dict[str, Any]) -> Bean | None`:
    `find_existing_bean` over the normalised name, roaster, origin and process.
- `routes/recipe._recommend` uses `match_bean(...) or transient_bean(...)`.
  The shot path keeps its owner-checked explicit-`bean_id` branch, then
  `match_bean`, then `transient_bean` followed by `db.add` and `db.flush`.

- [ ] **Step 1: Write the tests.**
  - `test_transient_bean_carries_roast_fields` (DB-free): `coffee_data` is
    `{"name": "X", "roast_level": "Medium-dark", "roast_date": "2026-09-01"}`.
    Assert that `roast_level_ord == roast_level_ordinal("Medium-dark")`, that
    `roast_date == date(2026, 9, 1)`, that `owner` is set, and that
    `origin == "Unknown"`. It fails on import, since the function doesn't
    exist yet.
  - `TestOwnershipOfDerivedRows.test_a_shot_cannot_land_on_another_users_coffee`
    (API flow): user B posts `/api/feedback` with user A's `bean_id` and a new
    name. Assert that A's coffee has no new shot and that B's library now holds
    the coffee. This one passes today; it pins the behaviour before the
    refactor.
- [ ] **Step 2:** Implement both helpers. Delete `_bean_for` and repoint both
  callers.
- [ ] **Step 3:** Full check passes, and the count is the baseline + 2.
- [ ] **Step 4:** Commit `refactor: one bean match/stand-in for recipes and shots`.

### Task 3: Split `web_helpers.py` by responsibility (finding B)

**Files** (move only; bodies unchanged except imports):

| New module | Takes from `web_helpers.py` |
| --- | --- |
| `src/core/parsing.py` | `as_non_empty_text`, `parse_grind_clicks`, `parse_roast_date`, `plausible_roast_date`, `roast_level_ordinal`, `normalize_label`, `_name_similarity` |
| `src/core/beans.py` | `find_existing_bean`, `match_bean`, `transient_bean`, `_bean_for_shot`, `bean_coffee_data`, `latest_photo_log`, `starting_dose_for_roast` |
| `src/core/setups.py` | `get_setting`, `set_setting`, `get_default_dose_g`, `set_default_dose_g`, `ensure_default_equipment`, `ensure_default_setup`, `get_active_setup`, `serialize_setup`, `serialize_equipment` |
| `src/core/shots.py` | `classify_data_quality`, `resolve_log_values`, `new_shot`, `save_shot` |
| `src/core/routes/meta.py` | `read_asset_version` (its only caller) |

`web_helpers.py` is deleted. Check each function's callers with grep before
moving it; if one belongs better elsewhere, follow its callers.

- [ ] **Step 1:** Move the functions. Update imports in `src/` and `tests/`.
- [ ] **Step 2:** `grep -rn "web_helpers" src tests docs *.md` returns nothing,
  apart from history in the science doc, if any.
- [ ] **Step 3:** Full check passes, same count. `mypy src` stays clean, with
  no new `# type: ignore`.
- [ ] **Step 4:** Update the layout lists in `CLAUDE.md` and `README.md`, in
  the same commit.
- [ ] **Step 5:** Commit `refactor: split web_helpers into parsing, beans, setups, shots`.

### Task 4: Shared test fixtures (finding D)

**Files:**

- Create: `tests/_fixtures.py` exporting `K6: GrinderCaps` (16 µm/click,
  0–90, step 1, `lower_is_finer`, exactly as currently copied) and
  `MACHINE_18G: MachineCaps(basket_size_g=18.0)`.
- Modify: the 8 files that define their own copy. Check each copy is
  byte-identical first; where one differs, keep it local, with a comment saying
  why.

- [ ] **Step 1:** Replace the local definitions with
  `from _fixtures import K6, MACHINE_18G`, the same import style as `_sim`.
- [ ] **Step 2:** Full check passes, same count.
- [ ] **Step 3:** Commit `test: share the K6 and 18 g basket fixtures`.

### Task 5: Name test files after what they test (finding E)

Every move is a `git mv`, plus a merge where two small files cover one module:

| From | To |
| --- | --- |
| `test_ai_refactors.py` | `test_model_selection.py` (move the one `vision` parse test into `test_vision.py`) |
| `test_rationale_guard.py` | `test_rationale.py` |
| `test_data_integrity.py` + `test_recents_photo.py` | `test_shots.py` and `test_parsing.py` / `test_beans.py`, following Task 3's modules |
| `test_use_less_coffee.py` | `test_brewing_dose_reduction.py` |
| `test_dose_term.py` | `test_brewing_dose_term.py` |
| `test_preinfusion.py` | `test_brewing_preinfusion.py` |
| `test_correction_policy.py` | `test_brewing_correction.py` |
| `test_brewing_physics.py`, `test_bean_scoping.py`, `test_fit_view.py`, `test_retrieval.py`, `test_eval_harness.py`, `test_admin.py`, `test_api_flows.py`, `test_web_app.py`, `test_science_doc.py`, `test_project_conventions.py`, `test_schema_models.py` | unchanged |

Rename the `TestAiRefactors` class too; keep the test method names, since they
already read as behaviour.

- [ ] **Step 1:** Do the moves. Update every docstring that says "following
  the pattern in test_web_app.py" or names an old file.
- [ ] **Step 2:** `pytest --collect-only -q | tail -1` matches the
  post-Task-2 count (baseline + 2).
- [ ] **Step 3:** Commit `test: name test files after the module they cover`.

### Task 6: Close the worst coverage holes (finding F)

**Files:**

- Create: `tests/test_backtest_cli.py`: `cli()` run against a stubbed
  shot source. Assert that it exits 0, prints one line per metric, and opens no
  write session. Use whatever seam `eval_harness` already exposes.
- Modify: `tests/test_admin.py`: extend it over `admin_stats` against the
  disposable DB fixture in `tests/_db.py`. Seed two users' shots, then assert the
  per-user counts and that the stats query never selects across a `WHERE owner`
  it should not.
- Modify: `tests/test_rationale.py`: the template-fallback branch
  (`rationale.py:182-249`). With the model chain stubbed to fail, the prose is
  the deterministic template and contains no numeral outside the allow-list.

`vision.py`'s uncovered block is the live Gemini call. Leave it uncovered.

- [ ] **Step 1:** Write the tests. Run them; they pass against current code,
  because this is coverage, not a fix. If one fails, stop: that is a bug, and it
  needs its own task.
- [ ] **Step 2:** Coverage: `backtest_cli` ≥ 80 %, `admin_stats` ≥ 70 %,
  `rationale` ≥ 80 %. TOTAL ≥ 88 %.
- [ ] **Step 3:** Commit `test: cover backtest CLI, admin stats and the rationale fallback`.

### Task 7: Docs agree with the code, and say each thing once (G–J)

**Files:** `README.md`, `CLAUDE.md`, `docs/open-decisions.md` (delete),
`.github/pull_request_template.md`.

Division of labour after this task:

- **README.md**: the human onboarding path. What it is, a five-line request
  flow (scan → `vision` → `engine.recommend` → `retrieval` → `calibration` →
  `brewing` → `rationale`), configuration, run, test, layout, security model.
  It is the only place the run, DB and test commands are written out.
- **CLAUDE.md**: the rules and traps an agent or a new developer would
  otherwise trip on. It links to README for the commands instead of repeating
  them.
- **docs/science.md**: unchanged; `test_science_doc.py` pins it.
- **docs/tailscale-setup.md**: unchanged, apart from a pass for anything Task 3
  renamed.

- [ ] **Step 1 (G):** Fix the OCR budget in CLAUDE.md to read from the code:
  45 s chain, 22 s per attempt (`VISION_BUDGET_S`, `VISION_ATTEMPT_TIMEOUT_S`),
  and 4 s / 2 s for the rationale.
- [ ] **Step 2 (H):** Change the commit-discipline bullet: `SESSION-STATE.md`
  is gitignored and local. Update it but never commit it.
- [ ] **Step 3 (I):** Cut CLAUDE.md's "Running it" and "Database" sections down
  to the traps: the port ownership, the `db` alias incident, `up web` skipping
  `db-backup`, the dumps that are plain SQL despite `.sql.gz`, never pruning
  volumes, and pgvector staying. Point everything else at README. Collapse the
  volume-rename history (2026-08 / 2026-09-08) to two sentences.
- [ ] **Step 4 (J):** Move the four settled "keep as is" decisions (#7 HEIC,
  #8 `/api/logs`, #10 pip-audit advisory, #13 moka) into a short
  "Decided, don't reopen" list in CLAUDE.md. Delete `docs/open-decisions.md`,
  and its mention in README's layout block.
- [ ] **Step 5:** Trim the PR template to Description, Testing and the checks
  line. Drop "Closes #", "Verified against requirements in linked issue" and
  the type-of-change boxes, which a solo repo never fills in.
- [ ] **Step 6:** `npx markdownlint-cli2 "**/*.md"` is clean, if available.
  The full check still passes, since `test_science_doc` and
  `test_project_conventions` read docs.
- [ ] **Step 7:** Commit `docs: one home for each instruction, fix drift`.

### Task 8: Wrap up

- [ ] **Step 1:** Delete this plan file. It has served its purpose, and plans
  left in `docs/` go stale.
- [ ] **Step 2:** Run the full check one final time and record the counts and
  coverage in the PR description.
- [ ] **Step 3:** Open the PR to `main`. After merge, deploy with the `deploy`
  skill. No static asset changed, so `wcda-v48` stays.
- [ ] **Step 4:** Update `docs/SESSION-STATE.md` (local only).

---

## Considered and not doing

- **Splitting `brewing.py` (1,819 lines) into a package.** It is pure and
  already sectioned (constants → types →
  physics → channeling → correction). A split is mostly import churn. Revisit
  only if a section grows past ~600 lines.
- **Splitting `app.js` (2,458 lines).** There is no build step, so splitting
  means more `<script>` tags, more precache entries and a CSP review, for no
  runtime gain.
- **Converting the tests from `unittest.TestCase` to bare pytest.** The style
  is consistent across all 19 files. Churn without benefit.
- **Dropping `requirements.txt`.** It keeps the Docker dependency layer cached,
  and a test already prevents drift.
- **Aligning the Python floor (3.12) with the runtime (3.14).** It works
  as it is. Raising the floor is a decision for the owner, not a cleanup.
