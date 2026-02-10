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

## Output Structure

For each group in `pogo_player_groups.csv`, a folder is created (if missing), and 4 files are generated:

1. `1_<date>_<Group>_xp_growth_with_players_pogo.png`
2. `2_<date>_<Group>_xp_progress_player_pogo.png`
3. `3_<date>_<Group>_log_xp_growth_with_players_pogo.png`
4. `4_<date>_<Group>_log_xp_progress_player_pogo.png`

Example:

- `Family\1_2026-02-10_Family_xp_growth_with_players_pogo.png`
- `Family\2_2026-02-10_Family_xp_progress_player_pogo.png`
- `Family\3_2026-02-10_Family_log_xp_growth_with_players_pogo.png`
- `Family\4_2026-02-10_Family_log_xp_progress_player_pogo.png`

## Notes

- Growth labels include level progress percent, e.g. `Thombay(85%)`.
- If points are very close, labels are stacked on the right with connector lines.
- Group and folder names are sanitized for filesystem-safe output names.
