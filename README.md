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
    medal_input_order.csv   (created by web app when you save medal input order)
  data/
    medal_snapshots.csv
    xp_history.csv
    xp_snapshots.csv   (future canonical per-account snapshots for medal-tracker)
  reference/
    total_xp_curve.csv
  templates/
    TotalXP.xlsx
    Vorlage.csv
    medal_snapshots_template.csv

pogo-xp/
  pogo_totalXP.py
  src/
  tools/

medal-tracker/
  tools/generate_report.py
  tools/append_from_xlsx.py

webapp/
  app.py

shared/paths.py
run_xp.py
run_medals.py
update_all.py
run_server.py
requirements-localhost.txt
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

Localhost dashboard:

```powershell
pip install -r requirements-localhost.txt
python run_server.py
```

Then open `http://127.0.0.1:8050`.

Dashboard pages:

- top horizontal page selector (no sidebar dropdown)
- `Dashboard`: latest XP + medal tables
- `XP Explorer`: interactive Total XP, rank step chart, gap change, interval pace
- `Medal Explorer`: interactive medal progress and derived platinum counts
- `Data Input`:
  - XP snapshot input for multiple accounts in one save
  - for selected date, accounts already entered are hidden so you only see missing accounts
  - medal snapshot input account-wise (`Thombay`, `Cerius`, `Thomzay`) with one-save full medal list
  - for selected date, accounts already entered are hidden so you only see missing accounts
  - medal list editor shows display names (no `medal_id` column in the UI)
  - quick reorder: move one medal to a target position (automatic shift, no manual renumbering)
  - saved medal input order per account via `inputs/config/medal_input_order.csv`
  - current default order is taken from `inputs/templates/medal_snapshots_template.csv` (Thombay block)
- `Pipelines`: run `run_xp.py`, `run_medals.py`, `update_all.py`
- `Generated Files`: browse generated PNG outputs under `output/`

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
- removes any manual `medal_id=total_xp` rows from snapshots input
- injects XP-derived rows as `medal_id=total_xp`
- writes `output/medal-tracker/medal_report.csv`

`medal-tracker/tools/append_from_xlsx.py` now:

- extracts medal progress rows into `inputs/data/medal_snapshots.csv`
- extracts shared goals into `inputs/config/medal_goals.csv` (once, not per account)
- excludes `total_xp` from medal snapshots
- generates `inputs/templates/medal_snapshots_template.csv` without `total_xp` rows

XP source for medal report:

- Preferred canonical file: `inputs/data/xp_snapshots.csv` with columns `date`, `spieler`, `total xp`
- Current working fallback: `inputs/data/xp_history.csv` + `inputs/reference/total_xp_curve.csv` (level + XP bar converted to total XP)
