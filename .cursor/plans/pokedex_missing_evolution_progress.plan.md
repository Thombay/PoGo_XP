---
name: Pokedex Missing And Evolution Progress
overview: Extend the Pokedex dashboard with release-aware max values, missing-count stats, species-level missing lists, per-line trend colors, evolution-unlock candidates, and additional progress graphs.
todos:
  - id: release-aware-max-values
    content: Clarify and enforce Pokedex entry config semantics for real Pokemon max values versus release-aware category max values.
    status: pending
  - id: missing-count-stats
    content: Add count-based missing stats overall and by region using latest Pokedex Entry Snapshot values plus configured max values.
    status: pending
  - id: unique-progress-line-colors
    content: Give each overall progress line its own deterministic color instead of coloring only by account.
    status: pending
  - id: species-level-tracking
    content: Add species-level Pokedex entry tracking so the app can list which Pokemon are missing in each category.
    status: pending
  - id: evolution-unlock-candidates
    content: Add evolution reference data and dashboard logic for entries unlockable by evolution right now.
    status: pending
  - id: new-pokedex-graphs
    content: Add focused Pokedex dashboard graphs for missing counts, progress percent, and evolution unlocks.
    status: pending
  - id: tests-and-docs
    content: Add focused tests and update docs for the new data sources and dashboard behavior.
    status: pending
isProject: false
---

# Pokedex Missing And Evolution Progress Plan

## Problem Statement

The current Pokedex dashboard can show saved Pokedex Entry Snapshot counts, but it does not yet answer the next questions:

- How many entries are missing overall and per region?
- Which exact Pokemon are missing in each category?
- Which missing entries can be unlocked immediately by evolving something already owned?
- How close is each account to the currently available max for non-normal categories?
- Can the progress chart visually distinguish every line?

The important domain rule is that `pokemon` uses the real full max value, while every other entry category uses the max value currently available in Pokemon GO. Those category max values are expected to increase as new shiny, lucky, XXL, XXS, G-Max, Mega, Shadow, Purified, or 100% entries become possible.

## Solution

Keep the existing aggregate snapshot model as the source for count progress, and add a separate species-level tracking model for name-level missing and evolution unlock views.

Aggregate count views should continue to use Pokedex Entry Snapshots. Missing counts are computed as:

```text
missing_count = configured_max_value - latest_snapshot_value
progress_pct = latest_snapshot_value / configured_max_value
```

For `pokemon`, configured max values represent the real regional/National Dex target. For all other entry types, configured max values represent the currently available Pokemon GO target. `overall` max values should be derived from regional config values wherever possible, so future releases only require updating regional config rows.

Species-name views need new data because aggregate counts cannot identify individual missing Pokemon. Add species-level completion data and evolution reference data, then join that data with the existing Pokemon catalog and latest account/category state.

Confirmed implementation choices:

- Track exact missing Pokemon with an editable species-level CSV keyed by account, entry type, and dex number.
- Keep current Pokemon GO category availability in editable config/reference CSVs.
- Determine "can unlock by evolution right now" with a manual `can_evolve_now` flag on owned source Pokemon.
- First graph slice includes missing by region/category, progress percent, and evolution unlock count. Broader chart ideas can wait.

## Implementation Scope

New species-level completion rows should capture the latest known state for one account, category, and Pokemon:

```text
date,account,entry_type,dex_number,registered,can_evolve_now,notes
```

New category availability rows should define which Pokemon are currently valid targets for a category:

```text
entry_type,dex_number,available,notes
```

New evolution reference rows should define editable Pokemon GO evolution edges:

```text
source_dex_number,target_dex_number,method,notes
```

The first implementation should not try to make species rows and aggregate count rows reconcile perfectly. Aggregate snapshots answer "how many"; species rows answer "which ones." If they disagree, the dashboard should label them as separate sources rather than silently forcing one to match the other.

## Commits

1. Clarify Pokedex max-value semantics
   - Document that `pokemon` max values are full real targets.
   - Document that non-`pokemon` max values are current Pokemon GO availability targets.
   - Treat config updates as normal release maintenance, not code changes.
   - Add tests proving locked `overall` rows are not manually saved and regional max values remain the validation source for input cells.

2. Add release-aware target helpers
   - Build a pure helper that normalizes Pokedex config rows into target rows by entry type and region.
   - Derive `overall` target max from the non-overall regions.
   - Preserve the configured `pokemon` full max behavior.
   - Return labels, max values, and locked state for dashboard use.
   - Add tests for `pokemon`, shiny-style categories, locked regions, zero-max regions, and derived `overall`.

3. Add missing-count dashboard data
   - Build a pure helper that joins latest Pokedex Entry Snapshot values to target max rows.
   - Add `missing_count` and `progress_pct` columns.
   - Clamp missing counts at zero for display, but keep validation errors for saved values above max.
   - Support both overall and regional summaries.
   - Add tests for latest-as-of-date behavior, missing regions with no snapshot yet, and selected-account filtering.

