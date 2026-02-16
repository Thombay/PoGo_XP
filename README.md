# Pogo XP Plot Generator

Generates grouped Pokemon GO XP plots from history data.

## Requirements

- Python 3.10+
- Packages:
  - `pandas`
  - `matplotlib`
  - `numpy`

Install once:

```powershell
pip install pandas matplotlib numpy
```

## Input Files

- `pogo_totalXP.csv`
  - Semicolon separated
  - Required columns: `Level;XP to next Lvl.;Total XP`
- `pogo_totalXP_history.csv`
  - Semicolon separated
  - Required columns: `Date;Spieler;Lvl;XP Bar`
- `pogo_player_groups.csv`
  - Defines which players appear in which output group
  - Format example:

```text
Family:
Babsi,Thombay,Martin

Work:
90erTom,86Berni,Thombay

Papiermuehlgasse:
Tastef,LuanYellow
```

## Run

```powershell
python pogo_totalXP.py
```

The script runs headless (no plot windows) and saves files directly.

Optional arguments:

```powershell
python pogo_totalXP.py --output-date 2026-02-16
python pogo_totalXP.py --groups-file pogo_player_groups.csv
python pogo_totalXP.py --no-show
```

## Output Structure

For each group in `pogo_player_groups.csv`, a folder is created (if missing), and 5 files are generated.
Filename format is now:

`<date>_<index-or-tag>_<Group>_<stem>.png`

1. `<date>_1_<Group>_xp_growth_with_players_pogo.png`
2. `<date>_2_<Group>_xp_progress_player_pogo.png`
3. `<date>_3_<Group>_xp_progress_per_day_player_pogo.png`
4. `<date>_log1_<Group>_log_xp_growth_with_players_pogo.png`
5. `<date>_log2_<Group>_log_xp_progress_player_pogo.png`

Example:

- `Family\2026-02-16_1_Family_xp_growth_with_players_pogo.png`
- `Family\2026-02-16_2_Family_xp_progress_player_pogo.png`
- `Family\2026-02-16_3_Family_xp_progress_per_day_player_pogo.png`
- `Family\2026-02-16_log1_Family_log_xp_growth_with_players_pogo.png`
- `Family\2026-02-16_log2_Family_log_xp_progress_player_pogo.png`

## Notes

- Growth labels include level progress percent, e.g. `Thombay(85%)`.
- If points are very close, labels are stacked on the right with connector lines.
- Group and folder names are sanitized for filesystem-safe output names.
- `XP/day` is computed from consecutive snapshots per player (`Total XP` delta divided by day delta).
