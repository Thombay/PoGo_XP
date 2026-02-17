# PoGo Repo (Restructured)

Two projects now live in one repo, with shared input files:

- `pogo-xp/`: XP plotting project
- `medal-tracker/`: medal reporting project
- `inputs/`: shared input source

## Layout

```text
inputs/
  config/
    player_groups.csv
    medal_goals.csv
  data/
    medal_snapshots.csv
    xp_history.csv
    xp_snapshots.csv   (future canonical per-account snapshots for medal-tracker)
  reference/
    total_xp_curve.csv
  templates/
    TotalXP.xlsx
    Vorlage.csv

pogo-xp/
  pogo_totalXP.py
  src/
  tools/

medal-tracker/
  tools/generate_report.py
  tools/append_from_xlsx.py

shared/paths.py
run_xp.py
run_medals.py
update_all.py
```

## Shared Paths

- Shared path resolver: `shared/paths.py`
- Default input root: `<repo>/inputs`
- Optional override: env var `POGO_INPUT_DIR`

Helpers:

- `total_xp_curve_path()`
- `xp_snapshots_path()`
- `xp_history_path()`
- `player_groups_path()`
- `medals_config_path()`
- `medal_snapshots_path()`
- `medal_report_path()`

## Run

XP plotting:

```powershell
python run_xp.py --no-show
```

Medal report:

```powershell
python run_medals.py
```

Extract medal snapshots + goals from Excel:

```powershell
python medal-tracker/tools/append_from_xlsx.py
```

Run both:

```powershell
python update_all.py
```

## XP Outputs

XP plots write into `output/<Group>/`, e.g.:

- `output/3Accounts/`
- `output/All/`
- `output/Bekannte/`
- `output/Family/`
- `output/Ich/`
- `output/Papiermuehlgasse/`
- `output/Work/`

Filename scheme remains:

`<date>_<index-or-tag>_<Group>_<stem>.png`

## Medal Tracker Status

Current scaffold is in place. `medal-tracker/tools/generate_report.py` already:

- reads `inputs/data/medal_snapshots.csv`
- tries to inject XP-derived rows as `medal_id=total_xp`
- writes `output/medal-tracker/medal_report.csv`

`medal-tracker/tools/append_from_xlsx.py` now:

- extracts medal progress rows into `inputs/data/medal_snapshots.csv`
- extracts shared goals into `inputs/config/medal_goals.csv` (once, not per account)
- excludes `total_xp` from medal snapshots (XP should come from canonical XP snapshots pipeline)

Current blocker:

- `inputs/reference/total_xp_curve.csv` is static curve/reference data (used by XP plotter), not per-account snapshots.
- `inputs/data/xp_snapshots.csv` is still missing/canonical schema not provided yet (`date`, `spieler`, `total xp`), so XP injection is skipped with a warning until that file exists.
