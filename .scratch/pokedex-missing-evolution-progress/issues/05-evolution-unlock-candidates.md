# Evolution Unlock Candidates

Status: ready-for-agent
Type: feature

## Problem

Users need to know which missing Pokedex entries can be unlocked by evolution right now. Aggregate counts cannot infer evolution paths, candy, items, or account readiness.

## Scope

- Add editable local CSV data for Pokemon GO evolution edges.
- Use columns: `source_dex_number,target_dex_number,method,notes`.
- Load and normalize evolution reference rows through the data layer.
- Build a helper that returns missing target entries where the source entry is registered and marked `can_evolve_now`.
- Match source and target entry type for categories that preserve through evolution, such as shiny, lucky, and hundo.
- Exclude unavailable category targets.
- Include source Pokemon, target Pokemon, account, category, region, method, and notes.

## Acceptance Criteria

- Evolution unlocks require a missing target entry.
- Evolution unlocks require a registered source entry.
- Evolution unlocks require `can_evolve_now` on the source species state.
- Unavailable category targets do not appear.
- Output explains why each target is unlockable.

## Testing

- Add data-file tests for evolution reference loading.
- Add helper tests for normal, shiny, lucky, and hundo unlocks.
- Add tests for blocked candidates when source is missing, target already registered, `can_evolve_now` is false, or target is unavailable.

## Comments
