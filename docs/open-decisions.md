# Open decisions

What the streamline and review (PR #2) left for the owner to decide. When one
is settled, record the answer here, and delete it once the work lands.

The owner decided all ten on 2026-09-23. What has landed has been removed:
#2 (Gemini only for a coffee's first recipe), #3 (starting dose as a fill of
the brewer's basket), #4 (migration 0009) and #9 (alembic pinned identically
in both files). #1 turned out to be settled already: the shared Kingrinder K6
on prod carries its documented 16 µm per click, so friends on a default setup
get a real starting grind.

## Decided, work in progress

| # | Decision | Answer |
|---|---|---|
| 5 | A dose term in the grind law | Build it: `+ γ·ln(dose)`, refit, tests, science.md |
| 6 | The "use less coffee" (Cameron) suggestion | Build it after #5, whose dose term the trigger needs |

**5. Dose term.** The grind law has no dose term
(`docs/science.md#beta-law`, "Missing term: dose"). A dose you ask for is
honoured, but the grind is still worked out at the last shot's dose, and the
per-coffee offset absorbs dose differences.

**6. Cameron.** `docs/science.md#cameron-reproducibility` describes using
about 20% less coffee and grinding coarser when a shot keeps channeling. No
code suggests it yet.

## Decided: keep as is

These are recorded so they are not reopened without a reason.

- **7. HEIC photos: keep refusing them.** Pillow has no HEIF decoder
  installed, and phones convert HEIC to JPEG when a web page asks for an
  image. One more native dependency in a read-only container isn't worth it.
- **8. `/api/logs/*` keeps its name.** It manages coffees, not shots, but a
  rename would break cached clients to fix a name. `core/routes/coffees.py`
  explains it in its first lines.
- **10. `pip-audit` stays advisory in CI.** Advisories arrive without any code
  change and would redden unrelated PRs. Read its output whenever
  dependencies are bumped.
