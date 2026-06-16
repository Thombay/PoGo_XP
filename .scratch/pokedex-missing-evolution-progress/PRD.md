# Pokedex Missing And Evolution Progress PRD

Status: ready-for-agent
Type: prd

## Problem

The Pokedex dashboard can show aggregate Pokedex Entry Snapshot counts, but it cannot yet answer these questions:

- How many Pokemon are missing overall and by region?
- Which exact Pokemon are missing in each category?
- Which missing entries can be unlocked immediately through evolution?
- How close is each account to the currently available Pokemon GO max for non-normal categories?
- Which line is which in the overall progress chart when several accounts and categories are shown?

The important rule is that `pokemon` max values are the real full Pokedex target, while every other entry category uses the currently available Pokemon GO target. Those category targets will rise as more entries become available.

## Goals

- Add release-aware count targets for Pokedex progress.
- Show missing-count stats overall and by region.
- Add exact missing Pokemon lists from species-level tracking.
- Add evolution unlock candidates based on editable evolution data and a manual `can_evolve_now` flag.
- Give every overall progress line a distinct deterministic color.
- Add first-slice graphs for missing counts, progress percent, and evolution unlock counts.

## Non-Goals

- No Pokemon GO account sync.
- No automatic knowledge of candy, items, trades, buddy requirements, form requirements, or event windows.
- No fully automatic shiny, shadow, purified, G-Max, or Mega availability scraping in the first slice.
- Do not replace aggregate Pokedex Entry Snapshots with species-level tracking.
- Do not backfill exact historical species ownership from aggregate counts.

## Data Sources

Aggregate count progress continues to come from Pokedex Entry Snapshots:

```text
date,account,entry_type,region,value
```

Release-aware count targets continue to come from Pokedex entry config:

```text
entry_type,region,max_value,locked,notes
```

New species-level completion rows should be local editable CSV data:

```text
date,account,entry_type,dex_number,registered,can_evolve_now,notes
```

New non-normal category availability rows should be local editable CSV data:

```text
entry_type,dex_number,available,notes
```

New Pokemon GO evolution edges should be local editable CSV data:

```text
source_dex_number,target_dex_number,method,notes
```

## Decisions

- `pokemon` max values mean real full Pokedex max values.
- Non-`pokemon` max values mean currently available Pokemon GO max values and may increase later.
- Aggregate snapshots remain the source for count progress.
- Species-level CSV rows are required for exact missing Pokemon.
- Category availability stays in editable CSV reference/config data first.
- Evolution unlocks require manual `can_evolve_now` state on the owned source Pokemon.
- Overall count targets should be derived from regional targets.
- Progress line colors should be based on account plus entry type, not account alone.
- First graph slice is missing by region/category, progress percent, and evolution unlock count.

## Implementation Issues

- `issues/01-release-aware-targets-and-missing-counts.md`
- `issues/02-distinct-progress-line-colors.md`
- `issues/03-species-level-tracking.md`
- `issues/04-missing-pokemon-lists.md`
- `issues/05-evolution-unlock-candidates.md`
- `issues/06-pokedex-dashboard-graphs-and-tables.md`
- `issues/07-docs-and-verification.md`

## Comments

- Created locally because GitHub CLI is not available in this environment and the repo issue-tracker setting now uses local markdown.
