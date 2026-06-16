# Species-Level Pokedex Tracking

Status: ready-for-agent
Type: feature

## Problem

Aggregate Pokedex Entry Snapshot counts can say how many Pokemon are missing, but they cannot say which Pokemon are missing. The dashboard needs a separate species-level source for list views and evolution unlocks.

## Scope

- Add an editable local CSV for species-level completion state.
- Use columns: `date,account,entry_type,dex_number,registered,can_evolve_now,notes`.
- Add path helpers and data-file loader/normalizer.
- Validate account text, entry type, dex number, boolean fields, and date values.
- Join species rows to the Pokemon catalog for names, German names, regions, and availability.
- Add helper logic for latest species state per account, entry type, and dex number.

## Acceptance Criteria

- Loading a missing species-level file returns an empty dataframe with expected columns.
- Latest state keeps the newest row for each account/category/Pokemon.
- Boolean fields accept normal CSV values like `true`, `false`, `yes`, `no`, `1`, and `0`.
- Species rows can be enriched with catalog name and region data.
- Aggregate Pokedex snapshots remain unchanged.

## Testing

- Add data-file tests for loading and normalization.
- Add Pokedex helper tests for latest species state.
- Add tests for catalog enrichment.

## Comments
