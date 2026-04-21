from __future__ import annotations

import math

import pandas as pd


def restrict_to_max_data_start_interval(
    df: pd.DataFrame,
    *,
    date_col: str,
    group_col: str,
    min_plateau_ratio: float = 0.95,
) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    if not {date_col, group_col}.issubset(df.columns):
        return df.copy()

    d = df.copy()
    d[date_col] = pd.to_datetime(d[date_col], errors="coerce")
    d[group_col] = d[group_col].astype(str).str.strip()
    d = d.dropna(subset=[date_col, group_col]).copy()
    d = d[d[group_col] != ""].copy()
    if d.empty:
        return df.iloc[0:0].copy()

    first_dates = d.groupby(group_col, as_index=False)[date_col].min().sort_values(date_col)
    if first_dates.empty:
        return df.iloc[0:0].copy()

    total_groups = int(first_dates[group_col].nunique())
    ratio = max(0.0, min(1.0, float(min_plateau_ratio)))
    if ratio >= 1.0:
        allowed_late_groups = 0
    else:
        allowed_late_groups = max(1, int(math.floor(total_groups * (1.0 - ratio))))
    # Pick the first date where the tracked account base is effectively established.
    # Counting first-snapshot cohorts avoids a new account on the latest snapshot
    # turning that latest date into the only "complete" interval.
    min_started_groups = max(1, total_groups - allowed_late_groups)

    starts_by_date = (
        first_dates.groupby(date_col, as_index=False)[group_col]
        .nunique()
        .rename(columns={group_col: "start_count"})
        .sort_values(date_col)
    )
    starts_by_date["started_count"] = starts_by_date["start_count"].cumsum()
    plateau = starts_by_date[starts_by_date["started_count"] >= min_started_groups].copy()
    start = pd.Timestamp(plateau[date_col].min() if not plateau.empty else starts_by_date[date_col].min())
    return d[d[date_col] >= start].sort_values([date_col, group_col]).reset_index(drop=True)


def carry_forward_value_rows(
    df: pd.DataFrame,
    *,
    date_col: str,
    group_col: str,
    value_cols: list[str],
    chart_dates: list[pd.Timestamp],
) -> pd.DataFrame:
    if df.empty or not chart_dates:
        return df.iloc[0:0].copy()
    required = {date_col, group_col, *value_cols}
    if not required.issubset(df.columns):
        return df.iloc[0:0].copy()

    d = df.copy()
    d[date_col] = pd.to_datetime(d[date_col], errors="coerce")
    d[group_col] = d[group_col].astype(str).str.strip()
    for col in value_cols:
        d[col] = pd.to_numeric(d[col], errors="coerce")
    d = d.dropna(subset=[date_col, group_col]).copy()
    d = d[d[group_col] != ""].copy()
    if d.empty:
        return d

    frames: list[pd.DataFrame] = []
    scaffold = pd.DataFrame({date_col: sorted(pd.Timestamp(dt) for dt in chart_dates)})
    for group_value, grp in d.sort_values([group_col, date_col]).groupby(group_col, sort=False):
        g = grp.sort_values(date_col).drop_duplicates(date_col, keep="last")
        merged = pd.merge_asof(
            scaffold,
            g[[date_col, *value_cols]].sort_values(date_col),
            on=date_col,
            direction="backward",
        )
        merged[group_col] = group_value
        merged = merged.dropna(subset=value_cols, how="all").copy()
        if not merged.empty:
            frames.append(merged)

    if not frames:
        return d.iloc[0:0].copy()
    return pd.concat(frames, ignore_index=True).sort_values([date_col, group_col]).reset_index(drop=True)
