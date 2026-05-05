from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date
from html import escape
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.paths import (
    additional_activity_path,
    config_dir,
    data_input_accounts_path,
    medal_snapshots_path,
    medals_config_path,
    output_dir,
    player_groups_path,
    pokedex_entry_config_path,
    pokedex_entry_snapshots_path,
    pokemon_catalog_path,
    total_xp_curve_path,
    xp_history_path,
)
from shared.data_intervals import carry_forward_value_rows, restrict_to_max_data_start_interval
from shared.xp_utils import carry_forward_max_level_rows, is_max_level, max_configured_level, total_xp_from_level_input
from webapp.metrics import (
    BASELINE_MIN_WINDOWS_DEFAULT,
    WINDOW_DAYS_DEFAULT,
    build_cumulative_gain_df,
    compute_player_kpis_window,
    recent_gain_table_from_metrics,
)
from webapp.data_files import (
    add_account_to_groups,
    accounts_for_selected_group,
    load_curve_map,
    load_data_input_accounts,
    load_medal_goals,
    load_medal_snapshots,
    load_pokedex_entry_config,
    load_pokedex_entry_snapshots,
    load_pokemon_catalog,
    load_xp_history,
    parse_groups,
    save_data_input_account_types,
    to_int_series,
)
from webapp.exporting import (
    build_dashboard_export_html as build_dashboard_export_html_impl,
    build_dashboard_export_png as build_dashboard_export_png_impl,
)
from webapp.ui_styles import inject_responsive_styles
from webapp.views.dashboard import render_dashboard_content_view
from webapp.views.xp_explorer import render_xp_explorer_section_view

ACCOUNT_ORDER = ["Thombay", "Cerius", "Thomzay"]
MEDAL_INPUT_CORE_ACCOUNTS = ["Thombay", "Cerius", "Thomzay"]
MEDAL_EXPLORER_CORE_ACCOUNTS = ["Thombay", "Cerius", "Thomzay"]
DERIVED_MEDAL_ID = "platinum_medals"
DATA_INPUT_TYPES = {"xp", "medal", "pokedex"}
DASHBOARD_WINDOW_OPTIONS = [7, 30]
MIN_ELIGIBLE_FOR_30D_DEFAULT = 2
TREND_MIN_DATE = pd.Timestamp("2025-01-01")
TREND_MIN_DATE_LABEL = "2025-01-01"
MEDAL_GOAL_TREND_SNAPSHOTS = 3
MIN_MEDAL_ROWS_FOR_TRACKING_START = 10
EXCLUDED_MANUAL_MEDAL_IDS = {"total_xp", DERIVED_MEDAL_ID}
GOAL_ALIAS_BY_MEDAL_ID = {
    "distance_walked": "jogger",
    "pokemon_caught": "collector",
    "pokestops_visited": "backpacker",
    "pokestops_vistited": "backpacker",
}
EXCLUDED_MEDAL_GRAPH_IDS = {"distance_walked", "pokemon_caught", "pokestops_visited", "pokestops_vistited"}
MEDAL_FILTER_SHOW_ALL = "Show all"
MEDAL_FILTER_NOT_COMPLETED = "Not completed"
MEDAL_FILTER_COMPLETED = "Completed"
MEDAL_SORT_COMPLETION = "Completion progress"
MEDAL_SORT_TIME = "Time until completion"
MEDAL_SORT_INPUT = "Data input order"
MEDAL_SORT_ASC = "Ascending"
MEDAL_SORT_DESC = "Descending"
MEDAL_SORT_DEFAULT_DIRECTION_BY_METRIC = {
    MEDAL_SORT_TIME: MEDAL_SORT_ASC,
    MEDAL_SORT_COMPLETION: MEDAL_SORT_DESC,
    MEDAL_SORT_INPUT: MEDAL_SORT_ASC,
}
XP_TAB_ACTIVITY_MEDAL_IDS = {
    "distance_walked": "jogger",
    "pokemon_caught": "collector",
}
POKEDEX_ENTRY_TYPES = [
    "pokemon",
    "shiny",
    "lucky",
    "xxl",
    "xxs",
    "gmax",
    "mega",
    "shadow",
    "purified",
    "hundo",
]
POKEDEX_ENTRY_TYPE_LABELS = {
    "pokemon": "Pokemon",
    "shiny": "Shiny",
    "lucky": "Lucky",
    "xxl": "XXL",
    "xxs": "XXS",
    "gmax": "G-Max",
    "mega": "Mega",
    "shadow": "Shadow",
    "purified": "Purified",
    "hundo": "100%",
}
POKEDEX_REGIONS = [
    "overall",
    "kanto",
    "johto",
    "hoenn",
    "sinnoh",
    "unova",
    "kalos",
    "alola",
    "galar",
    "hisui",
    "paldea",
    "unidentified",
]
POKEDEX_REGION_LABELS = {
    "overall": "Overall",
    "kanto": "Kanto",
    "johto": "Johto",
    "hoenn": "Hoenn",
    "sinnoh": "Sinnoh",
    "unova": "Unova",
    "kalos": "Kalos",
    "alola": "Alola",
    "galar": "Galar",
    "hisui": "Hisui",
    "paldea": "Paldea",
    "unidentified": "Unidentified",
}
POKEDEX_MEDAL_REGION_IDS = {
    "kanto",
    "johto",
    "hoenn",
    "sinnoh",
    "unova",
    "kalos",
    "alola",
    "galar",
    "hisui",
    "paldea",
}
SPECIAL_PLATINUM_MEDALS = [
    {
        "medal_id": "vivillon_collector",
        "display_name": "Vivillon Collector",
        "account_flags": {
            "Thombay": True,
            "Cerius": False,
            "Thomzay": False,
        },
        "account_achieved_date": {
            "Thombay": "2025-06-27",
        },
    }
]
UI_PREFERENCES_PATH = config_dir() / "ui_preferences.json"
UI_PREF_DASHBOARD_WINDOW_DAYS = "dashboard_window_days"
UI_PREF_DASHBOARD_GAP_LEADER_BY_GROUP = "dashboard_gap_leader_by_group"
UI_PREF_DATA_INPUT_INACTIVE = "data_input_inactive"
UI_PREF_DATA_INPUT_INACTIVE_DEFAULTS = "data_input_inactive_defaults"
ACCOUNT_COLORWAY = [
    "#4FA3FF",
    "#FF9F1C",
    "#2EC4B6",
    "#E71D36",
    "#9B5DE5",
    "#00BBF9",
    "#FFBF69",
    "#80ED99",
    "#F15BB5",
    "#AACC00",
    "#43AA8B",
    "#577590",
    "#F3722C",
    "#277DA1",
    "#90BE6D",
    "#F8961E",
    "#F94144",
    "#00F5D4",
    "#C77DFF",
    "#FFD166",
]


def ensure_account_in_xp_order(account_name: str, known_accounts: list[str] | None = None) -> None:
    account = str(account_name).strip()
    if not account:
        return
    base_accounts = [str(a).strip() for a in (known_accounts or []) if str(a).strip()]
    if account not in base_accounts:
        base_accounts.append(account)
    ordered = load_xp_input_order(base_accounts)
    if account not in ordered:
        ordered.append(account)
    save_xp_input_order(ordered)


def with_derived_platinum_rows(medal_df: pd.DataFrame, goals_df: pd.DataFrame) -> pd.DataFrame:
    if medal_df.empty or goals_df.empty:
        return medal_df.copy()

    source = medal_df.copy()
    source["date"] = pd.to_datetime(source["date"], errors="coerce")
    source["account"] = source["account"].astype(str).str.strip()
    source["medal_id"] = source["medal_id"].astype(str).str.strip().str.lower()
    source["value"] = pd.to_numeric(source["value"], errors="coerce")
    source = source.dropna(subset=["date", "account", "medal_id", "value"]).copy()
    source = source[~source["medal_id"].isin(EXCLUDED_MANUAL_MEDAL_IDS)].copy()
    if source.empty:
        return medal_df.copy()

    goals = goals_df[["medal_id", "goal_value"]].copy()
    goals["medal_id"] = goals["medal_id"].astype(str).str.strip().str.lower()
    goals["goal_medal_id"] = goals["medal_id"].map(goal_medal_id_for)
    goals["goal_value"] = pd.to_numeric(goals["goal_value"], errors="coerce")
    goals = goals.dropna(subset=["goal_medal_id", "goal_value"]).copy()
    goals = goals.sort_values("goal_value", ascending=False).drop_duplicates(subset=["goal_medal_id"], keep="first")

    source["goal_medal_id"] = source["medal_id"].map(goal_medal_id_for)
    source = source.merge(goals[["goal_medal_id", "goal_value"]], on="goal_medal_id", how="left")
    source = source.dropna(subset=["goal_value"]).copy()
    # Alias-safe de-duplication: if both legacy and canonical IDs exist for the same day, count only once.
    source = (
        source.sort_values("date")
        .groupby(["date", "account", "goal_medal_id"], as_index=False)
        .agg({"value": "max", "goal_value": "max"})
    )
    platinum_frames: list[pd.DataFrame] = []
    for account, grp in source.groupby("account", sort=False):
        g = grp.sort_values("date").copy()
        if g.empty:
            continue
        value_wide = g.pivot_table(index="date", columns="goal_medal_id", values="value", aggfunc="max")
        if value_wide.empty:
            continue
        value_wide = value_wide.sort_index().ffill()
        goal_by_medal = g.groupby("goal_medal_id", as_index=True)["goal_value"].max()
        common_cols = [c for c in value_wide.columns if c in set(goal_by_medal.index)]
        if not common_cols:
            continue
        reached_wide = value_wide[common_cols].ge(goal_by_medal.loc[common_cols], axis=1).fillna(False)
        counts = reached_wide.sum(axis=1).astype(int)
        platinum_frames.append(
            pd.DataFrame(
                {
                    "date": pd.to_datetime(counts.index, errors="coerce"),
                    "account": str(account),
                    "reached": counts.values,
                }
            )
        )
    platinum_counts = pd.concat(platinum_frames, ignore_index=True) if platinum_frames else pd.DataFrame(
        columns=["date", "account", "reached"]
    )
    if not platinum_counts.empty:
        bonus = pd.Series(0, index=platinum_counts.index, dtype="int64")
        for special in SPECIAL_PLATINUM_MEDALS:
            flags = special.get("account_flags", {})
            achieved_dates = special.get("account_achieved_date", {})
            for acc, is_true in flags.items():
                if not bool(is_true):
                    continue
                ach_raw = achieved_dates.get(acc)
                ach_date = pd.to_datetime(ach_raw, errors="coerce")
                if pd.isna(ach_date):
                    continue
                mask = (
                    platinum_counts["account"].astype(str).eq(str(acc))
                    & (pd.to_datetime(platinum_counts["date"], errors="coerce") >= ach_date)
                )
                bonus = bonus + mask.astype(int)
        if int(bonus.sum()) > 0:
            platinum_counts["reached"] = platinum_counts["reached"] + bonus
    if platinum_counts.empty:
        return medal_df.copy()

    platinum_rows = pd.DataFrame(
        {
            "date": platinum_counts["date"],
            "account": platinum_counts["account"],
            "medal_id": DERIVED_MEDAL_ID,
            "value": platinum_counts["reached"],
        }
    )

    combined = pd.concat([medal_df.copy(), platinum_rows], ignore_index=True)
    combined = combined.drop_duplicates(subset=["date", "account", "medal_id"], keep="last")
    order_map = {name: i for i, name in enumerate(ACCOUNT_ORDER)}
    combined["_acc_order"] = combined["account"].map(order_map).fillna(999)
    combined = combined.sort_values(["date", "_acc_order", "account", "medal_id"]).drop(columns=["_acc_order"])
    return combined.reset_index(drop=True)


def goal_medal_id_for(medal_id: str) -> str:
    mid = str(medal_id).strip().lower()
    return GOAL_ALIAS_BY_MEDAL_ID.get(mid, mid)


def medal_explanation_map_from_goals(goals_df: pd.DataFrame) -> dict[str, str]:
    if goals_df.empty or not {"medal_id", "explanation"}.issubset(goals_df.columns):
        return {}
    df = goals_df[["medal_id", "explanation"]].copy()
    df["medal_id"] = df["medal_id"].fillna("").astype(str).str.strip().str.lower().map(goal_medal_id_for)
    df["explanation"] = df["explanation"].fillna("").astype(str).str.strip()
    df["explanation_lc"] = df["explanation"].str.lower()
    df = df[
        (df["medal_id"] != "")
        & (df["explanation"] != "")
        & (~df["explanation_lc"].isin({"nan", "none", "null"}))
    ].copy()
    return dict(zip(df["medal_id"].tolist(), df["explanation"].tolist()))


def _filter_trend_series(series: pd.DataFrame, date_col: str, value_col: str) -> pd.DataFrame:
    s = series.copy()
    s[date_col] = pd.to_datetime(s[date_col], errors="coerce")
    s[value_col] = pd.to_numeric(s[value_col], errors="coerce")
    s = s.dropna(subset=[date_col, value_col]).copy()
    s = s[s[date_col] >= TREND_MIN_DATE].copy()
    return s.sort_values(date_col)


def _goal_projection_fit_series(
    series: pd.DataFrame,
    *,
    date_col: str,
    value_col: str,
    trend_points: int | None = None,
) -> pd.DataFrame:
    s = _filter_trend_series(series, date_col, value_col)
    if trend_points is not None and int(trend_points) > 0 and len(s) > int(trend_points):
        s = s.tail(int(trend_points)).copy()
    return s.reset_index(drop=True)


def infer_medal_tracking_start_dates(
    medal_df: pd.DataFrame,
    min_medal_rows: int = MIN_MEDAL_ROWS_FOR_TRACKING_START,
) -> dict[str, pd.Timestamp]:
    if medal_df.empty:
        return {}
    d = medal_df.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d["account"] = d["account"].astype(str).str.strip()
    d["medal_id"] = d["medal_id"].astype(str).str.strip().str.lower()
    d["value"] = pd.to_numeric(d["value"], errors="coerce")
    d = d.dropna(subset=["date", "account", "medal_id", "value"]).copy()
    d = d[~d["medal_id"].isin(EXCLUDED_MANUAL_MEDAL_IDS)].copy()
    if d.empty:
        return {}

    d["goal_medal_id"] = d["medal_id"].map(goal_medal_id_for)
    # If both legacy and canonical IDs exist for the same day, count them once.
    d = d.sort_values("date").drop_duplicates(["date", "account", "goal_medal_id"], keep="last")
    per_day = d.groupby(["account", "date"], as_index=False)["goal_medal_id"].nunique()
    per_day = per_day.rename(columns={"goal_medal_id": "medal_count"})
    if per_day.empty:
        return {}

    starts: dict[str, pd.Timestamp] = {}
    for account, grp in per_day.groupby("account", sort=False):
        g = grp.sort_values("date")
        tracked = g[g["medal_count"] >= int(min_medal_rows)]
        start = pd.to_datetime(tracked["date"].min(), errors="coerce") if not tracked.empty else pd.to_datetime(
            g["date"].min(), errors="coerce"
        )
        if pd.notna(start):
            starts[str(account)] = pd.Timestamp(start)
    return starts


def _predict_goal_eta(series: pd.DataFrame, goal_value: float, trend_points: int | None = None) -> pd.Timestamp | None:
    s = _goal_projection_fit_series(series, date_col="date", value_col="value", trend_points=trend_points)
    if len(s) < 2 or pd.isna(goal_value):
        return None

    last_value = float(s["value"].iloc[-1])
    if last_value >= float(goal_value):
        return None

    x = s["date"].map(pd.Timestamp.toordinal).astype(float)
    y = s["value"].astype(float)
    x_mean = float(x.mean())
    y_mean = float(y.mean())
    denom = float(((x - x_mean) ** 2).sum())
    if denom <= 0:
        return None

    slope = float(((x - x_mean) * (y - y_mean)).sum() / denom)
    if slope <= 0:
        return None

    intercept = y_mean - slope * x_mean
    target_x = (float(goal_value) - intercept) / slope
    last_x = float(x.iloc[-1])
    if target_x <= last_x:
        return None
    if (target_x - last_x) > 3650:
        return None
    return pd.Timestamp.fromordinal(int(round(target_x)))


def build_platinum_goal_projection_trace(
    source_df: pd.DataFrame,
    account: str,
    goals_map: dict[str, float],
    platinum_goal: float,
    color: str | None = None,
) -> go.Scatter | None:
    d = source_df.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d["account"] = d["account"].astype(str).str.strip()
    d["medal_id"] = d["medal_id"].astype(str).str.strip().str.lower()
    d["value"] = pd.to_numeric(d["value"], errors="coerce")
    d = d.dropna(subset=["date", "account", "medal_id", "value"]).copy()
    d = d[d["account"] == account].copy()
    d = d[d["medal_id"] != DERIVED_MEDAL_ID].copy()
    if d.empty:
        return None

    d["goal_medal_id"] = d["medal_id"].map(goal_medal_id_for)
    d = d[~d["goal_medal_id"].isin(EXCLUDED_MANUAL_MEDAL_IDS)].copy()
    d["goal_value"] = d["goal_medal_id"].map(goals_map)
    d = d.dropna(subset=["goal_value"]).copy()
    if d.empty:
        return None

    # If aliases map to the same canonical medal, keep the highest value for that day.
    d = (
        d.sort_values("date")
        .groupby(["goal_medal_id", "date"], as_index=False)
        .agg({"value": "max", "goal_value": "max"})
    )

    latest = d.sort_values("date").groupby("goal_medal_id", as_index=False).tail(1)
    if latest.empty:
        return None
    latest["reached"] = latest["value"] >= latest["goal_value"]
    current_count = int(latest["reached"].sum())
    current_date = pd.to_datetime(latest["date"].max(), errors="coerce")
    if pd.isna(current_date) or current_count >= float(platinum_goal):
        return None

    eta_dates: list[pd.Timestamp] = []
    pending = latest[~latest["reached"]].copy()
    for _, row in pending.iterrows():
        goal_medal_id = str(row["goal_medal_id"])
        goal_value = float(row["goal_value"])
        medal_series = d[d["goal_medal_id"] == goal_medal_id][["date", "value"]]
        eta = _predict_goal_eta(medal_series, goal_value)
        if eta is None:
            continue
        eta = pd.Timestamp(eta).normalize()
        if eta <= current_date:
            continue
        eta_dates.append(eta)

    if not eta_dates:
        return None

    events = pd.Series(eta_dates, dtype="datetime64[ns]").value_counts().sort_index()
    x = [pd.Timestamp(current_date)]
    y = [float(current_count)]
    running = float(current_count)
    eta_goal: pd.Timestamp | None = None
    for ev_date, add_count in events.items():
        running += float(add_count)
        x.append(pd.Timestamp(ev_date))
        y.append(running)
        if eta_goal is None and running >= float(platinum_goal):
            eta_goal = pd.Timestamp(ev_date)
            break

    if eta_goal is None:
        return None

    line_style: dict[str, object] = {"dash": "dot"}
    if color:
        line_style["color"] = color
    return go.Scatter(
        x=x,
        y=y,
        mode="lines",
        line_shape="hv",
        name=f"{account} completion trend -> {eta_goal.date().isoformat()}",
        line=line_style,
        hovertemplate="trend from medal completion ETAs<extra></extra>",
    )


def build_goal_projection_trace(
    series: pd.DataFrame,
    goal_value: float,
    account: str,
    color: str | None = None,
) -> go.Scatter | None:
    s = _goal_projection_fit_series(
        series,
        date_col="date",
        value_col="value",
        trend_points=MEDAL_GOAL_TREND_SNAPSHOTS,
    )
    if s.empty:
        return None
    eta = _predict_goal_eta(s[["date", "value"]], goal_value, trend_points=MEDAL_GOAL_TREND_SNAPSHOTS)
    if eta is None:
        return None

    x = s["date"].map(pd.Timestamp.toordinal).astype(float)
    y = s["value"].astype(float)
    x_mean = float(x.mean())
    y_mean = float(y.mean())
    denom = float(((x - x_mean) ** 2).sum())
    if denom <= 0:
        return None
    slope = float(((x - x_mean) * (y - y_mean)).sum() / denom)
    intercept = y_mean - slope * x_mean
    last_x = float(x.iloc[-1])
    y_last_fit = intercept + slope * last_x
    line_style: dict[str, object] = {"dash": "dot"}
    if color:
        line_style["color"] = color

    return go.Scatter(
        x=[s["date"].iloc[-1], eta],
        y=[y_last_fit, float(goal_value)],
        mode="lines",
        name=f"{account} trend -> {eta.date().isoformat()}",
        line=line_style,
        hovertemplate="trend to goal<extra></extra>",
    )


def build_xp_projection_trace(
    series: pd.DataFrame,
    goal_value: float,
    account: str,
    color: str | None = None,
) -> go.Scatter | None:
    s = _filter_trend_series(series, "Date", "Total XP")
    if s.empty:
        return None

    eta = _predict_goal_eta(s.rename(columns={"Date": "date", "Total XP": "value"})[["date", "value"]], goal_value)
    if eta is None:
        return None

    x = s["Date"].map(pd.Timestamp.toordinal).astype(float)
    y = s["Total XP"].astype(float)
    x_mean = float(x.mean())
    y_mean = float(y.mean())
    denom = float(((x - x_mean) ** 2).sum())
    if denom <= 0:
        return None
    slope = float(((x - x_mean) * (y - y_mean)).sum() / denom)
    intercept = y_mean - slope * x_mean

    last_date = pd.Timestamp(s["Date"].iloc[-1])
    last_x = float(last_date.toordinal())
    y_start = intercept + slope * last_x

    line_style: dict[str, object] = {"dash": "dot"}
    if color:
        line_style["color"] = color

    return go.Scatter(
        x=[last_date, eta],
        y=[y_start, float(goal_value)],
        mode="lines",
        name=f"{account} trend -> {eta.date().isoformat()}",
        line=line_style,
        hovertemplate="trend to goal<extra></extra>",
    )


def add_light_goal_reference(
    fig: go.Figure,
    goal_value: float,
    goal_label: str,
    *,
    band_ratio: float = 0.002,
    min_band_half: float = 0.5,
) -> None:
    goal = float(goal_value)
    band_half = max(float(min_band_half), abs(goal) * float(band_ratio))
    fig.add_hrect(
        y0=goal - band_half,
        y1=goal + band_half,
        fillcolor="rgba(100, 116, 139, 0.10)",
        line_width=0,
        layer="below",
    )
    fig.add_hline(
        y=goal,
        line_dash="dot",
        line_color="rgba(71, 85, 105, 0.70)",
        annotation_text=goal_label,
        annotation_position="top left",
    )


def _goal_days_status_for_account(
    series: pd.DataFrame,
    *,
    date_col: str,
    value_col: str,
    goal_value: float,
) -> tuple[str, str]:
    s = _filter_trend_series(series, date_col, value_col)
    if s.empty:
        return "n/a (insufficient trend data)", "unknown"

    def _pace_suffix() -> str:
        latest_pace: float | None = None
        previous_pace: float | None = None
        if len(s) >= 2:
            latest_value = pd.to_numeric(pd.Series([s[value_col].iloc[-1]]), errors="coerce").iloc[0]
            prev_value = pd.to_numeric(pd.Series([s[value_col].iloc[-2]]), errors="coerce").iloc[0]
            latest_dt = pd.Timestamp(s[date_col].iloc[-1]).normalize()
            prev_dt = pd.Timestamp(s[date_col].iloc[-2]).normalize()
            latest_days = int((latest_dt - prev_dt).days)
            if pd.notna(latest_value) and pd.notna(prev_value) and latest_days > 0:
                latest_pace = float(latest_value - prev_value) / float(latest_days)
        if len(s) >= 3:
            prev_value = pd.to_numeric(pd.Series([s[value_col].iloc[-2]]), errors="coerce").iloc[0]
            prev2_value = pd.to_numeric(pd.Series([s[value_col].iloc[-3]]), errors="coerce").iloc[0]
            prev_dt = pd.Timestamp(s[date_col].iloc[-2]).normalize()
            prev2_dt = pd.Timestamp(s[date_col].iloc[-3]).normalize()
            prev_days = int((prev_dt - prev2_dt).days)
            if pd.notna(prev_value) and pd.notna(prev2_value) and prev_days > 0:
                previous_pace = float(prev_value - prev2_value) / float(prev_days)
        if latest_pace is None:
            return ""
        if previous_pace is None:
            return f" | pace {latest_pace:,.2f}/day"
        return f" | pace {latest_pace:,.2f}/day vs prev {previous_pace:,.2f}/day"

    latest_date = pd.Timestamp(s[date_col].iloc[-1]).normalize()
    goal = float(goal_value)
    reached_rows = s[pd.to_numeric(s[value_col], errors="coerce") >= goal]
    if not reached_rows.empty:
        reached_date = pd.Timestamp(reached_rows[date_col].iloc[0]).normalize()
        reached_txt = reached_date.date().isoformat()
        days_ahead = int((latest_date - reached_date).days)
        if days_ahead <= 0:
            return f"completed (reached {reached_txt}){_pace_suffix()}", "completed"
        return f"completed ({days_ahead}d ago, reached {reached_txt}){_pace_suffix()}", "completed"

    eta = _predict_goal_eta(
        s.rename(columns={date_col: "date", value_col: "value"})[["date", "value"]],
        goal,
        trend_points=MEDAL_GOAL_TREND_SNAPSHOTS,
    )

    if eta is None:
        return "no ETA yet (trend too flat/negative)", "unknown"
    eta_txt = pd.Timestamp(eta).date().isoformat()

    previous_eta: pd.Timestamp | None = None
    if len(s) >= 3:
        previous_eta = _predict_goal_eta(
            s.iloc[:-1].rename(columns={date_col: "date", value_col: "value"})[["date", "value"]],
            goal,
            trend_points=MEDAL_GOAL_TREND_SNAPSHOTS,
        )

    if previous_eta is None:
        days_to_goal = int((pd.Timestamp(eta).normalize() - latest_date).days)
        if days_to_goal <= 0:
            return f"ETA {eta_txt}{_pace_suffix()}", "unknown"
        return f"ETA {eta_txt} ({days_to_goal}d from latest snapshot){_pace_suffix()}", "unknown"

    eta_shift_days = int((pd.Timestamp(eta).normalize() - pd.Timestamp(previous_eta).normalize()).days)
    if eta_shift_days < 0:
        return f"ETA improved by {abs(eta_shift_days)}d since last snapshot (ETA {eta_txt}){_pace_suffix()}", "improved"
    if eta_shift_days > 0:
        return f"ETA worsened by {abs(eta_shift_days)}d since last snapshot (ETA {eta_txt}){_pace_suffix()}", "declined"
    return f"ETA unchanged since last snapshot (ETA {eta_txt}){_pace_suffix()}", "unknown"


def build_goal_days_status_html(
    line_df: pd.DataFrame,
    *,
    account_col: str,
    date_col: str,
    value_col: str,
    goal_value: float,
) -> str | None:
    if line_df.empty:
        return None
    if not {account_col, date_col, value_col}.issubset(line_df.columns):
        return None

    account_names = line_df[account_col].dropna().astype(str).str.strip()
    unique_accounts = [a for a in account_names.tolist() if a]
    if not unique_accounts:
        return None
    unique_account_set = set(unique_accounts)
    ordered_accounts = [a for a in ACCOUNT_ORDER if a in unique_account_set]
    ordered_accounts += sorted([a for a in unique_account_set if a not in set(ordered_accounts)])

    rows: list[str] = []
    for account in ordered_accounts:
        grp = line_df[line_df[account_col].astype(str).str.strip() == account][[date_col, value_col]].copy()
        if grp.empty:
            continue
        status_text, status_kind = _goal_days_status_for_account(
            grp,
            date_col=date_col,
            value_col=value_col,
            goal_value=float(goal_value),
        )
        account_name = escape(str(account))
        status_color_map = {
            "improved": "#16A34A",
            "declined": "#DC2626",
            "completed": "#2563EB",
            "unknown": "#64748B",
        }
        status_color = status_color_map.get(status_kind, "#64748B")
        rows.append(f"<span style='color:{status_color}'><b>{account_name}</b>: {escape(status_text)}</span>")

    if not rows:
        return None

    return (
        "<b>Goal Pace</b><br>"
        "<span style='color:#94A3B8'>ETA change since previous snapshot</span><br>"
        + "<br>".join(rows)
    )


def add_goal_days_status_annotation(
    fig: go.Figure,
    line_df: pd.DataFrame,
    *,
    account_col: str,
    date_col: str,
    value_col: str,
    goal_value: float,
    y_top: float = 0.76,
) -> None:
    if fig is None:
        return

    status_html = build_goal_days_status_html(
        line_df,
        account_col=account_col,
        date_col=date_col,
        value_col=value_col,
        goal_value=float(goal_value),
    )
    if not status_html:
        return

    legend_items = 0
    for tr in fig.data:
        if getattr(tr, "showlegend", None) is False:
            continue
        name = str(getattr(tr, "name", "")).strip()
        if not name or name == "_nolegend_":
            continue
        legend_items += 1

    # Move the status block below the legend based on legend length.
    legend_bottom_y = 1.0 - (0.07 * float(max(0, legend_items)))
    annotation_y = min(float(y_top), legend_bottom_y - 0.04)
    annotation_y = max(0.06, annotation_y)

    current_margin = getattr(fig.layout, "margin", None)
    margin_dict: dict[str, int] = {}
    if current_margin is not None:
        for key in ("l", "r", "t", "b"):
            value = getattr(current_margin, key, None)
            if value is not None:
                margin_dict[key] = int(value)
    margin_dict["r"] = max(int(margin_dict.get("r", 0)), 220)
    fig.update_layout(
        legend=dict(orientation="v", yanchor="top", y=1.0, xanchor="left", x=1.01),
        margin=margin_dict,
    )
    fig.add_annotation(
        xref="paper",
        yref="paper",
        x=1.01,
        y=float(annotation_y),
        xanchor="left",
        yanchor="top",
        align="left",
        showarrow=False,
        text=status_html,
    )


def restrict_to_common_interval(df: pd.DataFrame) -> pd.DataFrame:
    return restrict_to_max_data_start_interval(df, date_col="Date", group_col="Spieler")


def _activity_chart_dates(
    series_df: pd.DataFrame,
    visible_start: pd.Timestamp,
    visible_end: pd.Timestamp,
    chart_dates: list[pd.Timestamp],
    start_date: pd.Timestamp | None = None,
) -> list[pd.Timestamp]:
    visible_start_ts = pd.Timestamp(visible_start)
    visible_end_ts = pd.Timestamp(visible_end)
    start_ts = pd.Timestamp(start_date) if start_date is not None else visible_start_ts
    if start_ts < visible_start_ts:
        start_ts = visible_start_ts
    if start_ts > visible_end_ts:
        start_ts = visible_end_ts
    shared_dates = {
        pd.Timestamp(dt)
        for dt in chart_dates
        if start_ts <= pd.Timestamp(dt) <= visible_end_ts
    }
    shared_dates.add(start_ts)
    if series_df.empty:
        return sorted(shared_dates)
    d = series_df.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d["account"] = d["account"].astype(str).str.strip()
    d = d.dropna(subset=["date", "account"]).copy()
    d = d[(d["date"] >= start_ts) & (d["date"] <= visible_end_ts)].copy()
    if d.empty:
        return sorted(shared_dates)
    first_visible_dates = d.groupby("account")["date"].min().dropna().tolist()
    return sorted(shared_dates.union(pd.Timestamp(dt) for dt in first_visible_dates))


def _activity_mode_start_date(
    series_df: pd.DataFrame,
    visible_start: pd.Timestamp,
    visible_end: pd.Timestamp,
) -> pd.Timestamp:
    visible_start_ts = pd.Timestamp(visible_start)
    visible_end_ts = pd.Timestamp(visible_end)
    if series_df.empty:
        return visible_start_ts
    d = series_df.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d["account"] = d["account"].astype(str).str.strip()
    d = d.dropna(subset=["date", "account"]).copy()
    d = d[d["date"] <= visible_end_ts].copy()
    if d.empty:
        return visible_start_ts
    first_dates = d.groupby("account")["date"].min().dt.normalize()
    if first_dates.empty:
        return visible_start_ts
    counts = first_dates.value_counts()
    max_count = int(counts.max()) if not counts.empty else 0
    if max_count <= 0:
        return visible_start_ts
    mode_start = pd.Timestamp(counts[counts == max_count].index.min())
    if mode_start < visible_start_ts:
        return visible_start_ts
    if mode_start > visible_end_ts:
        return visible_end_ts
    return mode_start


def _carry_forward_chart_rows(
    series_df: pd.DataFrame,
    chart_dates: list[pd.Timestamp],
    value_cols: list[str],
) -> pd.DataFrame:
    return carry_forward_value_rows(
        series_df,
        date_col="date",
        group_col="account",
        value_cols=value_cols,
        chart_dates=chart_dates,
    )


def _carry_forward_xp_chart_rows(xp_df: pd.DataFrame, chart_dates: list[pd.Timestamp]) -> pd.DataFrame:
    cols = ["Date", "Spieler", "Total XP"]
    out = carry_forward_value_rows(
        xp_df,
        date_col="Date",
        group_col="Spieler",
        value_cols=["Total XP"],
        chart_dates=chart_dates,
    )
    if out.empty:
        return pd.DataFrame(columns=cols)
    return out[cols].sort_values(["Date", "Spieler"]).reset_index(drop=True)


def select_real_xp_chart_rows(
    xp_df: pd.DataFrame,
    visible_start: object,
    visible_end: object,
) -> pd.DataFrame:
    cols = ["Date", "Spieler", "Total XP"]
    if xp_df.empty or not set(cols).issubset(xp_df.columns):
        return pd.DataFrame(columns=cols)
    start_ts = pd.to_datetime(visible_start, errors="coerce")
    end_ts = pd.to_datetime(visible_end, errors="coerce")
    if pd.isna(start_ts) or pd.isna(end_ts):
        return pd.DataFrame(columns=cols)
    out = xp_df.copy()
    out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
    out["Spieler"] = out["Spieler"].astype(str).str.strip()
    out["Total XP"] = pd.to_numeric(out["Total XP"], errors="coerce")
    out = out.dropna(subset=cols).copy()
    out = out[(out["Date"] >= pd.Timestamp(start_ts)) & (out["Date"] <= pd.Timestamp(end_ts))].copy()
    return out[cols].sort_values(["Date", "Spieler"]).reset_index(drop=True)


def build_rank_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.sort_values(["Date", "Spieler"]).copy()
    tie_order = {p: i for i, p in enumerate(sorted(out["Spieler"].unique()))}
    out["_tie"] = out["Spieler"].map(tie_order)
    out = out.sort_values(["Date", "Total XP", "_tie"], ascending=[True, False, True])
    out["Rank"] = out.groupby("Date").cumcount() + 1
    return out.drop(columns=["_tie"]).reset_index(drop=True)


def infer_default_gap_leader(df: pd.DataFrame) -> str | None:
    if df.empty or not {"Date", "Spieler", "Total XP"}.issubset(df.columns):
        return None
    d = df.copy()
    d["Date"] = pd.to_datetime(d["Date"], errors="coerce")
    d["Total XP"] = pd.to_numeric(d["Total XP"], errors="coerce")
    d["Spieler"] = d["Spieler"].astype(str).str.strip()
    d = d.dropna(subset=["Date", "Spieler", "Total XP"]).copy()
    if d.empty:
        return None
    latest_date = d["Date"].max()
    latest = d[d["Date"] == latest_date].copy()
    if latest.empty:
        return None
    latest = latest.sort_values(["Total XP", "Spieler"], ascending=[False, True])
    return str(latest.iloc[0]["Spieler"])


def build_gap_change_df(df: pd.DataFrame, leader: str | None = None) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.sort_values(["Date", "Spieler"]).copy()
    selected_leader = str(leader).strip() if leader is not None else ""
    if selected_leader:
        leader_rows = out[out["Spieler"] == selected_leader][["Date", "Total XP"]].copy()
        leader_rows = leader_rows.sort_values("Date").drop_duplicates(subset=["Date"], keep="last")
        leader_rows = leader_rows.rename(columns={"Total XP": "Leader XP"})
        out = out.merge(leader_rows, on="Date", how="left")
        out = out.dropna(subset=["Leader XP"]).copy()
        out["Gap"] = out["Leader XP"] - out["Total XP"]
        out = out.drop(columns=["Leader XP"])
    else:
        out["Gap"] = out.groupby("Date")["Total XP"].transform("max") - out["Total XP"]
    out["Gap Change"] = out["Gap"] - out.groupby("Spieler")["Gap"].transform("first")
    return out


def gap_baseline_annotation_text(gap_df: pd.DataFrame, leader: str | None = None) -> str:
    selected_leader = str(leader).strip() if leader is not None else ""
    if selected_leader:
        return f"{selected_leader} baseline (0)"
    if gap_df.empty or not {"Date", "Spieler", "Total XP"}.issubset(gap_df.columns):
        return "Baseline (0)"
    d = gap_df.copy()
    d["Date"] = pd.to_datetime(d["Date"], errors="coerce")
    d["Total XP"] = pd.to_numeric(d["Total XP"], errors="coerce")
    d = d.dropna(subset=["Date", "Spieler", "Total XP"]).copy()
    if d.empty:
        return "Baseline (0)"
    latest_date = d["Date"].max()
    latest = d[d["Date"] == latest_date].copy()
    if latest.empty:
        return "Baseline (0)"
    latest = latest.sort_values(["Total XP", "Spieler"], ascending=[False, True])
    leader = str(latest.iloc[0]["Spieler"])
    return leader


def _clean_xp_series_for_projection(series: pd.DataFrame) -> pd.DataFrame:
    s = series.copy()
    s["Date"] = pd.to_datetime(s["Date"], errors="coerce")
    s["Total XP"] = pd.to_numeric(s["Total XP"], errors="coerce")
    s = s.dropna(subset=["Date", "Total XP"]).copy()
    if s.empty:
        return s
    s = s[s["Date"] >= pd.Timestamp(TREND_MIN_DATE)].copy()
    s = s.sort_values("Date").drop_duplicates(subset=["Date"], keep="last")
    return s[["Date", "Total XP"]].reset_index(drop=True)


def build_xp_projection_series_map(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    required = {"Spieler", "Date", "Total XP"}
    if df.empty or not required.issubset(df.columns):
        return {}

    d = df.copy()
    d["Spieler"] = d["Spieler"].astype(str).str.strip()
    series_map: dict[str, pd.DataFrame] = {}
    for player, grp in d.groupby("Spieler", sort=True):
        cleaned = _clean_xp_series_for_projection(grp[["Date", "Total XP"]])
        series_map[str(player)] = cleaned
    return series_map


def _fit_linear_xp_trend(series: pd.DataFrame) -> tuple[pd.DataFrame, float, float] | None:
    s = _clean_xp_series_for_projection(series)
    if len(s) < 2:
        return None
    x = s["Date"].map(pd.Timestamp.toordinal).astype(float)
    y = s["Total XP"].astype(float)
    x_mean = float(x.mean())
    y_mean = float(y.mean())
    denom = float(((x - x_mean) ** 2).sum())
    if denom <= 0:
        return None
    slope = float(((x - x_mean) * (y - y_mean)).sum() / denom)
    intercept = y_mean - slope * x_mean
    return s, slope, intercept


def build_xp_catchup_projection_trace(
    player_series: pd.DataFrame,
    leader_series: pd.DataFrame,
    player: str,
    leader: str,
    color: str | None = None,
) -> tuple[go.Scatter | None, str | None]:
    player_fit = _fit_linear_xp_trend(player_series)
    if player_fit is None:
        return None, "not possible (need at least 2 valid snapshots)"
    leader_fit = _fit_linear_xp_trend(leader_series)
    if leader_fit is None:
        return None, f"not possible (leader {leader} needs at least 2 valid snapshots)"

    p_series, p_slope, p_intercept = player_fit
    l_series, l_slope, l_intercept = leader_fit
    overlap = p_series.merge(l_series, on="Date", how="inner", suffixes=("_player", "_leader"))
    if overlap.empty:
        return None, f"not possible (no overlapping dates with {leader})"

    latest_overlap = overlap.sort_values("Date").iloc[-1]
    current_date = pd.Timestamp(latest_overlap["Date"])
    current_gap = float(latest_overlap["Total XP_leader"]) - float(latest_overlap["Total XP_player"])
    if current_gap <= 0:
        return None, f"not possible (already tied or ahead of {leader})"

    rel_slope = p_slope - l_slope
    if rel_slope <= 0:
        return None, f"not possible (trend does not close gap to {leader})"

    current_x = float(current_date.toordinal())
    target_x = (l_intercept - p_intercept) / rel_slope
    if target_x <= current_x:
        return None, f"not possible (intersection is not in the future vs {leader})"
    if (target_x - current_x) > 3650:
        return None, f"not possible (ETA beyond 10 years vs {leader})"

    eta = pd.Timestamp.fromordinal(int(round(target_x)))
    y_start = p_intercept + p_slope * current_x
    y_end = p_intercept + p_slope * target_x

    line_style: dict[str, object] = {"dash": "dot"}
    if color:
        line_style["color"] = color

    return (
        go.Scatter(
            x=[current_date, eta],
            y=[y_start, y_end],
            mode="lines",
            name=f"{player} catch {leader} -> {eta.date().isoformat()}",
            line=line_style,
            hovertemplate=f"catch-up trend vs {leader}<extra></extra>",
        ),
        None,
    )


def build_selected_leader_trend_trace(
    leader_series: pd.DataFrame,
    leader: str,
    color: str | None = None,
    horizon_days: int = 180,
    end_date: pd.Timestamp | None = None,
) -> tuple[go.Scatter | None, str | None]:
    leader_fit = _fit_linear_xp_trend(leader_series)
    if leader_fit is None:
        return None, f"not possible (leader {leader} needs at least 2 valid snapshots)"

    s, slope, intercept = leader_fit
    last_date = pd.Timestamp(s["Date"].iloc[-1])
    if pd.isna(last_date):
        return None, f"not possible (leader {leader} has no valid latest date)"

    target_end = pd.to_datetime(end_date, errors="coerce") if end_date is not None else pd.NaT
    if pd.isna(target_end) or pd.Timestamp(target_end) <= last_date:
        horizon = max(1, int(horizon_days))
        target_end = last_date + pd.Timedelta(days=horizon)
    else:
        horizon = int((pd.Timestamp(target_end) - last_date).days)
        if horizon < 1:
            horizon = 1
            target_end = last_date + pd.Timedelta(days=horizon)

    start_x = float(last_date.toordinal())
    end_x = float(pd.Timestamp(target_end).toordinal())
    y_start = intercept + slope * start_x
    y_end = intercept + slope * end_x

    line_style: dict[str, object] = {"dash": "dash"}
    if color:
        line_style["color"] = color

    return (
        go.Scatter(
            x=[last_date, pd.Timestamp(target_end)],
            y=[y_start, y_end],
            mode="lines",
            name=f"{leader} trend (+{horizon}d)",
            line=line_style,
            hovertemplate=f"{leader} trend projection<extra></extra>",
        ),
        None,
    )


def build_player_trend_projection_trace(
    player_series: pd.DataFrame,
    player: str,
    color: str | None = None,
    horizon_days: int = 365,
    end_date: pd.Timestamp | None = None,
) -> tuple[go.Scatter | None, str | None]:
    player_fit = _fit_linear_xp_trend(player_series)
    if player_fit is None:
        return None, f"not possible ({player} needs at least 2 valid snapshots)"

    s, slope, intercept = player_fit
    last_date = pd.Timestamp(s["Date"].iloc[-1])
    if pd.isna(last_date):
        return None, f"not possible ({player} has no valid latest date)"

    target_end = pd.to_datetime(end_date, errors="coerce") if end_date is not None else pd.NaT
    if pd.isna(target_end) or pd.Timestamp(target_end) <= last_date:
        horizon = max(1, int(horizon_days))
        target_end = last_date + pd.Timedelta(days=horizon)
    else:
        horizon = int((pd.Timestamp(target_end) - last_date).days)
        if horizon < 1:
            horizon = 1
            target_end = last_date + pd.Timedelta(days=horizon)

    start_x = float(last_date.toordinal())
    end_x = float(pd.Timestamp(target_end).toordinal())
    y_start = intercept + slope * start_x
    y_end = intercept + slope * end_x

    line_style: dict[str, object] = {"dash": "dot"}
    if color:
        line_style["color"] = color

    return (
        go.Scatter(
            x=[last_date, pd.Timestamp(target_end)],
            y=[y_start, y_end],
            mode="lines",
            name=f"{player} trend (+{horizon}d)",
            line=line_style,
            hovertemplate=f"{player} trend projection<extra></extra>",
        ),
        None,
    )


def split_visibility_offset_years_months(start_date: pd.Timestamp, end_date: pd.Timestamp) -> tuple[int, int]:
    start_ts = pd.to_datetime(start_date, errors="coerce")
    end_ts = pd.to_datetime(end_date, errors="coerce")
    if pd.isna(start_ts) or pd.isna(end_ts) or pd.Timestamp(end_ts) <= pd.Timestamp(start_ts):
        return 0, 0

    start = pd.Timestamp(start_ts)
    end = pd.Timestamp(end_ts)
    months_total = (end.year - start.year) * 12 + (end.month - start.month)
    if months_total < 0:
        months_total = 0

    # Round up to include partial months so the default slider keeps the full projection visible.
    if (start + pd.DateOffset(months=months_total)) < end:
        months_total += 1

    years = months_total // 12
    months = months_total % 12
    return int(years), int(months)


def autoscale_y_for_visible_x(
    fig: go.Figure,
    x_start: pd.Timestamp,
    x_end: pd.Timestamp,
    *,
    y_floor: float = 0.0,
    padding_ratio: float = 0.05,
) -> tuple[float, float] | None:
    x_min = pd.to_datetime(x_start, errors="coerce")
    x_max = pd.to_datetime(x_end, errors="coerce")
    if pd.isna(x_min) or pd.isna(x_max):
        return None
    if pd.Timestamp(x_max) <= pd.Timestamp(x_min):
        return None

    y_vals: list[float] = []
    for tr in fig.data:
        x_raw = getattr(tr, "x", None)
        y_raw = getattr(tr, "y", None)
        if x_raw is None or y_raw is None:
            continue
        x_ser = pd.to_datetime(pd.Series(list(x_raw)), errors="coerce")
        y_ser = pd.to_numeric(pd.Series(list(y_raw)), errors="coerce")
        mask = x_ser.notna() & y_ser.notna()
        if not bool(mask.any()):
            continue
        x_ser = x_ser[mask]
        y_ser = y_ser[mask]
        in_view = (x_ser >= pd.Timestamp(x_min)) & (x_ser <= pd.Timestamp(x_max))
        if bool(in_view.any()):
            y_vals.extend([float(v) for v in y_ser[in_view].tolist()])
            continue
        # Include lines fully spanning the selected window, so trend traces still influence y-range.
        if len(x_ser) >= 2 and pd.Timestamp(x_ser.min()) < pd.Timestamp(x_min) and pd.Timestamp(x_ser.max()) > pd.Timestamp(x_max):
            y_vals.extend([float(v) for v in y_ser.tolist()])

    if not y_vals:
        return None
    y_max = max(y_vals)
    top = max(float(y_floor) + 1.0, float(y_max) * (1.0 + float(padding_ratio)))
    return float(y_floor), float(top)


def get_medal_ids_for_view_mode(
    medal_ids: list[str],
    source_df: pd.DataFrame,
    goals_map: dict[str, float],
    selected_accounts: list[str],
    filter_mode: str,
    sort_metric: str,
    sort_direction: str,
    sort_account: str | None,
    input_order: list[str],
) -> list[str]:
    if not medal_ids:
        return []
    default_order = [m for m in input_order if m in set(medal_ids)] + [m for m in medal_ids if m not in set(input_order)]
    default_index = {m: i for i, m in enumerate(default_order)}

    history = source_df.copy()
    history["date"] = pd.to_datetime(history["date"], errors="coerce")
    history["account"] = history["account"].astype(str).str.strip()
    history["medal_id"] = history["medal_id"].astype(str).str.strip().str.lower().map(goal_medal_id_for)
    history["value"] = pd.to_numeric(history["value"], errors="coerce")
    history = history.dropna(subset=["date", "account", "medal_id", "value"]).copy()
    history = history[history["medal_id"].isin(set(medal_ids))].copy()
    if history.empty:
        return default_order

    selected_set = {str(a).strip() for a in selected_accounts if str(a).strip()}
    primary_sort_account = str(sort_account or "").strip()
    focus_accounts = [primary_sort_account] if primary_sort_account and primary_sort_account in selected_set else []
    if not focus_accounts:
        focus_accounts = [a for a in MEDAL_EXPLORER_CORE_ACCOUNTS if a in selected_set]
    if not focus_accounts:
        focus_accounts = [a for a in selected_accounts if str(a).strip()]
    if not focus_accounts:
        return default_order

    progress_score: dict[str, float] = {}
    eta_days_score: dict[str, float] = {}
    completed_all: dict[str, bool] = {}
    for medal_id in medal_ids:
        goal = pd.to_numeric(pd.Series([goals_map.get(goal_medal_id_for(medal_id))]), errors="coerce").iloc[0]
        if pd.isna(goal) or float(goal) <= 0:
            progress_score[medal_id] = 0.0
            eta_days_score[medal_id] = float("inf")
            completed_all[medal_id] = False
            continue
        goal_f = float(goal)
        per_acc_progress: list[float] = []
        per_acc_eta_days: list[float] = []
        per_acc_completed: list[bool] = []
        for acc in focus_accounts:
            grp = history[(history["account"] == str(acc)) & (history["medal_id"] == medal_id)].sort_values("date")
            if grp.empty:
                per_acc_progress.append(0.0)
                per_acc_eta_days.append(float("inf"))
                per_acc_completed.append(False)
                continue
            latest_value = float(pd.to_numeric(pd.Series([grp["value"].iloc[-1]]), errors="coerce").iloc[0])
            ratio = latest_value / goal_f if goal_f > 0 else 0.0
            per_acc_progress.append(ratio)
            if latest_value >= goal_f:
                per_acc_eta_days.append(0.0)
                per_acc_completed.append(True)
                continue
            eta = _predict_goal_eta(grp[["date", "value"]], goal_f)
            if eta is None:
                per_acc_eta_days.append(float("inf"))
                per_acc_completed.append(False)
                continue
            latest_date = pd.to_datetime(grp["date"].iloc[-1], errors="coerce")
            if pd.isna(latest_date):
                per_acc_eta_days.append(float("inf"))
                per_acc_completed.append(False)
                continue
            days_until = int((pd.Timestamp(eta).normalize() - pd.Timestamp(latest_date).normalize()).days)
            per_acc_eta_days.append(float(max(0, days_until)))
            per_acc_completed.append(False)
        progress_score[medal_id] = float(sum(per_acc_progress) / len(per_acc_progress)) if per_acc_progress else 0.0
        eta_days_score[medal_id] = float(max(per_acc_eta_days)) if per_acc_eta_days else float("inf")
        completed_all[medal_id] = bool(per_acc_completed) and all(per_acc_completed)

    filtered = list(default_order)
    if filter_mode == MEDAL_FILTER_NOT_COMPLETED:
        filtered = [m for m in filtered if not completed_all.get(m, False)]
    elif filter_mode == MEDAL_FILTER_COMPLETED:
        filtered = [m for m in filtered if completed_all.get(m, False)]

    if sort_metric == MEDAL_SORT_INPUT:
        if sort_direction == MEDAL_SORT_DESC:
            return list(reversed(filtered))
        return filtered

    if sort_metric == MEDAL_SORT_COMPLETION:
        if sort_direction == MEDAL_SORT_DESC:
            return sorted(filtered, key=lambda m: (-progress_score.get(m, 0.0), default_index.get(m, 9999)))
        return sorted(filtered, key=lambda m: (progress_score.get(m, 0.0), default_index.get(m, 9999)))

    if sort_metric == MEDAL_SORT_TIME:
        if sort_direction == MEDAL_SORT_DESC:
            return sorted(
                filtered,
                key=lambda m: (
                    0 if eta_days_score.get(m, float("inf")) == float("inf") else 1,
                    -eta_days_score.get(m, 0.0) if eta_days_score.get(m, float("inf")) != float("inf") else 0.0,
                    default_index.get(m, 9999),
                ),
            )
        return sorted(
            filtered,
            key=lambda m: (
                1 if eta_days_score.get(m, float("inf")) == float("inf") else 0,
                eta_days_score.get(m, float("inf")),
                default_index.get(m, 9999),
            ),
        )

    return filtered


def build_pace_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.sort_values(["Spieler", "Date"]).copy()
    out["Days Delta"] = out.groupby("Spieler")["Date"].diff().dt.total_seconds() / 86_400
    out["XP Delta"] = out.groupby("Spieler")["Total XP"].diff()
    out["XP/day"] = out["XP Delta"] / out["Days Delta"]
    out = out[out["Days Delta"] > 0].copy()
    return out


def build_xp_gain_over_time_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.sort_values(["Spieler", "Date"]).copy()
    out["XP Gain"] = out["Total XP"] - out.groupby("Spieler")["Total XP"].transform("first")
    return out


def build_snapshot_interval_days_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["account", "period_end", "interval_days"])
    out = df.copy()
    out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
    out["Spieler"] = out["Spieler"].astype(str).str.strip()
    out = out.dropna(subset=["Date", "Spieler"]).copy()
    out = out.sort_values(["Spieler", "Date"]).copy()
    out["period_start"] = out.groupby("Spieler")["Date"].shift(1)
    out["interval_days"] = (out["Date"] - out["period_start"]).dt.total_seconds() / 86_400.0
    out = out[out["interval_days"] > 0].copy()
    out = out.rename(columns={"Spieler": "account", "Date": "period_end"})
    return out[["account", "period_end", "interval_days"]].reset_index(drop=True)


def build_medal_snapshot_interval_days_df(medal_df: pd.DataFrame, accounts: list[str]) -> pd.DataFrame:
    if medal_df.empty or not accounts:
        return pd.DataFrame(columns=["account", "period_end", "interval_days"])
    d = medal_df.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d["account"] = d["account"].astype(str).str.strip()
    d = d.dropna(subset=["date", "account"]).copy()
    d = d[d["account"].isin(set([str(a).strip() for a in accounts if str(a).strip()]))].copy()
    if d.empty:
        return pd.DataFrame(columns=["account", "period_end", "interval_days"])
    # one snapshot point per account/date regardless of medal row count
    d = d.sort_values("date").drop_duplicates(["account", "date"], keep="last")
    d = d.sort_values(["account", "date"]).copy()
    d["period_start"] = d.groupby("account")["date"].shift(1)
    d["interval_days"] = (d["date"] - d["period_start"]).dt.total_seconds() / 86_400.0
    d = d[d["interval_days"] > 0].copy()
    d = d.rename(columns={"date": "period_end"})
    return d[["account", "period_end", "interval_days"]].reset_index(drop=True)


def build_medal_interval_rate_df(
    medal_df: pd.DataFrame,
    accounts: list[str],
    medal_ids: list[str],
) -> pd.DataFrame:
    cols = ["account", "period_start", "period_end", "interval_days", "delta_value", "per_day"]
    if medal_df.empty or not accounts or not medal_ids:
        return pd.DataFrame(columns=cols)

    d = medal_df.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d["account"] = d["account"].astype(str).str.strip()
    d["medal_id"] = d["medal_id"].astype(str).str.strip().str.lower().map(goal_medal_id_for)
    d["value"] = pd.to_numeric(d["value"], errors="coerce")
    d = d.dropna(subset=["date", "account", "medal_id", "value"]).copy()
    d = d[d["account"].isin(set([str(a).strip() for a in accounts if str(a).strip()]))].copy()

    wanted = [goal_medal_id_for(m) for m in medal_ids]
    wanted = [w for w in list(dict.fromkeys(wanted)) if w]
    d = d[d["medal_id"].isin(set(wanted))].copy()
    if d.empty:
        return pd.DataFrame(columns=cols)

    d = (
        d.sort_values("date")
        .groupby(["account", "date", "medal_id"], as_index=False)
        .agg({"value": "max"})
    )

    frames: list[pd.DataFrame] = []
    for account, grp in d.groupby("account", sort=False):
        wide = grp.pivot_table(index="date", columns="medal_id", values="value", aggfunc="max").sort_index().ffill()
        for mid in wanted:
            if mid not in wide.columns:
                wide[mid] = 0.0
        total = wide[wanted].sum(axis=1)
        series = pd.DataFrame({"period_end": pd.to_datetime(total.index), "cum_value": pd.to_numeric(total.values, errors="coerce")})
        series = series.dropna(subset=["period_end", "cum_value"]).sort_values("period_end")
        if len(series) < 2:
            continue
        series["period_start"] = series["period_end"].shift(1)
        series["interval_days"] = (series["period_end"] - series["period_start"]).dt.total_seconds() / 86_400.0
        series["delta_value"] = series["cum_value"].diff()
        series = series[series["interval_days"] > 0].copy()
        if series.empty:
            continue
        series["per_day"] = series["delta_value"] / series["interval_days"]
        series["account"] = str(account)
        frames.append(series[["account", "period_start", "period_end", "interval_days", "delta_value", "per_day"]])

    if not frames:
        return pd.DataFrame(columns=cols)
    return pd.concat(frames, ignore_index=True).sort_values(["account", "period_end"]).reset_index(drop=True)


def build_additional_activity_interval_rate_df(additional_df: pd.DataFrame, accounts: list[str]) -> pd.DataFrame:
    cols = ["account", "period_start", "period_end", "interval_days", "delta_value", "per_day"]
    if additional_df.empty or not accounts:
        return pd.DataFrame(columns=cols)

    d = additional_df.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d["account"] = d["account"].astype(str).str.strip()
    d["battles_won"] = pd.to_numeric(d["battles_won"], errors="coerce")
    d = d.dropna(subset=["date", "account", "battles_won"]).copy()
    d = d[d["account"].isin(set([str(a).strip() for a in accounts if str(a).strip()]))].copy()
    if d.empty:
        return pd.DataFrame(columns=cols)

    d = d.sort_values("date").drop_duplicates(["account", "date"], keep="last")
    frames: list[pd.DataFrame] = []
    for account, grp in d.groupby("account", sort=False):
        series = grp[["date", "battles_won"]].copy().sort_values("date")
        if len(series) < 2:
            continue
        series = series.rename(columns={"date": "period_end", "battles_won": "cum_value"})
        series["period_start"] = series["period_end"].shift(1)
        series["interval_days"] = (series["period_end"] - series["period_start"]).dt.total_seconds() / 86_400.0
        series["delta_value"] = series["cum_value"].diff()
        series = series[series["interval_days"] > 0].copy()
        if series.empty:
            continue
        series["per_day"] = series["delta_value"] / series["interval_days"]
        series["account"] = str(account)
        frames.append(series[["account", "period_start", "period_end", "interval_days", "delta_value", "per_day"]])

    if not frames:
        return pd.DataFrame(columns=cols)
    return pd.concat(frames, ignore_index=True).sort_values(["account", "period_end"]).reset_index(drop=True)


def _trace_last_numeric_y(trace: object) -> float | None:
    y_values = getattr(trace, "y", None)
    if y_values is None:
        return None
    values = pd.to_numeric(pd.Series(y_values), errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.iloc[-1])


def _is_figure_y_axis_reversed(fig: go.Figure, axis_token: str) -> bool:
    axis_name = "yaxis" if axis_token in {"", "y"} else f"yaxis{axis_token[1:]}"
    axis_obj = getattr(fig.layout, axis_name, None)
    if axis_obj is None:
        return False
    autorange = str(getattr(axis_obj, "autorange", "")).strip().lower()
    if autorange.startswith("reversed"):
        return True
    axis_range = getattr(axis_obj, "range", None)
    if isinstance(axis_range, (list, tuple)) and len(axis_range) == 2:
        try:
            return float(axis_range[0]) > float(axis_range[1])
        except Exception:
            return False
    return False


def sort_legend_by_latest_y(fig: go.Figure | None) -> None:
    if fig is None or not getattr(fig, "data", None):
        return
    ranked: list[tuple[int, float, str]] = []
    for idx, trace in enumerate(fig.data):
        if getattr(trace, "showlegend", None) is False:
            continue
        name = str(getattr(trace, "name", "")).strip()
        if not name or name == "_nolegend_":
            continue
        score = _trace_last_numeric_y(trace)
        if score is None:
            continue
        axis_token = str(getattr(trace, "yaxis", "y") or "y")
        ranked.append((idx, score, axis_token))
    if len(ranked) < 2:
        return

    def _sort_key(item: tuple[int, float, str]) -> tuple[float, int]:
        idx, score, axis_token = item
        reversed_axis = _is_figure_y_axis_reversed(fig, axis_token)
        return (score if reversed_axis else -score, idx)

    ordered = sorted(ranked, key=_sort_key)
    for rank, (idx, _score, _axis) in enumerate(ordered, start=1):
        fig.data[idx].update(legendrank=rank)


def apply_total_xp_legend_order(fig: go.Figure, df: pd.DataFrame) -> None:
    if fig is None or not getattr(fig, "data", None) or df.empty:
        return
    if not {"Spieler", "Date", "Total XP"}.issubset(df.columns):
        return

    ranked_df = df[["Spieler", "Date", "Total XP"]].copy()
    ranked_df["Date"] = pd.to_datetime(ranked_df["Date"], errors="coerce")
    ranked_df["Total XP"] = pd.to_numeric(ranked_df["Total XP"], errors="coerce")
    ranked_df["Spieler"] = ranked_df["Spieler"].astype(str).str.strip()
    ranked_df = ranked_df.dropna(subset=["Spieler", "Date", "Total XP"]).copy()
    if ranked_df.empty:
        return
    ranked_df = ranked_df.sort_values(["Spieler", "Date"])
    ranked_df = ranked_df.groupby("Spieler", as_index=False).tail(1)
    ranked_df = ranked_df.sort_values(["Total XP", "Spieler"], ascending=[False, True]).reset_index(drop=True)

    player_rank = {str(row["Spieler"]): int(i) for i, (_, row) in enumerate(ranked_df.iterrows(), start=1)}
    stride = 10
    fallback_rank = (len(player_rank) + 1) * stride

    for trace in fig.data:
        if getattr(trace, "showlegend", None) is False:
            continue
        name = str(getattr(trace, "name", "")).strip()
        if not name or name == "_nolegend_":
            continue

        owner: str | None = None
        offset = 9
        if name in player_rank:
            owner = name
            offset = 0
        elif " catch " in name and " -> " in name:
            owner = name.split(" catch ", 1)[0].strip()
            offset = 1
        elif " trend (" in name:
            owner = name.split(" trend (", 1)[0].strip()
            offset = 2

        if owner and owner in player_rank:
            trace.update(legendrank=player_rank[owner] * stride + offset)
        else:
            trace.update(legendrank=fallback_rank)
            fallback_rank += 1


def render_plotly_chart(fig: go.Figure, sort_legend: bool = True, **kwargs: object) -> None:
    if sort_legend:
        sort_legend_by_latest_y(fig)
    st.plotly_chart(fig, **kwargs)


def select_date_range(
    label: str,
    min_date: date,
    max_date: date,
    key: str | None = None,
    show_reset: bool = False,
) -> tuple[date, date]:
    if min_date >= max_date:
        st.caption(f"{label}: only one snapshot date available ({min_date.isoformat()}).")
        return min_date, max_date
    default_range = (min_date, max_date)
    has_session_value = False
    if key and key in st.session_state:
        has_session_value = True
        current = st.session_state.get(key)
        clamped_range = default_range
        if isinstance(current, (tuple, list)) and len(current) == 2:
            current_start, current_end = current
            if isinstance(current_start, date) and isinstance(current_end, date):
                clamped_start = min(max(current_start, min_date), max_date)
                clamped_end = min(max(current_end, min_date), max_date)
                if clamped_start > clamped_end:
                    clamped_start, clamped_end = min_date, max_date
                clamped_range = (clamped_start, clamped_end)
        st.session_state[key] = clamped_range
    slider_parent = st
    if show_reset and key:
        slider_col, reset_col = st.columns([0.86, 0.14], gap="small")
        if reset_col.button(
            "Reset",
            key=f"{key}_reset",
            icon=":material/restart_alt:",
            help=f"Reset {label.lower()} to the computed full window.",
            use_container_width=True,
        ):
            st.session_state[key] = default_range
        slider_parent = slider_col
    slider_kwargs: dict[str, object] = {
        "label": label,
        "min_value": min_date,
        "max_value": max_date,
    }
    if key:
        slider_kwargs["key"] = key
        if not has_session_value:
            slider_kwargs["value"] = default_range
    else:
        slider_kwargs["value"] = default_range
    return slider_parent.slider(**slider_kwargs)


def render_xp_explorer_section(
    xp_subset_df: pd.DataFrame,
    key_prefix: str,
    medal_subset_df: pd.DataFrame | None = None,
    show_personal_activity: bool = False,
    additional_subset_df: pd.DataFrame | None = None,
    show_global_activity_trends: bool = False,
    activity_window_days: int = 7,
    leader_preference_key: str | None = None,
) -> None:
    render_xp_explorer_section_view(
        render_impl=_render_xp_explorer_section_impl,
        xp_subset_df=xp_subset_df,
        key_prefix=key_prefix,
        medal_subset_df=medal_subset_df,
        show_personal_activity=show_personal_activity,
        additional_subset_df=additional_subset_df,
        show_global_activity_trends=show_global_activity_trends,
        activity_window_days=activity_window_days,
        leader_preference_key=leader_preference_key,
    )


def _render_xp_explorer_section_impl(
    xp_subset_df: pd.DataFrame,
    key_prefix: str,
    medal_subset_df: pd.DataFrame | None = None,
    show_personal_activity: bool = False,
    additional_subset_df: pd.DataFrame | None = None,
    show_global_activity_trends: bool = False,
    activity_window_days: int = 7,
    leader_preference_key: str | None = None,
) -> None:
    st.subheader("XP Explorer")
    if xp_subset_df.empty:
        st.info("No XP history data found for this dashboard selection.")
        return

    player_options = sorted(xp_subset_df["Spieler"].dropna().astype(str).unique().tolist())
    selected_players = st.multiselect(
        "Players",
        options=player_options,
        default=player_options,
        key=f"{key_prefix}_players",
    )
    df_source = xp_subset_df[xp_subset_df["Spieler"].isin(selected_players)].copy()
    if df_source.empty:
        st.warning("No rows for selected filters.")
        return
    account_color_map = build_account_color_map(selected_players, df_source)

    interval_source = restrict_to_common_interval(df_source)
    if interval_source.empty:
        st.warning("No rows after interval filtering.")
        return

    min_ts = pd.to_datetime(interval_source["Date"], errors="coerce").min()
    max_ts = pd.to_datetime(df_source["Date"], errors="coerce").max()
    if pd.isna(min_ts) or pd.isna(max_ts):
        st.warning("No valid dates after interval filtering.")
        return
    min_date = pd.Timestamp(min_ts).date()
    max_date = pd.Timestamp(max_ts).date()
    d_start, d_end = select_date_range(
        label="Date range",
        min_date=min_date,
        max_date=max_date,
        key=f"{key_prefix}_date_range",
        show_reset=True,
    )
    visible_start = pd.Timestamp(d_start)
    visible_end = pd.Timestamp(d_end)
    df_range = df_source[(df_source["Date"] >= visible_start) & (df_source["Date"] <= visible_end)].copy()
    if df_range.empty:
        st.warning("No rows in selected date range.")
        return

    chart_seed_df = interval_source[
        (interval_source["Date"] >= visible_start) & (interval_source["Date"] <= visible_end)
    ].copy()
    if chart_seed_df.empty:
        st.warning("No rows in selected date range after interval filtering.")
        return
    df = select_real_xp_chart_rows(df_source, visible_start, visible_end)
    if df.empty:
        st.warning("No rows in selected date range.")
        return
    chart_dates = sorted(
        pd.Timestamp(dt) for dt in pd.to_datetime(df["Date"], errors="coerce").dropna().unique().tolist()
    )
    latest_date_by_player = df.groupby("Spieler", as_index=False)["Date"].max()
    latest_dates = sorted(pd.Timestamp(dt).date().isoformat() for dt in latest_date_by_player["Date"].dropna().unique())
    if len(latest_dates) > 1:
        lagging = latest_date_by_player.sort_values(["Date", "Spieler"]).head(6)
        lagging_label = ", ".join(
            f"{row['Spieler']} ({pd.Timestamp(row['Date']).date().isoformat()})" for _, row in lagging.iterrows()
        )
        st.caption(f"XP input dates differ across selected players. Lines stop at real input dates: {lagging_label}")

    # Recalculate trend projection defaults whenever the date range/player scope changes.
    trend_scope_sig = "|".join(
        [
            pd.Timestamp(d_start).date().isoformat(),
            pd.Timestamp(d_end).date().isoformat(),
            "max-data",
            ",".join(sorted([str(p).strip() for p in selected_players if str(p).strip()])),
        ]
    )
    trend_scope_key = f"{key_prefix}_trend_scope_sig"
    prior_scope_sig = str(st.session_state.get(trend_scope_key, ""))
    if trend_scope_sig != prior_scope_sig:
        for k in [f"{key_prefix}_total_xp_visibility_years", f"{key_prefix}_total_xp_visibility_months"]:
            if k in st.session_state:
                del st.session_state[k]
        st.session_state[trend_scope_key] = trend_scope_sig

    # Trendline source uses selected date range before common-interval clipping.
    # Projection fits are built once per player so switching leaders does not change another player's pace line.
    trend_source_df = df_range.copy()
    trend_source_df["Date"] = pd.to_datetime(trend_source_df["Date"], errors="coerce")
    trend_source_df["Total XP"] = pd.to_numeric(trend_source_df["Total XP"], errors="coerce")
    trend_source_df["Spieler"] = trend_source_df["Spieler"].astype(str).str.strip()
    trend_source_df = trend_source_df.dropna(subset=["Date", "Spieler", "Total XP"]).copy()
    trend_projection_series = build_xp_projection_series_map(trend_source_df)

    gain_df = build_xp_gain_over_time_df(df)
    pace_df = build_pace_df(df)
    rank_df = build_rank_df(df)

    # Top row: XP gain over time | interval pace
    top_left, top_right = st.columns(2)
    with top_left:
        fig_gain = px.line(
            gain_df,
            x="Date",
            y="XP Gain",
            color="Spieler",
            color_discrete_map=account_color_map,
            markers=True,
            title="XP Gain Over Time",
        )
        render_plotly_chart(fig_gain, use_container_width=True)
    with top_right:
        if pace_df.empty:
            st.info("Interval Pace (XP/day): not enough intervals yet.")
        else:
            fig_pace = px.line(
                pace_df,
                x="Date",
                y="XP/day",
                color="Spieler",
                color_discrete_map=account_color_map,
                markers=True,
                title="Interval Pace (XP/day)",
            )
            render_plotly_chart(fig_pace, use_container_width=True)

    leader_rank_df = df[["Spieler", "Date", "Total XP"]].copy()
    leader_rank_df["Date"] = pd.to_datetime(leader_rank_df["Date"], errors="coerce")
    leader_rank_df["Total XP"] = pd.to_numeric(leader_rank_df["Total XP"], errors="coerce")
    leader_rank_df["Spieler"] = leader_rank_df["Spieler"].astype(str).str.strip()
    leader_rank_df = leader_rank_df.dropna(subset=["Spieler", "Date", "Total XP"]).copy()
    leader_rank_df = leader_rank_df.sort_values(["Spieler", "Date"])
    leader_rank_df = leader_rank_df.groupby("Spieler", as_index=False).tail(1)
    leader_rank_df = leader_rank_df.sort_values(["Total XP", "Spieler"], ascending=[False, True])
    leader_options = leader_rank_df["Spieler"].tolist()
    if not leader_options:
        st.warning("No valid leader available for selected rows.")
        return
    inferred_default_leader = infer_default_gap_leader(df)
    saved_leader = load_saved_dashboard_gap_leader(leader_preference_key, leader_options) if leader_preference_key else None
    default_leader = saved_leader or inferred_default_leader
    default_idx = leader_options.index(default_leader) if default_leader in leader_options else 0
    leader_key = f"{key_prefix}_gap_leader"
    leader_scope_key = f"{key_prefix}_gap_leader_scope_sig"
    catchup_key = f"{key_prefix}_show_catchup_trends"
    prior_leader_scope_sig = str(st.session_state.get(leader_scope_key, ""))
    current_session_leader = str(st.session_state.get(leader_key, "")).strip()
    if prior_leader_scope_sig != trend_scope_sig:
        st.session_state[leader_scope_key] = trend_scope_sig
        if leader_key in st.session_state:
            del st.session_state[leader_key]
        current_session_leader = ""
    elif current_session_leader and current_session_leader not in leader_options:
        del st.session_state[leader_key]
        current_session_leader = ""
    if catchup_key not in st.session_state:
        st.session_state[catchup_key] = True
    selected_leader = current_session_leader if current_session_leader in leader_options else leader_options[default_idx]

    gap_df = build_gap_change_df(df, leader=selected_leader)

    # Middle row: gap change | rank over time
    mid_left, mid_right = st.columns(2)
    with mid_left:
        if gap_df.empty:
            st.info(f"Gap Change: not possible for selected leader {selected_leader} in this window.")
        else:
            fig_gap = px.line(
                gap_df,
                x="Date",
                y="Gap Change",
                color="Spieler",
                color_discrete_map=account_color_map,
                markers=True,
                title="Gap Change Since First Snapshot",
            )
            fig_gap.add_hline(
                y=0,
                line_dash="dash",
                annotation_text=gap_baseline_annotation_text(gap_df, leader=selected_leader),
                annotation_position="bottom right",
            )
            render_plotly_chart(fig_gap, use_container_width=True)
    with mid_right:
        fig_rank = go.Figure()
        for player, grp in rank_df.groupby("Spieler", sort=True):
            fig_rank.add_trace(
                go.Scatter(
                    x=grp["Date"],
                    y=grp["Rank"],
                    mode="lines+markers",
                    line_shape="hv",
                    name=player,
                    line=dict(color=account_color_map.get(str(player))),
                    marker=dict(color=account_color_map.get(str(player))),
                )
            )
        fig_rank.update_layout(title="Rank Over Time (Step)", legend_title="Player")
        fig_rank.update_yaxes(autorange="reversed", dtick=1)
        no_rank_changes = all(grp["Rank"].nunique() <= 1 for _, grp in rank_df.groupby("Spieler"))
        if no_rank_changes:
            fig_rank.add_annotation(
                text="No rank changes in this time window",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.95,
                showarrow=False,
            )
        render_plotly_chart(fig_rank, use_container_width=True)

    controls_left, controls_right = st.columns([1.35, 1.0])
    with controls_left:
        leader_select_kwargs: dict[str, object] = {
            "label": "Gap/Trend Leader",
            "options": leader_options,
            "key": leader_key,
        }
        if leader_key not in st.session_state:
            leader_select_kwargs["index"] = leader_options.index(selected_leader) if selected_leader in leader_options else default_idx
        selected_leader = st.selectbox(**leader_select_kwargs)
        if leader_preference_key:
            save_dashboard_gap_leader(leader_preference_key, selected_leader)
    with controls_right:
        show_catchup_trends = st.checkbox(
            "Show catch-up trendlines",
            key=catchup_key,
        )

    # Bottom row: total XP full width
    fig_total = px.line(
        df,
        x="Date",
        y="Total XP",
        color="Spieler",
        color_discrete_map=account_color_map,
        markers=True,
        title="Total XP Over Time",
    )
    trend_failures: list[str] = []
    latest_total_date = pd.to_datetime(df["Date"].max(), errors="coerce")
    if pd.isna(latest_total_date):
        latest_total_date = pd.Timestamp(d_end)
    auto_trend_end = pd.Timestamp(latest_total_date) + pd.DateOffset(years=1)
    if show_catchup_trends:
        apply_account_colors(fig_total, account_color_map)
        color_by_player: dict[str, str | None] = {str(acc): account_color_map.get(str(acc)) for acc in selected_players}

        leader_series_all = trend_projection_series.get(str(selected_leader), pd.DataFrame(columns=["Date", "Total XP"]))
        longest_trend_end: pd.Timestamp | None = None
        fallback_players: list[tuple[str, pd.DataFrame, str | None]] = []
        for player_name in sorted(trend_source_df["Spieler"].astype(str).unique().tolist()):
            if player_name == str(selected_leader):
                continue
            player_fit_series = trend_projection_series.get(player_name, pd.DataFrame(columns=["Date", "Total XP"]))
            trend_trace, trend_reason = build_xp_catchup_projection_trace(
                player_fit_series,
                leader_series_all,
                player_name,
                str(selected_leader),
                color_by_player.get(player_name),
            )
            if trend_trace is not None:
                fig_total.add_trace(trend_trace)
                catch_x = pd.to_datetime(trend_trace.x[-1], errors="coerce")
                catch_y = pd.to_numeric(pd.Series([trend_trace.y[-1]]), errors="coerce").iloc[0]
                if pd.notna(catch_x) and pd.notna(catch_y):
                    marker_color = getattr(getattr(trend_trace, "line", None), "color", None) or color_by_player.get(
                        player_name
                    )
                    fig_total.add_trace(
                        go.Scatter(
                            x=[pd.Timestamp(catch_x)],
                            y=[float(catch_y)],
                            mode="markers",
                            name=f"{player_name} catch point",
                            marker={
                                "symbol": "circle-open",
                                "size": 12,
                                "color": marker_color,
                                "line": {"width": 2},
                            },
                            showlegend=False,
                            hovertemplate=f"{player_name} catch point<extra></extra>",
                        )
                    )
                trend_end = pd.to_datetime(trend_trace.x[-1], errors="coerce")
                if pd.notna(trend_end):
                    trend_end_ts = pd.Timestamp(trend_end)
                    if longest_trend_end is None or trend_end_ts > longest_trend_end:
                        longest_trend_end = trend_end_ts
            else:
                fallback_players.append((player_name, player_fit_series.copy(), trend_reason))

        auto_trend_end = longest_trend_end if longest_trend_end is not None else auto_trend_end
        for player_name, player_series, catchup_reason in fallback_players:
            fallback_trace, fallback_reason = build_player_trend_projection_trace(
                player_series,
                player_name,
                color_by_player.get(player_name),
                end_date=auto_trend_end,
            )
            if fallback_trace is not None:
                fig_total.add_trace(fallback_trace)
            else:
                reason = fallback_reason or catchup_reason or "not possible (trendline unavailable)"
                trend_failures.append(f"{player_name}: {reason}")

        leader_trend_trace, leader_trend_reason = build_selected_leader_trend_trace(
            leader_series_all,
            str(selected_leader),
            color_by_player.get(str(selected_leader)),
            horizon_days=365,
            end_date=auto_trend_end,
        )
        if leader_trend_trace is not None:
            fig_total.add_trace(leader_trend_trace)
        elif leader_trend_reason:
            trend_failures.append(f"{selected_leader}: {leader_trend_reason}")

    if show_catchup_trends:
        max_visibility_years = 15
        default_years, default_months = split_visibility_offset_years_months(pd.Timestamp(latest_total_date), auto_trend_end)
        if default_years > max_visibility_years:
            default_years = max_visibility_years
            default_months = 11
        vis_col_year, vis_col_month = st.columns(2)
        with vis_col_year:
            visibility_years = st.slider(
                "Total XP visibility (years)",
                min_value=0,
                max_value=max_visibility_years,
                value=int(default_years),
                key=f"{key_prefix}_total_xp_visibility_years",
            )
        with vis_col_month:
            visibility_months = st.slider(
                "Total XP visibility (months)",
                min_value=0,
                max_value=11,
                value=int(default_months),
                key=f"{key_prefix}_total_xp_visibility_months",
            )
        visibility_end = pd.Timestamp(latest_total_date) + pd.DateOffset(
            years=int(visibility_years),
            months=int(visibility_months),
        )
        if visibility_end <= pd.Timestamp(latest_total_date):
            visibility_end = pd.Timestamp(latest_total_date) + pd.DateOffset(months=1)
    else:
        visibility_end = pd.Timestamp(latest_total_date)

    visible_start = pd.to_datetime(df["Date"].min(), errors="coerce")
    if pd.isna(visible_start):
        visible_start = pd.Timestamp(d_start)
    fig_total.update_xaxes(range=[pd.Timestamp(visible_start), pd.Timestamp(visibility_end)])
    y_range = autoscale_y_for_visible_x(
        fig_total,
        pd.Timestamp(visible_start),
        pd.Timestamp(visibility_end),
        y_floor=0.0,
        padding_ratio=0.06,
    )
    if y_range is not None:
        fig_total.update_yaxes(range=[float(y_range[0]), float(y_range[1])], tickformat=",.0f")
    else:
        fig_total.update_yaxes(tickformat=",.0f")
    apply_total_xp_legend_order(fig_total, df)
    apply_account_colors(fig_total, account_color_map)

    render_plotly_chart(fig_total, use_container_width=True, sort_legend=False)
    if show_catchup_trends and trend_failures:
        st.caption("Catch-up trendline status: " + " | ".join(trend_failures))
    if show_catchup_trends and len(selected_players) > 1:
        st.caption(
            "Trendline fit window: each player uses their own data since "
            f"max(player start, {TREND_MIN_DATE_LABEL}), independent from the selected leader."
        )

    if not show_personal_activity:
        if show_global_activity_trends:
            activity_accounts = [str(a).strip() for a in selected_players if str(a).strip()]
            medal_source = medal_subset_df.copy() if medal_subset_df is not None else pd.DataFrame()
            additional_source = additional_subset_df.copy() if additional_subset_df is not None else pd.DataFrame()

            def _medal_series(medal_id: str, accounts: list[str]) -> pd.DataFrame:
                cols = ["date", "account", "value"]
                if medal_source.empty or not accounts:
                    return pd.DataFrame(columns=cols)
                d = medal_source.copy()
                d["date"] = pd.to_datetime(d["date"], errors="coerce")
                d["account"] = d["account"].astype(str).str.strip()
                d["medal_id"] = d["medal_id"].astype(str).str.strip().str.lower().map(goal_medal_id_for)
                d["value"] = pd.to_numeric(d["value"], errors="coerce")
                d = d.dropna(subset=["date", "account", "medal_id", "value"]).copy()
                d = d[d["account"].isin(set(accounts))].copy()
                d = d[d["medal_id"] == goal_medal_id_for(medal_id)].copy()
                if d.empty:
                    return pd.DataFrame(columns=cols)
                d = d.sort_values("date").groupby(["account", "date"], as_index=False).agg({"value": "max"})
                return d[cols].sort_values(["account", "date"]).reset_index(drop=True)

            def _series_to_metric_df(series_df: pd.DataFrame) -> pd.DataFrame:
                if series_df.empty:
                    return pd.DataFrame(columns=["Date", "Spieler", "Total XP"])
                out = series_df.copy()
                out = out.rename(columns={"date": "Date", "account": "Spieler", "value": "Total XP"})
                out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
                out["Spieler"] = out["Spieler"].astype(str).str.strip()
                out["Total XP"] = pd.to_numeric(out["Total XP"], errors="coerce")
                out = out.dropna(subset=["Date", "Spieler", "Total XP"]).copy()
                out = out.sort_values(["Spieler", "Date"]).reset_index(drop=True)
                return out[["Date", "Spieler", "Total XP"]]

            battles_series = pd.DataFrame(columns=["date", "account", "value"])
            if not additional_source.empty and activity_accounts:
                d = additional_source.copy()
                d["date"] = pd.to_datetime(d["date"], errors="coerce")
                d["account"] = d["account"].astype(str).str.strip()
                d["battles_won"] = pd.to_numeric(d["battles_won"], errors="coerce")
                d = d.dropna(subset=["date", "account", "battles_won"]).copy()
                d = d[d["account"].isin(set(activity_accounts))].copy()
                if not d.empty:
                    d = d.sort_values("date").drop_duplicates(["account", "date"], keep="last")
                    battles_series = d.rename(columns={"battles_won": "value"})[["date", "account", "value"]]
                    battles_series = battles_series.sort_values(["account", "date"]).reset_index(drop=True)

            caught_series = _medal_series("collector", activity_accounts)
            km_series = _medal_series("jogger", activity_accounts)
            window_days = int(activity_window_days) if int(activity_window_days) in {7, 30} else 7
            w_label = f"{window_days}d"
            eligible_col = window_col("eligible", window_days)
            eligible_baseline_col = window_col("eligible_baseline", window_days)
            window_end_col = window_col("window_end", window_days)
            xp_gain_col = window_col("xp_gain", window_days)
            xp_per_day_col = window_col("xp_per_day", window_days)
            delta_col = window_col("delta_vs_baseline", window_days)

            def _window_rate_kpi(series_df: pd.DataFrame, unit_suffix: str, metric_label: str) -> tuple[str, str | None, str]:
                metric_df = _series_to_metric_df(series_df)
                if metric_df.empty:
                    return "-", None, f"no {w_label} data"
                kpis = compute_player_kpis_window(
                    metric_df,
                    window_days=window_days,
                    baseline_min_windows=BASELINE_MIN_WINDOWS_DEFAULT,
                )
                if kpis.empty or eligible_col not in kpis.columns:
                    return "-", None, f"no {w_label} data"
                eligible_pool = kpis[kpis[eligible_col] == True].copy()  # noqa: E712
                if eligible_pool.empty:
                    return "-", None, f"no eligible {w_label} windows"
                eligible_pool[xp_per_day_col] = pd.to_numeric(eligible_pool[xp_per_day_col], errors="coerce")
                eligible_pool[xp_gain_col] = pd.to_numeric(eligible_pool[xp_gain_col], errors="coerce")
                eligible_pool = eligible_pool.dropna(subset=[xp_per_day_col, xp_gain_col]).copy()
                if eligible_pool.empty:
                    return "-", None, f"no eligible {w_label} windows"
                active_pool = eligible_pool[eligible_pool[xp_gain_col] > 0].copy()
                headline_pool = active_pool if not active_pool.empty else eligible_pool
                leader = headline_pool.sort_values([xp_per_day_col, xp_gain_col], ascending=[False, False]).iloc[0]
                avg_val = float(eligible_pool[xp_per_day_col].mean())
                end_date = pd.to_datetime(eligible_pool[window_end_col], errors="coerce").max()
                date_txt = end_date.strftime("%Y-%m-%d") if pd.notna(end_date) else "-"
                noun = str(metric_label).strip().lower()
                unit_part = f" {str(unit_suffix).strip()}" if str(unit_suffix).strip() else ""
                value_txt = (
                    f"{float(leader[xp_per_day_col]):,.2f} {noun}/day"
                    if noun and unit_suffix == ""
                    else f"{float(leader[xp_per_day_col]):,.2f}{unit_part}/day"
                )
                winner_txt = str(leader["Spieler"])
                avg_txt = (
                    f"Team avg {avg_val:,.2f} {noun}/day | {w_label} window end: {date_txt} "
                    if noun and unit_suffix == ""
                    else f"Team avg {avg_val:,.2f}{unit_part}/day | {w_label} window end: {date_txt} "
                )
                context_txt = (
                    avg_txt + f"({int(len(eligible_pool))} account(s))"
                )
                if active_pool.empty:
                    context_txt += f" | no active {w_label} gains"
                return value_txt, winner_txt, context_txt

            st.caption(f"Activity Snapshot ({w_label})")
            render_account_color_legend(activity_accounts, account_color_map)
            with st.container(key="pogo_activity_snapshot_metrics"):
                a1, a2, a3 = st.columns(3)
                b_value, b_winner, b_context = _window_rate_kpi(battles_series, "", "Battles")
                c_value, c_winner, c_context = _window_rate_kpi(caught_series, "", "Pokemon")
                k_value, k_winner, k_context = _window_rate_kpi(km_series, "km", "Km")
                render_kpi_card(
                    a1,
                    "Battles/day",
                    b_value,
                    winner=b_winner,
                    winner_color=account_color_map.get(str(b_winner).strip()) if b_winner else None,
                    context=b_context,
                    help_text="Latest battles/day from Battles Won cumulative snapshots (additional activity data).",
                )
                render_kpi_card(
                    a2,
                    "Pokemon/day",
                    c_value,
                    winner=c_winner,
                    winner_color=account_color_map.get(str(c_winner).strip()) if c_winner else None,
                    context=c_context,
                    help_text="Latest caught/day from Collector medal deltas.",
                )
                render_kpi_card(
                    a3,
                    "Km/day",
                    k_value,
                    winner=k_winner,
                    winner_color=account_color_map.get(str(k_winner).strip()) if k_winner else None,
                    context=k_context,
                    help_text="Latest km/day from Jogger medal deltas.",
                )

            def _fmt_total(value: object, unit: str, metric_label: str = "") -> str:
                num = pd.to_numeric(value, errors="coerce")
                if pd.isna(num):
                    return "-"
                v = float(num)
                noun = str(metric_label).strip().lower()
                return f"{v:,.1f} km" if unit == "km" else f"{int(round(v)):,} {noun}"

            def _fmt_rate(value: object, unit: str, metric_label: str = "") -> str:
                num = pd.to_numeric(value, errors="coerce")
                if pd.isna(num):
                    return "-"
                v = float(num)
                noun = str(metric_label).strip().lower()
                return f"{v:,.2f} km/day" if unit == "km" else f"{v:,.2f} {noun}/day"

            def _fmt_gain(value: object, unit: str, metric_label: str = "") -> str:
                num = pd.to_numeric(value, errors="coerce")
                if pd.isna(num):
                    return "-"
                v = float(num)
                noun = str(metric_label).strip().lower()
                return f"{v:,.2f} km in {w_label}" if unit == "km" else f"{int(round(v)):,} {noun} in {w_label}"

            def _fmt_delta_rate(value: object, unit: str, metric_label: str = "") -> str:
                num = pd.to_numeric(value, errors="coerce")
                if pd.isna(num):
                    return "-"
                n = float(num)
                sign = "+" if n >= 0 else "-"
                abs_n = abs(n)
                if unit == "km":
                    return f"{sign}{abs_n:,.2f} km/day vs baseline"
                noun = str(metric_label).strip().lower()
                return f"{sign}{abs_n:,.2f} {noun}/day vs baseline"

            def _render_activity_kpi_row(series_df: pd.DataFrame, title: str, unit: str, metric_label: str = "") -> None:
                row_slug = re.sub(r"[^a-z0-9]+", "_", str(title).strip().lower()).strip("_") or "activity"
                with st.container(key=f"pogo_activity_perf_{row_slug}_{w_label}"):
                    st.markdown(f"**{title} ({w_label})**")
                    c1, c2, c3, c4, c5, c6 = st.columns(6)
                    metric_df = _series_to_metric_df(series_df)
                    if metric_df.empty:
                        render_kpi_card(c1, "Leader", "-", context="no data")
                        render_kpi_card(c2, f"Top Gain ({w_label})", "-", context="no data")
                        render_kpi_card(c3, f"Least Gain ({w_label})", "-", context="no data")
                        render_kpi_card(c4, f"Fastest {w_label} Pace", "-", context="no data")
                        render_kpi_card(c5, f"Most Improved ({w_label})", "-", context="no baseline data")
                        render_kpi_card(c6, f"Most Declined ({w_label})", "-", context="no baseline data")
                        return

                    latest_metric = series_df.sort_values("date").groupby("account", as_index=False).tail(1).copy()
                    latest_metric["value"] = pd.to_numeric(latest_metric["value"], errors="coerce")
                    latest_metric = latest_metric.dropna(subset=["value"])
                    if not latest_metric.empty:
                        leader_row = latest_metric.sort_values("value", ascending=False).iloc[0]
                        leader_date = pd.to_datetime(leader_row["date"], errors="coerce")
                        leader_date_txt = leader_date.strftime("%Y-%m-%d") if pd.notna(leader_date) else "-"
                        render_kpi_card(
                            c1,
                            "Leader",
                            _fmt_total(leader_row["value"], unit, metric_label),
                            winner=str(leader_row["account"]),
                            winner_color=account_color_map.get(str(leader_row["account"]).strip()),
                            context=f"as of {leader_date_txt}",
                        )
                    else:
                        render_kpi_card(c1, "Leader", "-", context="no data")

                    activity_kpis = compute_player_kpis_window(
                        metric_df,
                        window_days=window_days,
                        baseline_min_windows=BASELINE_MIN_WINDOWS_DEFAULT,
                    )
                    eligible_pool = (
                        activity_kpis[activity_kpis[eligible_col] == True].copy()  # noqa: E712
                        if not activity_kpis.empty and eligible_col in activity_kpis.columns
                        else pd.DataFrame()
                    )
                    active_pool = (
                        eligible_pool[pd.to_numeric(eligible_pool[xp_gain_col], errors="coerce") > 0].copy()
                        if not eligible_pool.empty
                        else pd.DataFrame()
                    )
                    baseline_pool = (
                        activity_kpis[activity_kpis[eligible_baseline_col] == True].copy()  # noqa: E712
                        if not activity_kpis.empty and eligible_baseline_col in activity_kpis.columns
                        else pd.DataFrame()
                    )

                    if not active_pool.empty:
                        best = active_pool.sort_values([xp_per_day_col, xp_gain_col], ascending=[False, False]).iloc[0]
                        top_gain = active_pool.sort_values([xp_gain_col, xp_per_day_col], ascending=[False, False]).iloc[0]
                        least_gain = active_pool.sort_values([xp_gain_col, xp_per_day_col], ascending=[True, True]).iloc[0]
                        render_kpi_card(
                            c2,
                            f"Top Gain ({w_label})",
                            _fmt_gain(top_gain[xp_gain_col], unit, metric_label),
                            winner=str(top_gain["Spieler"]),
                            winner_color=account_color_map.get(str(top_gain["Spieler"]).strip()),
                            context=_fmt_rate(top_gain[xp_per_day_col], unit, metric_label),
                        )
                        render_kpi_card(
                            c3,
                            f"Least Gain ({w_label})",
                            _fmt_gain(least_gain[xp_gain_col], unit, metric_label),
                            winner=str(least_gain["Spieler"]),
                            winner_color=account_color_map.get(str(least_gain["Spieler"]).strip()),
                            context=_fmt_rate(least_gain[xp_per_day_col], unit, metric_label),
                        )
                        render_kpi_card(
                            c4,
                            f"Fastest {w_label} Pace",
                            _fmt_rate(best[xp_per_day_col], unit, metric_label),
                            winner=str(best["Spieler"]),
                            winner_color=account_color_map.get(str(best["Spieler"]).strip()),
                            context=_fmt_gain(best[xp_gain_col], unit, metric_label),
                        )
                    elif not eligible_pool.empty:
                        no_active_ctx = f"all {xp_gain_col} = 0"
                        render_kpi_card(c2, f"Top Gain ({w_label})", f"No active ({w_label})", context=no_active_ctx, delta_color="off")
                        render_kpi_card(c3, f"Least Gain ({w_label})", f"No active ({w_label})", context=no_active_ctx, delta_color="off")
                        render_kpi_card(c4, f"Fastest {w_label} Pace", f"No active ({w_label})", context=no_active_ctx, delta_color="off")
                    else:
                        render_kpi_card(c2, f"Top Gain ({w_label})", "-", context="no data")
                        render_kpi_card(c3, f"Least Gain ({w_label})", "-", context="no data")
                        render_kpi_card(c4, f"Fastest {w_label} Pace", "-", context="no data")

                    if not baseline_pool.empty:
                        improved_pool = baseline_pool[pd.to_numeric(baseline_pool[delta_col], errors="coerce") > 0].copy()
                        declined_pool = baseline_pool[pd.to_numeric(baseline_pool[delta_col], errors="coerce") < 0].copy()
                        if not improved_pool.empty:
                            improved = improved_pool.sort_values(delta_col, ascending=False).iloc[0]
                            render_kpi_card(
                                c5,
                                f"Most Improved ({w_label})",
                                _fmt_rate(improved[xp_per_day_col], unit, metric_label),
                                winner=str(improved["Spieler"]),
                                winner_color=account_color_map.get(str(improved["Spieler"]).strip()),
                                delta=_fmt_delta_rate(improved[delta_col], unit, metric_label),
                            )
                        else:
                            render_kpi_card(c5, f"Most Improved ({w_label})", "No improvements", context="all deltas <= 0", delta_color="off")

                        if not declined_pool.empty:
                            declined = declined_pool.sort_values(delta_col, ascending=True).iloc[0]
                            render_kpi_card(
                                c6,
                                f"Most Declined ({w_label})",
                                _fmt_rate(declined[xp_per_day_col], unit, metric_label),
                                winner=str(declined["Spieler"]),
                                winner_color=account_color_map.get(str(declined["Spieler"]).strip()),
                                delta=_fmt_delta_rate(declined[delta_col], unit, metric_label),
                            )
                        else:
                            render_kpi_card(c6, f"Most Declined ({w_label})", "No decline", context="all deltas >= 0", delta_color="off")
                    else:
                        render_kpi_card(c5, f"Most Improved ({w_label})", "-", context="no baseline data")
                        render_kpi_card(c6, f"Most Declined ({w_label})", "-", context="no baseline data")

            st.caption(f"Activity Performance ({w_label})")
            _render_activity_kpi_row(battles_series, "Battles", "", "Battles")
            _render_activity_kpi_row(caught_series, "Pokemon", "", "Pokemon")
            _render_activity_kpi_row(km_series, "Distance Walked", "km", "Km")

            def _clip_series_to_selected_range(series_df: pd.DataFrame) -> pd.DataFrame:
                if series_df.empty:
                    return series_df.copy()
                d = series_df.copy()
                d["date"] = pd.to_datetime(d["date"], errors="coerce")
                d = d.dropna(subset=["date"]).copy()
                visible_start = pd.to_datetime(df["Date"].min(), errors="coerce")
                visible_end = pd.to_datetime(df["Date"].max(), errors="coerce")
                if pd.isna(visible_start):
                    visible_start = pd.Timestamp(d_start)
                if pd.isna(visible_end):
                    visible_end = pd.Timestamp(d_end)
                d = d[d["date"] <= pd.Timestamp(visible_end)].copy()
                activity_start = _activity_mode_start_date(d, pd.Timestamp(visible_start), pd.Timestamp(visible_end))
                activity_dates = _activity_chart_dates(
                    d,
                    pd.Timestamp(visible_start),
                    pd.Timestamp(visible_end),
                    chart_dates,
                    start_date=activity_start,
                )
                return _carry_forward_chart_rows(d, activity_dates, ["value"])

            def _build_activity_gain_series(series_df: pd.DataFrame) -> pd.DataFrame:
                visible_start = pd.to_datetime(df["Date"].min(), errors="coerce")
                visible_end = pd.to_datetime(df["Date"].max(), errors="coerce")
                if pd.isna(visible_start):
                    visible_start = pd.Timestamp(d_start)
                if pd.isna(visible_end):
                    visible_end = pd.Timestamp(d_end)
                base = series_df.copy()
                base["date"] = pd.to_datetime(base["date"], errors="coerce")
                base = base.dropna(subset=["date"]).copy()
                if base.empty:
                    return base
                base = base[base["date"] <= pd.Timestamp(visible_end)].copy()
                if base.empty:
                    return base
                activity_start = _activity_mode_start_date(base, pd.Timestamp(visible_start), pd.Timestamp(visible_end))
                activity_dates = _activity_chart_dates(
                    base,
                    pd.Timestamp(visible_start),
                    pd.Timestamp(visible_end),
                    chart_dates,
                    start_date=activity_start,
                )
                if not activity_dates:
                    return base.iloc[0:0].copy()
                accounts_with_anchor_baseline = set(
                    base[base["date"] <= activity_start]["account"].astype(str).str.strip().tolist()
                )
                gained = build_cumulative_gain_df(
                    base,
                    date_col="date",
                    group_col="account",
                    value_col="value",
                    gain_col="gain_value",
                    anchor_date=activity_start,
                    include_anchor_row=True,
                )
                gained = gained[gained["date"] >= activity_start].copy()
                synthetic_anchor_mask = (
                    (gained["date"] == activity_start)
                    & ~gained["account"].astype(str).str.strip().isin(accounts_with_anchor_baseline)
                )
                gained = gained[~synthetic_anchor_mask].copy()
                return _carry_forward_chart_rows(gained, activity_dates, ["value", "gain_value"])

            battles_plot = _build_activity_gain_series(battles_series)
            caught_plot = _build_activity_gain_series(caught_series)
            km_plot = _build_activity_gain_series(km_series)

            st.caption("Activity Trends (Since First Visible Snapshot)")
            g1, g2 = st.columns(2)
            with g1:
                if battles_plot.empty:
                    st.info("Battles Won trend: no data in selected range.")
                else:
                    fig_battles = px.line(
                        battles_plot,
                        x="date",
                        y="gain_value",
                        color="account",
                        color_discrete_map=account_color_map,
                        markers=True,
                        title="Battles Won Gained Over Time",
                    )
                    fig_battles.update_yaxes(title="battles won gained", tickformat=",.0f")
                    render_plotly_chart(fig_battles, use_container_width=True)
            with g2:
                if caught_plot.empty:
                    st.info("Pokemon Caught trend: no data in selected range.")
                else:
                    fig_caught = px.line(
                        caught_plot,
                        x="date",
                        y="gain_value",
                        color="account",
                        color_discrete_map=account_color_map,
                        markers=True,
                        title="Pokemon Caught Gained Over Time",
                    )
                    fig_caught.update_yaxes(title="pokemon caught gained", tickformat=",.0f")
                    render_plotly_chart(fig_caught, use_container_width=True)

            if km_plot.empty:
                st.info("Distance Walked trend: no data in selected range.")
            else:
                fig_km = px.line(
                    km_plot,
                    x="date",
                    y="gain_value",
                    color="account",
                    color_discrete_map=account_color_map,
                    markers=True,
                    title="Distance Walked Gained Over Time",
                )
                fig_km.update_yaxes(title="km gained", tickformat=",.1f")
                render_plotly_chart(fig_km, use_container_width=True)

            battles_total_plot = _clip_series_to_selected_range(battles_series)
            caught_total_plot = _clip_series_to_selected_range(caught_series)
            km_total_plot = _clip_series_to_selected_range(km_series)

            st.caption("Activity Trends (Totals)")
            t1, t2 = st.columns(2)
            with t1:
                if battles_total_plot.empty:
                    st.info("Battles Won total trend: no data in selected range.")
                else:
                    fig_battles_total = px.line(
                        battles_total_plot,
                        x="date",
                        y="value",
                        color="account",
                        color_discrete_map=account_color_map,
                        markers=True,
                        title="Battles Won Total Over Time",
                    )
                    fig_battles_total.update_yaxes(title="battles won", tickformat=",.0f")
                    render_plotly_chart(fig_battles_total, use_container_width=True)
            with t2:
                if caught_total_plot.empty:
                    st.info("Pokemon Caught total trend: no data in selected range.")
                else:
                    fig_caught_total = px.line(
                        caught_total_plot,
                        x="date",
                        y="value",
                        color="account",
                        color_discrete_map=account_color_map,
                        markers=True,
                        title="Pokemon Caught Total Over Time",
                    )
                    fig_caught_total.update_yaxes(title="pokemon caught", tickformat=",.0f")
                    render_plotly_chart(fig_caught_total, use_container_width=True)

            if km_total_plot.empty:
                st.info("Distance Walked total trend: no data in selected range.")
            else:
                fig_km_total = px.line(
                    km_total_plot,
                    x="date",
                    y="value",
                    color="account",
                    color_discrete_map=account_color_map,
                    markers=True,
                    title="Distance Walked Total Over Time",
                )
                fig_km_total.update_yaxes(title="km", tickformat=",.1f")
                render_plotly_chart(fig_km_total, use_container_width=True)
        return

    st.subheader("Personal Activity Intervals")
    medal_source = medal_subset_df.copy() if medal_subset_df is not None else pd.DataFrame()
    if medal_source.empty:
        st.info("No medal history available for personal activity stats.")
        return

    activity_accounts = [str(a).strip() for a in selected_players if str(a).strip()]
    if not activity_accounts:
        st.info("Select at least one account to compute personal activity stats.")
        return

    caught_df = build_medal_interval_rate_df(medal_source, activity_accounts, medal_ids=["collector"])
    raids_df = build_medal_interval_rate_df(medal_source, activity_accounts, medal_ids=["champion", "battle_legend"])
    stops_df = build_medal_interval_rate_df(medal_source, activity_accounts, medal_ids=["backpacker"])
    km_df = build_medal_interval_rate_df(medal_source, activity_accounts, medal_ids=["jogger"])
    intervals_df = build_medal_snapshot_interval_days_df(medal_source, activity_accounts)

    core_accounts = [a for a in ACCOUNT_ORDER if a in set(activity_accounts)]
    display_accounts = core_accounts if core_accounts else activity_accounts
    personal_activity_color_map = build_account_color_map(display_accounts or activity_accounts, xp_subset_df)

    def _latest_per_core_txt(df_rates: pd.DataFrame, value_col: str = "per_day", fmt: str = "{:,.2f}") -> str:
        if not display_accounts:
            return "-"
        latest_map: dict[str, float] = {}
        if not df_rates.empty:
            latest = df_rates.sort_values("period_end").groupby("account", as_index=False).tail(1)
            latest_map = {
                str(r["account"]): float(r[value_col])
                for _, r in latest.iterrows()
                if pd.notna(pd.to_numeric(r.get(value_col), errors="coerce"))
            }
        parts: list[str] = []
        for acc in display_accounts:
            if acc in latest_map:
                parts.append(f"{acc}: {fmt.format(latest_map[acc])}")
            else:
                parts.append(f"{acc}: -")
        return " | ".join(parts)

    def _avg_interval_txt(df_intervals: pd.DataFrame) -> str:
        if not display_accounts:
            return "-"
        per_acc: list[str] = []
        for acc in display_accounts:
            grp = df_intervals[df_intervals["account"].astype(str) == str(acc)] if not df_intervals.empty else pd.DataFrame()
            val = pd.to_numeric(grp.get("interval_days"), errors="coerce").mean() if not grp.empty else pd.NA
            if pd.isna(val):
                per_acc.append(f"{acc}: -")
            else:
                per_acc.append(f"{acc}: {float(val):.1f}d")
        return " | ".join(per_acc)

    render_account_color_legend(display_accounts or activity_accounts, personal_activity_color_map)
    with st.container(key="pogo_activity_personal_metrics"):
        k1, k2, k3, k4, k5 = st.columns(5)
        render_kpi_card(k1, "Pokemon Caught/day", _latest_per_core_txt(caught_df), help_text="Latest interval per core account from Collector medal deltas.")
        render_kpi_card(k2, "Raids/day", _latest_per_core_txt(raids_df), help_text="Latest interval per core account from Champion + Battle Legend deltas.")
        render_kpi_card(k3, "PokeStops/day", _latest_per_core_txt(stops_df), help_text="Latest interval per core account from Backpacker medal deltas.")
        render_kpi_card(k4, "Km/day", _latest_per_core_txt(km_df), help_text="Latest interval per core account from Jogger medal deltas.")
        render_kpi_card(k5, "Interval (avg days)", _avg_interval_txt(intervals_df), help_text="Average snapshot interval from medal history.")

    g1, g2 = st.columns(2)
    with g1:
        if caught_df.empty:
            st.info("Pokemon caught/day: not enough medal intervals yet.")
        else:
            fig_caught = px.line(
                caught_df,
                x="period_end",
                y="per_day",
                color="account",
                color_discrete_map=personal_activity_color_map,
                markers=True,
                title="Pokemon Caught per Day (Intervals)",
            )
            fig_caught.update_yaxes(title="caught/day")
            render_plotly_chart(fig_caught, use_container_width=True)
    with g2:
        if raids_df.empty:
            st.info("Raids/day: not enough medal intervals yet.")
        else:
            fig_raids = px.line(
                raids_df,
                x="period_end",
                y="per_day",
                color="account",
                color_discrete_map=personal_activity_color_map,
                markers=True,
                title="Raids per Day (Intervals)",
            )
            fig_raids.update_yaxes(title="raids/day")
            render_plotly_chart(fig_raids, use_container_width=True)

    g3, g4 = st.columns(2)
    with g3:
        if stops_df.empty:
            st.info("PokeStops/day: not enough medal intervals yet.")
        else:
            fig_stops = px.line(
                stops_df,
                x="period_end",
                y="per_day",
                color="account",
                color_discrete_map=personal_activity_color_map,
                markers=True,
                title="PokeStops Spun per Day (Intervals)",
            )
            fig_stops.update_yaxes(title="stops/day")
            render_plotly_chart(fig_stops, use_container_width=True)
    with g4:
        if km_df.empty:
            st.info("Km/day: not enough medal intervals yet.")
        else:
            fig_km = px.line(
                km_df,
                x="period_end",
                y="per_day",
                color="account",
                color_discrete_map=personal_activity_color_map,
                markers=True,
                title="KM per Day (Intervals)",
            )
            fig_km.update_yaxes(title="km/day")
            render_plotly_chart(fig_km, use_container_width=True)

    if intervals_df.empty:
        st.info("Intervals: not enough medal snapshots yet.")
    else:
        fig_intervals = px.bar(
            intervals_df,
            x="period_end",
            y="interval_days",
            color="account",
            color_discrete_map=personal_activity_color_map,
            title="Intervals (Days Between Medal Snapshots)",
            barmode="group",
        )
        fig_intervals.update_yaxes(title="days")
        render_plotly_chart(fig_intervals, use_container_width=True)


def append_xp_row(path: Path, row_date: date, account: str, level: int, xp_bar: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not path.exists() or path.stat().st_size == 0
    with open(path, "a", encoding="utf-8") as f:
        if needs_header:
            f.write("Date;Spieler;Lvl;XP Bar\n")
        f.write(f"{row_date.isoformat()};{account};{level};{xp_bar}\n")


def build_xp_activity_snapshot_rows(
    row_date: object,
    account: str,
    level: int,
    xp_bar: int,
    xp_locked: bool,
    battles_won: float,
    distance_walked: float,
    pokemon_caught: float,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    row_date_text = _input_inactive_date_key(row_date)
    account_name = str(account).strip()
    xp_rows: list[dict[str, object]] = []
    if not bool(xp_locked):
        xp_rows.append(
            {
                "Date": row_date_text,
                "Spieler": account_name,
                "Lvl": int(level),
                "XP Bar": int(xp_bar),
            }
        )
    additional_rows = [
        {
            "date": row_date_text,
            "account": account_name,
            "battles_won": float(battles_won),
        }
    ]
    medal_rows = [
        {
            "date": row_date_text,
            "account": account_name,
            "medal_id": XP_TAB_ACTIVITY_MEDAL_IDS["distance_walked"],
            "value": float(distance_walked),
        },
        {
            "date": row_date_text,
            "account": account_name,
            "medal_id": XP_TAB_ACTIVITY_MEDAL_IDS["pokemon_caught"],
            "value": float(pokemon_caught),
        },
    ]
    return xp_rows, additional_rows, medal_rows


def _validate_xp_rows_non_decreasing(
    existing_df: pd.DataFrame,
    new_df: pd.DataFrame,
    curve_map: dict[int, int],
) -> list[str]:
    errors: list[str] = []
    if new_df.empty:
        return errors

    existing = existing_df.copy()
    if not existing.empty:
        existing = existing.drop_duplicates(subset=["Date", "Spieler"], keep="last")
        existing["Lvl"] = pd.to_numeric(existing["Lvl"], errors="coerce")
        existing["XP Bar"] = pd.to_numeric(existing["XP Bar"], errors="coerce")
        existing = existing.dropna(subset=["Date", "Spieler", "Lvl", "XP Bar"]).copy()
        existing["Lvl"] = existing["Lvl"].astype(int)
        existing["XP Bar"] = existing["XP Bar"].astype(int)
        existing = existing[existing["Lvl"].isin(set(curve_map.keys()))].copy()
        existing["Total XP"] = existing.apply(
            lambda row: total_xp_from_level_input(int(row["Lvl"]), int(row["XP Bar"]), curve_map),
            axis=1,
        )
        existing = existing.dropna(subset=["Date", "Spieler", "Total XP"]).copy()

    rows = new_df.drop_duplicates(subset=["Date", "Spieler"], keep="last").copy()
    for _, row in rows.iterrows():
        player = str(row["Spieler"]).strip()
        dt = pd.to_datetime(row["Date"], errors="coerce")
        lvl = pd.to_numeric(row["Lvl"], errors="coerce")
        xp_bar = pd.to_numeric(row["XP Bar"], errors="coerce")
        if pd.isna(dt) or not player or pd.isna(lvl) or pd.isna(xp_bar):
            continue
        if int(lvl) not in curve_map:
            errors.append(f"{player} {pd.Timestamp(dt).date().isoformat()}: missing XP curve entry for level {int(lvl)}.")
            continue

        total_xp = total_xp_from_level_input(int(lvl), int(xp_bar), curve_map)
        if existing.empty:
            continue

        without_same_day = existing[~((existing["Spieler"] == player) & (existing["Date"] == dt))].copy()
        player_hist = without_same_day[without_same_day["Spieler"] == player].copy()
        if player_hist.empty:
            continue

        prev_rows = player_hist[player_hist["Date"] < dt].sort_values("Date")
        if not prev_rows.empty:
            prev = prev_rows.iloc[-1]
            prev_total = int(round(float(prev["Total XP"])))
            if total_xp < prev_total:
                prev_date = pd.to_datetime(prev["Date"], errors="coerce")
                prev_date_txt = prev_date.date().isoformat() if pd.notna(prev_date) else "-"
                errors.append(
                    f"{player} {pd.Timestamp(dt).date().isoformat()}: Total XP {total_xp:,} is below previous "
                    f"{prev_total:,} on {prev_date_txt}."
                )

        next_rows = player_hist[player_hist["Date"] > dt].sort_values("Date")
        if not next_rows.empty:
            nxt = next_rows.iloc[0]
            next_total = int(round(float(nxt["Total XP"])))
            if total_xp > next_total:
                next_date = pd.to_datetime(nxt["Date"], errors="coerce")
                next_date_txt = next_date.date().isoformat() if pd.notna(next_date) else "-"
                errors.append(
                    f"{player} {pd.Timestamp(dt).date().isoformat()}: Total XP {total_xp:,} is above next "
                    f"{next_total:,} on {next_date_txt}."
                )
    return errors


def _validate_medal_rows_non_decreasing(existing_df: pd.DataFrame, new_df: pd.DataFrame) -> list[str]:
    errors: list[str] = []
    if new_df.empty:
        return errors

    existing = existing_df.copy()
    if not existing.empty:
        existing = existing.drop_duplicates(subset=["date", "account", "medal_id"], keep="last")

    rows = new_df.drop_duplicates(subset=["date", "account", "medal_id"], keep="last").copy()
    for _, row in rows.iterrows():
        dt = pd.to_datetime(row["date"], errors="coerce")
        account = str(row["account"]).strip()
        medal_id = str(row["medal_id"]).strip().lower()
        value = pd.to_numeric(row["value"], errors="coerce")
        if pd.isna(dt) or not account or not medal_id or pd.isna(value):
            continue

        hist = existing[(existing["account"] == account) & (existing["medal_id"] == medal_id)].copy()
        if hist.empty:
            continue
        hist = hist[hist["date"] != dt].copy()

        prev_rows = hist[hist["date"] < dt].sort_values("date")
        if not prev_rows.empty:
            prev = prev_rows.iloc[-1]
            prev_value = float(prev["value"])
            if float(value) < prev_value:
                prev_date = pd.to_datetime(prev["date"], errors="coerce")
                prev_date_txt = prev_date.date().isoformat() if pd.notna(prev_date) else "-"
                errors.append(
                    f"{account} {medal_id} {pd.Timestamp(dt).date().isoformat()}: {float(value):g} is below previous "
                    f"{prev_value:g} on {prev_date_txt}."
                )

        next_rows = hist[hist["date"] > dt].sort_values("date")
        if not next_rows.empty:
            nxt = next_rows.iloc[0]
            next_value = float(nxt["value"])
            if float(value) > next_value:
                next_date = pd.to_datetime(nxt["date"], errors="coerce")
                next_date_txt = next_date.date().isoformat() if pd.notna(next_date) else "-"
                errors.append(
                    f"{account} {medal_id} {pd.Timestamp(dt).date().isoformat()}: {float(value):g} is above next "
                    f"{next_value:g} on {next_date_txt}."
                )
    return errors


def upsert_xp_rows(path: Path, rows: list[dict[str, object]]) -> int:
    if not rows:
        return 0

    new_df = pd.DataFrame(rows)
    new_df["Date"] = pd.to_datetime(new_df["Date"], errors="coerce")
    new_df["Spieler"] = new_df["Spieler"].astype(str).str.strip()
    new_df["Lvl"] = pd.to_numeric(new_df["Lvl"], errors="coerce")
    new_df["XP Bar"] = pd.to_numeric(new_df["XP Bar"], errors="coerce")
    new_df = new_df.dropna(subset=["Date", "Spieler", "Lvl", "XP Bar"]).copy()
    new_df["Lvl"] = new_df["Lvl"].astype(int)
    new_df["XP Bar"] = new_df["XP Bar"].astype(int)
    new_df = new_df.drop_duplicates(subset=["Date", "Spieler"], keep="last")
    if new_df.empty:
        return 0

    if path.exists():
        existing = pd.read_csv(path, sep=";", engine="python", encoding="utf-8-sig")
    else:
        existing = pd.DataFrame(columns=["Date", "Spieler", "Lvl", "XP Bar"])
    if not {"Date", "Spieler", "Lvl", "XP Bar"}.issubset(existing.columns):
        existing = pd.DataFrame(columns=["Date", "Spieler", "Lvl", "XP Bar"])
    else:
        existing = existing.copy()
        existing["Date"] = pd.to_datetime(existing["Date"], errors="coerce")
        existing["Spieler"] = existing["Spieler"].astype(str).str.strip()
        existing["Lvl"] = to_int_series(existing["Lvl"])
        existing["XP Bar"] = to_int_series(existing["XP Bar"])
        existing = existing.dropna(subset=["Date", "Spieler", "Lvl", "XP Bar"]).copy()
        existing["Lvl"] = existing["Lvl"].astype(int)
        existing["XP Bar"] = existing["XP Bar"].astype(int)

    curve_map = load_curve_map(total_xp_curve_path())
    monotonic_errors = _validate_xp_rows_non_decreasing(existing, new_df, curve_map)
    if monotonic_errors:
        details = "\n".join(monotonic_errors[:12])
        extra = f"\n... and {len(monotonic_errors) - 12} more issue(s)." if len(monotonic_errors) > 12 else ""
        raise ValueError("XP input rejected: values must be non-decreasing over time.\n" + details + extra)

    combined = pd.concat([existing, new_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["Date", "Spieler"], keep="last")
    combined = combined.sort_values(["Date", "Spieler"]).reset_index(drop=True)
    out = combined.copy()
    out["Date"] = out["Date"].dt.date.astype(str)
    path.parent.mkdir(parents=True, exist_ok=True)
    out[["Date", "Spieler", "Lvl", "XP Bar"]].to_csv(path, sep=";", index=False, encoding="utf-8-sig")
    return int(len(new_df))


def append_medal_rows(path: Path, rows: list[dict[str, object]]) -> int:
    if not rows:
        return 0

    existing = load_medal_snapshots(
        path,
        account_order=ACCOUNT_ORDER,
        excluded_manual_medal_ids=EXCLUDED_MANUAL_MEDAL_IDS,
    )
    new_df = pd.DataFrame(rows)
    new_df["date"] = pd.to_datetime(new_df["date"], errors="coerce")
    new_df["account"] = new_df["account"].astype(str).str.strip()
    new_df["medal_id"] = new_df["medal_id"].astype(str).str.strip().str.lower()
    new_df["value"] = pd.to_numeric(new_df["value"], errors="coerce")
    new_df = new_df.dropna(subset=["date", "account", "medal_id", "value"]).copy()
    new_df = new_df[~new_df["medal_id"].isin(EXCLUDED_MANUAL_MEDAL_IDS)].copy()
    new_df = new_df.drop_duplicates(subset=["date", "account", "medal_id"], keep="last")
    if new_df.empty:
        return 0

    monotonic_errors = _validate_medal_rows_non_decreasing(existing, new_df)

    if monotonic_errors:
        details = "\n".join(monotonic_errors[:12])
        extra = f"\n... and {len(monotonic_errors) - 12} more issue(s)." if len(monotonic_errors) > 12 else ""
        raise ValueError("Medal input rejected: values must be non-decreasing over time.\n" + details + extra)

    combined = pd.concat([existing, new_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["date", "account", "medal_id"], keep="last")
    order_map = {name: i for i, name in enumerate(ACCOUNT_ORDER)}
    combined["_acc_order"] = combined["account"].map(order_map).fillna(999)
    combined = combined.sort_values(["date", "_acc_order", "account", "medal_id"]).drop(columns=["_acc_order"])
    combined["date"] = combined["date"].dt.date.astype(str)
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(path, index=False, encoding="utf-8-sig")
    return int(len(new_df))


def with_medal_derived_pokedex_rows(pokedex_df: pd.DataFrame, source_medal_df: pd.DataFrame) -> pd.DataFrame:
    cols = ["date", "account", "entry_type", "region", "value"]
    base = pokedex_df[cols].copy() if not pokedex_df.empty else pd.DataFrame(columns=cols)
    if source_medal_df.empty:
        return with_derived_pokedex_overall_rows(base)

    derived = source_medal_df[["date", "account", "medal_id", "value"]].copy()
    derived["date"] = pd.to_datetime(derived["date"], errors="coerce")
    derived["account"] = derived["account"].astype(str).str.strip()
    derived["region"] = derived["medal_id"].astype(str).str.strip().str.lower()
    derived["value"] = pd.to_numeric(derived["value"], errors="coerce")
    derived = derived[derived["region"].isin(POKEDEX_MEDAL_REGION_IDS)].copy()
    derived = derived.dropna(subset=["date", "account", "region", "value"]).copy()
    if derived.empty:
        return base
    derived["entry_type"] = "pokemon"
    derived = derived[cols].copy()

    combined = derived.copy() if base.empty else pd.concat([base, derived], ignore_index=True)
    combined["_source_order"] = combined["entry_type"].eq("pokemon") & combined["region"].isin(POKEDEX_MEDAL_REGION_IDS)
    order_map = {name: i for i, name in enumerate(ACCOUNT_ORDER)}
    combined["_acc_order"] = combined["account"].map(order_map).fillna(999)
    combined = combined.sort_values(
        ["date", "_acc_order", "account", "entry_type", "region", "_source_order"]
    ).drop_duplicates(["date", "account", "entry_type", "region"], keep="last")
    combined = combined.drop(columns=["_source_order", "_acc_order"]).reset_index(drop=True)
    return with_derived_pokedex_overall_rows(combined)


def with_derived_pokedex_overall_rows(pokedex_df: pd.DataFrame) -> pd.DataFrame:
    cols = ["date", "account", "entry_type", "region", "value"]
    base = pokedex_df[cols].copy() if not pokedex_df.empty else pd.DataFrame(columns=cols)
    if base.empty:
        return base

    base["date"] = pd.to_datetime(base["date"], errors="coerce")
    base["account"] = base["account"].astype(str).str.strip()
    base["entry_type"] = base["entry_type"].astype(str).str.strip().str.lower()
    base["region"] = base["region"].astype(str).str.strip().str.lower()
    base["value"] = pd.to_numeric(base["value"], errors="coerce")
    base = base.dropna(subset=["date", "account", "entry_type", "region", "value"]).copy()
    regional = base[base["region"] != "overall"].copy()
    manual_without_overall = base[base["region"] != "overall"].copy()
    if regional.empty:
        return manual_without_overall.reset_index(drop=True)

    overall = (
        regional.groupby(["date", "account", "entry_type"], as_index=False)["value"]
        .sum()
        .assign(region="overall")
    )
    combined = pd.concat([manual_without_overall, overall[cols]], ignore_index=True)
    order_map = {name: i for i, name in enumerate(ACCOUNT_ORDER)}
    combined["_acc_order"] = combined["account"].map(order_map).fillna(999)
    combined["_type_order"] = combined["entry_type"].map({name: i for i, name in enumerate(POKEDEX_ENTRY_TYPES)}).fillna(999)
    combined["_region_order"] = combined["region"].map({name: i for i, name in enumerate(POKEDEX_REGIONS)}).fillna(999)
    combined = combined.sort_values(
        ["date", "_acc_order", "account", "_type_order", "_region_order", "entry_type", "region"]
    ).drop(columns=["_acc_order", "_type_order", "_region_order"])
    return combined.reset_index(drop=True)


def _is_medal_derived_pokedex_cell(entry_type: str, region: str) -> bool:
    return str(entry_type).strip().lower() == "pokemon" and str(region).strip().lower() in POKEDEX_MEDAL_REGION_IDS


def _is_overall_pokedex_cell(region: str) -> bool:
    return str(region).strip().lower() == "overall"


def _parse_float_loose_value(raw: object) -> float | None:
    s = str(raw).strip()
    if not s:
        return None
    s = s.replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s and "." not in s:
        if s.count(",") == 1:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        s = s.replace(",", "")
    val = pd.to_numeric(pd.Series([s]), errors="coerce").iloc[0]
    return None if pd.isna(val) else float(val)


def pokedex_entry_config_map(config_df: pd.DataFrame) -> dict[tuple[str, str], dict[str, object]]:
    if config_df.empty:
        return {}
    required = {"entry_type", "region", "max_value", "locked", "notes"}
    if not required.issubset(config_df.columns):
        return {}
    cfg = config_df.copy()
    cfg["entry_type"] = cfg["entry_type"].astype(str).str.strip().str.lower()
    cfg["region"] = cfg["region"].astype(str).str.strip().str.lower()
    cfg["max_value"] = pd.to_numeric(cfg["max_value"], errors="coerce")
    locked_text = cfg["locked"].fillna("").astype(str).str.strip().str.lower()
    cfg["locked"] = locked_text.isin({"1", "true", "yes", "y", "locked"})
    cfg["notes"] = cfg["notes"].fillna("").astype(str).str.strip()
    return {
        (str(row["entry_type"]), str(row["region"])): {
            "max_value": None if pd.isna(row["max_value"]) else float(row["max_value"]),
            "locked": bool(row["locked"]),
            "notes": str(row["notes"]),
        }
        for _, row in cfg.iterrows()
    }


def _pokedex_entry_config_errors(
    rows_df: pd.DataFrame,
    config: dict[tuple[str, str], dict[str, object]],
) -> list[str]:
    errors: list[str] = []
    if rows_df.empty or not config:
        return errors
    for _, row in rows_df.iterrows():
        entry_type = str(row.get("entry_type", "")).strip().lower()
        region = str(row.get("region", "")).strip().lower()
        value = pd.to_numeric(row.get("value"), errors="coerce")
        if pd.isna(value):
            continue
        cfg = config.get((entry_type, region), {})
        label = f"{POKEDEX_ENTRY_TYPE_LABELS.get(entry_type, entry_type)} {POKEDEX_REGION_LABELS.get(region, region)}"
        if bool(cfg.get("locked", False)):
            errors.append(f"{label} is locked in `inputs/config/pokedex_entry_config.csv`.")
            continue
        max_value = cfg.get("max_value")
        if max_value is not None and float(value) > float(max_value):
            errors.append(f"{label}: {float(value):g} is above configured max {float(max_value):g}.")
    return errors


def build_pokedex_category_snapshot_rows(
    row_date: object,
    account: str,
    entry_type: str,
    region_values: dict[str, object],
    entry_config: dict[tuple[str, str], dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    entry_type_key = str(entry_type).strip().lower()
    account_name = str(account).strip()
    row_date_text = _input_inactive_date_key(row_date)
    config = entry_config or {}
    rows: list[dict[str, object]] = []
    for raw_region, raw_value in region_values.items():
        region = str(raw_region).strip().lower()
        if (
            entry_type_key not in POKEDEX_ENTRY_TYPES
            or region not in POKEDEX_REGIONS
            or _is_medal_derived_pokedex_cell(entry_type_key, region)
            or _is_overall_pokedex_cell(region)
            or bool(config.get((entry_type_key, region), {}).get("locked", False))
        ):
            continue
        value = pd.to_numeric(raw_value, errors="coerce")
        if pd.isna(value):
            continue
        rows.append(
            {
                "date": row_date_text,
                "account": account_name,
                "entry_type": entry_type_key,
                "region": region,
                "value": float(value),
            }
        )
    return rows


def _validate_pokedex_entry_rows_non_decreasing(existing_df: pd.DataFrame, new_df: pd.DataFrame) -> list[str]:
    errors: list[str] = []
    if new_df.empty:
        return errors

    cols = ["date", "account", "entry_type", "region", "value"]
    existing = existing_df[cols].copy() if set(cols).issubset(existing_df.columns) else pd.DataFrame(columns=cols)
    if not existing.empty:
        existing["date"] = pd.to_datetime(existing["date"], errors="coerce")
        existing["account"] = existing["account"].astype(str).str.strip()
        existing["entry_type"] = existing["entry_type"].astype(str).str.strip().str.lower()
        existing["region"] = existing["region"].astype(str).str.strip().str.lower()
        existing["value"] = pd.to_numeric(existing["value"], errors="coerce")
        existing = existing.dropna(subset=["date", "account", "entry_type", "region", "value"]).copy()
        existing = existing.drop_duplicates(subset=["date", "account", "entry_type", "region"], keep="last")

    rows = new_df[cols].copy()
    rows["date"] = pd.to_datetime(rows["date"], errors="coerce")
    rows["account"] = rows["account"].astype(str).str.strip()
    rows["entry_type"] = rows["entry_type"].astype(str).str.strip().str.lower()
    rows["region"] = rows["region"].astype(str).str.strip().str.lower()
    rows["value"] = pd.to_numeric(rows["value"], errors="coerce")
    rows = rows.dropna(subset=["date", "account", "entry_type", "region", "value"]).copy()
    rows = rows.drop_duplicates(subset=["date", "account", "entry_type", "region"], keep="last")

    for _, row in rows.iterrows():
        dt = pd.to_datetime(row["date"], errors="coerce")
        account = str(row["account"]).strip()
        entry_type = str(row["entry_type"]).strip().lower()
        region = str(row["region"]).strip().lower()
        value = pd.to_numeric(row["value"], errors="coerce")
        if pd.isna(dt) or not account or not entry_type or not region or pd.isna(value):
            continue

        hist = existing[
            (existing["account"] == account)
            & (existing["entry_type"] == entry_type)
            & (existing["region"] == region)
        ].copy()
        if hist.empty:
            continue
        hist = hist[hist["date"] != dt].copy()

        label = f"{account} {POKEDEX_ENTRY_TYPE_LABELS.get(entry_type, entry_type)} {POKEDEX_REGION_LABELS.get(region, region)}"
        prev_rows = hist[hist["date"] < dt].sort_values("date")
        if not prev_rows.empty:
            prev = prev_rows.iloc[-1]
            prev_value = float(prev["value"])
            if float(value) < prev_value:
                prev_date = pd.to_datetime(prev["date"], errors="coerce")
                prev_date_txt = prev_date.date().isoformat() if pd.notna(prev_date) else "-"
                errors.append(
                    f"{label} {pd.Timestamp(dt).date().isoformat()}: {float(value):g} is below previous "
                    f"{prev_value:g} on {prev_date_txt}."
                )

        next_rows = hist[hist["date"] > dt].sort_values("date")
        if not next_rows.empty:
            nxt = next_rows.iloc[0]
            next_value = float(nxt["value"])
            if float(value) > next_value:
                next_date = pd.to_datetime(nxt["date"], errors="coerce")
                next_date_txt = next_date.date().isoformat() if pd.notna(next_date) else "-"
                errors.append(
                    f"{label} {pd.Timestamp(dt).date().isoformat()}: {float(value):g} is above next "
                    f"{next_value:g} on {next_date_txt}."
                )
    return errors


def upsert_pokedex_entry_rows(
    path: Path,
    rows: list[dict[str, object]],
    entry_config: dict[tuple[str, str], dict[str, object]] | None = None,
) -> int:
    if not rows:
        return 0

    existing = load_pokedex_entry_snapshots(
        path,
        account_order=ACCOUNT_ORDER,
        valid_entry_types=set(POKEDEX_ENTRY_TYPES),
        valid_regions=set(POKEDEX_REGIONS),
    )
    new_df = pd.DataFrame(rows)
    new_df["date"] = pd.to_datetime(new_df["date"], errors="coerce")
    new_df["account"] = new_df["account"].astype(str).str.strip()
    new_df["entry_type"] = new_df["entry_type"].astype(str).str.strip().str.lower()
    new_df["region"] = new_df["region"].astype(str).str.strip().str.lower()
    new_df["value"] = pd.to_numeric(new_df["value"], errors="coerce")
    new_df = new_df.dropna(subset=["date", "account", "entry_type", "region", "value"]).copy()
    new_df = new_df[new_df["entry_type"].isin(POKEDEX_ENTRY_TYPES) & new_df["region"].isin(POKEDEX_REGIONS)].copy()
    new_df = new_df[
        ~new_df.apply(
            lambda r: _is_medal_derived_pokedex_cell(r["entry_type"], r["region"])
            or _is_overall_pokedex_cell(r["region"]),
            axis=1,
        )
    ].copy()
    new_df = new_df.drop_duplicates(subset=["date", "account", "entry_type", "region"], keep="last")
    if new_df.empty:
        return 0

    config_errors = _pokedex_entry_config_errors(new_df, entry_config or {})
    if config_errors:
        details = "\n".join(config_errors[:12])
        extra = f"\n... and {len(config_errors) - 12} more issue(s)." if len(config_errors) > 12 else ""
        raise ValueError("Pokédex input rejected: values must match configured availability.\n" + details + extra)

    monotonic_errors = _validate_pokedex_entry_rows_non_decreasing(existing, new_df)
    if monotonic_errors:
        details = "\n".join(monotonic_errors[:12])
        extra = f"\n... and {len(monotonic_errors) - 12} more issue(s)." if len(monotonic_errors) > 12 else ""
        raise ValueError("Pokédex input rejected: values must be non-decreasing over time.\n" + details + extra)

    combined = new_df.copy() if existing.empty else pd.concat([existing, new_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["date", "account", "entry_type", "region"], keep="last")
    order_map = {name: i for i, name in enumerate(ACCOUNT_ORDER)}
    combined["_acc_order"] = combined["account"].map(order_map).fillna(999)
    combined["_type_order"] = combined["entry_type"].map({name: i for i, name in enumerate(POKEDEX_ENTRY_TYPES)}).fillna(999)
    combined["_region_order"] = combined["region"].map({name: i for i, name in enumerate(POKEDEX_REGIONS)}).fillna(999)
    combined = combined.sort_values(
        ["date", "_acc_order", "account", "_type_order", "_region_order", "entry_type", "region"]
    ).drop(columns=["_acc_order", "_type_order", "_region_order"])
    combined["date"] = combined["date"].dt.date.astype(str)
    path.parent.mkdir(parents=True, exist_ok=True)
    combined[["date", "account", "entry_type", "region", "value"]].to_csv(path, index=False, encoding="utf-8-sig")
    return int(len(new_df))


def load_additional_activity(path: Path) -> pd.DataFrame:
    cols = ["date", "account", "battles_won"]
    if not path.exists():
        return pd.DataFrame(columns=cols)
    try:
        df = pd.read_csv(path, encoding="utf-8-sig", sep=None, engine="python")
    except Exception:
        try:
            df = pd.read_csv(path, encoding="utf-8-sig")
        except Exception:
            return pd.DataFrame(columns=cols)
    if not set(cols).issubset(df.columns):
        return pd.DataFrame(columns=cols)
    df = df[cols].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["account"] = df["account"].astype(str).str.strip()
    df["battles_won"] = pd.to_numeric(df["battles_won"], errors="coerce")
    df = df.dropna(subset=["date", "account", "battles_won"]).copy()
    df = df.sort_values(["date", "account"]).drop_duplicates(["date", "account"], keep="last")
    return df.reset_index(drop=True)


def _validate_additional_activity_rows_non_decreasing(existing_df: pd.DataFrame, new_df: pd.DataFrame) -> list[str]:
    errors: list[str] = []
    if new_df.empty:
        return errors

    existing = existing_df.copy()
    if not existing.empty:
        existing = existing.drop_duplicates(subset=["date", "account"], keep="last")

    rows = new_df.drop_duplicates(subset=["date", "account"], keep="last").copy()
    for _, row in rows.iterrows():
        dt = pd.to_datetime(row["date"], errors="coerce")
        account = str(row["account"]).strip()
        battles_won = pd.to_numeric(row["battles_won"], errors="coerce")
        if pd.isna(dt) or not account or pd.isna(battles_won):
            continue

        hist = existing[existing["account"] == account].copy()
        if hist.empty:
            continue
        hist = hist[hist["date"] != dt].copy()

        prev_rows = hist[hist["date"] < dt].sort_values("date")
        if not prev_rows.empty:
            prev = prev_rows.iloc[-1]
            prev_value = float(prev["battles_won"])
            if float(battles_won) < prev_value:
                prev_date = pd.to_datetime(prev["date"], errors="coerce")
                prev_date_txt = prev_date.date().isoformat() if pd.notna(prev_date) else "-"
                errors.append(
                    f"{account} battles_won {pd.Timestamp(dt).date().isoformat()}: {float(battles_won):g} is below previous "
                    f"{prev_value:g} on {prev_date_txt}."
                )

        next_rows = hist[hist["date"] > dt].sort_values("date")
        if not next_rows.empty:
            nxt = next_rows.iloc[0]
            next_value = float(nxt["battles_won"])
            if float(battles_won) > next_value:
                next_date = pd.to_datetime(nxt["date"], errors="coerce")
                next_date_txt = next_date.date().isoformat() if pd.notna(next_date) else "-"
                errors.append(
                    f"{account} battles_won {pd.Timestamp(dt).date().isoformat()}: {float(battles_won):g} is above next "
                    f"{next_value:g} on {next_date_txt}."
                )
    return errors


def upsert_additional_activity_rows(path: Path, rows: list[dict[str, object]]) -> int:
    if not rows:
        return 0
    new_df = pd.DataFrame(rows)
    new_df["date"] = pd.to_datetime(new_df["date"], errors="coerce")
    new_df["account"] = new_df["account"].astype(str).str.strip()
    new_df["battles_won"] = pd.to_numeric(new_df["battles_won"], errors="coerce")
    new_df = new_df.dropna(subset=["date", "account", "battles_won"]).copy()
    new_df = new_df.drop_duplicates(subset=["date", "account"], keep="last")
    if new_df.empty:
        return 0

    existing = load_additional_activity(path)
    monotonic_errors = _validate_additional_activity_rows_non_decreasing(existing, new_df)
    if monotonic_errors:
        details = "\n".join(monotonic_errors[:12])
        extra = f"\n... and {len(monotonic_errors) - 12} more issue(s)." if len(monotonic_errors) > 12 else ""
        raise ValueError("Additional activity input rejected: battles_won must be non-decreasing over time.\n" + details + extra)

    combined = pd.concat([existing, new_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["date", "account"], keep="last")
    combined = combined.sort_values(["date", "account"]).reset_index(drop=True)
    out = combined.copy()
    out["date"] = out["date"].dt.date.astype(str)
    path.parent.mkdir(parents=True, exist_ok=True)
    out[["date", "account", "battles_won"]].to_csv(path, index=False, encoding="utf-8-sig")
    return int(len(new_df))


def medal_input_order_path() -> Path:
    return config_dir() / "medal_input_order.csv"


def xp_input_order_path() -> Path:
    return config_dir() / "xp_input_order.csv"


def _load_medal_order_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["account", "position", "medal_id"])
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame(columns=["account", "position", "medal_id"])

    if "medal_id" not in df.columns:
        return pd.DataFrame(columns=["account", "position", "medal_id"])

    if "account" not in df.columns:
        df = df.copy()
        df["account"] = "__default__"
    if "position" not in df.columns:
        df = df.copy()
        df["position"] = range(1, len(df) + 1)

    df = df[["account", "position", "medal_id"]].copy()
    df["account"] = df["account"].astype(str).str.strip()
    df["position"] = pd.to_numeric(df["position"], errors="coerce")
    df["medal_id"] = df["medal_id"].astype(str).str.strip().str.lower()
    df = df.dropna(subset=["position", "medal_id"]).copy()
    df["position"] = df["position"].astype(int)
    return df


def _load_xp_order_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["position", "account"])
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame(columns=["position", "account"])

    if "account" not in df.columns:
        return pd.DataFrame(columns=["position", "account"])
    if "position" not in df.columns:
        df = df.copy()
        df["position"] = range(1, len(df) + 1)

    df = df[["position", "account"]].copy()
    df["position"] = pd.to_numeric(df["position"], errors="coerce")
    df["account"] = df["account"].astype(str).str.strip()
    df = df.dropna(subset=["position", "account"]).copy()
    df = df[df["account"] != ""].copy()
    df["position"] = df["position"].astype(int)
    return df


def load_medal_input_order(goals: pd.DataFrame, account: str | None = None) -> list[str]:
    valid = [m for m in goals["medal_id"].astype(str).tolist() if m not in EXCLUDED_MANUAL_MEDAL_IDS]
    if not valid:
        return []

    order_file = medal_input_order_path()
    order_df = _load_medal_order_table(order_file)
    if not order_df.empty:
        if account:
            scoped = order_df[order_df["account"] == account].copy()
            if scoped.empty:
                scoped = order_df[order_df["account"] == "__default__"].copy()
        else:
            scoped = order_df[order_df["account"] == "__default__"].copy()
            if scoped.empty:
                scoped = order_df.copy()

        if not scoped.empty:
            scoped = scoped.sort_values(["position", "medal_id"])
            saved = scoped["medal_id"].astype(str).tolist()
            ordered = [m for m in saved if m in valid]
            missing = [m for m in valid if m not in ordered]
            return ordered + missing
    return valid


def load_xp_input_order(valid_accounts: list[str]) -> list[str]:
    valid = [str(a).strip() for a in valid_accounts if str(a).strip()]
    if not valid:
        return []

    order_df = _load_xp_order_table(xp_input_order_path())
    if order_df.empty:
        return valid
    order_df = order_df.sort_values(["position", "account"])
    saved = order_df["account"].astype(str).tolist()
    ordered = [a for a in saved if a in valid]
    missing = [a for a in valid if a not in ordered]
    return ordered + missing


def save_medal_input_order(account: str, ordered_medal_ids: list[str]) -> None:
    path = medal_input_order_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_medal_order_table(path)
    existing = existing[existing["account"] != account].copy()

    new_rows = pd.DataFrame(
        {
            "account": [account] * len(ordered_medal_ids),
            "position": list(range(1, len(ordered_medal_ids) + 1)),
            "medal_id": ordered_medal_ids,
        }
    )
    out = pd.concat([existing, new_rows], ignore_index=True)
    acc_order = {name: i for i, name in enumerate(ACCOUNT_ORDER)}
    out["_acc_order"] = out["account"].map(acc_order).fillna(999)
    out = out.sort_values(["_acc_order", "account", "position", "medal_id"]).drop(columns=["_acc_order"])
    out.to_csv(path, index=False, encoding="utf-8-sig")


def save_xp_input_order(ordered_accounts: list[str]) -> None:
    path = xp_input_order_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    out = pd.DataFrame(
        {
            "position": list(range(1, len(ordered_accounts) + 1)),
            "account": [str(a).strip() for a in ordered_accounts],
        }
    )
    out = out[out["account"] != ""].copy()
    out.to_csv(path, index=False, encoding="utf-8-sig")


def run_repo_command(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    output = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if err:
        output = f"{output}\n{err}".strip()
    return proc.returncode, output


def account_options_from_data(xp_df: pd.DataFrame, medal_df: pd.DataFrame, pokedex_df: pd.DataFrame | None = None) -> list[str]:
    players = set(xp_df["Spieler"].dropna().astype(str).tolist())
    accounts = set(medal_df["account"].dropna().astype(str).tolist())
    pokedex_accounts = (
        set(pokedex_df["account"].dropna().astype(str).tolist())
        if pokedex_df is not None and not pokedex_df.empty and "account" in pokedex_df.columns
        else set()
    )
    configured_groups = parse_groups(player_groups_path())
    group_accounts: set[str] = set()
    for names in configured_groups.values():
        for raw_name in names:
            name = str(raw_name).strip()
            if name:
                group_accounts.add(name)

    all_names = sorted(players | accounts | pokedex_accounts | group_accounts | set(ACCOUNT_ORDER))
    ordered = [a for a in ACCOUNT_ORDER if a in all_names]
    fallback_order = ordered + [a for a in all_names if a not in ordered]
    return load_xp_input_order(fallback_order)


def accounts_for_data_input(
    input_type: str,
    all_accounts: list[str],
    config_df: pd.DataFrame,
    fallback_accounts: list[str] | None = None,
) -> list[str]:
    input_key = str(input_type).strip().lower()
    available = [str(a).strip() for a in all_accounts if str(a).strip()]
    fallback = [str(a).strip() for a in (fallback_accounts or available) if str(a).strip()]
    if not input_key or config_df.empty or not {"input_type", "account", "enabled"}.issubset(config_df.columns):
        return [a for a in fallback if a in set(available)]

    scoped = config_df[config_df["input_type"].astype(str).str.strip().str.lower() == input_key].copy()
    if scoped.empty:
        return []
    scoped["account"] = scoped["account"].astype(str).str.strip()
    scoped["enabled"] = scoped["enabled"].fillna(False).astype(bool)
    enabled = scoped[scoped["enabled"]]["account"].tolist()
    enabled_set = set(enabled)
    return [a for a in available if a in enabled_set]


def latest_xp_snapshot(xp_df: pd.DataFrame) -> pd.DataFrame:
    cols = ["Date", "Spieler", "Lvl", "XP Bar", "Total XP"]
    if xp_df.empty:
        return pd.DataFrame(columns=cols)
    latest = xp_df.sort_values(["Spieler", "Date"]).groupby("Spieler", as_index=False).tail(1)
    latest = latest.sort_values("Total XP", ascending=False).reset_index(drop=True)
    return latest[cols].copy()


def window_suffix(window_days: int) -> str:
    return f"{int(window_days)}d"


def window_col(base: str, window_days: int) -> str:
    return f"{base}_{window_suffix(window_days)}"


def parse_window_days(value: object, fallback: int = WINDOW_DAYS_DEFAULT) -> int:
    m = re.search(r"(\d+)", str(value))
    if not m:
        return int(fallback)
    try:
        return int(m.group(1))
    except Exception:
        return int(fallback)


def _hex_to_rgba(color: str, alpha: float) -> str:
    text = str(color).strip().lstrip("#")
    if len(text) != 6:
        return f"rgba(148, 163, 184, {float(alpha)})"
    try:
        r = int(text[0:2], 16)
        g = int(text[2:4], 16)
        b = int(text[4:6], 16)
    except Exception:
        return f"rgba(148, 163, 184, {float(alpha)})"
    return f"rgba({r}, {g}, {b}, {float(alpha)})"


def _unique_accounts(accounts: Sequence[object]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in accounts:
        acc = str(raw).strip()
        if not acc or acc in seen:
            continue
        seen.add(acc)
        out.append(acc)
    return out


def build_account_color_map(accounts: Sequence[object], xp_df: pd.DataFrame | None = None) -> dict[str, str]:
    ordered_accounts = _unique_accounts(accounts)
    if xp_df is not None and not xp_df.empty and {"Spieler", "Date", "Total XP"}.issubset(xp_df.columns):
        ranked = xp_df[["Spieler", "Date", "Total XP"]].copy()
        ranked["Spieler"] = ranked["Spieler"].astype(str).str.strip()
        ranked["Date"] = pd.to_datetime(ranked["Date"], errors="coerce")
        ranked["Total XP"] = pd.to_numeric(ranked["Total XP"], errors="coerce")
        ranked = ranked.dropna(subset=["Spieler", "Date", "Total XP"]).copy()
        ranked = ranked[ranked["Spieler"].isin(set(ordered_accounts))].copy()
        if not ranked.empty:
            ranked = ranked.sort_values(["Spieler", "Date"])
            ranked = ranked.groupby("Spieler", as_index=False).tail(1)
            ranked = ranked.sort_values(["Total XP", "Spieler"], ascending=[False, True])
            ranked_accounts = ranked["Spieler"].astype(str).tolist()
            ordered_accounts = ranked_accounts + [a for a in ordered_accounts if a not in set(ranked_accounts)]
    return {acc: ACCOUNT_COLORWAY[idx % len(ACCOUNT_COLORWAY)] for idx, acc in enumerate(ordered_accounts)}


def _trace_owner_name(trace_name: object) -> str | None:
    name = str(trace_name).strip()
    if not name or name == "_nolegend_":
        return None
    if " catch " in name and " -> " in name:
        return name.split(" catch ", 1)[0].strip()
    if name.endswith(" catch point"):
        return name.rsplit(" catch point", 1)[0].strip()
    if " trend (" in name:
        return name.split(" trend (", 1)[0].strip()
    return name


def apply_account_colors(fig: go.Figure | None, account_color_map: dict[str, str]) -> None:
    if fig is None or not getattr(fig, "data", None) or not account_color_map:
        return
    for trace in fig.data:
        owner = _trace_owner_name(getattr(trace, "name", ""))
        if not owner:
            continue
        color = account_color_map.get(owner)
        if not color:
            continue
        trace_type = str(getattr(trace, "type", "")).strip().lower()
        if trace_type in {"scatter", "scattergl"}:
            trace.update(line={"color": color}, marker={"color": color})
        elif trace_type == "bar":
            trace.update(marker={"color": color})


def account_badge_html(label: object, color: str | None) -> str:
    text = str(label).strip()
    if not text:
        return ""
    swatch = ""
    if color:
        swatch = (
            f"<span style='display:inline-block;width:0.72rem;height:0.72rem;"
            f"border-radius:999px;background:{escape(str(color))};"
            "margin-right:0.42rem;vertical-align:-0.08rem;'></span>"
        )
    return f"<span style='white-space:nowrap;'>{swatch}{escape(text)}</span>"


def render_account_color_legend(accounts: Sequence[object], account_color_map: dict[str, str]) -> None:
    items = []
    for acc in _unique_accounts(accounts):
        items.append(account_badge_html(acc, account_color_map.get(acc)))
    if not items:
        return
    st.markdown(
        (
            "<div style='display:flex;flex-wrap:wrap;gap:0.55rem 1rem;margin:0.12rem 0 0.4rem 0;"
            "font-size:0.92rem;opacity:0.92;'>"
            + "".join(items)
            + "</div>"
        ),
        unsafe_allow_html=True,
    )


def account_cell_style(value: object, account_color_map: dict[str, str]) -> str:
    account = str(value).strip()
    color = account_color_map.get(account)
    if not color:
        return ""
    return f"background-color: {_hex_to_rgba(color, 0.16)}; border-left: 0.38rem solid {color}; font-weight: 600;"


def normalize_dashboard_window_days(value: object, fallback: int) -> int:
    parsed = parse_window_days(value, fallback=fallback)
    if int(parsed) in DASHBOARD_WINDOW_OPTIONS:
        return int(parsed)
    return int(fallback)


def load_ui_preferences(path: Path = UI_PREFERENCES_PATH) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def save_ui_preferences(prefs: dict[str, object], path: Path = UI_PREFERENCES_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(prefs, indent=2, sort_keys=True), encoding="utf-8")


def _input_inactive_date_key(row_date: object) -> str:
    parsed = pd.to_datetime(row_date, errors="coerce")
    if pd.notna(parsed):
        return pd.Timestamp(parsed).date().isoformat()
    return str(row_date).strip()


def load_input_inactive_marker(
    input_type: str,
    row_date: object,
    account: str,
    category: str | None = None,
    path: Path = UI_PREFERENCES_PATH,
) -> bool:
    prefs = load_ui_preferences(path)
    input_key = str(input_type).strip().lower()
    account_key = str(account).strip()
    if input_key == "xp" and category is None:
        raw_defaults = prefs.get(UI_PREF_DATA_INPUT_INACTIVE_DEFAULTS)
        if isinstance(raw_defaults, dict):
            xp_defaults = raw_defaults.get("xp")
            if isinstance(xp_defaults, dict) and account_key in xp_defaults:
                return bool(xp_defaults.get(account_key, False))

    raw_root = prefs.get(UI_PREF_DATA_INPUT_INACTIVE)
    if not isinstance(raw_root, dict):
        return False
    type_scope = raw_root.get(input_key)
    if not isinstance(type_scope, dict):
        return False
    date_scope = type_scope.get(_input_inactive_date_key(row_date))
    if not isinstance(date_scope, dict):
        return False
    if category is None:
        return bool(date_scope.get(account_key, False))
    account_scope = date_scope.get(account_key)
    if not isinstance(account_scope, dict):
        return False
    return bool(account_scope.get(str(category).strip().lower(), False))


def save_input_inactive_marker(
    input_type: str,
    row_date: object,
    account: str,
    inactive: bool,
    category: str | None = None,
    path: Path = UI_PREFERENCES_PATH,
) -> None:
    input_key = str(input_type).strip().lower()
    account_key = str(account).strip()
    date_key = _input_inactive_date_key(row_date)
    if not input_key or not account_key or not date_key:
        return

    prefs = load_ui_preferences(path)
    if input_key == "xp" and category is None:
        raw_defaults = prefs.get(UI_PREF_DATA_INPUT_INACTIVE_DEFAULTS)
        defaults = dict(raw_defaults) if isinstance(raw_defaults, dict) else {}
        raw_xp_defaults = defaults.get("xp")
        xp_defaults = dict(raw_xp_defaults) if isinstance(raw_xp_defaults, dict) else {}
        if inactive:
            xp_defaults[account_key] = True
        else:
            xp_defaults.pop(account_key, None)
        if xp_defaults:
            defaults["xp"] = xp_defaults
        else:
            defaults.pop("xp", None)
        if defaults:
            prefs[UI_PREF_DATA_INPUT_INACTIVE_DEFAULTS] = defaults
        else:
            prefs.pop(UI_PREF_DATA_INPUT_INACTIVE_DEFAULTS, None)
        raw_root = prefs.get(UI_PREF_DATA_INPUT_INACTIVE)
        root = dict(raw_root) if isinstance(raw_root, dict) else {}
        raw_type_scope = root.get(input_key)
        type_scope = dict(raw_type_scope) if isinstance(raw_type_scope, dict) else {}
        raw_date_scope = type_scope.get(date_key)
        date_scope = dict(raw_date_scope) if isinstance(raw_date_scope, dict) else {}
        date_scope.pop(account_key, None)
        if date_scope:
            type_scope[date_key] = date_scope
        else:
            type_scope.pop(date_key, None)
        if type_scope:
            root[input_key] = type_scope
        else:
            root.pop(input_key, None)
        if root:
            prefs[UI_PREF_DATA_INPUT_INACTIVE] = root
        else:
            prefs.pop(UI_PREF_DATA_INPUT_INACTIVE, None)
        if prefs == load_ui_preferences(path):
            return
        save_ui_preferences(prefs, path)
        return

    raw_root = prefs.get(UI_PREF_DATA_INPUT_INACTIVE)
    root = dict(raw_root) if isinstance(raw_root, dict) else {}
    type_scope = dict(root.get(input_key)) if isinstance(root.get(input_key), dict) else {}
    date_scope = dict(type_scope.get(date_key)) if isinstance(type_scope.get(date_key), dict) else {}

    if category is None:
        if inactive:
            date_scope[account_key] = True
        else:
            date_scope.pop(account_key, None)
    else:
        category_key = str(category).strip().lower()
        if not category_key:
            return
        account_scope = dict(date_scope.get(account_key)) if isinstance(date_scope.get(account_key), dict) else {}
        if inactive:
            account_scope[category_key] = True
        else:
            account_scope.pop(category_key, None)
        if account_scope:
            date_scope[account_key] = account_scope
        else:
            date_scope.pop(account_key, None)

    if date_scope:
        type_scope[date_key] = date_scope
    else:
        type_scope.pop(date_key, None)
    if type_scope:
        root[input_key] = type_scope
    else:
        root.pop(input_key, None)
    if root:
        prefs[UI_PREF_DATA_INPUT_INACTIVE] = root
    else:
        prefs.pop(UI_PREF_DATA_INPUT_INACTIVE, None)
    if prefs == load_ui_preferences(path):
        return
    save_ui_preferences(prefs, path)


def mark_session_flag(key: str) -> None:
    st.session_state[str(key)] = True


def load_saved_dashboard_window_days(fallback: int, path: Path = UI_PREFERENCES_PATH) -> int:
    prefs = load_ui_preferences(path)
    return normalize_dashboard_window_days(prefs.get(UI_PREF_DASHBOARD_WINDOW_DAYS), fallback=fallback)


def save_dashboard_window_days(window_days: int, path: Path = UI_PREFERENCES_PATH) -> None:
    normalized = normalize_dashboard_window_days(window_days, fallback=DASHBOARD_WINDOW_OPTIONS[0])
    prefs = load_ui_preferences(path)
    if prefs.get(UI_PREF_DASHBOARD_WINDOW_DAYS) == int(normalized):
        return
    prefs[UI_PREF_DASHBOARD_WINDOW_DAYS] = int(normalized)
    save_ui_preferences(prefs, path)


def load_saved_dashboard_gap_leader(group_key: object, valid_leaders: Sequence[str], path: Path = UI_PREFERENCES_PATH) -> str | None:
    key = str(group_key).strip()
    if not key:
        return None
    prefs = load_ui_preferences(path)
    raw_by_group = prefs.get(UI_PREF_DASHBOARD_GAP_LEADER_BY_GROUP)
    if not isinstance(raw_by_group, dict):
        return None
    saved = str(raw_by_group.get(key, "")).strip()
    valid = {str(leader).strip() for leader in valid_leaders if str(leader).strip()}
    return saved if saved in valid else None


def save_dashboard_gap_leader(group_key: object, leader: object, path: Path = UI_PREFERENCES_PATH) -> None:
    key = str(group_key).strip()
    saved_leader = str(leader).strip()
    if not key or not saved_leader:
        return
    prefs = load_ui_preferences(path)
    raw_by_group = prefs.get(UI_PREF_DASHBOARD_GAP_LEADER_BY_GROUP)
    by_group = dict(raw_by_group) if isinstance(raw_by_group, dict) else {}
    if by_group.get(key) == saved_leader:
        return
    by_group[key] = saved_leader
    prefs[UI_PREF_DASHBOARD_GAP_LEADER_BY_GROUP] = by_group
    save_ui_preferences(prefs, path)


def format_kpi_number(value: object, suffix: str = "") -> str:
    n = pd.to_numeric(value, errors="coerce")
    if pd.isna(n):
        return "-"
    if suffix:
        return f"{int(round(float(n))):,} {suffix}"
    return f"{int(round(float(n))):,}"


def render_kpi_card(
    col: object,
    title: str,
    value: str,
    *,
    winner: str | None = None,
    winner_color: str | None = None,
    context: str | None = None,
    delta: str | None = None,
    delta_color: str = "normal",
    help_text: str | None = None,
) -> None:
    card_help = str(help_text).strip() if help_text is not None else ""
    if not card_help:
        details: list[str] = [f"Metric: {title}", f"Value: {value}"]
        if winner is not None and str(winner).strip():
            details.append(f"Winner: {str(winner).strip()}")
        if context is not None and str(context).strip():
            details.append(f"Context: {str(context).strip()}")
        if delta is not None and str(delta).strip():
            details.append(f"Delta: {str(delta).strip()}")
        card_help = "\n".join(details)
    with col:
        st.metric(
            title,
            value,
            delta=delta,
            delta_color=delta_color,
            help=card_help,
        )
        if winner is not None and str(winner).strip():
            if str(winner_color or "").strip():
                st.markdown(account_badge_html(winner, winner_color), unsafe_allow_html=True)
            else:
                st.caption(str(winner))
        if context is not None and str(context).strip():
            st.caption(str(context))


def compute_metrics_by_window(
    xp_df: pd.DataFrame,
    window_options: list[int] | None = None,
    baseline_min_windows: int = BASELINE_MIN_WINDOWS_DEFAULT,
) -> dict[int, pd.DataFrame]:
    windows = window_options or DASHBOARD_WINDOW_OPTIONS
    out: dict[int, pd.DataFrame] = {}
    for w in windows:
        w_int = int(w)
        out[w_int] = compute_player_kpis_window(
            xp_df,
            window_days=w_int,
            baseline_min_windows=baseline_min_windows,
        )
    return out


def count_window_eligible(metrics_df: pd.DataFrame, window_days: int, baseline: bool = False) -> int:
    if metrics_df.empty:
        return 0
    col = window_col("eligible_baseline" if baseline else "eligible", window_days)
    if col not in metrics_df.columns:
        return 0
    return int(metrics_df[col].fillna(False).astype(bool).sum())


def auto_default_window_days(
    metrics_by_window: dict[int, pd.DataFrame],
    preferred_window_days: int = WINDOW_DAYS_DEFAULT,
    fallback_window_days: int = 7,
    min_eligible_for_preferred: int = MIN_ELIGIBLE_FOR_30D_DEFAULT,
) -> int:
    if not metrics_by_window:
        return int(fallback_window_days)

    scored_windows: list[tuple[int, int]] = []
    for window_days in sorted(metrics_by_window.keys()):
        eligible_count = count_window_eligible(metrics_by_window.get(int(window_days), pd.DataFrame()), int(window_days), baseline=False)
        scored_windows.append((int(window_days), int(eligible_count)))
    if not scored_windows:
        return int(fallback_window_days)

    max_eligible = max(score for _, score in scored_windows)
    candidates = [window for window, score in scored_windows if score == max_eligible]
    preferred_window = int(preferred_window_days)
    fallback_window = int(fallback_window_days)
    if preferred_window in candidates and max_eligible >= int(min_eligible_for_preferred):
        return preferred_window
    if fallback_window in candidates:
        return fallback_window
    return int(min(candidates))


def xp_recent_gain(xp_df: pd.DataFrame, days: int = 30) -> pd.DataFrame:
    metrics_df = compute_player_kpis_window(
        xp_df,
        window_days=int(days),
        baseline_min_windows=BASELINE_MIN_WINDOWS_DEFAULT,
    )
    return recent_gain_table_from_metrics(metrics_df, window_days=int(days))


def top_newcomer(xp_df: pd.DataFrame, window_days: int = WINDOW_DAYS_DEFAULT) -> dict[str, object] | None:
    w = int(window_days)
    metrics_df = compute_player_kpis_window(
        xp_df,
        window_days=w,
        baseline_min_windows=BASELINE_MIN_WINDOWS_DEFAULT,
    )
    if metrics_df.empty:
        return None
    eligible_col = window_col("eligible_baseline", w)
    delta_col = window_col("delta_vs_baseline", w)
    baseline_col = window_col("baseline_xp_per_day", w)
    pace_col = window_col("xp_per_day", w)
    end_col = window_col("window_end", w)
    eligible = metrics_df[metrics_df[eligible_col] == True].copy()  # noqa: E712
    if eligible.empty:
        return None
    ranked = eligible.sort_values(delta_col, ascending=False).reset_index(drop=True)
    row = ranked.iloc[0]
    if float(row[delta_col]) <= 0:
        return None
    baseline = pd.to_numeric(row.get(baseline_col), errors="coerce")
    current = pd.to_numeric(row.get(pace_col), errors="coerce")
    ratio = (float(current) / float(baseline)) if pd.notna(baseline) and float(baseline) != 0 else float("nan")
    return {
        "spieler": str(row["Spieler"]),
        "current_pace": float(current),
        "baseline_pace": float(baseline) if pd.notna(baseline) else float("nan"),
        "improvement": float(row[delta_col]),
        "ratio": float(ratio),
        "as_of": pd.to_datetime(row[end_col], errors="coerce"),
    }


def top_decliner(xp_df: pd.DataFrame, window_days: int = WINDOW_DAYS_DEFAULT) -> dict[str, object] | None:
    w = int(window_days)
    metrics_df = compute_player_kpis_window(
        xp_df,
        window_days=w,
        baseline_min_windows=BASELINE_MIN_WINDOWS_DEFAULT,
    )
    if metrics_df.empty:
        return None
    eligible_col = window_col("eligible_baseline", w)
    delta_col = window_col("delta_vs_baseline", w)
    baseline_col = window_col("baseline_xp_per_day", w)
    pace_col = window_col("xp_per_day", w)
    end_col = window_col("window_end", w)
    eligible = metrics_df[metrics_df[eligible_col] == True].copy()  # noqa: E712
    if eligible.empty:
        return None
    ranked = eligible.sort_values(delta_col, ascending=True).reset_index(drop=True)
    row = ranked.iloc[0]
    if float(row[delta_col]) >= 0:
        return None
    baseline = pd.to_numeric(row.get(baseline_col), errors="coerce")
    current = pd.to_numeric(row.get(pace_col), errors="coerce")
    ratio_value = (float(current) / float(baseline)) if pd.notna(baseline) and float(baseline) != 0 else float("nan")
    return {
        "spieler": str(row["Spieler"]),
        "current_pace": float(current),
        "baseline_pace": float(baseline) if pd.notna(baseline) else float("nan"),
        "improvement": float(row[delta_col]),
        "ratio": float(ratio_value) if pd.notna(ratio_value) else float("nan"),
        "as_of": pd.to_datetime(row[end_col], errors="coerce"),
    }


def build_xp_growth_figure(
    curve_map: dict[int, int],
    latest_df: pd.DataFrame,
    account_color_map: dict[str, str] | None = None,
) -> go.Figure | None:
    if not curve_map:
        return None

    curve_df = pd.DataFrame(
        {
            "Level": list(curve_map.keys()),
            "Total XP": list(curve_map.values()),
        }
    ).sort_values("Level")
    if curve_df.empty:
        return None
    curve_df["Total XP (M)"] = curve_df["Total XP"] / 1_000_000
    curve_df["XP per Level (M)"] = curve_df["Total XP"].diff().fillna(0) / 1_000_000

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    max_total_xp_m = float(curve_df["Total XP (M)"].max())
    max_xp_per_level_m = float(curve_df["XP per Level (M)"].max())
    fig.add_trace(
        go.Bar(
            x=curve_df["Level"],
            y=curve_df["XP per Level (M)"],
            name="XP per level",
            marker_color="rgba(148,163,184,0.22)",
            marker_line_width=0,
            opacity=0.45,
            hoverinfo="skip",
        ),
        secondary_y=True,
    )
    fig.add_trace(
        go.Scatter(
            x=curve_df["Level"],
            y=curve_df["Total XP (M)"],
            mode="lines",
            name="Total XP (curve)",
            line=dict(width=3),
        ),
        secondary_y=False,
    )
    has_player_points = False
    if not latest_df.empty:
        pts = latest_df.copy()
        pts["Lvl"] = pd.to_numeric(pts["Lvl"], errors="coerce")
        pts["Total XP"] = pd.to_numeric(pts["Total XP"], errors="coerce")
        pts = pts.dropna(subset=["Lvl", "Total XP"]).copy()
        pts["Lvl"] = pts["Lvl"].astype(int)
        pts["Total XP (M)"] = pts["Total XP"] / 1_000_000
        pts = pts.sort_values("Total XP", ascending=False).reset_index(drop=True)
        pts["label"] = ""
        max_labels = 12
        label_count = min(max_labels, len(pts))
        pts.loc[: label_count - 1, "label"] = pts.loc[: label_count - 1].apply(
            lambda r: f"{r['Spieler']} ({r['Total XP (M)']:.1f}M)",
            axis=1,
        )
        fig.add_trace(
            go.Scatter(
                x=pts["Lvl"],
                y=pts["Total XP (M)"],
                mode="markers+text",
                name="Players",
                text=pts["label"],
                textposition="top center",
                cliponaxis=False,
                marker=dict(
                    size=9,
                    color=[
                        (account_color_map or {}).get(str(player), "#ff4d4d")
                        for player in pts["Spieler"].astype(str).tolist()
                    ],
                    symbol=[
                        "diamond" if is_max_level(int(lvl), curve_map) else "circle"
                        for lvl in pts["Lvl"].tolist()
                    ],
                ),
                hovertemplate="Player: %{customdata[0]}<br>Level: %{x}<br>Total XP: %{customdata[1]:,.0f}<extra></extra>",
                customdata=pts[["Spieler", "Total XP"]],
            ),
            secondary_y=False,
        )
        if not pts.empty:
            has_player_points = True
            max_total_xp_m = max(max_total_xp_m, float(pts["Total XP (M)"].max()))

    fig.update_layout(
        title="PoGo XP Growth",
        bargap=0.08,
        legend=dict(orientation="h", y=1.05, x=0),
        margin=dict(l=20, r=20, t=50, b=20),
        height=540,
    )
    level_min = int(curve_df["Level"].min())
    level_max = int(curve_df["Level"].max())
    fig.update_xaxes(
        title_text="Level",
        range=[level_min - 0.5, level_max + 0.5],
    )
    left_headroom = 1.15 if has_player_points else 1.05
    left_max = max(1.0, max_total_xp_m * left_headroom)
    right_max = max(1.0, max_xp_per_level_m * 1.02)
    fig.update_yaxes(
        title_text="Total XP (M)",
        secondary_y=False,
        range=[0, left_max],
        nticks=6,
        tickformat=",.0f",
    )
    fig.update_yaxes(
        title_text="XP per Level (M)",
        secondary_y=True,
        range=[0, right_max],
        nticks=6,
        tickformat=",.1f",
        showgrid=False,
        showline=False,
        zeroline=False,
    )
    return fig


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(value).strip()).strip("_").lower()
    return slug or "group"


def _build_medal_export_tables(
    dash_medal_df: pd.DataFrame,
    dash_display_medal_df: pd.DataFrame,
    goals_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if dash_display_medal_df.empty or goals_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    latest_medals = dash_display_medal_df.sort_values("date").groupby(["account", "medal_id"], as_index=False).tail(1)
    latest_medals = latest_medals.merge(goals_df, on="medal_id", how="left")
    latest_medals["pct_goal"] = (latest_medals["value"] / latest_medals["goal_value"] * 100).round(1)
    latest_medals["is_platinum"] = latest_medals["value"] >= latest_medals["goal_value"]
    latest_medals_view = latest_medals[
        ["date", "account", "display_name", "value", "goal_value", "pct_goal", "is_platinum"]
    ].sort_values(["account", "display_name"])

    history = dash_medal_df.copy()
    history["date"] = pd.to_datetime(history["date"], errors="coerce")
    history["account"] = history["account"].astype(str).str.strip()
    history["medal_id"] = history["medal_id"].astype(str).str.strip().str.lower()
    history["value"] = pd.to_numeric(history["value"], errors="coerce")
    history = history.dropna(subset=["date", "account", "medal_id", "value"]).copy()
    history = history[history["medal_id"] != DERIVED_MEDAL_ID].copy()

    goals_map = goals_df[["medal_id", "display_name", "goal_value"]].copy()
    goals_map["medal_id"] = goals_map["medal_id"].astype(str).str.strip().str.lower()
    goals_map["goal_value"] = pd.to_numeric(goals_map["goal_value"], errors="coerce")
    goals_map = goals_map.dropna(subset=["goal_value"]).drop_duplicates(subset=["medal_id"], keep="last")

    achieved = history.merge(goals_map, on="medal_id", how="left")
    achieved = achieved.dropna(subset=["goal_value"]).copy()
    achieved["is_platinum"] = achieved["value"] >= achieved["goal_value"]
    achieved = achieved[achieved["is_platinum"]].copy()
    if achieved.empty:
        return latest_medals_view, pd.DataFrame()

    first_achieved = (
        achieved.sort_values("date")
        .groupby(["account", "medal_id"], as_index=False)
        .head(1)[["date", "account", "display_name", "medal_id", "value", "goal_value"]]
    )
    first_achieved = first_achieved.rename(columns={"date": "achieved_date", "value": "value_at_achievement"})

    existing_pairs = set(
        zip(
            first_achieved["account"].astype(str).tolist(),
            first_achieved["medal_id"].astype(str).tolist(),
        )
    )
    special_rows: list[dict[str, object]] = []
    for special in SPECIAL_PLATINUM_MEDALS:
        medal_id = str(special.get("medal_id", "")).strip().lower()
        display_name = str(special.get("display_name", medal_id)).strip() or medal_id
        flags = special.get("account_flags", {})
        achieved_dates = special.get("account_achieved_date", {})
        for acc, is_true in flags.items():
            account = str(acc).strip()
            if not account or not bool(is_true):
                continue
            if (account, medal_id) in existing_pairs:
                continue
            achieved_date = pd.to_datetime(achieved_dates.get(account), errors="coerce")
            if pd.isna(achieved_date):
                continue
            special_rows.append(
                {
                    "achieved_date": pd.to_datetime(achieved_date),
                    "account": account,
                    "display_name": display_name,
                    "medal_id": medal_id,
                    "value_at_achievement": 1.0,
                    "goal_value": 1.0,
                }
            )
    if special_rows:
        first_achieved = pd.concat([first_achieved, pd.DataFrame(special_rows)], ignore_index=True)

    first_achieved["_acc_order"] = first_achieved["account"].map({a: i for i, a in enumerate(ACCOUNT_ORDER)}).fillna(999)
    first_achieved = first_achieved.sort_values(["achieved_date", "_acc_order", "account"], ascending=[False, True, True])
    first_achieved = first_achieved.drop(columns=["_acc_order"])
    return latest_medals_view, first_achieved[
        ["achieved_date", "account", "display_name", "value_at_achievement", "goal_value"]
    ].copy()


def render_latest_medal_status_panel(
    dash_medal_df: pd.DataFrame,
    dash_display_medal_df: pd.DataFrame,
    goals_df: pd.DataFrame,
    title: str = "Latest Medal Status",
) -> None:
    st.subheader(title)
    if dash_display_medal_df.empty or goals_df.empty:
        st.info("No medal status data available for current selection.")
        return

    _latest_medals_view, first_achieved_view = _build_medal_export_tables(dash_medal_df, dash_display_medal_df, goals_df)

    display_latest = dash_display_medal_df.copy()
    display_latest["date"] = pd.to_datetime(display_latest.get("date"), errors="coerce")
    display_latest["account"] = display_latest.get("account", pd.Series(dtype=str)).astype(str).str.strip()
    display_latest["medal_id"] = display_latest.get("medal_id", pd.Series(dtype=str)).astype(str).str.strip().str.lower()
    display_latest["value"] = pd.to_numeric(display_latest.get("value"), errors="coerce")
    display_latest = display_latest.dropna(subset=["date", "account", "medal_id", "value"]).copy()
    display_latest = display_latest.sort_values("date").groupby(["account", "medal_id"], as_index=False).tail(1)
    platinum_now = display_latest[display_latest["medal_id"] == DERIVED_MEDAL_ID][["account", "value"]].copy()
    platinum_now = platinum_now.rename(columns={"value": "platinum_count"})

    if not platinum_now.empty:
        ordered_accounts = [a for a in ACCOUNT_ORDER if a in set(platinum_now["account"].astype(str))]
        ordered_accounts += [a for a in sorted(platinum_now["account"].astype(str).unique().tolist()) if a not in ordered_accounts]
        cols = st.columns(max(1, len(ordered_accounts)))
        for idx, acc in enumerate(ordered_accounts):
            row = platinum_now[platinum_now["account"].astype(str) == acc]
            if row.empty:
                cols[idx].metric(f"{acc} Platinum", "0")
            else:
                cols[idx].metric(f"{acc} Platinum", f"{int(float(row['platinum_count'].iloc[0]))}")

    if first_achieved_view.empty:
        st.info("No achieved platinum medals found yet.")
        return

    st.dataframe(
        first_achieved_view[["achieved_date", "account", "display_name", "value_at_achievement", "goal_value"]],
        use_container_width=True,
        hide_index=True,
    )


def _build_dashboard_export_payload(
    selected_accounts: list[str],
    dash_xp_df: pd.DataFrame,
    dash_medal_df: pd.DataFrame,
    dash_additional_df: pd.DataFrame,
    dash_display_medal_df: pd.DataFrame,
    goals_df: pd.DataFrame,
    curve_map: dict[int, int],
    show_medals: bool,
    window_days: int,
    selected_gap_leader: str | None = None,
    xp_explorer_date_range: tuple[date, date] | list[date] | None = None,
    xp_explorer_players: list[str] | tuple[str, ...] | None = None,
) -> dict[str, object]:
    w = int(window_days)
    w_label = f"{w}d"
    eligible_col = window_col("eligible", w)
    eligible_baseline_col = window_col("eligible_baseline", w)
    window_end_col = window_col("window_end", w)
    xp_gain_col = window_col("xp_gain", w)
    xp_per_day_col = window_col("xp_per_day", w)
    delta_col = window_col("delta_vs_baseline", w)
    pct_col = window_col("pct_vs_baseline", w)

    dash_latest_xp_df = latest_xp_snapshot(dash_xp_df)
    metrics_window_df = compute_player_kpis_window(
        dash_xp_df,
        window_days=w,
        baseline_min_windows=BASELINE_MIN_WINDOWS_DEFAULT,
    )
    dash_recent_gain_df = recent_gain_table_from_metrics(metrics_window_df, window_days=w)
    total_players = int(metrics_window_df["Spieler"].nunique()) if not metrics_window_df.empty else 0
    eligible_window = (
        int(metrics_window_df[eligible_col].fillna(False).astype(bool).sum())
        if not metrics_window_df.empty and eligible_col in metrics_window_df.columns
        else 0
    )
    eligible_baseline_window = (
        int(metrics_window_df[eligible_baseline_col].fillna(False).astype(bool).sum())
        if not metrics_window_df.empty and eligible_baseline_col in metrics_window_df.columns
        else 0
    )
    latest_level_map: dict[str, int] = {}
    if not dash_latest_xp_df.empty:
        latest_level_map = (
            dash_latest_xp_df[["Spieler", "Lvl"]]
            .dropna(subset=["Spieler", "Lvl"])
            .drop_duplicates(subset=["Spieler"], keep="last")
            .set_index("Spieler")["Lvl"]
            .astype(int)
            .to_dict()
        )

    def winner_with_level(player_name: object) -> str:
        p = str(player_name)
        lvl = latest_level_map.get(p)
        if lvl is None:
            return p
        return f"{p} (Lvl {int(lvl)})"

    eligible_gain_pool = (
        metrics_window_df[metrics_window_df[eligible_col] == True].copy()  # noqa: E712
        if not metrics_window_df.empty and eligible_col in metrics_window_df.columns
        else pd.DataFrame()
    )
    active_kpi_pool = (
        eligible_gain_pool[pd.to_numeric(eligible_gain_pool[xp_gain_col], errors="coerce") > 0].copy()
        if not eligible_gain_pool.empty
        else pd.DataFrame()
    )
    active_kpi_count = int(len(active_kpi_pool))
    eligible_baseline_pool = (
        metrics_window_df[metrics_window_df[eligible_baseline_col] == True].copy()  # noqa: E712
        if not metrics_window_df.empty and eligible_baseline_col in metrics_window_df.columns
        else pd.DataFrame()
    )
    baseline_headline_pool = (
        eligible_baseline_pool[pd.to_numeric(eligible_baseline_pool[xp_gain_col], errors="coerce") > 0].copy()
        if not eligible_baseline_pool.empty
        else pd.DataFrame()
    )
    export_account_color_map = build_account_color_map(selected_accounts, dash_xp_df)
    selected_account_set = {str(a).strip() for a in selected_accounts if str(a).strip()}
    explorer_accounts = [
        str(a).strip()
        for a in (list(xp_explorer_players) if xp_explorer_players is not None else selected_accounts)
        if str(a).strip() and str(a).strip() in selected_account_set
    ]
    if not explorer_accounts:
        explorer_accounts = [str(a).strip() for a in selected_accounts if str(a).strip()]
    explorer_color_map = build_account_color_map(explorer_accounts, dash_xp_df)

    def _headline_export_card(
        label: str,
        value: str,
        *,
        winner: object | None = None,
        detail: str | None = None,
    ) -> dict[str, object]:
        winner_text = "" if winner is None else str(winner).strip()
        winner_name = winner_text.split(" (Lvl", 1)[0].strip() if winner_text else ""
        return {
            "label": str(label),
            "value": str(value),
            "winner": winner_text,
            "winner_color": export_account_color_map.get(winner_name, "") if winner_name else "",
            "detail": "" if detail is None else str(detail),
        }

    metric_cards: list[object] = []
    if not dash_latest_xp_df.empty:
        leader_row = dash_latest_xp_df.sort_values("Total XP", ascending=False).iloc[0]
        metric_cards.append(
            _headline_export_card(
                "XP Leader",
                f"{int(leader_row['Total XP']):,}",
                winner=f"{leader_row['Spieler']} (Lvl {int(leader_row['Lvl'])})",
            )
        )
    else:
        metric_cards.append(_headline_export_card("XP Leader", "-", detail="no data"))

    if not active_kpi_pool.empty:
        gain_leader = active_kpi_pool.sort_values([xp_gain_col, xp_per_day_col], ascending=[False, False]).iloc[0]
        metric_cards.append(
            _headline_export_card(
                f"Top XP Gain ({w_label})",
                format_kpi_number(gain_leader[xp_gain_col], "XP"),
                winner=winner_with_level(gain_leader["Spieler"]),
            )
        )
        gain_trailer = active_kpi_pool.sort_values([xp_gain_col, xp_per_day_col], ascending=[True, True]).iloc[0]
        metric_cards.append(
            _headline_export_card(
                f"Least XP Gain ({w_label})",
                format_kpi_number(gain_trailer[xp_gain_col], "XP"),
                winner=winner_with_level(gain_trailer["Spieler"]),
            )
        )
    elif not eligible_gain_pool.empty:
        metric_cards.append(
            _headline_export_card(
                f"Top XP Gain ({w_label})",
                f"No active players ({w_label})",
                detail=f"all {xp_gain_col} = 0",
            )
        )
        metric_cards.append(
            _headline_export_card(
                f"Least XP Gain ({w_label})",
                f"No active players ({w_label})",
                detail=f"all {xp_gain_col} = 0",
            )
        )
    else:
        metric_cards.append(_headline_export_card(f"Top XP Gain ({w_label})", "-", detail="no data"))
        metric_cards.append(_headline_export_card(f"Least XP Gain ({w_label})", "-", detail="no data"))

    if show_medals:
        platinum_latest = dash_display_medal_df[dash_display_medal_df["medal_id"] == DERIVED_MEDAL_ID].copy()
        if not platinum_latest.empty:
            platinum_latest = platinum_latest.sort_values("date").groupby("account", as_index=False).tail(1)
            team_platinum_total = int(pd.to_numeric(platinum_latest["value"], errors="coerce").fillna(0).sum())
            breakdown = []
            for acc in ACCOUNT_ORDER:
                row = platinum_latest[platinum_latest["account"].astype(str) == acc]
                if not row.empty:
                    breakdown.append(f"{acc}:{int(float(row['value'].iloc[0]))}")
            metric_cards.append(_headline_export_card("Team Platinum Total", f"{team_platinum_total:,}", detail=" | ".join(breakdown)))
        else:
            metric_cards.append(_headline_export_card("Team Platinum Total", "-", detail="no data"))
    else:
        if active_kpi_pool.empty:
            if not eligible_gain_pool.empty:
                metric_cards.append(
                    _headline_export_card(
                        f"Fastest {w_label} Pace",
                        f"No active players ({w_label})",
                        detail=f"all {xp_gain_col} = 0",
                    )
                )
            else:
                metric_cards.append(_headline_export_card(f"Fastest {w_label} Pace", "-", detail="no data"))
        else:
            fastest = active_kpi_pool.sort_values([xp_per_day_col, xp_gain_col], ascending=[False, False]).iloc[0]
            metric_cards.append(
                _headline_export_card(
                    f"Fastest {w_label} Pace",
                    format_kpi_number(fastest[xp_per_day_col], "XP/day"),
                    winner=winner_with_level(fastest["Spieler"]),
                )
            )

        if eligible_baseline_pool.empty:
            metric_cards.append(_headline_export_card(f"Most Improved vs Baseline ({w_label})", "-", detail="no baseline-eligible data"))
            metric_cards.append(_headline_export_card(f"Most Declined vs Baseline ({w_label})", "-", detail="no baseline-eligible data"))
        elif baseline_headline_pool.empty:
            metric_cards.append(
                _headline_export_card(
                    f"Most Improved vs Baseline ({w_label})",
                    "No improvements",
                    detail=f"all {xp_gain_col} = 0 for baseline-eligible players",
                )
            )
            metric_cards.append(
                _headline_export_card(
                    f"Most Declined vs Baseline ({w_label})",
                    "No decline",
                    detail=f"all {xp_gain_col} = 0 for baseline-eligible players",
                )
            )
        else:
            improvements = baseline_headline_pool[baseline_headline_pool[delta_col] > 0].copy()
            if improvements.empty:
                metric_cards.append(
                    _headline_export_card(
                        f"Most Improved vs Baseline ({w_label})",
                        "No improvements",
                        detail="all deltas <= 0",
                    )
                )
            else:
                improved = improvements.sort_values(delta_col, ascending=False).iloc[0]
                metric_cards.append(
                    _headline_export_card(
                        f"Most Improved vs Baseline ({w_label})",
                        format_kpi_number(improved[xp_per_day_col], "XP/day"),
                        winner=winner_with_level(improved["Spieler"]),
                        detail=f"{int(round(float(improved[delta_col]))):+,} XP/day vs baseline",
                    )
                )
            declines = baseline_headline_pool[baseline_headline_pool[delta_col] < 0].copy()
            if declines.empty:
                metric_cards.append(
                    _headline_export_card(
                        f"Most Declined vs Baseline ({w_label})",
                        "No decline",
                        detail="all deltas >= 0",
                    )
                )
            else:
                declined = declines.sort_values(delta_col, ascending=True).iloc[0]
                metric_cards.append(
                    _headline_export_card(
                        f"Most Declined vs Baseline ({w_label})",
                        format_kpi_number(declined[xp_per_day_col], "XP/day"),
                        winner=winner_with_level(declined["Spieler"]),
                        detail=f"{int(round(float(declined[delta_col]))):+,} XP/day vs baseline",
                    )
                )

    if not dash_latest_xp_df.empty:
        latest_xp_date = pd.to_datetime(dash_latest_xp_df["Date"], errors="coerce").max()
        if pd.notna(latest_xp_date):
            days_ago = (pd.Timestamp.today().normalize() - latest_xp_date.normalize()).days
            metric_cards.append(
                _headline_export_card(
                    "Last XP Snapshot",
                    latest_xp_date.strftime("%Y-%m-%d"),
                    detail=f"{int(days_ago)} day(s) ago",
                )
            )
        else:
            metric_cards.append(_headline_export_card("Last XP Snapshot", "-", detail="no data"))
    else:
        metric_cards.append(_headline_export_card("Last XP Snapshot", "-", detail="no data"))
    metric_cards.append(
        _headline_export_card(
            f"Coverage ({w_label} / baseline)",
            f"{eligible_window}/{total_players}",
            detail=f"{eligible_baseline_window}/{total_players} | active {active_kpi_count}/{total_players}",
        )
    )

    ranking_view = pd.DataFrame()
    gain_view = pd.DataFrame()
    fig_growth = None
    fig_gain = None
    fig_xp_total = None
    fig_xp_gain_over_time = None
    fig_rank = None
    fig_gap = None
    fig_pace = None
    if not dash_latest_xp_df.empty:
        ranking_df = dash_latest_xp_df.sort_values("Total XP", ascending=False).reset_index(drop=True).copy()
        ranking_df["rank"] = range(1, len(ranking_df) + 1)
        leader_xp = float(ranking_df["Total XP"].iloc[0]) if not ranking_df.empty else 0.0
        ranking_df["gap_to_leader"] = leader_xp - ranking_df["Total XP"]
        if not metrics_window_df.empty:
            metric_cols = metrics_window_df[
                [
                    "Spieler",
                    xp_per_day_col,
                    delta_col,
                    pct_col,
                    eligible_col,
                    eligible_baseline_col,
                ]
            ].copy()
            ranking_df = ranking_df.merge(metric_cols, on="Spieler", how="left")
            ranking_df.loc[~ranking_df[eligible_col].fillna(False), xp_per_day_col] = pd.NA
            ranking_df.loc[~ranking_df[eligible_baseline_col].fillna(False), delta_col] = pd.NA
            ranking_df.loc[~ranking_df[eligible_baseline_col].fillna(False), pct_col] = pd.NA
        else:
            ranking_df[xp_per_day_col] = pd.NA
            ranking_df[delta_col] = pd.NA
            ranking_df[pct_col] = pd.NA

        ranking_view = ranking_df[
            [
                "rank",
                "Spieler",
                "Lvl",
                "Total XP",
                "gap_to_leader",
                xp_per_day_col,
                delta_col,
                pct_col,
            ]
        ].copy().rename(
            columns={
                "rank": "Rank",
                "gap_to_leader": "Gap to Leader",
                xp_per_day_col: f"XP/day ({w_label})",
                delta_col: f"Delta vs Baseline ({w_label})",
                pct_col: f"% vs Baseline ({w_label})",
            }
        )
        fig_growth = build_xp_growth_figure(curve_map, dash_latest_xp_df, export_account_color_map)

        if not dash_recent_gain_df.empty:
            gain_top = dash_recent_gain_df.sort_values("xp_gain", ascending=False).head(10).copy()
            fig_gain = px.bar(
                gain_top.sort_values("xp_gain", ascending=True),
                x="xp_gain",
                y="Spieler",
                orientation="h",
                color="Spieler",
                color_discrete_map=export_account_color_map,
                title=f"Top XP Gain ({w_label})",
                labels={"xp_gain": "XP Gain", "Spieler": "Account"},
            )
            gain_height = max(320, 34 * len(gain_top) + 80)
            fig_gain.update_layout(height=gain_height, margin=dict(l=150, r=30, t=45, b=35))
            fig_gain.update_layout(showlegend=False)
            fig_gain.update_xaxes(tickformat=",")
            fig_gain.update_yaxes(automargin=True, autorange="reversed")
            gain_view = gain_top[["Spieler", "xp_gain", "xp_per_day"]].copy().rename(
                columns={"xp_gain": "XP Gain", "xp_per_day": "XP/Day"}
            )

    xp_explorer_chart_dates: list[pd.Timestamp] = []
    xp_explorer_df = dash_xp_df[dash_xp_df["Spieler"].isin(explorer_accounts)].copy()
    if not xp_explorer_df.empty:
        xp_interval_df = restrict_to_common_interval(xp_explorer_df)
        if xp_interval_df.empty:
            xp_interval_df = xp_explorer_df.copy()
        min_ts = pd.to_datetime(xp_interval_df["Date"], errors="coerce").min()
        max_ts = pd.to_datetime(xp_explorer_df["Date"], errors="coerce").max()
        visible_start_ts = pd.Timestamp(min_ts) if pd.notna(min_ts) else None
        visible_end_ts = pd.Timestamp(max_ts) if pd.notna(max_ts) else None
        if (
            xp_explorer_date_range is not None
            and isinstance(xp_explorer_date_range, (tuple, list))
            and len(xp_explorer_date_range) == 2
            and visible_start_ts is not None
            and visible_end_ts is not None
        ):
            raw_start, raw_end = xp_explorer_date_range
            selected_start = pd.to_datetime(raw_start, errors="coerce")
            selected_end = pd.to_datetime(raw_end, errors="coerce")
            if pd.notna(selected_start) and pd.notna(selected_end):
                visible_start_ts = min(max(pd.Timestamp(selected_start), visible_start_ts), visible_end_ts)
                visible_end_ts = min(max(pd.Timestamp(selected_end), visible_start_ts), visible_end_ts)
                if visible_start_ts > visible_end_ts:
                    visible_start_ts = pd.Timestamp(min_ts)
                    visible_end_ts = pd.Timestamp(max_ts)
        chart_seed_df = xp_interval_df.copy()
        if visible_start_ts is not None and visible_end_ts is not None:
            chart_seed_df = chart_seed_df[
                (chart_seed_df["Date"] >= visible_start_ts)
                & (chart_seed_df["Date"] <= visible_end_ts)
            ].copy()
        xp_explorer_df = select_real_xp_chart_rows(xp_explorer_df, visible_start_ts, visible_end_ts)
        if xp_explorer_df.empty:
            xp_explorer_df = chart_seed_df.copy() if not chart_seed_df.empty else xp_interval_df.copy()
        xp_explorer_df = xp_explorer_df.sort_values(["Date", "Spieler"]).copy()
        xp_explorer_chart_dates = sorted(
            pd.Timestamp(dt)
            for dt in pd.to_datetime(xp_explorer_df["Date"], errors="coerce").dropna().unique().tolist()
        )

        gain_over_time_df = build_xp_gain_over_time_df(xp_explorer_df)
        fig_xp_gain_over_time = px.line(
            gain_over_time_df,
            x="Date",
            y="XP Gain",
            color="Spieler",
            color_discrete_map=explorer_color_map,
            markers=True,
            title="XP Gain Over Time",
        )

        fig_xp_total = px.line(
            xp_explorer_df,
            x="Date",
            y="Total XP",
            color="Spieler",
            color_discrete_map=explorer_color_map,
            markers=True,
            title="Total XP Over Time",
        )

        rank_df = build_rank_df(xp_explorer_df)
        if not rank_df.empty:
            fig_rank = go.Figure()
            for player, grp in rank_df.groupby("Spieler", sort=True):
                fig_rank.add_trace(
                    go.Scatter(
                        x=grp["Date"],
                        y=grp["Rank"],
                        mode="lines+markers",
                        line_shape="hv",
                        name=player,
                        line=dict(color=explorer_color_map.get(str(player))),
                        marker=dict(color=explorer_color_map.get(str(player))),
                    )
                )
            fig_rank.update_layout(title="Rank Over Time (Step)", legend_title="Player")
            fig_rank.update_yaxes(autorange="reversed", dtick=1)
            no_rank_changes = all(grp["Rank"].nunique() <= 1 for _, grp in rank_df.groupby("Spieler"))
            if no_rank_changes:
                fig_rank.add_annotation(
                    text="No rank changes in this time window",
                    xref="paper",
                    yref="paper",
                    x=0.5,
                    y=0.95,
                    showarrow=False,
                )

        export_gap_leader = str(selected_gap_leader).strip() if selected_gap_leader is not None else ""
        if export_gap_leader and export_gap_leader not in set(xp_explorer_df["Spieler"].astype(str).str.strip()):
            export_gap_leader = ""
        if not export_gap_leader:
            export_gap_leader = infer_default_gap_leader(xp_explorer_df) or ""
        gap_df = build_gap_change_df(xp_explorer_df, leader=export_gap_leader or None)
        if not gap_df.empty:
            fig_gap = px.line(
                gap_df,
                x="Date",
                y="Gap Change",
                color="Spieler",
                color_discrete_map=explorer_color_map,
                markers=True,
                title="Gap Change Since First Snapshot",
            )
            fig_gap.add_hline(
                y=0,
                line_dash="dash",
                annotation_text=gap_baseline_annotation_text(gap_df, leader=export_gap_leader or None),
                annotation_position="bottom right",
            )

        pace_df = build_pace_df(xp_explorer_df)
        if not pace_df.empty:
            fig_pace = px.line(
                pace_df,
                x="Date",
                y="XP/day",
                color="Spieler",
                color_discrete_map=explorer_color_map,
                markers=True,
                title="Interval Pace (XP/day)",
            )

    activity_chart_items: list[tuple[str, go.Figure | None]] = []
    activity_sections: list[tuple[str, pd.DataFrame]] = []
    if not show_medals:
        activity_accounts = [str(a).strip() for a in explorer_accounts if str(a).strip()]
        activity_color_map = explorer_color_map
        medal_source = dash_medal_df.copy()
        additional_source = dash_additional_df.copy()

        def _medal_series(medal_id: str, accounts: list[str]) -> pd.DataFrame:
            cols = ["date", "account", "value"]
            if medal_source.empty or not accounts:
                return pd.DataFrame(columns=cols)
            d = medal_source.copy()
            d["date"] = pd.to_datetime(d["date"], errors="coerce")
            d["account"] = d["account"].astype(str).str.strip()
            d["medal_id"] = d["medal_id"].astype(str).str.strip().str.lower().map(goal_medal_id_for)
            d["value"] = pd.to_numeric(d["value"], errors="coerce")
            d = d.dropna(subset=["date", "account", "medal_id", "value"]).copy()
            d = d[d["account"].isin(set(accounts))].copy()
            d = d[d["medal_id"] == goal_medal_id_for(medal_id)].copy()
            if d.empty:
                return pd.DataFrame(columns=cols)
            d = d.sort_values("date").groupby(["account", "date"], as_index=False).agg({"value": "max"})
            return d[cols].sort_values(["account", "date"]).reset_index(drop=True)

        def _series_to_metric_df(series_df: pd.DataFrame) -> pd.DataFrame:
            if series_df.empty:
                return pd.DataFrame(columns=["Date", "Spieler", "Total XP"])
            out = series_df.copy()
            out = out.rename(columns={"date": "Date", "account": "Spieler", "value": "Total XP"})
            out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
            out["Spieler"] = out["Spieler"].astype(str).str.strip()
            out["Total XP"] = pd.to_numeric(out["Total XP"], errors="coerce")
            out = out.dropna(subset=["Date", "Spieler", "Total XP"]).copy()
            out = out.sort_values(["Spieler", "Date"]).reset_index(drop=True)
            return out[["Date", "Spieler", "Total XP"]]

        def _fmt_total(value: object, unit: str, metric_label: str = "") -> str:
            num = pd.to_numeric(value, errors="coerce")
            if pd.isna(num):
                return "-"
            noun = str(metric_label).strip().lower()
            return f"{float(num):,.1f} km" if unit == "km" else f"{int(round(float(num))):,} {noun}"

        def _fmt_rate(value: object, unit: str, metric_label: str = "") -> str:
            num = pd.to_numeric(value, errors="coerce")
            if pd.isna(num):
                return "-"
            noun = str(metric_label).strip().lower()
            return f"{float(num):,.2f} km/day" if unit == "km" else f"{float(num):,.2f} {noun}/day"

        def _fmt_gain(value: object, unit: str, metric_label: str = "") -> str:
            num = pd.to_numeric(value, errors="coerce")
            if pd.isna(num):
                return "-"
            noun = str(metric_label).strip().lower()
            return f"{float(num):,.2f} km in {w_label}" if unit == "km" else f"{int(round(float(num))):,} {noun} in {w_label}"

        def _fmt_delta_rate(value: object, unit: str, metric_label: str = "") -> str:
            num = pd.to_numeric(value, errors="coerce")
            if pd.isna(num):
                return "-"
            n = float(num)
            sign = "+" if n >= 0 else "-"
            abs_n = abs(n)
            if unit == "km":
                return f"{sign}{abs_n:,.2f} km/day vs baseline"
            noun = str(metric_label).strip().lower()
            return f"{sign}{abs_n:,.2f} {noun}/day vs baseline"

        def _build_activity_snapshot_card(
            series_df: pd.DataFrame,
            title: str,
            unit_suffix: str,
            metric_label: str,
        ) -> tuple[str, str, str]:
            metric_df = _series_to_metric_df(series_df)
            if metric_df.empty:
                return (title, "-", f"no {w_label} data")
            kpis = compute_player_kpis_window(
                metric_df,
                window_days=w,
                baseline_min_windows=BASELINE_MIN_WINDOWS_DEFAULT,
            )
            if kpis.empty or eligible_col not in kpis.columns:
                return (title, "-", f"no {w_label} data")
            eligible_pool = kpis[kpis[eligible_col] == True].copy()  # noqa: E712
            if eligible_pool.empty:
                return (title, "-", f"no eligible {w_label} windows")
            eligible_pool[xp_per_day_col] = pd.to_numeric(eligible_pool[xp_per_day_col], errors="coerce")
            eligible_pool[xp_gain_col] = pd.to_numeric(eligible_pool[xp_gain_col], errors="coerce")
            eligible_pool = eligible_pool.dropna(subset=[xp_per_day_col, xp_gain_col]).copy()
            if eligible_pool.empty:
                return (title, "-", f"no eligible {w_label} windows")
            active_pool = eligible_pool[eligible_pool[xp_gain_col] > 0].copy()
            headline_pool = active_pool if not active_pool.empty else eligible_pool
            leader = headline_pool.sort_values([xp_per_day_col, xp_gain_col], ascending=[False, False]).iloc[0]
            avg_val = float(eligible_pool[xp_per_day_col].mean())
            end_date = pd.to_datetime(eligible_pool[window_end_col], errors="coerce").max()
            date_txt = end_date.strftime("%Y-%m-%d") if pd.notna(end_date) else "-"
            noun = str(metric_label).strip().lower()
            unit_part = f" {str(unit_suffix).strip()}" if str(unit_suffix).strip() else ""
            value_txt = (
                f"{float(leader[xp_per_day_col]):,.2f} {noun}/day"
                if noun and unit_suffix == ""
                else f"{float(leader[xp_per_day_col]):,.2f}{unit_part}/day"
            )
            context_txt = (
                f"{str(leader['Spieler']).strip()} | "
                + (
                    f"Team avg {avg_val:,.2f} {noun}/day | {w_label} window end: {date_txt}"
                    if noun and unit_suffix == ""
                    else f"Team avg {avg_val:,.2f}{unit_part}/day | {w_label} window end: {date_txt}"
                )
                + f" ({int(len(eligible_pool))} account(s))"
            )
            if active_pool.empty:
                context_txt += f" | no active {w_label} gains"
            return (title, value_txt, context_txt)

        def _activity_export_card(
            label: str,
            value: str,
            *,
            winner: object | None = None,
            winner_color: str | None = None,
            detail: str | None = None,
        ) -> dict[str, object]:
            return {
                "label": str(label),
                "value": str(value),
                "winner": "" if winner is None else str(winner),
                "winner_color": "" if winner_color is None else str(winner_color),
                "detail": "" if detail is None else str(detail),
            }

        def _build_activity_export_cards(series_df: pd.DataFrame, unit: str, metric_label: str) -> list[dict[str, object]]:
            metric_df = _series_to_metric_df(series_df)
            if metric_df.empty:
                return [
                    _activity_export_card("Leader", "-", detail="no data"),
                    _activity_export_card(f"Top Gain ({w_label})", "-", detail="no data"),
                    _activity_export_card(f"Least Gain ({w_label})", "-", detail="no data"),
                    _activity_export_card(f"Fastest {w_label} Pace", "-", detail="no data"),
                    _activity_export_card(f"Most Improved ({w_label})", "-", detail="no baseline data"),
                    _activity_export_card(f"Most Declined ({w_label})", "-", detail="no baseline data"),
                ]

            latest_metric = series_df.sort_values("date").groupby("account", as_index=False).tail(1).copy()
            latest_metric["value"] = pd.to_numeric(latest_metric["value"], errors="coerce")
            latest_metric["date"] = pd.to_datetime(latest_metric["date"], errors="coerce")
            latest_metric = latest_metric.dropna(subset=["value"]).copy()

            activity_kpis = compute_player_kpis_window(
                metric_df,
                window_days=w,
                baseline_min_windows=BASELINE_MIN_WINDOWS_DEFAULT,
            )
            eligible_pool = (
                activity_kpis[activity_kpis[eligible_col] == True].copy()  # noqa: E712
                if not activity_kpis.empty and eligible_col in activity_kpis.columns
                else pd.DataFrame()
            )
            active_pool = (
                eligible_pool[pd.to_numeric(eligible_pool[xp_gain_col], errors="coerce") > 0].copy()
                if not eligible_pool.empty
                else pd.DataFrame()
            )
            baseline_pool = (
                activity_kpis[activity_kpis[eligible_baseline_col] == True].copy()  # noqa: E712
                if not activity_kpis.empty and eligible_baseline_col in activity_kpis.columns
                else pd.DataFrame()
            )

            cards: list[dict[str, object]] = []
            if not latest_metric.empty:
                leader_row = latest_metric.sort_values("value", ascending=False).iloc[0]
                leader_date = pd.to_datetime(leader_row["date"], errors="coerce")
                leader_date_txt = leader_date.strftime("%Y-%m-%d") if pd.notna(leader_date) else "-"
                leader_name = str(leader_row["account"]).strip()
                cards.append(
                    _activity_export_card(
                        "Leader",
                        _fmt_total(leader_row["value"], unit, metric_label),
                        winner=leader_name,
                        winner_color=activity_color_map.get(leader_name),
                        detail=f"as of {leader_date_txt}",
                    )
                )
            else:
                cards.append(_activity_export_card("Leader", "-", detail="no data"))

            if not active_pool.empty:
                best = active_pool.sort_values([xp_per_day_col, xp_gain_col], ascending=[False, False]).iloc[0]
                top_gain = active_pool.sort_values([xp_gain_col, xp_per_day_col], ascending=[False, False]).iloc[0]
                least_gain = active_pool.sort_values([xp_gain_col, xp_per_day_col], ascending=[True, True]).iloc[0]
                top_name = str(top_gain["Spieler"]).strip()
                least_name = str(least_gain["Spieler"]).strip()
                best_name = str(best["Spieler"]).strip()
                cards.extend(
                    [
                        _activity_export_card(
                            f"Top Gain ({w_label})",
                            _fmt_gain(top_gain[xp_gain_col], unit, metric_label),
                            winner=top_name,
                            winner_color=activity_color_map.get(top_name),
                            detail=_fmt_rate(top_gain[xp_per_day_col], unit, metric_label),
                        ),
                        _activity_export_card(
                            f"Least Gain ({w_label})",
                            _fmt_gain(least_gain[xp_gain_col], unit, metric_label),
                            winner=least_name,
                            winner_color=activity_color_map.get(least_name),
                            detail=_fmt_rate(least_gain[xp_per_day_col], unit, metric_label),
                        ),
                        _activity_export_card(
                            f"Fastest {w_label} Pace",
                            _fmt_rate(best[xp_per_day_col], unit, metric_label),
                            winner=best_name,
                            winner_color=activity_color_map.get(best_name),
                            detail=_fmt_gain(best[xp_gain_col], unit, metric_label),
                        ),
                    ]
                )
            elif not eligible_pool.empty:
                no_active_ctx = f"all {xp_gain_col} = 0"
                cards.extend(
                    [
                        _activity_export_card(f"Top Gain ({w_label})", f"No active ({w_label})", detail=no_active_ctx),
                        _activity_export_card(f"Least Gain ({w_label})", f"No active ({w_label})", detail=no_active_ctx),
                        _activity_export_card(f"Fastest {w_label} Pace", f"No active ({w_label})", detail=no_active_ctx),
                    ]
                )
            else:
                cards.extend(
                    [
                        _activity_export_card(f"Top Gain ({w_label})", "-", detail="no data"),
                        _activity_export_card(f"Least Gain ({w_label})", "-", detail="no data"),
                        _activity_export_card(f"Fastest {w_label} Pace", "-", detail="no data"),
                    ]
                )

            if not baseline_pool.empty:
                improved_pool = baseline_pool[pd.to_numeric(baseline_pool[delta_col], errors="coerce") > 0].copy()
                declined_pool = baseline_pool[pd.to_numeric(baseline_pool[delta_col], errors="coerce") < 0].copy()
                if not improved_pool.empty:
                    improved = improved_pool.sort_values(delta_col, ascending=False).iloc[0]
                    improved_name = str(improved["Spieler"]).strip()
                    cards.append(
                        _activity_export_card(
                            f"Most Improved ({w_label})",
                            _fmt_rate(improved[xp_per_day_col], unit, metric_label),
                            winner=improved_name,
                            winner_color=activity_color_map.get(improved_name),
                            detail=_fmt_delta_rate(improved[delta_col], unit, metric_label),
                        )
                    )
                else:
                    cards.append(
                        _activity_export_card(
                            f"Most Improved ({w_label})",
                            "No improvements",
                            detail="all deltas <= 0",
                        )
                    )

                if not declined_pool.empty:
                    declined = declined_pool.sort_values(delta_col, ascending=True).iloc[0]
                    declined_name = str(declined["Spieler"]).strip()
                    cards.append(
                        _activity_export_card(
                            f"Most Declined ({w_label})",
                            _fmt_rate(declined[xp_per_day_col], unit, metric_label),
                            winner=declined_name,
                            winner_color=activity_color_map.get(declined_name),
                            detail=_fmt_delta_rate(declined[delta_col], unit, metric_label),
                        )
                    )
                else:
                    cards.append(
                        _activity_export_card(
                            f"Most Declined ({w_label})",
                            "No decline",
                            detail="all deltas >= 0",
                        )
                    )
            else:
                cards.extend(
                    [
                        _activity_export_card(f"Most Improved ({w_label})", "-", detail="no baseline data"),
                        _activity_export_card(f"Most Declined ({w_label})", "-", detail="no baseline data"),
                    ]
                )
            return cards

        def _build_activity_performance_view(series_df: pd.DataFrame, unit: str, metric_label: str) -> pd.DataFrame:
            metric_df = _series_to_metric_df(series_df)
            if metric_df.empty:
                return pd.DataFrame()
            latest_metric = series_df.sort_values("date").groupby("account", as_index=False).tail(1).copy()
            latest_metric["value"] = pd.to_numeric(latest_metric["value"], errors="coerce")
            latest_metric["date"] = pd.to_datetime(latest_metric["date"], errors="coerce")
            latest_metric = latest_metric.dropna(subset=["value"]).copy()
            activity_kpis = compute_player_kpis_window(
                metric_df,
                window_days=w,
                baseline_min_windows=BASELINE_MIN_WINDOWS_DEFAULT,
            )
            if activity_kpis.empty:
                merged = latest_metric.rename(columns={"account": "Spieler"})
            else:
                merged = latest_metric.rename(columns={"account": "Spieler"}).merge(
                    activity_kpis[
                        [
                            "Spieler",
                            window_end_col,
                            xp_gain_col,
                            xp_per_day_col,
                            delta_col,
                            eligible_col,
                            eligible_baseline_col,
                        ]
                    ],
                    on="Spieler",
                    how="left",
                )
            merged["_sort_total"] = pd.to_numeric(merged["value"], errors="coerce").fillna(-1)
            merged = merged.sort_values(["_sort_total", "Spieler"], ascending=[False, True]).copy()
            merged["Snapshot Date"] = pd.to_datetime(merged["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            merged["Window End"] = pd.to_datetime(
                merged.get(window_end_col, pd.Series(index=merged.index, dtype=object)),
                errors="coerce",
            ).dt.strftime("%Y-%m-%d")
            merged["Total"] = merged["value"].map(lambda v: _fmt_total(v, unit, metric_label))
            merged[f"Gain ({w_label})"] = merged.get(xp_gain_col, pd.Series(index=merged.index, dtype=object)).map(
                lambda v: _fmt_gain(v, unit, metric_label)
            )
            merged[f"Pace ({w_label})"] = merged.get(
                xp_per_day_col,
                pd.Series(index=merged.index, dtype=object),
            ).map(
                lambda v: _fmt_rate(v, unit, metric_label)
            )
            merged[f"Delta vs Baseline ({w_label})"] = merged.get(
                delta_col,
                pd.Series(index=merged.index, dtype=object),
            ).map(
                lambda v: _fmt_delta_rate(v, unit, metric_label)
            )
            merged["Eligible"] = merged.get(eligible_col, pd.Series(index=merged.index, dtype=object)).map(
                lambda v: "Yes" if bool(v) else "No"
            )
            merged["Baseline Eligible"] = merged.get(
                eligible_baseline_col,
                pd.Series(index=merged.index, dtype=object),
            ).map(
                lambda v: "Yes" if bool(v) else "No"
            )
            return merged[
                [
                    "Spieler",
                    "Snapshot Date",
                    "Total",
                    f"Gain ({w_label})",
                    f"Pace ({w_label})",
                    f"Delta vs Baseline ({w_label})",
                    "Window End",
                    "Eligible",
                    "Baseline Eligible",
                ]
            ].rename(columns={"Spieler": "Account"})

        visible_start = (
            pd.to_datetime(xp_explorer_df["Date"].min(), errors="coerce")
            if not xp_explorer_df.empty
            else pd.to_datetime(dash_xp_df["Date"].min(), errors="coerce")
        )
        visible_end = (
            pd.to_datetime(xp_explorer_df["Date"].max(), errors="coerce")
            if not xp_explorer_df.empty
            else pd.to_datetime(dash_xp_df["Date"].max(), errors="coerce")
        )

        def _clip_series_to_selected_range(series_df: pd.DataFrame) -> pd.DataFrame:
            if series_df.empty:
                return series_df.copy()
            d = series_df.copy()
            d["date"] = pd.to_datetime(d["date"], errors="coerce")
            d = d.dropna(subset=["date"]).copy()
            if pd.notna(visible_start):
                visible_start_ts = pd.Timestamp(visible_start)
            else:
                visible_start_ts = pd.Timestamp(d["date"].min())
            if pd.notna(visible_end):
                visible_end_ts = pd.Timestamp(visible_end)
            else:
                visible_end_ts = pd.Timestamp(d["date"].max())
            d = d[d["date"] <= visible_end_ts].copy()
            activity_start = _activity_mode_start_date(d, visible_start_ts, visible_end_ts)
            activity_dates = _activity_chart_dates(
                d,
                visible_start_ts,
                visible_end_ts,
                xp_explorer_chart_dates,
                start_date=activity_start,
            )
            return _carry_forward_chart_rows(d, activity_dates, ["value"])

        def _build_activity_gain_series(series_df: pd.DataFrame) -> pd.DataFrame:
            base = series_df.copy()
            base["date"] = pd.to_datetime(base["date"], errors="coerce")
            base = base.dropna(subset=["date"]).copy()
            if base.empty:
                return base
            if pd.notna(visible_end):
                base = base[base["date"] <= pd.Timestamp(visible_end)].copy()
            if base.empty:
                return base
            visible_start_ts = pd.Timestamp(visible_start) if pd.notna(visible_start) else pd.Timestamp(base["date"].min())
            visible_end_ts = pd.Timestamp(visible_end) if pd.notna(visible_end) else pd.Timestamp(base["date"].max())
            activity_start = _activity_mode_start_date(base, visible_start_ts, visible_end_ts)
            activity_dates = _activity_chart_dates(
                base,
                visible_start_ts,
                visible_end_ts,
                xp_explorer_chart_dates,
                start_date=activity_start,
            )
            if not activity_dates:
                return base.iloc[0:0].copy()
            accounts_with_anchor_baseline = set()
            if pd.notna(activity_start):
                accounts_with_anchor_baseline = set(
                    base[base["date"] <= activity_start]["account"].astype(str).str.strip().tolist()
                )
            gained = build_cumulative_gain_df(
                base,
                date_col="date",
                group_col="account",
                value_col="value",
                gain_col="gain_value",
                anchor_date=activity_start,
                include_anchor_row=True,
            )
            gained = gained[gained["date"] >= activity_start].copy()
            synthetic_anchor_mask = (
                (gained["date"] == activity_start)
                & ~gained["account"].astype(str).str.strip().isin(accounts_with_anchor_baseline)
            )
            gained = gained[~synthetic_anchor_mask].copy()
            return _carry_forward_chart_rows(gained, activity_dates, ["value", "gain_value"])

        battles_series = pd.DataFrame(columns=["date", "account", "value"])
        if not additional_source.empty and activity_accounts:
            d = additional_source.copy()
            d["date"] = pd.to_datetime(d["date"], errors="coerce")
            d["account"] = d["account"].astype(str).str.strip()
            d["battles_won"] = pd.to_numeric(d["battles_won"], errors="coerce")
            d = d.dropna(subset=["date", "account", "battles_won"]).copy()
            d = d[d["account"].isin(set(activity_accounts))].copy()
            if not d.empty:
                d = d.sort_values("date").drop_duplicates(["account", "date"], keep="last")
                battles_series = d.rename(columns={"battles_won": "value"})[["date", "account", "value"]]
                battles_series = battles_series.sort_values(["account", "date"]).reset_index(drop=True)
        caught_series = _medal_series("collector", activity_accounts)
        km_series = _medal_series("jogger", activity_accounts)

        battles_performance_view = _build_activity_performance_view(battles_series, "", "Battles")
        if not battles_performance_view.empty:
            activity_sections.append((f"Activity Performance: Battles ({w_label})", battles_performance_view))
        pokemon_performance_view = _build_activity_performance_view(caught_series, "", "Pokemon")
        if not pokemon_performance_view.empty:
            activity_sections.append((f"Activity Performance: Pokemon ({w_label})", pokemon_performance_view))
        km_performance_view = _build_activity_performance_view(km_series, "km", "Km")
        if not km_performance_view.empty:
            activity_sections.append((f"Activity Performance: Distance Walked ({w_label})", km_performance_view))

        battles_plot = _build_activity_gain_series(battles_series)
        if not battles_plot.empty:
            fig_battles = px.line(
                battles_plot,
                x="date",
                y="gain_value",
                color="account",
                color_discrete_map=activity_color_map,
                markers=True,
                title="Battles Gained Over Time",
            )
            fig_battles.update_yaxes(title="battles gained", tickformat=",.0f")
            activity_chart_items.append(("Activity: Battles Gained Over Time", fig_battles))

        caught_plot = _build_activity_gain_series(caught_series)
        if not caught_plot.empty:
            fig_caught = px.line(
                caught_plot,
                x="date",
                y="gain_value",
                color="account",
                color_discrete_map=activity_color_map,
                markers=True,
                title="Pokemon Gained Over Time",
            )
            fig_caught.update_yaxes(title="pokemon gained", tickformat=",.0f")
            activity_chart_items.append(("Activity: Pokemon Gained Over Time", fig_caught))

        km_plot = _build_activity_gain_series(km_series)
        if not km_plot.empty:
            fig_km = px.line(
                km_plot,
                x="date",
                y="gain_value",
                color="account",
                color_discrete_map=activity_color_map,
                markers=True,
                title="Distance Walked Gained Over Time",
            )
            fig_km.update_yaxes(title="km gained", tickformat=",.1f")
            activity_chart_items.append(("Activity: Distance Walked Gained Over Time", fig_km))

        battles_total_plot = _clip_series_to_selected_range(battles_series)
        if not battles_total_plot.empty:
            fig_battles_total = px.line(
                battles_total_plot,
                x="date",
                y="value",
                color="account",
                color_discrete_map=activity_color_map,
                markers=True,
                title="Battles Total Over Time",
            )
            fig_battles_total.update_yaxes(title="battles", tickformat=",.0f")
            activity_chart_items.append(("Activity: Battles Total Over Time", fig_battles_total))

        caught_total_plot = _clip_series_to_selected_range(caught_series)
        if not caught_total_plot.empty:
            fig_caught_total = px.line(
                caught_total_plot,
                x="date",
                y="value",
                color="account",
                color_discrete_map=activity_color_map,
                markers=True,
                title="Pokemon Total Over Time",
            )
            fig_caught_total.update_yaxes(title="pokemon", tickformat=",.0f")
            activity_chart_items.append(("Activity: Pokemon Total Over Time", fig_caught_total))

        km_total_plot = _clip_series_to_selected_range(km_series)
        if not km_total_plot.empty:
            fig_km_total = px.line(
                km_total_plot,
                x="date",
                y="value",
                color="account",
                color_discrete_map=activity_color_map,
                markers=True,
                title="Distance Walked Total Over Time",
            )
            fig_km_total.update_yaxes(title="km", tickformat=",.1f")
            activity_chart_items.append(("Activity: Distance Walked Total Over Time", fig_km_total))

        activity_ordered_blocks: list[dict[str, object]] = [
            {
                "type": "card_group",
                "title": f"Activity Summary: Battles ({w_label})",
                "cards": _build_activity_export_cards(battles_series, "", "Battles"),
            },
            {"type": "chart", "title": "Activity: Battles Gained Over Time", "figure": fig_battles if 'fig_battles' in locals() else None},
            {"type": "chart", "title": "Activity: Battles Total Over Time", "figure": fig_battles_total if 'fig_battles_total' in locals() else None},
            {
                "type": "card_group",
                "title": f"Activity Summary: Pokemon ({w_label})",
                "cards": _build_activity_export_cards(caught_series, "", "Pokemon"),
            },
            {"type": "chart", "title": "Activity: Pokemon Gained Over Time", "figure": fig_caught if 'fig_caught' in locals() else None},
            {"type": "chart", "title": "Activity: Pokemon Total Over Time", "figure": fig_caught_total if 'fig_caught_total' in locals() else None},
            {
                "type": "card_group",
                "title": f"Activity Summary: Distance Walked ({w_label})",
                "cards": _build_activity_export_cards(km_series, "km", "Km"),
            },
            {"type": "chart", "title": "Activity: Distance Walked Gained Over Time", "figure": fig_km if 'fig_km' in locals() else None},
            {"type": "chart", "title": "Activity: Distance Walked Total Over Time", "figure": fig_km_total if 'fig_km_total' in locals() else None},
        ]
    else:
        activity_ordered_blocks = []

    latest_medals_view = pd.DataFrame()
    first_achieved_view = pd.DataFrame()
    if show_medals:
        latest_medals_view, first_achieved_view = _build_medal_export_tables(dash_medal_df, dash_display_medal_df, goals_df)

    chart_items: list[tuple[str, go.Figure | None]] = [
        ("PoGo XP Growth", fig_growth),
        (f"XP Gain (Last {w} Days)", fig_gain),
        ("XP Explorer: XP Gain Over Time", fig_xp_gain_over_time),
        ("XP Explorer: Interval Pace (XP/day)", fig_pace),
        ("XP Explorer: Gap Change Since First Snapshot", fig_gap),
        ("XP Explorer: Rank Over Time (Step)", fig_rank),
        ("XP Explorer: Total XP Over Time", fig_xp_total),
    ]
    chart_items.extend(activity_chart_items)

    ordered_blocks: list[dict[str, object]] = [
        {"type": "chart", "title": "PoGo XP Growth", "figure": fig_growth},
        {"type": "chart", "title": f"XP Gain (Last {w} Days)", "figure": fig_gain},
        {"type": "chart", "title": "XP Explorer: XP Gain Over Time", "figure": fig_xp_gain_over_time},
        {"type": "chart", "title": "XP Explorer: Interval Pace (XP/day)", "figure": fig_pace},
        {"type": "chart", "title": "XP Explorer: Gap Change Since First Snapshot", "figure": fig_gap},
        {"type": "chart", "title": "XP Explorer: Rank Over Time (Step)", "figure": fig_rank},
        {"type": "chart", "title": "XP Explorer: Total XP Over Time", "figure": fig_xp_total},
    ]
    ordered_blocks.extend(activity_ordered_blocks)

    sections: list[tuple[str, pd.DataFrame]] = [
        ("Current XP Ranking", ranking_view),
        (f"XP Gain Table (Last {w} Days)", gain_view),
    ]
    sections.extend(activity_sections)
    if show_medals:
        sections.append(("Latest Medal Status", latest_medals_view))
        sections.append(("Latest Achieved Platinum Medals", first_achieved_view))

    accounts_text = ", ".join([str(a) for a in selected_accounts]) if selected_accounts else "-"
    generated_at = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "metric_cards": metric_cards,
        "ordered_blocks": ordered_blocks,
        "chart_items": chart_items,
        "sections": sections,
        "accounts_text": accounts_text,
        "generated_at": generated_at,
    }


def build_dashboard_export_html(
    dashboard_title: str,
    selected_group: str,
    selected_accounts: list[str],
    dash_xp_df: pd.DataFrame,
    dash_medal_df: pd.DataFrame,
    dash_additional_df: pd.DataFrame,
    dash_display_medal_df: pd.DataFrame,
    goals_df: pd.DataFrame,
    curve_map: dict[int, int],
    show_medals: bool,
    export_mode: str,
    window_days: int,
    selected_gap_leader: str | None = None,
    xp_explorer_date_range: tuple[date, date] | list[date] | None = None,
    xp_explorer_players: list[str] | tuple[str, ...] | None = None,
) -> str:
    def _build_payload_for_window(window_days_inner: int) -> dict[str, object]:
        return _build_dashboard_export_payload(
            selected_accounts=selected_accounts,
            dash_xp_df=dash_xp_df,
            dash_medal_df=dash_medal_df,
            dash_additional_df=dash_additional_df,
            dash_display_medal_df=dash_display_medal_df,
            goals_df=goals_df,
            curve_map=curve_map,
            show_medals=show_medals,
            window_days=int(window_days_inner),
            selected_gap_leader=selected_gap_leader,
            xp_explorer_date_range=xp_explorer_date_range,
            xp_explorer_players=xp_explorer_players,
        )

    return build_dashboard_export_html_impl(
        dashboard_title=dashboard_title,
        selected_group=selected_group,
        export_mode=export_mode,
        window_days=int(window_days),
        dashboard_window_options=DASHBOARD_WINDOW_OPTIONS,
        build_payload_for_window=_build_payload_for_window,
        sort_legend_by_latest_y=sort_legend_by_latest_y,
    )


def build_dashboard_export_png(
    dashboard_title: str,
    selected_group: str,
    selected_accounts: list[str],
    dash_xp_df: pd.DataFrame,
    dash_medal_df: pd.DataFrame,
    dash_additional_df: pd.DataFrame,
    dash_display_medal_df: pd.DataFrame,
    goals_df: pd.DataFrame,
    curve_map: dict[int, int],
    show_medals: bool,
    export_mode: str,
    window_days: int,
    selected_gap_leader: str | None = None,
    xp_explorer_date_range: tuple[date, date] | list[date] | None = None,
    xp_explorer_players: list[str] | tuple[str, ...] | None = None,
) -> tuple[bytes | None, str | None]:
    def _build_payload_for_window(window_days_inner: int) -> dict[str, object]:
        return _build_dashboard_export_payload(
            selected_accounts=selected_accounts,
            dash_xp_df=dash_xp_df,
            dash_medal_df=dash_medal_df,
            dash_additional_df=dash_additional_df,
            dash_display_medal_df=dash_display_medal_df,
            goals_df=goals_df,
            curve_map=curve_map,
            show_medals=show_medals,
            window_days=int(window_days_inner),
            selected_gap_leader=selected_gap_leader,
            xp_explorer_date_range=xp_explorer_date_range,
            xp_explorer_players=xp_explorer_players,
        )

    return build_dashboard_export_png_impl(
        dashboard_title=dashboard_title,
        selected_group=selected_group,
        export_mode=export_mode,
        window_days=int(window_days),
        build_payload_for_window=_build_payload_for_window,
        sort_legend_by_latest_y=sort_legend_by_latest_y,
    )


def render_dashboard_export_button(
    dashboard_title: str,
    selected_group: str,
    selected_accounts: list[str],
    dash_xp_df: pd.DataFrame,
    dash_medal_df: pd.DataFrame,
    dash_additional_df: pd.DataFrame,
    dash_display_medal_df: pd.DataFrame,
    goals_df: pd.DataFrame,
    curve_map: dict[int, int],
    show_medals: bool,
    window_days: int,
    key: str,
    selected_gap_leader: str | None = None,
    xp_explorer_date_range: tuple[date, date] | list[date] | None = None,
    xp_explorer_players: list[str] | tuple[str, ...] | None = None,
) -> None:
    mode_options = ["Dark", "Light", "WhatsApp", "Smartphone"]
    mode_col, fmt_col, action_col = st.columns([1.2, 1.3, 1.2])
    with mode_col:
        st.caption("Mode")
        mode_label = st.selectbox(
            "Export Mode",
            options=mode_options,
            index=0,
            key=f"{key}_mode",
            label_visibility="collapsed",
        )
    export_mode = str(mode_label).strip().lower()
    with fmt_col:
        st.caption("Format")
        export_format = st.selectbox(
            "Export Format",
            options=["HTML", "Picture (PNG)"],
            index=0,
            key=f"{key}_format",
            label_visibility="collapsed",
        )
    stamp = pd.Timestamp.now().strftime("%Y-%m-%d")
    base_name = (
        f"{stamp}_{_slugify(selected_group)}_{_slugify(dashboard_title)}_{_slugify(export_mode)}"
    )

    if export_format == "Picture (PNG)":
        png_bytes, png_err = build_dashboard_export_png(
            dashboard_title=dashboard_title,
            selected_group=selected_group,
            selected_accounts=selected_accounts,
            dash_xp_df=dash_xp_df,
            dash_medal_df=dash_medal_df,
            dash_additional_df=dash_additional_df,
            dash_display_medal_df=dash_display_medal_df,
            goals_df=goals_df,
            curve_map=curve_map,
            show_medals=show_medals,
            export_mode=export_mode,
            window_days=window_days,
            selected_gap_leader=selected_gap_leader,
            xp_explorer_date_range=xp_explorer_date_range,
            xp_explorer_players=xp_explorer_players,
        )
        if png_err:
            st.warning(png_err)
        with action_col:
            st.caption("Export")
            st.download_button(
                "PNG",
                data=png_bytes or b"",
                file_name=f"{base_name}_picture.png",
                mime="image/png",
                disabled=png_bytes is None,
                key=f"{key}_png",
            )
        return

    html = build_dashboard_export_html(
        dashboard_title=dashboard_title,
        selected_group=selected_group,
        selected_accounts=selected_accounts,
        dash_xp_df=dash_xp_df,
        dash_medal_df=dash_medal_df,
        dash_additional_df=dash_additional_df,
        dash_display_medal_df=dash_display_medal_df,
        goals_df=goals_df,
        curve_map=curve_map,
        show_medals=show_medals,
        export_mode=export_mode,
        window_days=window_days,
        selected_gap_leader=selected_gap_leader,
        xp_explorer_date_range=xp_explorer_date_range,
        xp_explorer_players=xp_explorer_players,
    )
    with action_col:
        st.caption("Export")
        st.download_button(
            "HTML",
            data=html.encode("utf-8"),
            file_name=f"{base_name}.html",
            mime="text/html",
            key=f"{key}_html",
        )


def render_dashboard_content(
    dash_xp_df: pd.DataFrame,
    dash_medal_df: pd.DataFrame,
    dash_additional_df: pd.DataFrame,
    dash_display_medal_df: pd.DataFrame,
    goals_df: pd.DataFrame,
    curve_map: dict[int, int],
    show_medals: bool,
    window_days: int,
    window_state_key: str,
    show_30d_limited_hint: bool,
) -> None:
    dashboard_accounts = sorted(dash_xp_df["Spieler"].dropna().astype(str).str.strip().unique().tolist()) if not dash_xp_df.empty else []
    account_color_map = build_account_color_map(dashboard_accounts, dash_xp_df)
    render_dashboard_content_view(
        dash_xp_df=dash_xp_df,
        dash_medal_df=dash_medal_df,
        dash_additional_df=dash_additional_df,
        dash_display_medal_df=dash_display_medal_df,
        goals_df=goals_df,
        curve_map=curve_map,
        show_medals=show_medals,
        window_days=window_days,
        window_state_key=window_state_key,
        show_30d_limited_hint=show_30d_limited_hint,
        account_color_map=account_color_map,
        account_order=ACCOUNT_ORDER,
        derived_medal_id=DERIVED_MEDAL_ID,
        baseline_min_windows_default=BASELINE_MIN_WINDOWS_DEFAULT,
        window_col_fn=window_col,
        latest_xp_snapshot_fn=latest_xp_snapshot,
        render_kpi_card_fn=render_kpi_card,
        format_kpi_number_fn=format_kpi_number,
        build_xp_growth_figure_fn=build_xp_growth_figure,
        account_cell_style_fn=account_cell_style,
        render_account_color_legend_fn=render_account_color_legend,
        apply_account_colors_fn=apply_account_colors,
        render_plotly_chart_fn=render_plotly_chart,
    )


st.set_page_config(page_title="PoGo Local Dashboard", layout="wide")
inject_responsive_styles()
st.title("PoGo Local Dashboard")
st.caption("Interactive XP + medal dashboard.")

curve_map = load_curve_map(total_xp_curve_path())
xp_input_df = load_xp_history(xp_history_path(), curve_map)
xp_df = carry_forward_max_level_rows(xp_input_df, curve_map)
additional_activity_df = load_additional_activity(additional_activity_path())
groups = parse_groups(player_groups_path())
medal_df = load_medal_snapshots(
    medal_snapshots_path(),
    account_order=ACCOUNT_ORDER,
    excluded_manual_medal_ids=EXCLUDED_MANUAL_MEDAL_IDS,
)
goals_df = load_medal_goals(medals_config_path())
medal_explanations_map = medal_explanation_map_from_goals(goals_df)
display_medal_df = with_derived_platinum_rows(medal_df, goals_df)
pokedex_df = load_pokedex_entry_snapshots(
    pokedex_entry_snapshots_path(),
    account_order=ACCOUNT_ORDER,
    valid_entry_types=set(POKEDEX_ENTRY_TYPES),
    valid_regions=set(POKEDEX_REGIONS),
)
pokedex_entry_config_df = load_pokedex_entry_config(
    pokedex_entry_config_path(),
    valid_entry_types=set(POKEDEX_ENTRY_TYPES),
    valid_regions=set(POKEDEX_REGIONS),
)
pokedex_entry_config = pokedex_entry_config_map(pokedex_entry_config_df)
display_pokedex_df = with_medal_derived_pokedex_rows(pokedex_df, medal_df)
pokemon_catalog_df = load_pokemon_catalog(pokemon_catalog_path())
all_accounts = account_options_from_data(xp_input_df, medal_df, display_pokedex_df)
data_input_accounts_df = load_data_input_accounts(data_input_accounts_path(), valid_input_types=DATA_INPUT_TYPES)
xp_input_accounts = accounts_for_data_input("xp", all_accounts, data_input_accounts_df, fallback_accounts=all_accounts)
medal_input_accounts = accounts_for_data_input(
    "medal",
    all_accounts,
    data_input_accounts_df,
    fallback_accounts=MEDAL_INPUT_CORE_ACCOUNTS,
)
pokedex_input_accounts = accounts_for_data_input(
    "pokedex",
    all_accounts,
    data_input_accounts_df,
    fallback_accounts=all_accounts,
)
latest_xp_df = latest_xp_snapshot(xp_input_df)

pages = [
    "Dashboard Global",
    "Dashboard Personal",
    "Medal Explorer",
    "Data Input",
    "Last Inputs",
    "Pipelines",
    "Generated Files",
]
all_dashboard_accounts = sorted(
    set(xp_df["Spieler"].dropna().astype(str).tolist()) | set(display_medal_df["account"].dropna().astype(str).tolist())
)
personal_group_names = {g for g in groups.keys() if str(g).strip().lower() in {"ich", "ownaccounts"}}
global_dashboard_group_options = ["All"] + [g for g in groups.keys() if g and g != "All" and g not in personal_group_names]
personal_groups_by_key = {str(g).strip().lower(): g for g in groups.keys() if str(g).strip().lower() in {"ich", "ownaccounts"}}
personal_dashboard_group_options = [personal_groups_by_key[k] for k in ["ownaccounts", "ich"] if k in personal_groups_by_key]

with st.container(key="pogo_controls_bar"):
    page_col, group_col, window_ctrl_col = st.columns([3.4, 2.8, 1.0], gap="small")
    with page_col:
        page = st.radio("Page", pages, horizontal=True)
    with group_col:
        group_slot = st.empty()
    with window_ctrl_col:
        window_slot = st.empty()

if page == "Dashboard Global":
    with group_slot.container():
        selected_dashboard_group = st.radio(
            "Global Group",
            global_dashboard_group_options,
            index=0,
            horizontal=True,
            key="dashboard_global_group",
        )
    dashboard_accounts = accounts_for_selected_group(selected_dashboard_group, groups, all_dashboard_accounts)
    if not dashboard_accounts:
        with window_slot.container():
            st.caption("Window")
            st.caption("-")
        st.subheader("Dashboard Global")
        st.info("No accounts found for the selected global group.")
    else:
        dash_xp_df = xp_df[xp_df["Spieler"].isin(dashboard_accounts)].copy()
        dash_medal_df = medal_df[medal_df["account"].isin(dashboard_accounts)].copy()
        dash_additional_df = additional_activity_df[additional_activity_df["account"].isin(dashboard_accounts)].copy()
        dash_display_medal_df = display_medal_df[display_medal_df["account"].isin(dashboard_accounts)].copy()
        metrics_by_window = compute_metrics_by_window(dash_xp_df, window_options=DASHBOARD_WINDOW_OPTIONS)
        default_window_days = auto_default_window_days(metrics_by_window)
        saved_window_days = load_saved_dashboard_window_days(default_window_days)
        window_key = "dashboard_window_days"
        if window_key not in st.session_state:
            st.session_state[window_key] = int(saved_window_days)
        else:
            st.session_state[window_key] = normalize_dashboard_window_days(
                st.session_state.get(window_key),
                fallback=saved_window_days,
            )
        eligible_30d_count = count_window_eligible(metrics_by_window.get(30, pd.DataFrame()), 30, baseline=False)
        show_30d_limited_hint = eligible_30d_count < MIN_ELIGIBLE_FOR_30D_DEFAULT
        with window_slot.container():
            st.caption("Window")
            st.segmented_control(
                "Window",
                options=[7, 30],
                key=window_key,
                format_func=lambda x: f"{int(x)}d",
                label_visibility="collapsed",
            )
            if show_30d_limited_hint:
                st.caption("30d limited")
        selected_window_days = normalize_dashboard_window_days(
            st.session_state.get(window_key),
            fallback=saved_window_days,
        )
        save_dashboard_window_days(selected_window_days)
        header_left, header_right = st.columns([4.0, 1.65], gap="small")
        with header_left:
            st.subheader("Dashboard Global")
        with header_right:
            export_slot = st.empty()
        render_dashboard_content(
            dash_xp_df=dash_xp_df,
            dash_medal_df=dash_medal_df,
            dash_additional_df=dash_additional_df,
            dash_display_medal_df=dash_display_medal_df,
            goals_df=goals_df,
            curve_map=curve_map,
            show_medals=False,
            window_days=selected_window_days,
            window_state_key=window_key,
            show_30d_limited_hint=show_30d_limited_hint,
        )
        st.divider()
        render_xp_explorer_section(
            dash_xp_df,
            key_prefix="dashboard_global_xp_explorer",
            medal_subset_df=dash_medal_df,
            show_personal_activity=False,
            additional_subset_df=dash_additional_df,
            show_global_activity_trends=True,
            activity_window_days=selected_window_days,
            leader_preference_key=f"global:{selected_dashboard_group}",
        )
        with export_slot.container():
            with st.container(key="pogo_export_header_global"):
                render_dashboard_export_button(
                    dashboard_title="Dashboard Global",
                    selected_group=selected_dashboard_group,
                    selected_accounts=dashboard_accounts,
                    dash_xp_df=dash_xp_df,
                    dash_medal_df=dash_medal_df,
                    dash_additional_df=dash_additional_df,
                    dash_display_medal_df=dash_display_medal_df,
                    goals_df=goals_df,
                    curve_map=curve_map,
                    show_medals=False,
                    window_days=selected_window_days,
                    key="export_dashboard_global",
                    selected_gap_leader=st.session_state.get("dashboard_global_xp_explorer_gap_leader"),
                    xp_explorer_date_range=st.session_state.get("dashboard_global_xp_explorer_date_range"),
                    xp_explorer_players=st.session_state.get("dashboard_global_xp_explorer_players"),
                )

if page == "Dashboard Personal":
    if not personal_dashboard_group_options:
        with group_slot.container():
            st.caption("Personal Group")
            st.caption("No groups configured")
        with window_slot.container():
            st.caption("Window")
            st.caption("-")
        st.subheader("Dashboard Personal")
        st.info("No personal groups found. Add `Ich:` and/or `OwnAccounts:` to `inputs/config/player_groups.csv`.")
        st.stop()

    with group_slot.container():
        selected_dashboard_group = st.radio(
            "Personal Group",
            personal_dashboard_group_options,
            index=0,
            horizontal=True,
            key="dashboard_personal_group",
        )
    dashboard_accounts = accounts_for_selected_group(selected_dashboard_group, groups, all_dashboard_accounts)
    if not dashboard_accounts:
        with window_slot.container():
            st.caption("Window")
            st.caption("-")
        st.subheader("Dashboard Personal")
        st.info("No accounts found for the selected personal group.")
    else:
        dash_xp_df = xp_df[xp_df["Spieler"].isin(dashboard_accounts)].copy()
        dash_medal_df = medal_df[medal_df["account"].isin(dashboard_accounts)].copy()
        dash_additional_df = additional_activity_df[additional_activity_df["account"].isin(dashboard_accounts)].copy()
        dash_display_medal_df = display_medal_df[display_medal_df["account"].isin(dashboard_accounts)].copy()
        metrics_by_window = compute_metrics_by_window(dash_xp_df, window_options=DASHBOARD_WINDOW_OPTIONS)
        default_window_days = auto_default_window_days(metrics_by_window)
        saved_window_days = load_saved_dashboard_window_days(default_window_days)
        window_key = "dashboard_window_days"
        if window_key not in st.session_state:
            st.session_state[window_key] = int(saved_window_days)
        else:
            st.session_state[window_key] = normalize_dashboard_window_days(
                st.session_state.get(window_key),
                fallback=saved_window_days,
            )
        eligible_30d_count = count_window_eligible(metrics_by_window.get(30, pd.DataFrame()), 30, baseline=False)
        show_30d_limited_hint = eligible_30d_count < MIN_ELIGIBLE_FOR_30D_DEFAULT
        with window_slot.container():
            st.caption("Window")
            st.segmented_control(
                "Window",
                options=[7, 30],
                key=window_key,
                format_func=lambda x: f"{int(x)}d",
                label_visibility="collapsed",
            )
            if show_30d_limited_hint:
                st.caption("30d limited")
        selected_window_days = normalize_dashboard_window_days(
            st.session_state.get(window_key),
            fallback=saved_window_days,
        )
        save_dashboard_window_days(selected_window_days)
        header_left, header_right = st.columns([4.0, 1.65], gap="small")
        with header_left:
            st.subheader("Dashboard Personal")
        with header_right:
            export_slot = st.empty()
        render_dashboard_content(
            dash_xp_df=dash_xp_df,
            dash_medal_df=dash_medal_df,
            dash_additional_df=dash_additional_df,
            dash_display_medal_df=dash_display_medal_df,
            goals_df=goals_df,
            curve_map=curve_map,
            show_medals=True,
            window_days=selected_window_days,
            window_state_key=window_key,
            show_30d_limited_hint=show_30d_limited_hint,
        )
        st.divider()
        render_xp_explorer_section(
            dash_xp_df,
            key_prefix="dashboard_personal_xp_explorer",
            medal_subset_df=dash_medal_df,
            show_personal_activity=True,
            additional_subset_df=dash_additional_df,
            show_global_activity_trends=False,
            activity_window_days=selected_window_days,
            leader_preference_key=f"personal:{selected_dashboard_group}",
        )
        with export_slot.container():
            with st.container(key="pogo_export_header_personal"):
                render_dashboard_export_button(
                    dashboard_title="Dashboard Personal",
                    selected_group=selected_dashboard_group,
                    selected_accounts=dashboard_accounts,
                    dash_xp_df=dash_xp_df,
                    dash_medal_df=dash_medal_df,
                    dash_additional_df=dash_additional_df,
                    dash_display_medal_df=dash_display_medal_df,
                    goals_df=goals_df,
                    curve_map=curve_map,
                    show_medals=True,
                    window_days=selected_window_days,
                    key="export_dashboard_personal",
                    selected_gap_leader=st.session_state.get("dashboard_personal_xp_explorer_gap_leader"),
                    xp_explorer_date_range=st.session_state.get("dashboard_personal_xp_explorer_date_range"),
                    xp_explorer_players=st.session_state.get("dashboard_personal_xp_explorer_players"),
                )
if page not in {"Dashboard Global", "Dashboard Personal"}:
    with group_slot.container():
        st.caption("Group")
        st.caption("-")
    with window_slot.container():
        st.caption("Window")
        st.caption("-")

if page == "Medal Explorer":
    header_left, header_right = st.columns([3.6, 1.4])
    with header_left:
        st.subheader("Medal Explorer")
    with header_right:
        latest_medal_date = pd.to_datetime(medal_df.get("date"), errors="coerce").max() if not medal_df.empty else pd.NaT
        if pd.notna(latest_medal_date):
            medal_days_ago = (pd.Timestamp.today().normalize() - latest_medal_date.normalize()).days
            st.metric(
                "Last Medal Snapshot",
                latest_medal_date.strftime("%Y-%m-%d"),
                delta=f"{int(medal_days_ago)} day(s) ago",
                help="Latest snapshot date in `inputs/data/medal_snapshots.csv`.",
            )
        else:
            st.metric("Last Medal Snapshot", "-", delta="no data")
    if display_medal_df.empty:
        st.warning("No medal snapshot data found.")
    else:
        default_medal_accounts = [a for a in MEDAL_EXPLORER_CORE_ACCOUNTS if a in set(all_accounts)]
        if not default_medal_accounts:
            default_medal_accounts = all_accounts[:3] or all_accounts
        selected_accounts = st.multiselect("Accounts", all_accounts, default=default_medal_accounts)
        medal_account_color_map = build_account_color_map(
            selected_accounts,
            xp_df[xp_df["Spieler"].isin(selected_accounts)].copy(),
        )
        selected_medal_source_df = medal_df[medal_df["account"].isin(selected_accounts)].copy()
        tracking_start_by_account = infer_medal_tracking_start_dates(
            selected_medal_source_df,
            min_medal_rows=MIN_MEDAL_ROWS_FOR_TRACKING_START,
        )
        df = display_medal_df[display_medal_df["account"].isin(selected_accounts)].copy()
        if df.empty:
            st.warning("No rows for selected accounts.")
        else:
            min_date = df["date"].min().date()
            max_date = df["date"].max().date()
            d_start, d_end = select_date_range(
                label="Date range",
                min_date=min_date,
                max_date=max_date,
                key="medal_overview_date_range",
            )
            df = df[(df["date"] >= pd.Timestamp(d_start)) & (df["date"] <= pd.Timestamp(d_end))].copy()
            medal_status_medal_df = selected_medal_source_df[
                (selected_medal_source_df["date"] >= pd.Timestamp(d_start))
                & (selected_medal_source_df["date"] <= pd.Timestamp(d_end))
            ].copy()
            medal_status_display_df = df.copy()

            goals_map: dict[str, float] = {}
            display_map: dict[str, str] = {}
            if not goals_df.empty:
                goals_for_plot = goals_df.copy()
                goals_for_plot["medal_id"] = goals_for_plot["medal_id"].astype(str).str.strip().str.lower()
                goals_for_plot["goal_value"] = pd.to_numeric(goals_for_plot["goal_value"], errors="coerce")
                goals_for_plot = goals_for_plot.dropna(subset=["medal_id", "goal_value"]).copy()
                goals_map = dict(
                    zip(
                        goals_for_plot["medal_id"].astype(str).tolist(),
                        goals_for_plot["goal_value"].astype(float).tolist(),
                    )
                )
                display_map = dict(
                    zip(
                        goals_for_plot["medal_id"].astype(str).tolist(),
                        goals_for_plot["display_name"].astype(str).tolist(),
                    )
                )

            filter_mode_options = [MEDAL_FILTER_SHOW_ALL, MEDAL_FILTER_NOT_COMPLETED, MEDAL_FILTER_COMPLETED]
            sort_metric_options = [MEDAL_SORT_COMPLETION, MEDAL_SORT_TIME, MEDAL_SORT_INPUT]
            sort_direction_options = [MEDAL_SORT_ASC, MEDAL_SORT_DESC]
            sort_account_options = [a for a in MEDAL_EXPLORER_CORE_ACCOUNTS if a in set(selected_accounts)]
            if not sort_account_options:
                sort_account_options = [str(a).strip() for a in selected_accounts if str(a).strip()]

            if "show_medal_goal_trends" not in st.session_state:
                st.session_state["show_medal_goal_trends"] = True
            if "medal_filter_mode" not in st.session_state:
                st.session_state["medal_filter_mode"] = MEDAL_FILTER_SHOW_ALL
            if "medal_sort_metric" not in st.session_state:
                st.session_state["medal_sort_metric"] = MEDAL_SORT_INPUT
            if "medal_sort_direction" not in st.session_state:
                st.session_state["medal_sort_direction"] = MEDAL_SORT_DEFAULT_DIRECTION_BY_METRIC.get(
                    str(st.session_state.get("medal_sort_metric", MEDAL_SORT_INPUT)),
                    MEDAL_SORT_ASC,
                )
            if "medal_sort_account" not in st.session_state:
                st.session_state["medal_sort_account"] = sort_account_options[0] if sort_account_options else ""

            if str(st.session_state.get("medal_filter_mode")) not in filter_mode_options:
                st.session_state["medal_filter_mode"] = MEDAL_FILTER_SHOW_ALL
            if str(st.session_state.get("medal_sort_metric")) not in sort_metric_options:
                st.session_state["medal_sort_metric"] = MEDAL_SORT_INPUT
            if str(st.session_state.get("medal_sort_direction")) not in sort_direction_options:
                st.session_state["medal_sort_direction"] = MEDAL_SORT_ASC

            current_sort_metric = str(st.session_state.get("medal_sort_metric", MEDAL_SORT_INPUT))
            previous_sort_metric = str(st.session_state.get("medal_sort_metric_prev", current_sort_metric))
            if current_sort_metric != previous_sort_metric:
                st.session_state["medal_sort_direction"] = MEDAL_SORT_DEFAULT_DIRECTION_BY_METRIC.get(
                    current_sort_metric,
                    MEDAL_SORT_ASC,
                )
            st.session_state["medal_sort_metric_prev"] = current_sort_metric

            saved_sort_account = str(st.session_state.get("medal_sort_account", "")).strip()
            if saved_sort_account not in set(sort_account_options):
                saved_sort_account = sort_account_options[0] if sort_account_options else ""
            st.session_state["medal_sort_account"] = saved_sort_account

            show_goal_trends = bool(st.session_state.get("show_medal_goal_trends", False))
            medal_filter_mode = str(st.session_state.get("medal_filter_mode", MEDAL_FILTER_SHOW_ALL))
            medal_sort_metric = str(st.session_state.get("medal_sort_metric", MEDAL_SORT_INPUT))
            medal_sort_direction = str(st.session_state.get("medal_sort_direction", MEDAL_SORT_ASC))
            medal_sort_account = str(st.session_state.get("medal_sort_account", "")).strip()

            def add_goal_and_trends(
                fig_medal: go.Figure,
                line_df: pd.DataFrame,
                medal_id: str,
                status_mode: str = "in_chart",
            ) -> str | None:
                goal_lookup_id = goal_medal_id_for(medal_id)
                goal_val = goals_map.get(goal_lookup_id)
                if goal_val is None or pd.isna(goal_val):
                    return None
                goal_val_f = float(goal_val)

                add_light_goal_reference(fig_medal, goal_val_f, f"Goal: {goal_val:g}")
                y_max_data = pd.to_numeric(line_df.get("value"), errors="coerce").max()
                if pd.notna(y_max_data):
                    y_top = max(float(y_max_data), goal_val_f)
                    if y_top <= 0:
                        y_top = 1.0
                    fig_medal.update_yaxes(range=[0, y_top * 1.05])
                status_html = build_goal_days_status_html(
                    line_df,
                    account_col="account",
                    date_col="date",
                    value_col="value",
                    goal_value=goal_val_f,
                )
                if not show_goal_trends:
                    if status_mode == "in_chart":
                        account_count = int(line_df["account"].dropna().astype(str).nunique())
                        status_y = max(0.22, min(0.84, 1.0 - 0.06 * max(1, account_count)))
                        add_goal_days_status_annotation(
                            fig_medal,
                            line_df,
                            account_col="account",
                            date_col="date",
                            value_col="value",
                            goal_value=goal_val_f,
                            y_top=status_y,
                        )
                    return status_html
                color_by_account: dict[str, str | None] = {}
                for tr in fig_medal.data:
                    name = str(getattr(tr, "name", ""))
                    color = getattr(getattr(tr, "line", None), "color", None)
                    color_by_account[name] = color
                for acc, grp in line_df.groupby("account", sort=True):
                    if medal_id == DERIVED_MEDAL_ID:
                        trend_trace = build_platinum_goal_projection_trace(
                            df,
                            str(acc),
                            goals_map,
                            float(goal_val),
                            color_by_account.get(str(acc)),
                        )
                    else:
                        trend_trace = build_goal_projection_trace(
                            grp[["date", "value"]],
                            float(goal_val),
                            str(acc),
                            color_by_account.get(str(acc)),
                        )
                    if trend_trace is not None:
                        fig_medal.add_trace(trend_trace)
                if status_mode == "in_chart":
                    account_count = int(line_df["account"].dropna().astype(str).nunique())
                    status_y = max(0.22, min(0.84, 1.0 - 0.06 * max(1, account_count)))
                    add_goal_days_status_annotation(
                        fig_medal,
                        line_df,
                        account_col="account",
                        date_col="date",
                        value_col="value",
                        goal_value=goal_val_f,
                        y_top=status_y,
                    )
                return status_html

            medal_ids_available = set(df["medal_id"].astype(str).tolist())

            # Full-width platinum chart on top.
            if DERIVED_MEDAL_ID in medal_ids_available:
                platinum_df = df[df["medal_id"] == DERIVED_MEDAL_ID].copy()
                if not platinum_df.empty:
                    platinum_df["tracking_start"] = platinum_df["account"].map(tracking_start_by_account)
                    platinum_df = platinum_df[
                        platinum_df["tracking_start"].isna() | (platinum_df["date"] >= platinum_df["tracking_start"])
                    ].copy()
                if not platinum_df.empty:
                    platinum_title = display_map.get(DERIVED_MEDAL_ID, "Platinum Medals")
                    fig_platinum = px.line(
                        platinum_df,
                        x="date",
                        y="value",
                        color="account",
                        color_discrete_map=medal_account_color_map,
                        markers=True,
                        title=f"Progress: {platinum_title}",
                    )
                    add_goal_and_trends(fig_platinum, platinum_df, DERIVED_MEDAL_ID, status_mode="in_chart")
                    apply_account_colors(fig_platinum, medal_account_color_map)
                    fig_platinum.update_layout(height=520)
                    render_plotly_chart(fig_platinum, use_container_width=True)
                    st.caption(
                        "Platinum graph starts at medal tracking start per account "
                        f"(first date with >= {MIN_MEDAL_ROWS_FOR_TRACKING_START} medal rows)."
                    )

            xp_line_df = xp_df[xp_df["Spieler"].isin(selected_accounts)].copy()
            xp_line_df = xp_line_df[
                (xp_line_df["Date"] >= pd.Timestamp(d_start)) & (xp_line_df["Date"] <= pd.Timestamp(d_end))
            ].copy()
            if not xp_line_df.empty:
                xp_goal_value: float | None = None
                fig_xp = px.line(
                    xp_line_df,
                    x="Date",
                    y="Total XP",
                    color="Spieler",
                    color_discrete_map=medal_account_color_map,
                    markers=True,
                    title="Progress: XP",
                )
                if curve_map:
                    xp_goal_level = 80 if 80 in curve_map else int(max(curve_map.keys()))
                    xp_goal_value = float(curve_map[xp_goal_level])
                    add_light_goal_reference(fig_xp, xp_goal_value, f"Goal L{xp_goal_level}: {int(xp_goal_value):,}")
                if show_goal_trends:
                    color_by_player: dict[str, str | None] = {}
                    for tr in fig_xp.data:
                        name = str(getattr(tr, "name", ""))
                        color = getattr(getattr(tr, "line", None), "color", None)
                        color_by_player[name] = color
                    if xp_goal_value is not None:
                        for player, grp in xp_line_df.groupby("Spieler", sort=True):
                            trend_trace = build_xp_projection_trace(
                                grp[["Date", "Total XP"]],
                                float(xp_goal_value),
                                str(player),
                                color_by_player.get(str(player)),
                            )
                            if trend_trace is not None:
                                fig_xp.add_trace(trend_trace)
                apply_account_colors(fig_xp, medal_account_color_map)
                if xp_goal_value is not None:
                    account_count_xp = int(xp_line_df["Spieler"].dropna().astype(str).nunique())
                    status_y_xp = max(0.22, min(0.84, 1.0 - 0.06 * max(1, account_count_xp)))
                    add_goal_days_status_annotation(
                        fig_xp,
                        xp_line_df,
                        account_col="Spieler",
                        date_col="Date",
                        value_col="Total XP",
                        goal_value=float(xp_goal_value),
                        y_top=status_y_xp,
                    )
                fig_xp.update_layout(height=460)
                y_max_xp = pd.to_numeric(xp_line_df["Total XP"], errors="coerce").max()
                if xp_goal_value is not None:
                    y_max_xp = max(float(y_max_xp), xp_goal_value)
                if pd.notna(y_max_xp):
                    y_top_xp = max(1.0, float(y_max_xp) * 1.05)
                    fig_xp.update_yaxes(range=[0, y_top_xp], tickformat=",.0f")
                else:
                    fig_xp.update_yaxes(tickformat=",.0f")
                render_plotly_chart(fig_xp, use_container_width=True)

            render_latest_medal_status_panel(
                dash_medal_df=medal_status_medal_df,
                dash_display_medal_df=medal_status_display_df,
                goals_df=goals_df,
            )

            medals_for_grid = {
                m for m in medal_ids_available if m not in EXCLUDED_MEDAL_GRAPH_IDS and m != DERIVED_MEDAL_ID
            }
            thombay_order = load_medal_input_order(goals_df, account="Thombay")
            medal_ids_base = [m for m in thombay_order if m in medals_for_grid]
            medal_ids_base += sorted([m for m in medals_for_grid if m not in medal_ids_base])
            medal_ids = get_medal_ids_for_view_mode(
                medal_ids=medal_ids_base,
                source_df=medal_status_medal_df,
                goals_map=goals_map,
                selected_accounts=selected_accounts,
                filter_mode=medal_filter_mode,
                sort_metric=medal_sort_metric,
                sort_direction=medal_sort_direction,
                sort_account=medal_sort_account,
                input_order=thombay_order,
            )

            selected_medals = st.multiselect(
                "Medals",
                options=medal_ids,
                default=medal_ids,
                help="All medals are selected by default. Click legend items in each chart to show/hide accounts.",
            )
            selected_medals = [m for m in medal_ids if m in set(selected_medals)]
            show_goal_trends = st.checkbox(
                (
                    "Show trend-to-goal lines (legend selectable; platinum uses medal-completion trends; "
                    f"trends use data since {TREND_MIN_DATE_LABEL})"
                ),
                key="show_medal_goal_trends",
            )
            f_col, d_col = st.columns([1.55, 1.0])
            with f_col:
                medal_filter_mode = st.radio(
                    "Filter",
                    options=filter_mode_options,
                    horizontal=True,
                    key="medal_filter_mode",
                )
            with d_col:
                medal_sort_direction = st.radio(
                    "Sort direction",
                    options=sort_direction_options,
                    horizontal=True,
                    key="medal_sort_direction",
                )
            s_col, a_col = st.columns([1.0, 1.55])
            with s_col:
                medal_sort_metric = st.selectbox(
                    "Sort metric",
                    options=sort_metric_options,
                    key="medal_sort_metric",
                )
            with a_col:
                medal_sort_account = st.selectbox(
                    "Sort by account",
                    options=sort_account_options,
                    key="medal_sort_account",
                    help="Sorting/filtering uses this selected account.",
                )

            if not selected_medals:
                st.info("Select at least one medal.")
            else:
                for i in range(0, len(selected_medals), 2):
                    row_cols = st.columns(2)
                    for col_idx, medal_id in enumerate(selected_medals[i : i + 2]):
                        line_df = df[df["medal_id"] == medal_id].copy()
                        if line_df.empty:
                            continue

                        title_label = display_map.get(medal_id, medal_id)
                        fig_medal = px.line(
                            line_df,
                            x="date",
                            y="value",
                            color="account",
                            color_discrete_map=medal_account_color_map,
                            markers=True,
                            title=None,
                        )
                        medal_info = medal_explanations_map.get(goal_medal_id_for(medal_id), "")
                        if medal_info:
                            info_txt = str(medal_info).strip()
                            if info_txt:
                                for tr in fig_medal.data:
                                    x_raw = getattr(tr, "x", None)
                                    x_vals = list(x_raw) if x_raw is not None else []
                                    tr.update(
                                        customdata=[[info_txt] for _ in x_vals],
                                        hovertemplate=(
                                            "Date: %{x|%Y-%m-%d}<br>"
                                            "Account: %{fullData.name}<br>"
                                            "Value: %{y:,}<br>"
                                            "Info: %{customdata[0]}<extra></extra>"
                                        ),
                                    )
                        status_html = add_goal_and_trends(fig_medal, line_df, medal_id, status_mode="below_chart")
                        apply_account_colors(fig_medal, medal_account_color_map)
                        fig_medal.update_layout(height=320, margin=dict(t=20))
                        with row_cols[col_idx]:
                            title_text = f"Progress: {title_label}"
                            if medal_info and str(medal_info).strip():
                                title_attr = escape(str(medal_info).strip(), quote=True)
                                st.markdown(
                                    (
                                        "<div style='font-weight:600;margin-bottom:0.2rem;'>"
                                        f"<span title=\"{title_attr}\" "
                                        "style='border-bottom:1px dotted #94a3b8; cursor:help;'>"
                                        f"{escape(title_text)}"
                                        "</span>"
                                        "</div>"
                                    ),
                                    unsafe_allow_html=True,
                                )
                            else:
                                st.markdown(f"**{escape(title_text)}**", unsafe_allow_html=True)
                            render_plotly_chart(fig_medal, use_container_width=True)
                            if status_html:
                                st.markdown(
                                    (
                                        "<div style='font-size:0.86rem;line-height:1.3;"
                                        "margin-top:-0.15rem;margin-bottom:0.35rem;'>"
                                        f"{status_html}"
                                        "</div>"
                                    ),
                                    unsafe_allow_html=True,
                                )

if page == "Last Inputs":
    st.subheader("Last Inputs")

    st.markdown("Latest XP Input Values")
    if latest_xp_df.empty:
        st.warning("No XP input history found.")
    else:
        st.dataframe(
            latest_xp_df[["Date", "Spieler", "Lvl", "XP Bar", "Total XP"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "XP Bar": st.column_config.NumberColumn(format="%d"),
                "Total XP": st.column_config.NumberColumn(format="%d"),
            },
        )

    st.markdown("Latest Medal Input Snapshot per Account")
    if medal_df.empty:
        st.warning("No medal input history found.")
    else:
        latest_medal_dates = medal_df.groupby("account", as_index=False)["date"].max()
        latest_medal_dates = latest_medal_dates.rename(columns={"date": "latest_medal_date"})
        counts = medal_df.groupby(["account", "date"], as_index=False).size().rename(columns={"size": "rows"})
        latest_medal_dates = latest_medal_dates.merge(
            counts, left_on=["account", "latest_medal_date"], right_on=["account", "date"], how="left"
        ).drop(columns=["date"])

        latest_platinum = (
            display_medal_df[display_medal_df["medal_id"] == DERIVED_MEDAL_ID]
            .sort_values("date")
            .groupby("account", as_index=False)
            .tail(1)[["account", "value"]]
            .rename(columns={"value": "platinum_count"})
        )
        latest_medal_dates = latest_medal_dates.merge(latest_platinum, on="account", how="left")
        latest_medal_dates = latest_medal_dates.sort_values(["latest_medal_date", "account"], ascending=[False, True])
        st.dataframe(latest_medal_dates, use_container_width=True, hide_index=True)

    st.markdown("Latest Pokédex Entry Snapshot per Account")
    if display_pokedex_df.empty:
        st.warning("No Pokédex entry history found.")
    else:
        latest_pokedex_dates = display_pokedex_df.groupby("account", as_index=False)["date"].max()
        latest_pokedex_dates = latest_pokedex_dates.rename(columns={"date": "latest_pokedex_date"})
        counts = display_pokedex_df.groupby(["account", "date"], as_index=False).size().rename(columns={"size": "rows"})
        latest_pokedex_dates = latest_pokedex_dates.merge(
            counts, left_on=["account", "latest_pokedex_date"], right_on=["account", "date"], how="left"
        ).drop(columns=["date"])
        latest_pokedex_dates = latest_pokedex_dates.sort_values(["latest_pokedex_date", "account"], ascending=[False, True])
        st.dataframe(latest_pokedex_dates, use_container_width=True, hide_index=True)

if page == "Data Input":
    st.subheader("Data Input")
    with st.expander("Add New Account", expanded=False):
        st.caption("Create a new account for XP/medal inputs and optionally add it to existing groups.")
        new_account_name = st.text_input("Account Name", key="new_account_name")
        group_options = [str(g).strip() for g in groups.keys() if str(g).strip()]
        default_group_selection = [g for g in ["All"] if g in group_options]
        selected_target_groups = st.multiselect(
            "Add account to groups",
            options=group_options,
            default=default_group_selection,
            key="new_account_target_groups",
        )
        st.caption("Enable this account for Data Input tabs")
        input_xp_col, input_medal_col, input_pokedex_col = st.columns(3)
        enable_new_account_xp = input_xp_col.checkbox("XP", value=True, key="new_account_enable_xp")
        enable_new_account_medal = input_medal_col.checkbox("Medal", value=False, key="new_account_enable_medal")
        enable_new_account_pokedex = input_pokedex_col.checkbox("Pokédex", value=False, key="new_account_enable_pokedex")
        add_account_clicked = st.button("Add Account", key="add_new_account")
        if add_account_clicked:
            account_name = str(new_account_name).strip()
            existing_by_lower = {str(a).strip().lower(): str(a).strip() for a in all_accounts if str(a).strip()}
            if not account_name:
                st.error("Enter an account name.")
            elif any(ch in account_name for ch in [",", ":", "\n", "\r"]):
                st.error("Account name cannot include ',', ':', or line breaks.")
            elif account_name.lower() in existing_by_lower:
                st.info(f"Account already exists: {existing_by_lower[account_name.lower()]}")
            else:
                try:
                    applied_groups = add_account_to_groups(
                        player_groups_path(),
                        account_name,
                        selected_target_groups,
                    )
                    selected_input_types = []
                    if enable_new_account_xp:
                        selected_input_types.append("xp")
                        ensure_account_in_xp_order(account_name, known_accounts=all_accounts)
                    if enable_new_account_medal:
                        selected_input_types.append("medal")
                    if enable_new_account_pokedex:
                        selected_input_types.append("pokedex")
                    save_data_input_account_types(
                        data_input_accounts_path(),
                        account_name,
                        selected_input_types,
                        type_order=["xp", "medal", "pokedex"],
                    )
                except Exception as exc:
                    st.error(f"Failed to add account: {exc}")
                else:
                    group_label = ", ".join(applied_groups) if applied_groups else "All"
                    input_label = ", ".join(selected_input_types) if selected_input_types else "none"
                    st.success(f"Added account `{account_name}` (groups: {group_label}; inputs: {input_label}).")
                    st.rerun()

    tab_xp, tab_medal, tab_pokedex = st.tabs(["XP Snapshot Input", "Medal Snapshot Input", "Pokédex Entries Input"])

    with tab_xp:
        st.caption("Enter one snapshot date and update multiple accounts at once.")
        st.caption("Available XP accounts are controlled by `inputs/config/data_input_accounts.csv`.")
        xp_date = st.date_input("XP Date", value=date.today(), key="xp_batch_date")
        raw_players = list(xp_input_accounts) if xp_input_accounts else list(ACCOUNT_ORDER)
        all_players = load_xp_input_order(raw_players)
        xp_on_date = set()
        if not xp_input_df.empty:
            xp_on_date = set(xp_input_df[xp_input_df["Date"].dt.date == xp_date]["Spieler"].astype(str).tolist())
        max_level_accounts: set[str] = set()
        xp_level_max = max_configured_level(curve_map) or 100
        if not xp_input_df.empty:
            latest_actual_xp = xp_input_df.sort_values(["Spieler", "Date"]).groupby("Spieler", as_index=False).tail(1)
            max_level_accounts = set(
                latest_actual_xp[latest_actual_xp["Lvl"].astype(int) >= int(xp_level_max)]["Spieler"].astype(str).tolist()
            )
        battles_on_date: set[str] = set()
        if not additional_activity_df.empty:
            battles_on_date = set(
                additional_activity_df[additional_activity_df["date"].dt.date == xp_date]["account"]
                .astype(str)
                .str.strip()
                .tolist()
            )
        distance_on_date: set[str] = set()
        caught_on_date: set[str] = set()
        if not medal_df.empty:
            same_day_activity = medal_df[medal_df["date"].dt.date == xp_date].copy()
            if not same_day_activity.empty:
                same_day_activity["account"] = same_day_activity["account"].astype(str).str.strip()
                same_day_activity["medal_id"] = (
                    same_day_activity["medal_id"].astype(str).str.strip().str.lower().map(goal_medal_id_for)
                )
                distance_medal_id = XP_TAB_ACTIVITY_MEDAL_IDS["distance_walked"]
                caught_medal_id = XP_TAB_ACTIVITY_MEDAL_IDS["pokemon_caught"]
                distance_on_date = set(
                    same_day_activity[same_day_activity["medal_id"] == distance_medal_id]["account"].tolist()
                )
                caught_on_date = set(
                    same_day_activity[same_day_activity["medal_id"] == caught_medal_id]["account"].tolist()
                )
        activity_complete_on_date = battles_on_date & distance_on_date & caught_on_date
        missing_xp_accounts = [a for a in all_players if a not in xp_on_date and a not in max_level_accounts]
        max_level_activity_accounts = [
            a for a in all_players if a in max_level_accounts and a not in activity_complete_on_date
        ]
        available_account_set = set(missing_xp_accounts) | set(max_level_activity_accounts)
        available_xp_accounts = [a for a in all_players if a in available_account_set]

        if xp_on_date:
            st.caption(f"Already entered for this date: {', '.join(sorted(xp_on_date))}")
        if max_level_accounts:
            st.caption(
                f"No XP input needed after max level {xp_level_max}: {', '.join(sorted(max_level_accounts))}"
            )
        if missing_xp_accounts:
            st.caption(f"Missing XP/activity for this date: {', '.join(missing_xp_accounts)}")
        if max_level_activity_accounts:
            st.caption(
                "Missing activity only for this date after max level: "
                f"{', '.join(max_level_activity_accounts)}"
            )

        selected_xp_accounts = st.multiselect(
            "Accounts to update (missing XP or activity for selected date)",
            options=available_xp_accounts,
            default=available_xp_accounts,
            key="xp_batch_accounts",
        )
        if not available_xp_accounts:
            st.success("XP/activity snapshot complete for selected date. No missing accounts.")
        elif not selected_xp_accounts:
            st.info("Select at least one missing account.")
        else:
            latest_map: dict[str, tuple[int, int]] = {}
            if not xp_input_df.empty:
                latest_xp = xp_input_df.sort_values(["Spieler", "Date"]).groupby("Spieler", as_index=False).tail(1)
                for _, r in latest_xp.iterrows():
                    latest_map[str(r["Spieler"])] = (int(r["Lvl"]), int(r["XP Bar"]))

            additional_activity_df = load_additional_activity(additional_activity_path())
            latest_battles_map: dict[str, float] = {}
            if not additional_activity_df.empty:
                latest_additional = additional_activity_df.sort_values("date").groupby("account", as_index=False).tail(1)
                for _, r in latest_additional.iterrows():
                    latest_battles_map[str(r["account"])] = float(r["battles_won"])

            latest_activity_map: dict[tuple[str, str], float] = {}
            if not medal_df.empty:
                medal_latest = medal_df.copy()
                medal_latest["date"] = pd.to_datetime(medal_latest["date"], errors="coerce")
                medal_latest["account"] = medal_latest["account"].astype(str).str.strip()
                medal_latest["medal_id"] = medal_latest["medal_id"].astype(str).str.strip().str.lower().map(goal_medal_id_for)
                medal_latest["value"] = pd.to_numeric(medal_latest["value"], errors="coerce")
                medal_latest = medal_latest.dropna(subset=["date", "account", "medal_id", "value"]).copy()
                medal_latest = medal_latest[medal_latest["medal_id"].isin(set(XP_TAB_ACTIVITY_MEDAL_IDS.values()))].copy()
                if not medal_latest.empty:
                    medal_latest = (
                        medal_latest.sort_values("date")
                        .groupby(["account", "medal_id"], as_index=False)
                        .tail(1)
                    )
                    for _, r in medal_latest.iterrows():
                        latest_activity_map[(str(r["account"]), str(r["medal_id"]))] = float(r["value"])

            medal_existing_for_validation = (
                medal_df[["date", "account", "medal_id", "value"]].copy()
                if not medal_df.empty
                else pd.DataFrame(columns=["date", "account", "medal_id", "value"])
            )
            additional_existing_for_validation = (
                additional_activity_df[["date", "account", "battles_won"]].copy()
                if not additional_activity_df.empty
                else pd.DataFrame(columns=["date", "account", "battles_won"])
            )

            xp_editor_rows = []
            for acc in selected_xp_accounts:
                lvl_default, xp_default = latest_map.get(acc, (1, 0))
                battles_default = latest_battles_map.get(str(acc), 0.0)
                distance_default = latest_activity_map.get((str(acc), XP_TAB_ACTIVITY_MEDAL_IDS["distance_walked"]), 0.0)
                caught_default = latest_activity_map.get((str(acc), XP_TAB_ACTIVITY_MEDAL_IDS["pokemon_caught"]), 0.0)
                xp_editor_rows.append(
                    {
                        "account": acc,
                        "lvl_last": int(lvl_default),
                        "xp_bar_last": int(xp_default),
                        "lvl": lvl_default,
                        "xp_bar": xp_default,
                        "xp_locked": str(acc) in max_level_accounts,
                        "battles_last": battles_default,
                        "distance_last": distance_default,
                        "caught_last": caught_default,
                    }
                )

            xp_input_col = st.container()
            col_widths = [1.25, 0.62, 0.92, 0.18, 0.52, 0.18, 0.9, 0.72, 0.9, 0.72, 0.95, 0.72, 0.95, 1.85]
            h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14 = xp_input_col.columns(col_widths, gap="small")
            h1.markdown("**Account**")
            h2.markdown("**Level (last Data)**")
            h3.markdown("**XPBar (last Data)**")
            h4.caption("")
            h5.markdown("**Level**")
            h6.caption("")
            h7.markdown("**XP Bar**")
            h8.markdown("**Battles (last)**")
            h9.markdown("**Battles Won**")
            h10.markdown("**Distance (last)**")
            h11.markdown("**Distance Walked**")
            h12.markdown("**Caught (last)**")
            h13.markdown("**Pokemon Caught**")
            h14.markdown("**Inactive / Status**")

            xp_existing_for_validation = (
                xp_input_df[["Date", "Spieler", "Lvl", "XP Bar"]].copy()
                if not xp_input_df.empty
                else pd.DataFrame(columns=["Date", "Spieler", "Lvl", "XP Bar"])
            )

            def _fmt_input_default(val: object, decimals: int = 0) -> str:
                num = pd.to_numeric(pd.Series([val]), errors="coerce").iloc[0]
                if pd.isna(num):
                    return "0" if decimals <= 0 else f"0.{''.join(['0'] * decimals)}"
                n = float(num)
                if decimals <= 0:
                    return str(int(round(n)))
                return f"{n:.{int(decimals)}f}"

            def _parse_float_loose(raw: object) -> float | None:
                s = str(raw).strip()
                if not s:
                    return None
                s = s.replace(" ", "")
                if "," in s and "." in s:
                    if s.rfind(",") > s.rfind("."):
                        s = s.replace(".", "").replace(",", ".")
                    else:
                        s = s.replace(",", "")
                elif "," in s and "." not in s:
                    if s.count(",") == 1:
                        s = s.replace(",", ".")
                    else:
                        s = s.replace(",", "")
                else:
                    s = s.replace(",", "")
                val = pd.to_numeric(pd.Series([s]), errors="coerce").iloc[0]
                return None if pd.isna(val) else float(val)

            for row in xp_editor_rows:
                acc = str(row["account"])
                xp_locked = bool(row.get("xp_locked", False))
                draft_key = f"xp_draft_{xp_date.isoformat()}_{acc}"
                status_key = f"xp_draft_status_{xp_date.isoformat()}_{acc}"
                inactive_key = f"xp_inactive_{xp_date.isoformat()}_{acc}"
                refresh_key = f"xp_draft_refresh_{xp_date.isoformat()}_{acc}"
                if inactive_key not in st.session_state:
                    st.session_state[inactive_key] = load_input_inactive_marker("xp", xp_date, acc)
                inactive_current = bool(st.session_state.get(inactive_key, False))
                with xp_input_col.container():
                    c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, c11, c12, c13, c14 = st.columns(
                        col_widths,
                        gap="small",
                    )
                    account_slot = c1.empty()
                    c2.markdown(f"`{int(row['lvl_last'])}`")
                    c3.markdown(f"`{int(row['xp_bar_last']):,}`")
                    c4.caption("")
                    c6.caption("")
                    c8.markdown(f"`{_fmt_input_default(row.get('battles_last', 0.0), 0)}`")
                    c10.markdown(f"`{_fmt_input_default(row.get('distance_last', 0.0), 1)}`")
                    c12.markdown(f"`{_fmt_input_default(row.get('caught_last', 0.0), 0)}`")
                    lvl_state_key = f"xp_level_input_{xp_date.isoformat()}_{acc}"
                    if lvl_state_key not in st.session_state:
                        st.session_state[lvl_state_key] = int(row["lvl"])
                    else:
                        try:
                            current_lvl = int(st.session_state[lvl_state_key])
                        except Exception:
                            current_lvl = int(row["lvl"])
                        st.session_state[lvl_state_key] = max(1, min(xp_level_max, current_lvl))
                    lvl_value = c5.number_input(
                        "Level",
                        min_value=1,
                        max_value=xp_level_max,
                        step=1,
                        format="%d",
                        key=lvl_state_key,
                        label_visibility="collapsed",
                        disabled=xp_locked or inactive_current,
                    )
                    xp_bar_value = c7.text_input(
                        "XP Bar",
                        value=str(int(row["xp_bar"])),
                        key=f"xp_bar_input_{xp_date.isoformat()}_{acc}",
                        label_visibility="collapsed",
                        disabled=xp_locked or inactive_current,
                    )
                    battles_default = _fmt_input_default(row.get("battles_last", 0.0), 0)
                    distance_default = _fmt_input_default(row.get("distance_last", 0.0), 1)
                    caught_default = _fmt_input_default(row.get("caught_last", 0.0), 0)
                    battles_value = c9.text_input(
                        "Battles Won",
                        value=battles_default,
                        key=f"xp_battles_input_{xp_date.isoformat()}_{acc}",
                        label_visibility="collapsed",
                        disabled=inactive_current,
                    )
                    distance_value = c11.text_input(
                        "Distance Walked",
                        value=distance_default,
                        key=f"xp_distance_input_{xp_date.isoformat()}_{acc}",
                        label_visibility="collapsed",
                        disabled=inactive_current,
                    )
                    caught_value = c13.text_input(
                        "Pokemon Caught",
                        value=caught_default,
                        key=f"xp_caught_input_{xp_date.isoformat()}_{acc}",
                        label_visibility="collapsed",
                        disabled=inactive_current,
                        on_change=mark_session_flag,
                        args=(refresh_key,),
                    )
                    xp_bar_num = pd.to_numeric(xp_bar_value, errors="coerce")
                    battles_num = _parse_float_loose(battles_value)
                    distance_num = _parse_float_loose(distance_value)
                    caught_num = _parse_float_loose(caught_value)
                    row_changed = False
                    if not xp_locked:
                        row_changed = int(lvl_value) != int(row["lvl_last"])
                        if pd.isna(xp_bar_num):
                            row_changed = row_changed or (str(xp_bar_value).strip() != str(int(row["xp_bar_last"])))
                        else:
                            row_changed = row_changed or (int(xp_bar_num) != int(row["xp_bar_last"]))
                    if not pd.isna(battles_num):
                        row_changed = row_changed or (float(battles_num) != float(row.get("battles_last", 0.0)))
                    if not pd.isna(distance_num):
                        row_changed = row_changed or (float(distance_num) != float(row.get("distance_last", 0.0)))
                    if not pd.isna(caught_num):
                        row_changed = row_changed or (float(caught_num) != float(row.get("caught_last", 0.0)))
                    inactive_value = c14.checkbox(
                        "Inactive",
                        key=inactive_key,
                        help="Document unchanged values for this date on final save.",
                        on_change=mark_session_flag,
                        args=(refresh_key,),
                    )
                    if inactive_value:
                        c5.markdown("<span style='color:#9ca3af'>inactive</span>", unsafe_allow_html=True)
                    account_color = "#9ca3af" if row_changed else "inherit"
                    account_slot.markdown(
                        f"<span style='color:{account_color}; font-weight:500'>{escape(acc)}</span>",
                        unsafe_allow_html=True,
                    )

                    if bool(st.session_state.pop(refresh_key, False)):
                        row_errors: list[str] = []
                        draft_level = int(row["lvl_last"]) if inactive_value or xp_locked else int(lvl_value)
                        draft_xp_bar_raw = int(row["xp_bar_last"]) if inactive_value or xp_locked else xp_bar_value
                        draft_battles_raw = row.get("battles_last", 0.0) if inactive_value else battles_value
                        draft_distance_raw = row.get("distance_last", 0.0) if inactive_value else distance_value
                        draft_caught_raw = row.get("caught_last", 0.0) if inactive_value else caught_value
                        draft_xp_bar = pd.to_numeric(draft_xp_bar_raw, errors="coerce")
                        draft_battles = _parse_float_loose(draft_battles_raw)
                        draft_distance = _parse_float_loose(draft_distance_raw)
                        draft_caught = _parse_float_loose(draft_caught_raw)
                        if xp_locked:
                            pass
                        elif pd.isna(draft_xp_bar) or int(draft_xp_bar) < 0:
                            row_errors.append("XP Bar must be a number >= 0.")
                        else:
                            row_df = pd.DataFrame(
                                [
                                    {
                                        "Date": pd.Timestamp(xp_date),
                                        "Spieler": acc,
                                        "Lvl": int(draft_level),
                                        "XP Bar": int(draft_xp_bar),
                                    }
                                ]
                            )
                            row_errors.extend(_validate_xp_rows_non_decreasing(xp_existing_for_validation, row_df, curve_map))
                        if draft_battles is None or float(draft_battles) < 0:
                            row_errors.append("Battles Won must be a number >= 0.")
                        if draft_distance is None or float(draft_distance) < 0:
                            row_errors.append("Distance Walked must be a number >= 0.")
                        if draft_caught is None or float(draft_caught) < 0:
                            row_errors.append("Pokemon Caught must be a number >= 0.")
                        if not row_errors:
                            additional_row_df = pd.DataFrame(
                                [
                                    {
                                        "date": pd.Timestamp(xp_date),
                                        "account": acc,
                                        "battles_won": float(draft_battles),
                                    }
                                ]
                            )
                            row_errors.extend(
                                _validate_additional_activity_rows_non_decreasing(
                                    additional_existing_for_validation,
                                    additional_row_df,
                                )
                            )
                        if not row_errors:
                            medal_row_df = pd.DataFrame(
                                [
                                    {
                                        "date": pd.Timestamp(xp_date),
                                        "account": acc,
                                        "medal_id": XP_TAB_ACTIVITY_MEDAL_IDS["distance_walked"],
                                        "value": float(draft_distance),
                                    },
                                    {
                                        "date": pd.Timestamp(xp_date),
                                        "account": acc,
                                        "medal_id": XP_TAB_ACTIVITY_MEDAL_IDS["pokemon_caught"],
                                        "value": float(draft_caught),
                                    },
                                ]
                            )
                            row_errors.extend(_validate_medal_rows_non_decreasing(medal_existing_for_validation, medal_row_df))
                        row_changed_for_draft = False
                        if not xp_locked:
                            if pd.isna(draft_xp_bar):
                                row_changed_for_draft = str(draft_xp_bar_raw).strip() != str(int(row["xp_bar_last"]))
                            else:
                                row_changed_for_draft = (
                                    int(draft_level) != int(row["lvl_last"])
                                    or int(draft_xp_bar) != int(row["xp_bar_last"])
                                )
                        row_changed_for_draft = row_changed_for_draft or float(draft_battles or 0) != float(row.get("battles_last", 0.0))
                        row_changed_for_draft = row_changed_for_draft or float(draft_distance or 0) != float(row.get("distance_last", 0.0))
                        row_changed_for_draft = row_changed_for_draft or float(draft_caught or 0) != float(row.get("caught_last", 0.0))
                        st.session_state[draft_key] = {
                            "account": acc,
                            "lvl": int(draft_level),
                            "xp_bar": None if pd.isna(draft_xp_bar) else int(draft_xp_bar),
                            "xp_locked": xp_locked,
                            "battles_won": draft_battles,
                            "distance_walked": draft_distance,
                            "pokemon_caught": draft_caught,
                            "inactive": bool(inactive_value),
                            "changed": bool(row_changed_for_draft),
                            "valid": not bool(row_errors),
                            "errors": row_errors,
                        }
                        st.session_state[status_key] = {
                            "valid": not bool(row_errors),
                            "inactive": bool(inactive_value),
                            "changed": bool(row_changed_for_draft),
                            "errors": row_errors,
                        }
                        save_input_inactive_marker("xp", xp_date, acc, bool(inactive_value))
                        if row_errors:
                            pass
                        else:
                            if inactive_value:
                                pass
                            elif row_changed_for_draft:
                                pass
                            else:
                                pass
                    current_status = st.session_state.get(status_key)
                    if isinstance(current_status, dict):
                        if not bool(current_status.get("valid", False)):
                            c14.caption("Draft error")
                        elif bool(current_status.get("inactive", False)):
                            c14.caption("Inactive draft")
                        elif bool(current_status.get("changed", False)):
                            c14.caption("Draft OK")
                        else:
                            c14.caption("Unchanged")

            if st.button("Save all XP/activity changes", key="xp_batch_final_save"):
                rows_to_write: list[dict[str, object]] = []
                additional_rows_to_write: list[dict[str, object]] = []
                medal_rows_to_write: list[dict[str, object]] = []
                final_errors: list[str] = []
                skipped_unchanged: list[str] = []
                for row in xp_editor_rows:
                    acc = str(row["account"])
                    xp_locked = bool(row.get("xp_locked", False))
                    draft_key = f"xp_draft_{xp_date.isoformat()}_{acc}"
                    draft = st.session_state.get(draft_key)
                    inactive_saved = load_input_inactive_marker("xp", xp_date, acc)
                    if isinstance(draft, dict):
                        if not bool(draft.get("valid", False)):
                            final_errors.extend([f"{acc}: {err}" for err in draft.get("errors", [])])
                            continue
                        should_write = bool(draft.get("changed", False)) or bool(draft.get("inactive", False)) or xp_locked
                        if not should_write:
                            skipped_unchanged.append(acc)
                            continue
                        xp_rows, activity_rows, activity_medal_rows = build_xp_activity_snapshot_rows(
                            xp_date,
                            acc,
                            int(draft.get("lvl", row["lvl_last"])),
                            int(draft.get("xp_bar", row["xp_bar_last"])),
                            bool(draft.get("xp_locked", xp_locked)),
                            float(draft.get("battles_won", row.get("battles_last", 0.0))),
                            float(draft.get("distance_walked", row.get("distance_last", 0.0))),
                            float(draft.get("pokemon_caught", row.get("caught_last", 0.0))),
                        )
                    elif inactive_saved or xp_locked:
                        xp_rows, activity_rows, activity_medal_rows = build_xp_activity_snapshot_rows(
                            xp_date,
                            acc,
                            int(row["lvl_last"]),
                            int(row["xp_bar_last"]),
                            xp_locked,
                            float(row.get("battles_last", 0.0)),
                            float(row.get("distance_last", 0.0)),
                            float(row.get("caught_last", 0.0)),
                        )
                    else:
                        skipped_unchanged.append(acc)
                        continue
                    rows_to_write.extend(xp_rows)
                    additional_rows_to_write.extend(activity_rows)
                    medal_rows_to_write.extend(activity_medal_rows)
                if final_errors:
                    st.error("Fix draft errors before saving:\n" + "\n".join(final_errors[:12]))
                elif not rows_to_write and not additional_rows_to_write and not medal_rows_to_write:
                    st.info("No changed or inactive XP/activity rows to save.")
                else:
                    try:
                        written = upsert_xp_rows(xp_history_path(), rows_to_write)
                        written_additional = upsert_additional_activity_rows(
                            additional_activity_path(),
                            additional_rows_to_write,
                        )
                        written_medals = append_medal_rows(medal_snapshots_path(), medal_rows_to_write)
                    except ValueError as e:
                        st.error(str(e))
                    else:
                        st.success(
                            f"Saved XP rows: {written}. Saved battles rows: {written_additional}. "
                            f"Saved activity medal rows: {written_medals}."
                        )
                        if skipped_unchanged:
                            st.caption(f"Unchanged without inactive marker stayed open: {', '.join(skipped_unchanged)}")

        if all_players:
            st.markdown("Input order for XP accounts")
            st.caption("Use up/down for one-step moves, or enter an exact target position and press Go.")
            xp_order = load_xp_input_order(all_players)
            for idx, account_name in enumerate(xp_order):
                pos_col, name_col, target_col, go_col, up_col, down_col = st.columns([0.45, 2.0, 0.9, 0.65, 0.65, 0.65])
                pos_col.markdown(f"`{idx + 1}`")
                name_col.markdown(f"**{escape(str(account_name))}**", unsafe_allow_html=True)
                target_pos = int(
                    target_col.number_input(
                        "Target Pos",
                        min_value=1,
                        max_value=max(1, len(xp_order)),
                        value=int(idx + 1),
                        step=1,
                        key=f"xp_order_target_{account_name}",
                        label_visibility="collapsed",
                    )
                )
                if go_col.button("Go", key=f"xp_order_go_{idx}_{account_name}", use_container_width=True):
                    if 1 <= int(target_pos) <= len(xp_order):
                        new_order = [a for a in xp_order if a != account_name]
                        insert_idx = int(target_pos) - 1
                        new_order.insert(insert_idx, account_name)
                        save_xp_input_order(new_order)
                        st.rerun()
                if up_col.button("Up", key=f"xp_order_up_{idx}_{account_name}", disabled=idx == 0, use_container_width=True):
                    new_order = xp_order.copy()
                    new_order[idx - 1], new_order[idx] = new_order[idx], new_order[idx - 1]
                    save_xp_input_order(new_order)
                    st.rerun()
                if down_col.button(
                    "Down",
                    key=f"xp_order_down_{idx}_{account_name}",
                    disabled=idx >= (len(xp_order) - 1),
                    use_container_width=True,
                ):
                    new_order = xp_order.copy()
                    new_order[idx], new_order[idx + 1] = new_order[idx + 1], new_order[idx]
                    save_xp_input_order(new_order)
                    st.rerun()

    with tab_medal:
        st.caption("Enter one full medal snapshot per account.")
        st.caption("`Platinum Medals` is derived automatically from medals that reached their goal.")
        medal_date = st.date_input("Medal Date", value=date.today(), key="medal_full_date")
        allowed_accounts = list(medal_input_accounts) if medal_input_accounts else list(MEDAL_INPUT_CORE_ACCOUNTS)
        st.caption("Available medal accounts are controlled by `inputs/config/data_input_accounts.csv`.")
        valid_manual_medal_ids = {
            str(m).strip().lower()
            for m in goals_df.get("medal_id", pd.Series(dtype="object")).astype(str).tolist()
            if str(m).strip() and str(m).strip().lower() not in EXCLUDED_MANUAL_MEDAL_IDS
        }
        xp_activity_medal_ids = set(XP_TAB_ACTIVITY_MEDAL_IDS.values())
        expected_medal_count = len(valid_manual_medal_ids)
        complete_medal_on_date: set[str] = set()
        partial_medal_counts: dict[str, int] = {}
        partial_medal_ids: dict[str, list[str]] = {}
        if not medal_df.empty and expected_medal_count > 0:
            same_day_medals = medal_df[medal_df["date"].dt.date == medal_date].copy()
            if not same_day_medals.empty:
                same_day_medals["account"] = same_day_medals["account"].astype(str).str.strip()
                same_day_medals["medal_id"] = same_day_medals["medal_id"].astype(str).str.strip().str.lower()
                same_day_medals = same_day_medals[same_day_medals["medal_id"].isin(valid_manual_medal_ids)].copy()
                medal_counts = (
                    same_day_medals.groupby("account", as_index=False)["medal_id"]
                    .nunique()
                    .rename(columns={"medal_id": "medal_count"})
                )
                for _, row in medal_counts.iterrows():
                    account_name = str(row["account"]).strip()
                    medal_count = int(row["medal_count"])
                    medal_ids_for_account = sorted(
                        same_day_medals[same_day_medals["account"] == account_name]["medal_id"].astype(str).unique().tolist()
                    )
                    if medal_count >= expected_medal_count:
                        complete_medal_on_date.add(account_name)
                    elif medal_count > 0:
                        partial_medal_counts[account_name] = medal_count
                        partial_medal_ids[account_name] = medal_ids_for_account
        available_medal_accounts = [a for a in allowed_accounts if a not in complete_medal_on_date]
        if complete_medal_on_date:
            st.caption(f"Already entered for this date: {', '.join(sorted(complete_medal_on_date))}")
        if partial_medal_counts:
            activity_only_accounts = []
            other_partial_accounts = []
            for acc, cnt in sorted(partial_medal_counts.items()):
                medal_ids_for_account = set(partial_medal_ids.get(acc, []))
                label = f"{acc} ({cnt}/{expected_medal_count})"
                if medal_ids_for_account and medal_ids_for_account.issubset(xp_activity_medal_ids):
                    activity_only_accounts.append(label)
                else:
                    other_partial_accounts.append(label)
            if activity_only_accounts:
                st.caption(
                    "Activity medal rows already on this date from XP input "
                    f"(Distance Walked, Pokemon Caught): {', '.join(activity_only_accounts)}"
                )
            if other_partial_accounts:
                st.caption(f"Partial medal rows on this date: {', '.join(other_partial_accounts)}")
        if available_medal_accounts:
            st.caption(f"Missing for this date: {', '.join(available_medal_accounts)}")
            medal_account = st.selectbox(
                "Account (missing only for selected date)",
                options=available_medal_accounts,
                key="medal_full_account",
            )
        else:
            st.success("Medal snapshot complete for selected date. No missing accounts.")
            medal_account = None

        if goals_df.empty:
            st.warning("No medal goals found. Check `inputs/config/medal_goals.csv`.")
        elif medal_account is None:
            st.info("Choose another date to enter new medal snapshots.")
        else:
            goals_map = goals_df.set_index("medal_id")[["display_name", "goal_value"]].to_dict("index")

            latest_account_rows = medal_df[medal_df["account"] == medal_account].copy()
            latest_vals: dict[str, float] = {}
            if not latest_account_rows.empty:
                latest_account_rows = latest_account_rows[
                    pd.to_datetime(latest_account_rows["date"], errors="coerce") <= pd.Timestamp(medal_date)
                ].copy()
                latest_account_rows = latest_account_rows.sort_values("date").drop_duplicates("medal_id", keep="last")
                latest_vals = dict(
                    zip(latest_account_rows["medal_id"].astype(str).tolist(), latest_account_rows["value"].astype(float).tolist())
                )

            st.markdown(f"Full medal snapshot for `{medal_account}`")
            medal_order_for_account = load_medal_input_order(goals_df, account=medal_account)
            editor_rows = []
            for medal_id in medal_order_for_account:
                row_goal = goals_map.get(medal_id, {})
                last_input_value = latest_vals.get(medal_id, 0.0)
                editor_rows.append(
                    {
                        "medal_id": medal_id,
                        "display_name": row_goal.get("display_name", medal_id),
                        "goal_value": row_goal.get("goal_value", 0),
                        "last_input_value": last_input_value,
                        "value": last_input_value,
                    }
                )

            def _fmt_compact_number(value: object) -> str:
                num = pd.to_numeric(value, errors="coerce")
                if pd.isna(num):
                    return "-"
                num_float = float(num)
                if num_float.is_integer():
                    return f"{int(num_float):,}"
                return f"{num_float:,.2f}".rstrip("0").rstrip(".")

            _, medal_input_col, _ = st.columns([0.24, 0.52, 0.24], gap="small")
            col_widths = [2.1, 0.8, 1.0, 1.2, 2.2]
            h1, h2, h3, h4, h5 = medal_input_col.columns(col_widths, gap="small")
            h1.markdown("**Medal**")
            h2.markdown("**Goal**")
            h3.markdown("**Last**")
            h4.markdown("**Value**")
            h5.markdown("**Status**")

            medal_inputs: list[dict[str, object]] = []
            inline_medal_errors: list[str] = []
            medal_existing_for_validation = (
                medal_df[["date", "account", "medal_id", "value"]].copy()
                if not medal_df.empty
                else pd.DataFrame(columns=["date", "account", "medal_id", "value"])
            )
            additional_existing_for_validation = (
                additional_activity_df[["date", "account", "battles_won"]].copy()
                if not additional_activity_df.empty
                else pd.DataFrame(columns=["date", "account", "battles_won"])
            )
            for row in editor_rows:
                medal_id = str(row.get("medal_id", "")).strip().lower()
                display_name = str(row.get("display_name", medal_id)).strip() or medal_id
                goal_value = row.get("goal_value", 0)
                last_input_raw = pd.to_numeric(row.get("last_input_value"), errors="coerce")
                last_input_value = 0.0 if pd.isna(last_input_raw) else float(last_input_raw)
                c1, c2, c3, c4, c5 = medal_input_col.columns(col_widths, gap="small")

                name_slot = c1.empty()
                c2.markdown(f"`{_fmt_compact_number(goal_value)}`")
                c3.markdown(f"`{_fmt_compact_number(last_input_value)}`")

                value_default = _fmt_compact_number(last_input_value).replace(",", "")
                value_input_key = f"medal_value_input_{medal_date.isoformat()}_{medal_account}_{medal_id}"
                if value_input_key not in st.session_state:
                    st.session_state[value_input_key] = value_default
                value_input = c4.text_input(
                    "Value",
                    key=value_input_key,
                    label_visibility="collapsed",
                )
                value_num = pd.to_numeric(value_input, errors="coerce")
                if pd.isna(value_num):
                    row_changed = str(value_input).strip() != str(value_default).strip()
                else:
                    row_changed = float(value_num) != float(last_input_value)

                name_color = "#9ca3af" if row_changed else "inherit"
                name_slot.markdown(
                    f"<span style='color:{name_color}; font-weight:500'>{escape(display_name)}</span>",
                    unsafe_allow_html=True,
                )

                value = pd.to_numeric(value_input, errors="coerce")
                row_errors: list[str] = []
                if not medal_id:
                    row_errors.append("Missing medal_id.")
                elif medal_id in EXCLUDED_MANUAL_MEDAL_IDS:
                    row_errors.append("Derived medal cannot be saved.")
                elif pd.isna(value):
                    row_errors.append("Value is empty.")
                else:
                    row_df = pd.DataFrame(
                        [
                            {
                                "date": pd.Timestamp(medal_date),
                                "account": medal_account,
                                "medal_id": medal_id,
                                "value": float(value),
                            }
                        ]
                    )
                    row_mono_errors = _validate_medal_rows_non_decreasing(medal_existing_for_validation, row_df)
                    if row_mono_errors:
                        row_errors.append(row_mono_errors[0])

                if row_errors:
                    inline_medal_errors.append(f"{display_name}: {row_errors[0]}")
                    c5.markdown(
                        f"<span style='color:#ef4444; font-size:0.82rem'>{escape(row_errors[0])}</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    c5.markdown("<span style='color:#22c55e; font-size:0.82rem'>OK</span>", unsafe_allow_html=True)

                medal_inputs.append(
                    {
                        "medal_id": medal_id,
                        "display_name": display_name,
                        "value": value_input,
                    }
                )

            if inline_medal_errors:
                details = "\n".join([f"- {x}" for x in inline_medal_errors[:12]])
                extra = f"\n... and {len(inline_medal_errors) - 12} more issue(s)." if len(inline_medal_errors) > 12 else ""
                st.error("Live validation issues:\n" + details + extra)
            else:
                st.caption("Live validation: OK")

            if st.button(
                "Save full medal snapshot for account",
                key="save_full_medal_snapshot",
                disabled=bool(inline_medal_errors),
            ):
                rows_to_write: list[dict[str, object]] = []
                errors: list[str] = []
                for r in medal_inputs:
                    medal_id = str(r.get("medal_id", "")).strip().lower()
                    display_name = str(r.get("display_name", medal_id)).strip() or medal_id
                    value = pd.to_numeric(r.get("value"), errors="coerce")
                    if not medal_id:
                        errors.append("Missing medal_id.")
                        continue
                    if medal_id in EXCLUDED_MANUAL_MEDAL_IDS:
                        errors.append(f"{display_name}: derived medal is not allowed in medal snapshots.")
                        continue
                    if pd.isna(value):
                        errors.append(f"{display_name}: value is empty.")
                        continue
                    rows_to_write.append(
                        {
                            "date": medal_date.isoformat(),
                            "account": medal_account,
                            "medal_id": medal_id,
                            "value": float(value),
                        }
                    )
                if errors:
                    st.error("\n".join(errors))
                else:
                    try:
                        written = append_medal_rows(medal_snapshots_path(), rows_to_write)
                    except ValueError as e:
                        st.error(str(e))
                    else:
                        st.success(f"Saved medal snapshot rows: {written} for {medal_account}")

            medal_order = load_medal_input_order(goals_df, account=medal_account)
            st.markdown(f"Input order for `{medal_account}`")
            st.caption("Use up/down for one-step moves, or enter an exact target position and press Go.")
            for idx, medal_id in enumerate(medal_order):
                display_name = goals_map.get(medal_id, {}).get("display_name", medal_id)
                pos_col, name_col, target_col, go_col, up_col, down_col = st.columns([0.45, 2.0, 0.9, 0.65, 0.65, 0.65])
                pos_col.markdown(f"`{idx + 1}`")
                name_col.markdown(f"**{escape(str(display_name))}**", unsafe_allow_html=True)
                target_pos = int(
                    target_col.number_input(
                        "Target Pos",
                        min_value=1,
                        max_value=max(1, len(medal_order)),
                        value=int(idx + 1),
                        step=1,
                        key=f"medal_order_target_{medal_account}_{medal_id}",
                        label_visibility="collapsed",
                    )
                )
                if go_col.button(
                    "Go",
                    key=f"medal_order_go_{medal_account}_{idx}_{medal_id}",
                    use_container_width=True,
                ):
                    if 1 <= int(target_pos) <= len(medal_order):
                        new_order = [m for m in medal_order if m != medal_id]
                        insert_idx = int(target_pos) - 1
                        new_order.insert(insert_idx, medal_id)
                        save_medal_input_order(medal_account, new_order)
                        st.rerun()
                if up_col.button(
                    "Up",
                    key=f"medal_order_up_{medal_account}_{idx}_{medal_id}",
                    disabled=idx == 0,
                    use_container_width=True,
                ):
                    new_order = medal_order.copy()
                    new_order[idx - 1], new_order[idx] = new_order[idx], new_order[idx - 1]
                    save_medal_input_order(medal_account, new_order)
                    st.rerun()
                if down_col.button(
                    "Down",
                    key=f"medal_order_down_{medal_account}_{idx}_{medal_id}",
                    disabled=idx >= (len(medal_order) - 1),
                    use_container_width=True,
                ):
                    new_order = medal_order.copy()
                    new_order[idx], new_order[idx + 1] = new_order[idx + 1], new_order[idx]
                    save_medal_input_order(medal_account, new_order)
                    st.rerun()

    with tab_pokedex:
        st.caption("Enter counts by category and region. Pokemon region counts are read from medal snapshots.")
        st.caption("Available Pokédex accounts are controlled by `inputs/config/data_input_accounts.csv`.")
        pokedex_date = st.date_input("Pokédex Date", value=date.today(), key="pokedex_entry_date")
        pokedex_accounts = list(pokedex_input_accounts) if pokedex_input_accounts else list(ACCOUNT_ORDER)

        def _pokedex_cell_config(entry_type: str, region: str) -> dict[str, object]:
            return pokedex_entry_config.get((str(entry_type).strip().lower(), str(region).strip().lower()), {})

        def _is_locked_pokedex_cell(entry_type: str, region: str) -> bool:
            return bool(_pokedex_cell_config(entry_type, region).get("locked", False))

        editable_cells = [
            (entry_type, region)
            for entry_type in POKEDEX_ENTRY_TYPES
            for region in POKEDEX_REGIONS
            if not _is_overall_pokedex_cell(region)
            and not _is_medal_derived_pokedex_cell(entry_type, region)
            and not _is_locked_pokedex_cell(entry_type, region)
        ]
        expected_pokedex_count = len(editable_cells)
        complete_pokedex_on_date: set[str] = set()
        partial_pokedex_counts: dict[str, int] = {}
        if not pokedex_df.empty and expected_pokedex_count > 0:
            same_day_pokedex = pokedex_df[pokedex_df["date"].dt.date == pokedex_date].copy()
            if not same_day_pokedex.empty:
                same_day_pokedex["account"] = same_day_pokedex["account"].astype(str).str.strip()
                same_day_pokedex["entry_type"] = same_day_pokedex["entry_type"].astype(str).str.strip().str.lower()
                same_day_pokedex["region"] = same_day_pokedex["region"].astype(str).str.strip().str.lower()
                same_day_pokedex = same_day_pokedex[
                    same_day_pokedex.apply(
                        lambda r: (str(r["entry_type"]), str(r["region"])) in set(editable_cells),
                        axis=1,
                    )
                ].copy()
                pokedex_counts = (
                    same_day_pokedex.assign(cell=same_day_pokedex["entry_type"] + ":" + same_day_pokedex["region"])
                    .groupby("account", as_index=False)["cell"]
                    .nunique()
                    .rename(columns={"cell": "entry_count"})
                )
                for _, row in pokedex_counts.iterrows():
                    account_name = str(row["account"]).strip()
                    entry_count = int(row["entry_count"])
                    if entry_count >= expected_pokedex_count:
                        complete_pokedex_on_date.add(account_name)
                    elif entry_count > 0:
                        partial_pokedex_counts[account_name] = entry_count

        available_pokedex_accounts = [a for a in pokedex_accounts if a not in complete_pokedex_on_date]
        if complete_pokedex_on_date:
            st.caption(f"Already entered for this date: {', '.join(sorted(complete_pokedex_on_date))}")
        if partial_pokedex_counts:
            partial_label = ", ".join(
                f"{acc} ({cnt}/{expected_pokedex_count})" for acc, cnt in sorted(partial_pokedex_counts.items())
            )
            st.caption(f"Partial Pokédex rows on this date: {partial_label}")
        if available_pokedex_accounts:
            st.caption(f"Missing for this date: {', '.join(available_pokedex_accounts)}")
            pokedex_account = st.selectbox(
                "Account (missing only for selected date)",
                options=available_pokedex_accounts,
                key="pokedex_entry_account",
            )
        else:
            st.success("Pokédex entry snapshot complete for selected date. No missing accounts.")
            pokedex_account = None

        if pokedex_account is None:
            st.info("Choose another date to enter new Pokédex counts.")
        else:
            latest_pokedex_rows = display_pokedex_df[display_pokedex_df["account"] == pokedex_account].copy()
            latest_vals: dict[tuple[str, str], float] = {}
            if not latest_pokedex_rows.empty:
                latest_pokedex_rows = latest_pokedex_rows[
                    pd.to_datetime(latest_pokedex_rows["date"], errors="coerce") <= pd.Timestamp(pokedex_date)
                ].copy()
                latest_pokedex_rows = latest_pokedex_rows.sort_values("date").drop_duplicates(
                    ["entry_type", "region"], keep="last"
                )
                latest_vals = {
                    (str(r["entry_type"]), str(r["region"])): float(r["value"])
                    for _, r in latest_pokedex_rows.iterrows()
                }

            def _fmt_pokedex_value(value: object) -> str:
                num = pd.to_numeric(value, errors="coerce")
                if pd.isna(num):
                    return "0"
                num_float = float(num)
                if num_float.is_integer():
                    return str(int(num_float))
                return f"{num_float:.2f}".rstrip("0").rstrip(".")

            complete_pokedex_entry_types_on_date: set[str] = set()
            if not pokedex_df.empty:
                account_day_pokedex = pokedex_df[
                    (pokedex_df["date"].dt.date == pokedex_date)
                    & (pokedex_df["account"].astype(str).str.strip() == str(pokedex_account).strip())
                ].copy()
                if not account_day_pokedex.empty:
                    account_day_pokedex["entry_type"] = (
                        account_day_pokedex["entry_type"].astype(str).str.strip().str.lower()
                    )
                    account_day_pokedex["region"] = account_day_pokedex["region"].astype(str).str.strip().str.lower()
                    for entry_type in POKEDEX_ENTRY_TYPES:
                        required_regions = {
                            region
                            for cell_entry_type, region in editable_cells
                            if cell_entry_type == entry_type
                        }
                        present_regions = set(
                            account_day_pokedex[account_day_pokedex["entry_type"] == entry_type]["region"].tolist()
                        )
                        if required_regions and required_regions.issubset(present_regions):
                            complete_pokedex_entry_types_on_date.add(entry_type)
            visible_pokedex_entry_types = [
                entry_type for entry_type in POKEDEX_ENTRY_TYPES if entry_type not in complete_pokedex_entry_types_on_date
            ]
            if complete_pokedex_entry_types_on_date:
                completed_labels = [
                    POKEDEX_ENTRY_TYPE_LABELS.get(entry_type, entry_type)
                    for entry_type in POKEDEX_ENTRY_TYPES
                    if entry_type in complete_pokedex_entry_types_on_date
                ]
                st.caption(f"Already saved categories for this date: {', '.join(completed_labels)}")

            st.markdown(f"Full Pokédex entries snapshot for `{pokedex_account}`")
            st.caption(
                "Grey Pokemon region values are derived from medal inputs. Locked cells and max values come from "
                "`inputs/config/pokedex_entry_config.csv`."
            )

            col_widths = [1.15] + [0.72] * len(POKEDEX_REGIONS) + [1.6]
            pokedex_input_col = st.container()
            header_cols = pokedex_input_col.columns(col_widths, gap="small")
            header_cols[0].markdown("**Type**")
            for idx, region in enumerate(POKEDEX_REGIONS, start=1):
                header_cols[idx].markdown(f"**{POKEDEX_REGION_LABELS.get(region, region)}**")
            header_cols[-1].markdown("**Status**")

            pokedex_existing_for_validation = (
                pokedex_df[["date", "account", "entry_type", "region", "value"]].copy()
                if not pokedex_df.empty
                else pd.DataFrame(columns=["date", "account", "entry_type", "region", "value"])
            )
            for entry_type in visible_pokedex_entry_types:
                category_draft_key = f"pokedex_draft_{pokedex_date.isoformat()}_{pokedex_account}_{entry_type}"
                category_status_key = f"pokedex_draft_status_{pokedex_date.isoformat()}_{pokedex_account}_{entry_type}"
                category_refresh_key = f"pokedex_draft_refresh_{pokedex_date.isoformat()}_{pokedex_account}_{entry_type}"
                with pokedex_input_col.container():
                    row_cols = st.columns(col_widths, gap="small")
                    row_cols[0].markdown(f"**{POKEDEX_ENTRY_TYPE_LABELS.get(entry_type, entry_type)}**")
                    row_inputs: list[dict[str, object]] = []
                    editable_regions_for_entry = [
                        region
                        for region in POKEDEX_REGIONS
                        if not _is_overall_pokedex_cell(region)
                        and not _is_medal_derived_pokedex_cell(entry_type, region)
                        and not bool(_pokedex_cell_config(entry_type, region).get("locked", False))
                    ]
                    last_editable_region = editable_regions_for_entry[-1] if editable_regions_for_entry else None
                    for idx, region in enumerate(POKEDEX_REGIONS, start=1):
                        last_value = latest_vals.get((entry_type, region), 0.0)
                        is_overall = _is_overall_pokedex_cell(region)
                        is_derived = _is_medal_derived_pokedex_cell(entry_type, region)
                        cell_config = _pokedex_cell_config(entry_type, region)
                        is_locked = bool(cell_config.get("locked", False))
                        max_value = cell_config.get("max_value")
                        config_notes = str(cell_config.get("notes", "")).strip()
                        value_default = _fmt_pokedex_value(last_value)
                        if is_overall or is_derived:
                            row_cols[idx].markdown(
                                f"<span style='color:#9ca3af'>{escape(value_default)}</span>",
                                unsafe_allow_html=True,
                            )
                            continue
                        if is_locked:
                            locked_value = max_value if max_value is not None else last_value
                            locked_label = _fmt_pokedex_value(locked_value)
                            note = f" title='{escape(config_notes)}'" if config_notes else ""
                            row_cols[idx].markdown(
                                f"<span style='color:#9ca3af'{note}>{escape(locked_label)}</span>",
                                unsafe_allow_html=True,
                            )
                            continue

                        input_key = f"pokedex_value_input_{pokedex_date.isoformat()}_{pokedex_account}_{entry_type}_{region}"
                        if input_key not in st.session_state:
                            st.session_state[input_key] = value_default
                        help_parts = []
                        if max_value is not None:
                            help_parts.append(f"Configured max: {_fmt_pokedex_value(max_value)}")
                        if config_notes:
                            help_parts.append(config_notes)
                        value_input = row_cols[idx].text_input(
                            f"{POKEDEX_ENTRY_TYPE_LABELS.get(entry_type, entry_type)} {POKEDEX_REGION_LABELS.get(region, region)}",
                            key=input_key,
                            label_visibility="collapsed",
                            help=" | ".join(help_parts) if help_parts else None,
                            on_change=mark_session_flag if region == last_editable_region else None,
                            args=(category_refresh_key,) if region == last_editable_region else None,
                        )
                        row_inputs.append(
                            {
                                "entry_type": entry_type,
                                "region": region,
                                "value": value_input,
                                "last_value": last_value,
                                "max_value": max_value,
                            }
                        )

                    if bool(st.session_state.pop(category_refresh_key, False)):
                        rows_to_write: list[dict[str, object]] = []
                        errors: list[str] = []
                        region_values: dict[str, object] = {}
                        category_changed = False
                        for r in row_inputs:
                            row_entry_type = str(r.get("entry_type", "")).strip().lower()
                            region = str(r.get("region", "")).strip().lower()
                            last_value = pd.to_numeric(r.get("last_value"), errors="coerce")
                            raw_value = r.get("value")
                            value = _parse_float_loose_value(raw_value)
                            max_value = r.get("max_value")
                            region_label = POKEDEX_REGION_LABELS.get(region, region)
                            if row_entry_type not in POKEDEX_ENTRY_TYPES:
                                errors.append(f"Invalid Pokédex entry type: {row_entry_type}")
                                continue
                            if region not in POKEDEX_REGIONS:
                                errors.append(f"Invalid Pokédex region: {region}")
                                continue
                            if value is None:
                                errors.append(f"{region_label} must be a number.")
                                continue
                            if float(value) < 0:
                                errors.append(f"{region_label} must be >= 0.")
                                continue
                            if max_value is not None and float(value) > float(max_value):
                                errors.append(f"{region_label} must be <= {_fmt_pokedex_value(max_value)}.")
                                continue
                            if pd.notna(last_value) and float(value) != float(last_value):
                                category_changed = True
                            region_values[region] = float(value)
                            row_df = pd.DataFrame(
                                [
                                    {
                                        "date": pd.Timestamp(pokedex_date),
                                        "account": pokedex_account,
                                        "entry_type": row_entry_type,
                                        "region": region,
                                        "value": float(value),
                                    }
                                ]
                            )
                            row_mono_errors = _validate_pokedex_entry_rows_non_decreasing(
                                pokedex_existing_for_validation,
                                row_df,
                            )
                            if row_mono_errors:
                                errors.append(row_mono_errors[0])
                                continue
                        if not errors:
                            rows_to_write = build_pokedex_category_snapshot_rows(
                                pokedex_date,
                                pokedex_account,
                                entry_type,
                                region_values,
                                entry_config=pokedex_entry_config,
                            )
                        st.session_state[category_draft_key] = {
                            "account": pokedex_account,
                            "entry_type": entry_type,
                            "rows": rows_to_write,
                            "inactive": False,
                            "changed": bool(category_changed),
                            "valid": not bool(errors),
                            "errors": errors,
                        }
                        st.session_state[category_status_key] = {
                            "valid": not bool(errors),
                            "inactive": False,
                            "changed": bool(category_changed),
                            "errors": errors,
                        }
                        if errors:
                            pass
                        else:
                            if category_changed:
                                pass
                            else:
                                pass
                    current_status = st.session_state.get(category_status_key)
                    if isinstance(current_status, dict):
                        if not bool(current_status.get("valid", False)):
                            row_cols[-1].caption("Draft error")
                        elif bool(current_status.get("changed", False)):
                            row_cols[-1].caption("Draft OK")
                        else:
                            row_cols[-1].caption("Unchanged")

            if st.button("Save all Pokédex changes", key="pokedex_final_save"):
                rows_to_write: list[dict[str, object]] = []
                final_errors: list[str] = []
                skipped_unchanged: list[str] = []
                for entry_type in visible_pokedex_entry_types:
                    category_draft_key = f"pokedex_draft_{pokedex_date.isoformat()}_{pokedex_account}_{entry_type}"
                    draft = st.session_state.get(category_draft_key)
                    if isinstance(draft, dict):
                        if not bool(draft.get("valid", False)):
                            final_errors.extend(
                                [
                                    f"{POKEDEX_ENTRY_TYPE_LABELS.get(entry_type, entry_type)}: {err}"
                                    for err in draft.get("errors", [])
                                ]
                            )
                            continue
                        should_write = bool(draft.get("changed", False)) or bool(draft.get("inactive", False))
                        if not should_write:
                            skipped_unchanged.append(POKEDEX_ENTRY_TYPE_LABELS.get(entry_type, entry_type))
                            continue
                        rows_to_write.extend(list(draft.get("rows", [])))
                    else:
                        skipped_unchanged.append(POKEDEX_ENTRY_TYPE_LABELS.get(entry_type, entry_type))
                if final_errors:
                    st.error("Fix Pokédex draft errors before saving:\n" + "\n".join(final_errors[:12]))
                elif not rows_to_write:
                    st.info("No changed or inactive Pokédex categories to save.")
                else:
                    try:
                        written = upsert_pokedex_entry_rows(
                            pokedex_entry_snapshots_path(),
                            rows_to_write,
                            entry_config=pokedex_entry_config,
                        )
                    except ValueError as e:
                        st.error(str(e))
                    else:
                        st.success(f"Saved Pokédex entry rows: {written} for {pokedex_account}")
                        if skipped_unchanged:
                            st.caption(
                                "Unchanged without inactive marker stayed open: "
                                + ", ".join(skipped_unchanged)
                            )

        with st.expander("Pokemon Catalog (1-1025)", expanded=False):
            st.caption("Reference data comes from `inputs/reference/pokemon_catalog.csv`; edit availability or notes in the CSV.")
            if pokemon_catalog_df.empty:
                st.warning("No Pokemon catalog found. Run `python tools/update_pokemon_catalog.py`.")
            else:
                st.dataframe(pokemon_catalog_df, use_container_width=True, hide_index=True)

if page == "Pipelines":
    st.subheader("Pipelines")
    c1, c2, c3 = st.columns(3)
    if c1.button("Run XP Plots"):
        rc, out = run_repo_command([sys.executable, "run_xp.py", "--no-show"])
        st.code(out or "(no output)", language="text")
        if rc == 0:
            st.success("XP pipeline finished.")
        else:
            st.error(f"XP pipeline failed with exit code {rc}.")

    if c2.button("Run Medal Report"):
        rc, out = run_repo_command([sys.executable, "run_medals.py"])
        st.code(out or "(no output)", language="text")
        if rc == 0:
            st.success("Medal report pipeline finished.")
        else:
            st.error(f"Medal pipeline failed with exit code {rc}.")

    if c3.button("Run Update All"):
        rc, out = run_repo_command([sys.executable, "update_all.py"])
        st.code(out or "(no output)", language="text")
        if rc == 0:
            st.success("update_all.py finished.")
        else:
            st.error(f"update_all.py failed with exit code {rc}.")

if page == "Generated Files":
    st.subheader("Generated PNGs")
    out_root = output_dir()
    folders = sorted([p for p in out_root.iterdir() if p.is_dir()]) if out_root.exists() else []
    if not folders:
        st.warning("No output folders found.")
    else:
        folder_names = [f.name for f in folders]
        selected_folder_name = st.selectbox("Folder", folder_names)
        folder = out_root / selected_folder_name
        pngs = sorted(folder.glob("*.png"), key=lambda p: p.name, reverse=True)
        if not pngs:
            st.warning("No PNG files in selected folder.")
        else:
            selected_png = st.selectbox("Image", [p.name for p in pngs])
            st.image(str(folder / selected_png), caption=selected_png, use_container_width=True)







