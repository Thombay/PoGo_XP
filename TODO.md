# TODO

## Active

### Data + Pipelines
- [ ] Extend `update_all.py` with the real XLSX append step (mapping + validation flow).
- [~] Decide whether to enforce `inputs/data/xp_snapshots.csv` as mandatory canonical snapshot input.
  - Current state: optional fallback from `inputs/data/xp_history.csv` works.

### Webapp Structure
- [~] Finish the view split:
  - [x] Dashboard rendering moved to `webapp/views/dashboard.py`
  - [ ] Move full XP Explorer implementation out of `webapp/app.py` into `webapp/views/xp_explorer.py`

### Exports
- [ ] Fill missing export info/functions (`export infos missing and functions`).

---

## Next Suggested
- [ ] Add a small regression test/check script for XP trendline behavior (group invariance for same player vs same leader).
- [ ] Add a short `README` section documenting trendline fit rules:
  - Pairwise fit window for multi-player comparisons
  - Start clamp at `>= 2025-01-01`
  - Personal `Ich` behavior

---

## Completed (Condensed)

### Repo Restructure
- [x] Shared input layout established (`inputs/config`, `inputs/data`, `inputs/reference`, `inputs/templates`).
- [x] XP + medal projects wired to shared paths.
- [x] Key files renamed/moved to canonical locations.
- [x] Entry points available: `run_xp.py`, `run_medals.py`, `update_all.py`, `run_server.py`.

### Medal Tracker
- [x] Medal report pipeline works from shared inputs.
- [x] XP injection works without manual Total XP entry in medal snapshots.

### Webapp UX + Features
- [x] Data Input row move buttons reworked (single-step up/down).
- [x] Medal Explorer filter/sort modes implemented.
- [x] Goal pace colors + hover explanations added.
- [x] Responsive scaling improved.
- [x] Smartphone export mode added.
- [x] Global/Personal dashboard activity KPIs and activity trends added/reworked.
- [x] PokeStops handling aligned (Global removed where needed, Personal kept).
- [x] Current XP Ranking formatting regressions fixed.

### Trendline + XP Explorer Fixes
- [x] Gap/trend leader controls and catch-up trendline behavior improved.
- [x] Trendline consistency fixed for same player vs same leader across groups (`All`/`Bekannte`).
- [x] Multi-player trendline fit uses pairwise start with clamp `>= 2025-01-01`.
- [x] Total XP x-axis now starts from visible data (no empty 2016 left area when not applicable).
- [x] Trendline projection recalculates when date-range scope changes (visibility controls reset).

### Cleanup
- [x] Export logic split to `webapp/exporting.py`.
- [x] Dashboard view split started under `webapp/views/`.
- [x] Removed generated/unused folders (`.mypy_cache`, `.pytest_cache`, `__pycache__`, `_Archiv`).
