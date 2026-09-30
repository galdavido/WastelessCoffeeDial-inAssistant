# Open decisions

What the streamline and review (PR #2) left for the owner to decide. When one
is settled, record the answer here, and delete it once the work lands.

The owner decided all ten on 2026-09-23. What has landed has been removed: #2
(Gemini only for a coffee's first recipe), #3 (starting dose as a fill of the
brewer's basket), #4 (migration 0009), #5 (a bed-depth dose term in the grind
law), #6 (the use-less-coffee suggestion) and #9 (alembic pinned identically in
both files). #1 turned out to be settled already: the shared Kingrinder K6 on
prod carries its documented 16 µm per click, so friends on a default setup get a
real starting grind.

The literature review of 2026-09-30 raised #11–#13
(`docs/science.md#open-conflicts`). The owner decided them the same day, and
both #11 and #12 have landed: temperature is now the last taste lever, with the
roast-level split kept as `LITERATURE`; the channeling floor is noise-aware,
warns on one sign and stops the grinder on two, and a deadband says "pull it
again" inside the noise. Alongside them, a shot that tasted balanced outside the
time band now keeps its grind.

## Decided: keep as is

These are recorded so they are not reopened without a reason.

- **13. Moka stays as it is for now.** The moka extract averages ~80 °C and
  the final sputtering phase extracts the harshest compounds (Navarini 2009),
  which argues for a heat-cut prompt. The owner set moka and pour-over aside
  (2026-09-30) to concentrate on espresso; revisit with a dedicated flow.

- **7. HEIC photos: keep refusing them.** Pillow has no HEIF decoder
  installed, and phones convert HEIC to JPEG when a web page asks for an
  image. One more native dependency in a read-only container isn't worth it.
- **8. `/api/logs/*` keeps its name.** It manages coffees, not shots, but a
  rename would break cached clients to fix a name. `core/routes/coffees.py`
  explains it in its first lines.
- **10. `pip-audit` stays advisory in CI.** Advisories arrive without any code
  change and would redden unrelated PRs. Read its output whenever
  dependencies are bumped.
