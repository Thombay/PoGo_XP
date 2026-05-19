---
name: "Separate Pokédex Medal And Entry Saves "
overview: "Separate regional Pokédex medal values from Pokédex entry values so both save flows remain independent, while preserving historical medal-derived Pokémon region rows as seeded Pokédex history. "
todos:
  - id: document-domain-boundary
    content: "Keep the domain language clear: medal snapshots and Pokédex entry snapshots are separate observations that may differ. "
    status: completed
  - id: migrate-historical-pokemon-rows
    content: "Add a fill-only migration for historical regional medal rows into missing `pokemon` Pokédex entry rows. "
    status: completed
  - id: make-pokemon-regions-editable
    content: "Let the Pokédex entry input save regional `pokemon` counts directly, including `unidentified`. "
    status: completed
  - id: remove-medal-derived-main-values
    content: "Stop using regional medal rows as main Pokédex display values; show them only as reference values. "
    status: completed
  - id: define-seeded-correction-behavior
    content: "Watch after implementation whether seeded historical rows need a correction workflow when exact Pokédex values are lower. "
    status: pending
  - id: update-tests-and-docs
    content: "Update tests, README, config notes, Streamlit captions, and stale dashboard planning for the separated save behavior and migration rule. "
    status: completed
isProject: false
---

# Separate Pokédex Medal And Entry Saves Plan

## Decisions
- **Medal snapshots** and **Pokédex entry snapshots** are separate observations. They may describe similar Pokémon region progress, but they are not the same source of truth.
- Regional `pokemon` counts in `inputs/data/pokedex_entry_snapshots.csv` become first-class Pokédex entry rows for regions `kanto` through `paldea` plus `unidentified`.
- `pokemon/overall` remains derived from regional Pokédex entry rows and is not saved manually.
- Medal values remain visible in the Pokédex input UI as reference values only. They must not overwrite the main Pokédex values.
- Historical data should be seeded from regional medal rows because it is the best available pre-separation history, even though it may not be exact.
- The separation date is the implementation/migration date. Before that date, seeded regional `pokemon` rows are approximate medal-derived history; after that date, new regional `pokemon` rows are direct Pokédex observations.
- The migration is fill-only: it copies all historical regional medal rows into missing regional `pokemon` Pokédex entry rows, but never overwrites existing Pokédex entry rows.
- A later intentional Pokédex save for the same account/date/category may replace seeded approximate rows with exact values.
- Migration must run before the main Pokédex display stops merging medal-derived rows, otherwise regional `pokemon` values will temporarily disappear from the UI.
- Medal reference values in the Pokédex input should be looked up as of the selected Pokédex date, not as the latest medal value globally.
- After migration, old dates may appear as already saved for the `pokemon` category because seeded rows exist. Treat that as intentional historical behavior.
- If seeded rows later prove too high, handle that as a post-implementation data correction concern instead of weakening normal Pokédex save validation now.
- The CSV schema stays unchanged for now; seeded vs direct rows are distinguished by the documented separation date, not by a `source` column.

## Current Code Shape
- `webapp/app.py` currently builds `display_pokedex_df` by calling `with_medal_derived_pokedex_rows(pokedex_df, medal_df)`.
- `with_medal_derived_pokedex_rows(...)` maps medal IDs in `POKEDEX_MEDAL_REGION_IDS` to `entry_type = "pokemon"` rows, then derives `overall`.
- `_is_medal_derived_pokedex_cell(...)` makes `pokemon` regional cells read-only in the Pokédex input UI.
- `build_pokedex_category_snapshot_rows(...)` and `upsert_pokedex_entry_rows(...)` skip medal-derived `pokemon` cells, so those values cannot currently be saved as Pokédex entry rows.
- The admin/latest Pokédex summary also uses `display_pokedex_df`, so it currently counts medal-derived rows as if they were Pokédex entry rows.
- When both a Pokédex row and a medal row exist for the same date/account/pokemon/region, the current medal merge can let the medal-derived value win in display data.
- `inputs/config/pokedex_entry_config.csv`, the Pokédex input captions, and `README.md` still describe regional `pokemon` values as medal-derived.
- `.cursor/plans/pokedex_dashboard_5a357165.plan.md` has been reconciled to depend on saved Pokédex entry rows instead of the old medal-derived display pipeline.
- Existing tests in `tests/test_pokedex_entries.py` lock in the old behavior and will need to be updated.

## Implementation Order
1. Add and test the fill-only migration helper.
2. Run the migration on current repo data so `pokedex_entry_snapshots.csv` has historical regional `pokemon` rows before display behavior changes.
3. Switch main Pokédex display and admin/latest summaries to use saved Pokédex entry rows plus derived `overall`, not medal-derived rows.
4. Make regional `pokemon` cells editable/savable and add medal references beside them.
5. Update tests, README, config notes, Streamlit captions, and the stale dashboard plan.

