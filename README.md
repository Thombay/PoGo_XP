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
python pogo_totalXP.py --include-optional-8
python pogo_totalXP.py --no-show
```

## Output Structure

For each group in `pogo_player_groups.csv`, a folder is created (if missing), and 9 standard files are generated.
Filename format is now:

`<date>_<index-or-tag>_<Group>_<stem>.png`

1. `<date>_1_<Group>_xp_growth_with_players_pogo.png`
2. `<date>_2_<Group>_xp_progress_player_pogo.png`
3. `<date>_3_<Group>_xp_progress_per_day_player_pogo.png`
4. `<date>_4_<Group>_xp_gain_per_month_player_pogo.png`
5. `<date>_5_<Group>_rank_over_time_pogo.png`
6. `<date>_6_<Group>_gap_to_leader_pogo.png`
7. `<date>_6d_<Group>_gap_delta_per_interval_pogo.png`
8. `<date>_log1_<Group>_log_xp_growth_with_players_pogo.png`
9. `<date>_log2_<Group>_log_xp_progress_player_pogo.png`

Optional (only with `--include-optional-8`):

- `<date>_8_<Group>_interval_pace_pogo.png`

Example:

- `Family\2026-02-16_1_Family_xp_growth_with_players_pogo.png`
- `Family\2026-02-16_2_Family_xp_progress_player_pogo.png`
- `Family\2026-02-16_3_Family_xp_progress_per_day_player_pogo.png`
- `Family\2026-02-16_4_Family_xp_gain_per_month_player_pogo.png`
- `Family\2026-02-16_5_Family_rank_over_time_pogo.png`
- `Family\2026-02-16_6_Family_gap_to_leader_pogo.png`
- `Family\2026-02-16_6d_Family_gap_delta_per_interval_pogo.png`
- `Family\2026-02-16_log1_Family_log_xp_growth_with_players_pogo.png`
- `Family\2026-02-16_log2_Family_log_xp_progress_player_pogo.png`

## Notes

- Growth labels include level progress percent, e.g. `Thombay(85%)`.
- If points are very close, labels are stacked on the right with connector lines.
- Group and folder names are sanitized for filesystem-safe output names.
- Plot `3` is labeled honestly as average pace over interval: `Delta XP / Delta days`.
- Plot `3` annotates `Delta days` at points so long gaps are visible.
- Plot `2` is explicitly gain since first snapshot (title + y-axis).
- Plot `5` uses step-style ranks and shows a message when no rank changes occurred.
- Plot `6` keeps absolute gap and includes an inset with `gap_change = gap - gap_first`.
- Plot `6d` shows per-interval change in gap to leader (`Delta gap`).
- A single per-group `player_colors` mapping is reused across all plots for consistent colors.
- Plot `8` (optional) uses same-color raw markers + trend line and end-of-line labels instead of trend legend entries.
- Group player names are matched against history with a normalization fallback (common leetspeak like `3->e`, trailing digits removed), and mappings are logged as `Info [...]`.
- If no exact/mapped name is found, the script logs `Warning [...]` with close-match suggestions.
- The script warns in console when an interval is large (`Delta days > 10`).
