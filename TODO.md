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

-Data Input: move button next to the name/medal to move only 1 position up and down

-Medal explorer different modi for which graphs are shown or sorted.:
    + show all 
    + only show medals that are not completed (Thombay, Cerius, Thomzay)
    + show only completed (Thombay, Cerius, Thomzay)
    + sort after completion progress ascending/descending (Thombay, Cerius, Thomzay)
    + sort after time until completion ascending/descending (Thombay, Cerius, Thomzay)
    + sort after Data Input Order (Thombay, Cerius, Thomzay)

-Medal explorer graphs: goal pace: ahead in green, behind keep in red, completed in blue

-Dashboard: over every number you can hover and it shows more detailed info how it is calcualted or show the exact calculation.

-scale the whole website depending on the windowsize

-make a new output version that is more suitable for smartphones

-move gap/trend leader dropdown left of show catch-up trendlines

-Total xp over time y axis should also react with the slider and fill the graph automatically.

-Create a file in config where i can input some explanations for the medals that is shown when you hover over the medal.