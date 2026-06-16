# Pokedex Dashboard Graphs And Tables

Status: ready-for-agent
Type: feature

## Problem

After the new missing-count, species-list, and evolution helper data exists, the dashboard needs focused UI that surfaces it without making the page noisy.

## Scope

- Add missing-count headline metrics.
- Add a regional missing table with latest value, max value, missing count, and progress percent.
- Add a Missing Pokemon view using species-level list data.
- Add an Evolution Unlocks view using evolution candidate data.
- Add the first graph slice:
  - Missing count by region/category.
  - Progress percent by account/category.
  - Evolution unlock count by account/category.
- Add downloads for missing and evolution tables only if this matches existing dashboard style.

## Acceptance Criteria

- Users can see how many entries are missing overall and by region.
- Users can see exact missing Pokemon by account, category, and region.
- Users can see evolution unlock candidates that are available right now.
- Graphs respect selected accounts, categories, regions, and dates where applicable.
- Empty states explain which source has no data.

## Testing

- Prefer pure helper tests from earlier issues.
- Add small formatting helper tests if table-shaping logic is extracted.
- Manually verify the Streamlit dashboard with current sample data.

## Comments
