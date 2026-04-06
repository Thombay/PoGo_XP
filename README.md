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
- dashboard rolling-window KPIs are computed from one shared metrics pipeline (`webapp/metrics.py`)
- global dashboard window selector: `7d | 30d`
  - auto default: `30d` when enough coverage, otherwise `7d`
  - hint shown when `30d` coverage is limited: `30d limited coverage, showing 7d recommended`
  - selector is shown in the KPI row on the right, next to `Last XP Snapshot`, as compact segmented buttons
- XP KPI set includes:
  - `Top XP Gain (7d|30d)`
  - `Least XP Gain (7d|30d)`
  - `Fastest 7d/30d Pace`
  - `Most Improved vs Baseline (7d|30d)` (sign-split; shows no-improvements state when none > 0)
  - `Most Declined vs Baseline (7d|30d)` (sign-split; shows no-declines state when none < 0)
  - headline winners are selected only from active players in window (`xp_gain_W > 0`)
  - inactive players (`xp_gain_W = 0`) remain visible in charts/tables and are excluded only from headline winner selection
  - no-state cards use: `No improvements`, `No decline`, or `No active players (W)` when applicable
- coverage indicator near KPIs:
  - `Eligible for 7d/30d stats: X/Y`
  - `Eligible for baseline comparisons: X/Y`
  - `Active in W window (xp_gain_W > 0): X/Y`
- `Dashboard Personal` group selector shows only personal groups in this order: `OwnAccounts`, then `Ich` (no `All`)
- dashboard export controls (`Mode`, `Format`, `Export`) are compact, right-aligned, and on the same row as the group radio
  - HTML export includes an in-file `7d/30d` window switch (client-side toggle)
  - HTML export window switching triggers Plotly resize so charts keep full width after toggling `7d/30d`
  - export filenames omit `7d/30d` in the name, because one HTML export contains both windows
- `XP Explorer`: interactive Total XP, rank step chart, gap change, interval pace
  - graph order:
    - top row: `XP Gain Over Time` | `Interval Pace (XP/day)`
    - middle row: `Gap Change Since First Snapshot` (baseline line + per-account baseline labels) | `Rank Over Time (Step)`
    - bottom row: `Total XP Over Time` (full width)
- `Medal Explorer`: interactive medal progress and derived platinum counts
  - shows a right-aligned `Last Medal Snapshot` card next to the headline
  - trend-to-goal projections use data since `2025-01-01` (older data excluded from trend calculations)
  - platinum progress graph ignores dates before medal tracking start per account
- `Data Input`:
  - XP snapshot input for multiple accounts in one save
  - accounts whose latest XP row is already at the highest configured level (currently `80`) are skipped in XP input because no further visible XP input is expected
  - for selected date, accounts already entered are hidden so you only see missing accounts
  - medal snapshot input account-wise (`Thombay`, `Cerius`, `Thomzay`) with one-save full medal list
  - for selected date, accounts already entered are hidden so you only see missing accounts
  - medal list editor shows display names (no `medal_id` column in the UI)
  - quick reorder: move one medal to a target position (automatic shift, no manual renumbering)
  - saved medal input order per account via `inputs/config/medal_input_order.csv`
  - current default order is taken from `inputs/templates/medal_snapshots_template.csv` (Thombay block)
- `Pipelines`: run `run_xp.py`, `run_medals.py`, `update_all.py`
- `Generated Files`: browse generated PNG outputs under `output/`

## Metrics Engine

`webapp/metrics.py` is the single source of truth for rolling XP metrics.
The same code path computes both `7d` and `30d` variants.

Per-player windowed fields (`7d` and `30d`):

- `xp_gain_{7d|30d}`
- `xp_per_day_{7d|30d}`
- `baseline_xp_per_day_{7d|30d}` (median of previous rolling matching windows; current window excluded)
- `delta_vs_baseline_{7d|30d}`
- `pct_vs_baseline_{7d|30d}`

Rolling `xp_at(target_date)` logic:

- preferred: linear interpolation between nearest snapshots around target date
- fallback: step/last-known value before target when interpolation is not possible

Eligibility:

- selected-window stats require a window spanning `now-window` to `now`
- baseline comparisons require at least 5 prior rolling selected-window intervals

Tests:

```powershell
python -m unittest -v tests/test_metrics.py
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
- removes any manual `medal_id=total_xp` rows from snapshots input
- injects XP-derived rows as `medal_id=total_xp`
- writes `output/medal-tracker/medal_report.csv`

`medal-tracker/tools/append_from_xlsx.py` now:

- extracts medal progress rows into `inputs/data/medal_snapshots.csv`
- extracts shared goals into `inputs/config/medal_goals.csv` (once, not per account)
- excludes `total_xp` from medal snapshots
- generates `inputs/templates/medal_snapshots_template.csv` without `total_xp` rows
- for legacy/manual imports, keep `distance_walked/pokemon_caught/pokestops_visited` aligned with `jogger/collector/backpacker`
- platinum derivation is alias-safe: legacy IDs and canonical IDs are normalized and counted once per day/account/medal
- platinum counts are computed as-of each date (latest known medal value per medal is carried forward), so partial snapshots do not cause false drops

XP source for medal report:

- Preferred canonical file: `inputs/data/xp_snapshots.csv` with columns `date`, `spieler`, `total xp`
- Current working fallback: `inputs/data/xp_history.csv` + `inputs/reference/total_xp_curve.csv` (level + XP bar converted to total XP)
  - max-level rows in `xp_history.csv` still use the stored level-plus-bar format; dashboard/XP plots can carry the last known max-level value forward on later snapshot dates