## Implementation Plan
1. Add a migration helper for seeded regional `pokemon` rows.
   - Read existing medal snapshots.
   - Keep only regional medal IDs in `POKEDEX_MEDAL_REGION_IDS`.
   - Dedupe duplicate `(date, account, medal_id)` rows consistently with current medal loading/display behavior, keeping the last value.
   - Convert each row to `date,account,entry_type,region,value` with `entry_type = "pokemon"`.
   - Merge into `inputs/data/pokedex_entry_snapshots.csv` only where the exact `date/account/pokemon/region` row is missing.
   - Do not create `pokemon/unidentified` rows during migration because no medal maps to it.
   - Preserve `utf-8-sig` encoding and the existing columns: `date,account,entry_type,region,value`.
   - Treat this migration as mandatory for the display cutover, whether it is implemented as a one-off tool or a maintenance helper.

2. Make regional `pokemon` cells normal Pokédex entry cells.
   - Change `_is_medal_derived_pokedex_cell(...)` usage so regional `pokemon` cells are no longer excluded from editable/savable Pokédex inputs.
   - Keep `overall` read-only and derived.
   - Keep locked/max validation from `inputs/config/pokedex_entry_config.csv`.
   - Save `pokemon` as a full category row, matching the current full-category behavior for other Pokédex entry types.
   - Include all savable regional `pokemon` cells in the category draft, including `unidentified`.
   - Expect the per-date completion count to increase because `pokemon` now has normal editable regional cells.

3. Separate main Pokédex values from medal reference values.
   - Replace the current `display_pokedex_df = with_medal_derived_pokedex_rows(...)` behavior for main Pokédex values.
   - Build main Pokédex display values from `pokedex_entry_snapshots.csv` plus derived `overall` rows only, for example with `with_derived_pokedex_overall_rows(pokedex_df)`.
   - Update the admin/latest Pokédex summary to use the same saved-entry display data, not medal-derived rows.
   - Add a separate reference lookup for regional medal values by account/date/region using the latest medal row on or before the selected Pokédex date.
   - In the `pokemon` row of the Pokédex input UI, show the medal reference beside or under the editable value without using it as the saved value.
   - Do not reuse `with_medal_derived_pokedex_rows(...)` for main display after separation; if it survives, restrict it to migration/reference-only behavior.

4. Preserve correction behavior.
   - Keep `upsert_pokedex_entry_rows(...)` replacing rows for the same `date/account/entry_type/region`, so exact Pokédex saves can correct seeded historical approximations.
   - Keep non-decreasing validation for Pokédex entry rows.
   - Do not add a broad validation bypass during the first implementation.
   - Watch after implementation whether seeded values copied from medals are ever too high for exact Pokédex observations.
   - If that happens, add a targeted seeded-history correction workflow instead of changing normal Pokédex save rules.

5. Update documentation.
   - Update `README.md` Data Input notes to say regional `pokemon` counts are saved in Pokédex entries, while medal values are reference-only.
   - Update `inputs/config/pokedex_entry_config.csv` notes that currently say regional `pokemon` rows are derived from medal input.
   - Update Pokédex input captions in `webapp/app.py` so they describe saved values plus medal references.
   - Keep `.cursor/plans/pokedex_dashboard_5a357165.plan.md` aligned so future dashboard work does not use medal-derived `pokemon` rows as main data.
   - Document that historical regional `pokemon` rows before the migration date were seeded from regional medal snapshots.
   - Keep `CONTEXT.md` as the glossary for the domain distinction.

## Test Plan
- Update tests that currently expect regional `pokemon` cells to be skipped.
- Add a migration test proving medal rows become missing `pokemon` rows and existing Pokédex rows are not overwritten.
- Add migration coverage for duplicate medal rows, multiple accounts, and keeping the last medal value for each date/account/region.
- Add a test proving `pokemon/unidentified` is not seeded from medals but remains editable/savable.
- Add a test proving main Pokédex display values come from Pokédex snapshots, not medal-derived rows.
- Add a test where saved `pokemon/kanto` and medal `kanto` differ; the main Pokédex value must use the saved Pokédex row.
- Add a test for the medal reference lookup using the latest regional medal value on or before the selected Pokédex date.
- Add coverage for `pokemon` row loading/normalization in `tests/test_data_files.py`.
- Add a save test for `pokemon/kanto` with configured max validation.
- Keep tests for derived `overall` rows and non-decreasing validation.
- Run `python -m unittest -v tests.test_data_files tests.test_pokedex_entries`.

## Open Implementation Details
- Exact UI presentation for medal references: compact text below each regional `pokemon` input is probably enough, but this can be adjusted during implementation.
- Whether the migration runs as a one-off tool or as an explicit maintenance function called once during implementation; either way, it must be run before display cutover.
- Whether to add a future `source` column remains deferred; the current plan keeps the CSV schema unchanged.

## Post-Implementation Watch Items
- Watch for seeded historical `pokemon` rows that are higher than exact Pokédex observations. If this happens in real data, add a targeted correction workflow for seeded pre-separation rows while keeping normal Pokédex entry validation strict.
