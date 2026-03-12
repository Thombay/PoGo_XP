# TODO (Codex): Restructure repo into 2 projects + shared inputs (no double XP)

## 0) Goal

- [~] Keep ONE canonical XP dataset.
- [x] Medal tracker reads XP from the XP dataset (no manual Total XP entry in medal tracker).
- [x] Keep shared data for both projects under `inputs/`.
- [x] Minimize disruption to existing script usage and output folders.

Notes:

- Static XP curve is now clearly named: `inputs/reference/total_xp_curve.csv`.
- Dynamic shared data is under `inputs/data/`.
- Shared config is under `inputs/config/`.

---

## 1) Folder layout

- [x] `inputs/`
- [x] `inputs/config/`
- [x] `inputs/data/`
- [x] `inputs/reference/`
- [x] `inputs/templates/`
- [x] `pogo-xp/`, `pogo-xp/src/`, `pogo-xp/tools/`
- [x] `medal-tracker/`, `medal-tracker/tools/` (config/data moved to shared `inputs/`)
- [x] `shared/`
- [x] `output/`

---

## 2) Shared files moved and renamed

- [x] `pogo_totalXP.csv` -> `inputs/reference/total_xp_curve.csv`
- [x] `pogo_totalXP_history.csv` -> `inputs/data/xp_history.csv`
- [x] `pogo_player_groups.csv` -> `inputs/config/player_groups.csv`
- [x] `TotalXP.xlsx` -> `inputs/templates/TotalXP.xlsx`
- [x] `Vorlage.csv` -> `inputs/templates/Vorlage.csv`
- [x] `Pogo Medals.xlsx` -> `inputs/templates/Pogo Medals.xlsx`
- [x] `medal-tracker/config/medals.csv` -> `inputs/config/medal_goals.csv`
- [x] `medal-tracker/data/medal_snapshots.csv` -> `inputs/data/medal_snapshots.csv`
- [x] `medal-tracker/out/medal_report.csv` -> `output/medal-tracker/medal_report.csv`

---

## 3) XP project wiring

- [x] XP code moved: `pogo-xp/pogo_totalXP.py`
- [x] Uses shared path resolver `shared/paths.py`
- [x] Reads:
  - [x] `inputs/reference/total_xp_curve.csv`
  - [x] `inputs/data/xp_history.csv`
  - [x] `inputs/config/player_groups.csv`
- [x] Writes group outputs to `output/<Group>/...`

---

## 4) Medal tracker wiring

- [x] Project scaffold exists (`tools`; config/data are shared in `inputs/`)
- [x] `run_medals.py` executes report pipeline
- [x] `medal-tracker/tools/generate_report.py` injects XP with `merge_asof`
- [x] `medal-tracker/tools/append_from_xlsx.py` extracts workbook data into:
  - [x] `inputs/data/medal_snapshots.csv` (medal progress rows)
  - [x] `inputs/config/medal_goals.csv` (shared goals)
- [x] `total_xp` rows are excluded from `medal_snapshots.csv` (no manual Total XP in medal snapshots)
- [~] Preferred canonical XP snapshots file still optional:
  - expected file: `inputs/data/xp_snapshots.csv`
  - expected columns: `date`, `spieler`, `total xp`
- [x] Medal template flow has no manual Total XP field (`inputs/templates/medal_snapshots_template.csv`)
- [x] XP injection now works from `inputs/data/xp_history.csv` (+ `inputs/reference/total_xp_curve.csv`) when `xp_snapshots.csv` is not present

---

## 5) Entry points

- [x] `run_xp.py`
- [x] `run_medals.py`
- [x] `update_all.py` (basic chain)
- [ ] Extend `update_all.py` with real XLSX append step once mapping is defined

---

## 6) Validation

- [x] `python run_xp.py --no-show` works after rename/move
- [x] `python run_medals.py` runs and writes `output/medal-tracker/medal_report.csv`
- [x] Medal report includes derived `total_xp` rows

---

## 7) Webapp UX follow-ups

- [x] Data Input: move buttons next to account/medal to move only 1 position up/down
- [x] Medal Explorer modes for graph visibility/sorting:
  - [x] show all
  - [x] only medals not completed (Thombay, Cerius, Thomzay)
  - [x] only completed (Thombay, Cerius, Thomzay)
  - [x] sort by completion progress ascending/descending (Thombay, Cerius, Thomzay)
  - [x] sort by time until completion ascending/descending (Thombay, Cerius, Thomzay)
  - [x] sort by data input order (Thombay)
- [x] Medal Explorer goal pace colors:
  - [x] ahead = green
  - [x] behind = red
  - [x] completed = blue
- [x] Dashboard KPI hover help includes more detailed calculation/context info
- [x] Website scales better with window size (responsive CSS)
- [x] New export mode suitable for smartphones
- [x] Move gap/trend leader dropdown left of show catch-up trendlines
- [x] Total XP over time y-axis reacts to slider x-range and auto-fits
- [x] Config file for medal explanations + show explanation in medal hover
  - [x] `inputs/config/medal_explanations.csv` created and prefilled with all medal IDs
- [x] Personal dashboard: medal-based activity stats/graphs below Total XP (caught/day, raids/day, pokestops/day, km/day, intervals)
- [x] Personal dashboard KPI summary expanded to show values for every core account
- [x] Data Input (XP tab): added per-account activity medal inputs and save flow for:
  - [x] Battles Won
  - [x] Distance Walked
  - [x] Pokemon Caught
- [x] Battles Won decoupled from `battle_girl` medal and stored as separate additional activity data
- [x] Dashboard Global: added activity KPI row below top KPIs using new data (`Battles/day`, `Pokemon Caught/day`, `Km/day`, `PokeStops/day`)
- [x] Dashboard Global XP Explorer: added cumulative activity trend graphs directly below `Total XP Over Time` (`Battles Won`, `Pokemon Caught`, `Distance Walked`)
- [x] Dashboard Global XP Explorer: added `Activity Performance` KPIs below Total XP (`Leader`, `Best`, `Worst`, `Improved`, `Declined`) with metric selector
- [x] `PokeStops/day` removed from Global activity cards/analysis (kept in Personal only)
- [x] Moved `Activity Snapshot (Latest Intervals)` KPI row below `Total XP Over Time` in Dashboard Global XP Explorer
- [x] PokeStops over-time chart kept only in Dashboard Personal (removed from Global XP Explorer)
- [x] Global XP Explorer `Activity Performance` now shows all metrics in one row (no selector)
- [x] Global XP Explorer `Activity Snapshot` now uses selected window (7d/30d) for consistent values
- [x] Global activity KPI rates decoupled from XP date-range/common-interval clipping (per-account values now stable across groups)
- [x] Activity Performance layout switched to KPI-type columns (Leader/Best/Worst/Improved/Declined), each listing all metrics
- [x] Activity Performance redesigned to card-style KPI rows per activity (matches Global KPI card style)


show catch up trendlines deselect reset graph to full scaling