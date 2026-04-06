from __future__ import annotations

from collections.abc import Mapping

import pandas as pd


def max_configured_level(curve_map: Mapping[int, int]) -> int | None:
    if not curve_map:
        return None
    return max(int(level) for level in curve_map.keys())


def is_max_level(level: int, curve_map: Mapping[int, int]) -> bool:
    max_level = max_configured_level(curve_map)
    if max_level is None:
        return False
    return int(level) >= int(max_level)


def uses_total_xp_input(level: int, curve_map: Mapping[int, int]) -> bool:
    return is_max_level(level, curve_map)


def total_xp_from_level_input(level: int, xp_input_value: int, curve_map: Mapping[int, int]) -> int:
    lvl = int(level)
    raw_value = int(xp_input_value)
    if lvl not in curve_map:
        raise KeyError(lvl)

    base_xp = int(curve_map[lvl])
    return base_xp + raw_value


def xp_input_label(level: int, curve_map: Mapping[int, int]) -> str:
    return "XP Bar"


def carry_forward_max_level_rows(
    df: pd.DataFrame,
    curve_map: Mapping[int, int],
    *,
    date_col: str = "Date",
    player_col: str = "Spieler",
    level_col: str = "Lvl",
) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    required = {date_col, player_col, level_col}
    if not required.issubset(df.columns):
        return df.copy()

    out = df.copy()
    out[date_col] = pd.to_datetime(out[date_col], errors="coerce")
    out[player_col] = out[player_col].astype(str).str.strip()
    out[level_col] = pd.to_numeric(out[level_col], errors="coerce")
    out = out.dropna(subset=[date_col, player_col, level_col]).copy()
    if out.empty:
        return df.copy()

    out[level_col] = out[level_col].astype(int)
    out = out.sort_values([player_col, date_col]).reset_index(drop=True)
    all_dates = sorted(pd.to_datetime(out[date_col].dropna().unique()).tolist())
    if not all_dates:
        return out

    extra_rows: list[pd.Series] = []
    for _, grp in out.groupby(player_col, sort=False):
        latest = grp.sort_values(date_col).iloc[-1]
        if not is_max_level(int(latest[level_col]), curve_map):
            continue
        last_date = pd.Timestamp(latest[date_col])
        for future_date in all_dates:
            future_ts = pd.Timestamp(future_date)
            if future_ts <= last_date:
                continue
            row = latest.copy()
            row[date_col] = future_ts
            extra_rows.append(row)

    if not extra_rows:
        return out

    expanded = pd.concat([out, pd.DataFrame(extra_rows)], ignore_index=True)
    expanded = expanded.drop_duplicates(subset=[date_col, player_col], keep="last")
    return expanded.sort_values([date_col, player_col]).reset_index(drop=True)