4. Add missing-count UI
   - Add headline metrics for total missing entries in the selected categories.
   - Add a regional missing table with account, category, region, latest value, max value, missing count, and progress percent.
   - Keep empty states clear when selected filters have no usable snapshot rows.
   - Reuse existing labels for accounts, entry types, and regions.

5. Give every progress line a unique color
   - Change the overall progress chart series identity from just account color plus entry-type dash to a combined series key such as account plus entry type.
   - Generate a deterministic color map for every visible line.
   - Keep the legend readable by showing labels like `Thombay - Shiny`.
   - Add a test for stable series labels/color keys if the color-key helper is pure.

6. Add species-level entry tracking
   - Add a new species-level CSV for account/category/dex-number completion state.
   - Include date, account, entry type, dex number, registered state, `can_evolve_now`, and notes.
   - Load and normalize this data through the existing data-files layer.
   - Join it to the Pokemon catalog for names, German names, regions, and availability.
   - Treat aggregate Pokedex Entry Snapshots as count truth and species-level rows as list truth until the two can be reconciled.
   - Add tests for latest species state per account/category/dex number.

7. Add missing-Pokemon list helpers
   - Build a pure helper that finds missing Pokemon by account, category, and region.
   - For `pokemon`, use the full catalog target.
   - For non-`pokemon` categories, use the editable category availability reference.
   - Include filters for account, entry type, region, and availability.
   - Add tests showing that aggregate counts alone are not required for the missing list.

8. Add evolution reference data
   - Add a reference source for evolution edges: source dex number, target dex number, method, item notes, and optional constraints.
   - Keep this editable/manual at first, because Pokemon GO evolution rules can differ from main-series Pokemon data.
   - Add a loader and tests for valid evolution edges.

9. Add evolution-unlock candidate helpers
   - Build a pure helper that returns missing target entries where a registered source entry can evolve into the target.
   - Use the manual `can_evolve_now` flag from species-level state for the source Pokemon, because the app cannot know candy/items from aggregate counts.
   - For categories that preserve through evolution, match source and target entry type, such as shiny source to shiny target.
   - Exclude categories where evolution does not unlock the target in a meaningful way unless explicitly supported.
   - Add tests for normal, shiny, lucky, hundo, and an unavailable/blocked evolution.

10. Add species and evolution dashboard UI
    - Add a view mode or tabs for `Missing Pokemon` and `Evolution Unlocks`.
    - Show missing Pokemon with dex number, name, German name, region, category, account, and notes.
    - Show evolution unlocks with source Pokemon, target Pokemon, category, account, method, and why it is currently unlockable.
    - Add download buttons for the missing and evolution tables if that matches existing dashboard style.

11. Add new Pokedex graphs
    - Add a missing-count bar chart by region and category.
    - Add a progress-percent chart by account and category.
    - Add an evolution-unlock count chart by account/category.
    - Defer heatmaps and broader exploratory graphs until after the first slice is usable.

12. Update docs and run verification
    - Document the aggregate snapshot source, config source, species-level source, and evolution source.
    - Explain why count-based missing stats and name-level missing lists come from different data.
    - Add focused unit tests for the pure helpers.
    - Run the existing Pokedex test suite plus any new tests.
    - Manually verify the Streamlit dashboard with current sample data.

## Decision Document

- `pokemon` max values mean real full Pokedex max values.
- Non-`pokemon` max values mean currently available Pokemon GO max values and may increase later.
- The existing Pokedex entry config remains the count-target source.
- Derived `overall` targets should come from regional target rows, not from manually entered dashboard logic.
- Aggregate Pokedex Entry Snapshots remain the source for count progress.
- A new editable species-level CSV is required to answer which Pokemon are missing.
- Non-normal category availability should stay in editable CSV reference/config data first.
- Evolution-unlock candidates require explicit manual "can evolve now" state, because candy, items, forms, and account inventory are not inferable from aggregate snapshots.
- Evolution reference data should start as editable local reference data rather than relying fully on an external API.
- Progress chart colors should be assigned by visible line identity, not only by account.
- The first dashboard graph slice is missing by region/category, progress percent, and evolution unlock count.

## Testing Decisions

- Test pure data helpers first: target normalization, missing-count summaries, species latest state, missing-list generation, evolution candidates, and progress series keys.
- UI tests are not required initially; keep dashboard behavior covered through helper tests and manual Streamlit verification.
- Existing tests in the Pokedex area are the closest prior art and should be extended rather than duplicated elsewhere.
- Good tests should assert user-facing behavior: latest values, missing counts, missing species, unlock candidates, labels, and empty states.

## Out Of Scope

- Automatic live sync from a Pokemon GO account.
- Automatic knowledge of candy, evolution items, buddy requirements, trades, forms, or event-only evolution windows unless manually recorded.
- Fully automatic shiny/shadow/purified/G-Max/Mega availability scraping in the first implementation.
- Replacing aggregate Pokedex Entry Snapshots with species-level tracking.
- Backfilling exact historical species-level ownership from aggregate counts, because counts do not contain names.
