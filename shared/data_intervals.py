from __future__ import annotations

import pandas as pd


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
