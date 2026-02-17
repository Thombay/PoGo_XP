# PoGo XP plots - Current Task Checklist

## Improve Graph 5 (rank over time)

- [x] Switch rank plotting to step style (`where="post"`).
- [x] Detect if no rank changes happened in the shown date range.
- [x] If none: add annotation `No rank changes in this time window`.
- [x] Handle ties explicitly with stable ordering so ranks do not jitter when `Total XP` matches.
- [x] Label ranks at the right edge and avoid crowded legend.

## Improve Graph 6 (gap to leader)

- [x] Keep absolute gap plot for context.
- [x] Add inset showing gap change since first snapshot:
  - `gap_change = gap - gap_first`
  - negative = catching up, positive = falling behind
- [x] Add horizontal reference line at 0 for `gap_change`.
- [x] Annotate last point per player with final absolute gap.
- [x] Add derived variant for per-interval gap change:
  - `Delta gap = gap_now - gap_prev`
  - filename tag: `*_6d_<Group>_gap_delta_per_interval_pogo.png`

## Improve Graph 8 readability (colors + clutter)

- [x] Create a single `player_colors` mapping (player -> color) and reuse it across all plots.
- [x] In Graph 8: use same color per player; raw pace and trend differ by style (not by color).
- [x] Remove trend legend entries; use end-of-line labels at the right edge.

## Output + naming scheme

- [x] Keep existing filename scheme: `<date>_<index-or-tag>_<Group>_<stem>.png`.
- [x] Keep existing output names; derived variant uses safe tag `6d`.

## De-duplicate Graph 2 vs Graph 7

- [x] Remove Graph 7 from outputs and TODO (redundant with Graph 2).
- [x] Keep Graph 2 stem as-is for compatibility; make title and y-label explicitly `Gain Since First Snapshot`.
- [x] Remove Graph 7 code path from generation.
