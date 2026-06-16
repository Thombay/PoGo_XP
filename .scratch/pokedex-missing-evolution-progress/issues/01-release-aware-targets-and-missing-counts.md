# Release-Aware Targets And Missing Counts

Status: ready-for-agent
Type: feature

## Problem

The Pokedex dashboard has latest count views, but it does not calculate missing counts against the right target semantics. Normal `pokemon` targets are full real Pokedex targets. Every other category target is the currently available Pokemon GO target and may increase in future config updates.

## Scope

- Add pure helpers that normalize Pokedex entry config into target rows.
- Derive `overall` target max values from regional rows.
- Join latest Pokedex Entry Snapshot values to target rows.
- Add `missing_count` and `progress_pct` fields.
- Support overall and regional summaries.
- Clamp display missing counts at zero while keeping existing validation for saved values above max.

## Acceptance Criteria

- Missing counts are available overall and by region for selected accounts and entry types.
- `pokemon` uses full configured regional targets.
- Non-`pokemon` categories use current configured availability targets.
- `overall` target values are derived from non-overall regions.
- Empty snapshot rows still produce useful target/missing rows with latest value `0`.

## Testing

- Extend Pokedex helper tests.
- Cover latest-as-of-date behavior.
- Cover missing region rows with no snapshot yet.
- Cover derived `overall` targets.
- Cover selected-account and selected-category filtering.

## Comments
