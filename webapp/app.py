from __future__ import annotations

import io
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
    config_dir,
    medal_explanations_path,
    medal_snapshots_path,
    medals_config_path,
    output_dir,
    player_groups_path,
    total_xp_curve_path,
    xp_history_path,
)
from webapp.metrics import (
    BASELINE_MIN_WINDOWS_DEFAULT,
    WINDOW_DAYS_DEFAULT,
    compute_player_kpis_window,
    recent_gain_table_from_metrics,
)

ACCOUNT_ORDER = ["Thombay", "Cerius", "Thomzay"]
MEDAL_INPUT_CORE_ACCOUNTS = ["Thombay", "Cerius", "Thomzay"]
MEDAL_EXPLORER_CORE_ACCOUNTS = ["Thombay", "Cerius", "Thomzay"]
DERIVED_MEDAL_ID = "platinum_medals"
DASHBOARD_WINDOW_OPTIONS = [7, 30]
MIN_ELIGIBLE_FOR_30D_DEFAULT = 2
TREND_MIN_DATE = pd.Timestamp("2025-01-01")
TREND_MIN_DATE_LABEL = "2025-01-01"
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
    "battles_won": "battle_girl",
    "distance_walked": "jogger",
    "pokemon_caught": "collector",
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


def to_int_series(series: pd.Series) -> pd.Series:
    cleaned = series.astype(str).str.replace(r"[^0-9\-]", "", regex=True)
    cleaned = cleaned.replace("", pd.NA)
    return pd.to_numeric(cleaned, errors="coerce")


def parse_groups(path: Path) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    if not path.exists():
        return groups

    current: str | None = None
    with open(path, "r", encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.endswith(":"):
                current = line[:-1].strip()
                groups.setdefault(current, [])
                continue
            if current is None:
                continue
            names = [x.strip() for x in line.split(",")]
            for name in names:
                if name and name != "...":
                    groups[current].append(name)

    for group, names in list(groups.items()):
        groups[group] = list(dict.fromkeys(names))
        if not groups[group]:
            groups.pop(group, None)
    return groups


def save_groups(path: Path, groups: dict[str, list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for group, names in groups.items():
        group_name = str(group).strip()
        if not group_name:
            continue
        unique_names: list[str] = []
        seen: set[str] = set()
        for raw_name in names:
            name = str(raw_name).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            unique_names.append(name)
        lines.append(f"{group_name}:")
        lines.append(",".join(unique_names))
        lines.append("")
    content = "\n".join(lines).rstrip() + "\n"
    path.write_text(content, encoding="utf-8-sig")


def add_account_to_groups(path: Path, account_name: str, target_groups: list[str] | None = None) -> list[str]:
    account = str(account_name).strip()
    if not account:
        return []

    groups = parse_groups(path)
    group_order = list(groups.keys())
    if "All" not in groups:
        groups["All"] = []
        group_order.append("All")

    requested = ["All"] + [str(g).strip() for g in (target_groups or []) if str(g).strip()]
    selected_groups: list[str] = []
    for group_name in requested:
        if group_name not in selected_groups:
            selected_groups.append(group_name)
        if group_name not in groups:
            groups[group_name] = []
            group_order.append(group_name)
        if account not in groups[group_name]:
            groups[group_name].append(account)

    ordered_groups = {group_name: groups.get(group_name, []) for group_name in group_order}
    save_groups(path, ordered_groups)
    return selected_groups


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


def load_curve_map(path: Path) -> dict[int, int]:
    if not path.exists():
        return {}
    curve = pd.read_csv(path, sep=";", engine="python", encoding="utf-8-sig")
    if not {"Level", "Total XP"}.issubset(curve.columns):
        return {}
    curve["Level"] = to_int_series(curve["Level"])
    curve["Total XP"] = to_int_series(curve["Total XP"])
    curve = curve.dropna(subset=["Level", "Total XP"]).copy()
    curve["Level"] = curve["Level"].astype(int)
    curve["Total XP"] = curve["Total XP"].astype(int)
    return dict(zip(curve["Level"], curve["Total XP"]))


def load_xp_history(path: Path, curve_map: dict[int, int]) -> pd.DataFrame:
    cols = ["Date", "Spieler", "Lvl", "XP Bar", "Total XP"]
    if not path.exists():
        return pd.DataFrame(columns=cols)

    hist = pd.read_csv(path, sep=";", engine="python", encoding="utf-8-sig")
    if not {"Date", "Spieler", "Lvl", "XP Bar"}.issubset(hist.columns):
        return pd.DataFrame(columns=cols)

    hist = hist.copy()
    hist["Date"] = pd.to_datetime(hist["Date"], errors="coerce")
    hist["Spieler"] = hist["Spieler"].astype(str).str.strip()
    hist["Lvl"] = to_int_series(hist["Lvl"])
    hist["XP Bar"] = to_int_series(hist["XP Bar"])
    hist = hist.dropna(subset=["Date", "Spieler", "Lvl", "XP Bar"]).copy()
    hist["Lvl"] = hist["Lvl"].astype(int)
    hist["XP Bar"] = hist["XP Bar"].astype(int)
    hist["base_xp"] = hist["Lvl"].map(curve_map)
    hist = hist.dropna(subset=["base_xp"]).copy()
    hist["Total XP"] = hist["base_xp"].astype(int) + hist["XP Bar"]
    return hist[cols].sort_values(["Date", "Spieler"]).reset_index(drop=True)


def load_medal_snapshots(path: Path) -> pd.DataFrame:
    cols = ["date", "account", "medal_id", "value"]
    if not path.exists():
        return pd.DataFrame(columns=cols)

    df = pd.read_csv(path, encoding="utf-8-sig")
    if not set(cols).issubset(df.columns):
        return pd.DataFrame(columns=cols)

    df = df.copy()
    df["date"] = df["date"].replace("", pd.NA).ffill()
    df["account"] = df["account"].replace("", pd.NA).ffill()
    df = df[df["date"].astype(str).str.upper() != "YYYY-MM-DD"].copy()
    df["medal_id"] = df["medal_id"].astype(str).str.strip().str.lower()
    df = df[~df["medal_id"].isin(EXCLUDED_MANUAL_MEDAL_IDS)].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["account"] = df["account"].astype(str).str.strip()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["date", "account", "medal_id", "value"]).copy()
    order_map = {name: i for i, name in enumerate(ACCOUNT_ORDER)}
    df["_acc_order"] = df["account"].map(order_map).fillna(999)
    df = df.sort_values(["date", "_acc_order", "account", "medal_id"]).drop(columns=["_acc_order"])
    return df.reset_index(drop=True)


def load_medal_goals(path: Path) -> pd.DataFrame:
    cols = ["medal_id", "display_name", "goal_value"]
    if not path.exists():
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(path, encoding="utf-8-sig")
    if not set(cols).issubset(df.columns):
        return pd.DataFrame(columns=cols)
    df = df.copy()
    df["medal_id"] = df["medal_id"].astype(str).str.strip().str.lower()
    df["goal_value"] = pd.to_numeric(df["goal_value"], errors="coerce")
    df = df.dropna(subset=["medal_id", "display_name", "goal_value"]).copy()
    return df[cols].drop_duplicates(subset=["medal_id"]).sort_values(["display_name", "medal_id"]).reset_index(
        drop=True
    )


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


def ensure_medal_explanations_file(path: Path, goals_df: pd.DataFrame) -> None:
    if path.exists():
        return
    medal_ids: list[str] = []
    if not goals_df.empty and "medal_id" in goals_df.columns:
        medal_ids = [
            goal_medal_id_for(mid)
            for mid in goals_df["medal_id"].astype(str).str.strip().str.lower().tolist()
            if str(mid).strip()
        ]
        medal_ids = [m for m in list(dict.fromkeys(medal_ids)) if m and m not in EXCLUDED_MANUAL_MEDAL_IDS]
    out = pd.DataFrame({"medal_id": medal_ids, "explanation": [""] * len(medal_ids)})
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, encoding="utf-8-sig")


def load_medal_explanations(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path, encoding="utf-8-sig", sep=None, engine="python")
    except Exception:
        try:
            df = pd.read_csv(path, encoding="utf-8-sig")
        except Exception:
            return {}
    if "medal_id" not in df.columns:
        return {}
    if "explanation" not in df.columns:
        df = df.copy()
        df["explanation"] = ""
    df = df[["medal_id", "explanation"]].copy()
    df["medal_id"] = df["medal_id"].fillna("").astype(str).str.strip().str.lower()
    df["medal_id"] = df["medal_id"].map(goal_medal_id_for)
    df["explanation"] = df["explanation"].fillna("").astype(str).str.strip()
    df["explanation_lc"] = df["explanation"].str.lower()
    df = df[
        (df["medal_id"] != "")
        & (df["explanation"] != "")
        & (~df["explanation_lc"].isin({"nan", "none", "null"}))
    ].copy()
    df = df.drop(columns=["explanation_lc"])
    return dict(zip(df["medal_id"].tolist(), df["explanation"].tolist()))


def _filter_trend_series(series: pd.DataFrame, date_col: str, value_col: str) -> pd.DataFrame:
    s = series.copy()
    s[date_col] = pd.to_datetime(s[date_col], errors="coerce")
    s[value_col] = pd.to_numeric(s[value_col], errors="coerce")
    s = s.dropna(subset=[date_col, value_col]).copy()
    s = s[s[date_col] >= TREND_MIN_DATE].copy()
    return s.sort_values(date_col)


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


def _predict_goal_eta(series: pd.DataFrame, goal_value: float) -> pd.Timestamp | None:
    s = _filter_trend_series(series, "date", "value")
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
    s = _filter_trend_series(series, "date", "value")
    if s.empty:
        return None
    eta = _predict_goal_eta(s[["date", "value"]], goal_value)
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

    latest_date = pd.Timestamp(s[date_col].iloc[-1]).normalize()
    goal = float(goal_value)
    reached_rows = s[pd.to_numeric(s[value_col], errors="coerce") >= goal]
    if not reached_rows.empty:
        reached_date = pd.Timestamp(reached_rows[date_col].iloc[0]).normalize()
        reached_txt = reached_date.date().isoformat()
        days_ahead = int((latest_date - reached_date).days)
        if days_ahead <= 0:
            return f"completed (reached {reached_txt})", "completed"
        return f"completed ({days_ahead}d ago, reached {reached_txt})", "completed"

    eta = _predict_goal_eta(
        s.rename(columns={date_col: "date", value_col: "value"})[["date", "value"]],
        goal,
    )
    if eta is None:
        return "behind (no ETA: trend too flat/negative)", "behind"
    eta_txt = pd.Timestamp(eta).date().isoformat()
    days_behind = int((pd.Timestamp(eta).normalize() - latest_date).days)
    if days_behind <= 0:
        return f"ahead (ETA {eta_txt})", "ahead"
    return f"{days_behind}d behind (ETA {eta_txt})", "behind"


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
            "ahead": "#16A34A",
            "behind": "#DC2626",
            "completed": "#2563EB",
            "unknown": "#64748B",
        }
        status_color = status_color_map.get(status_kind, "#64748B")
        rows.append(f"<span style='color:{status_color}'><b>{account_name}</b>: {escape(status_text)}</span>")

    if not rows:
        return None

    return (
        "<b>Goal Pace</b><br>"
        "<span style='color:#94A3B8'>relative to latest snapshot date</span><br>"
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
    if df.empty:
        return df.copy()
    ranges = df.groupby("Spieler")["Date"].agg(["min", "max"])
    if ranges.empty:
        return df.copy()

    events: list[tuple[pd.Timestamp, int]] = []
    for _, r in ranges.iterrows():
        start = pd.to_datetime(r["min"], errors="coerce")
        end = pd.to_datetime(r["max"], errors="coerce")
        if pd.isna(start) or pd.isna(end) or start > end:
            continue
        events.append((pd.Timestamp(start), 1))
        events.append((pd.Timestamp(end) + pd.Timedelta(nanoseconds=1), -1))
    if not events:
        return df.iloc[0:0].copy()

    events.sort(key=lambda x: x[0])
    idx = 0
    active = 0
    prev_time: pd.Timestamp | None = None
    segments: list[tuple[pd.Timestamp, pd.Timestamp, int]] = []
    while idx < len(events):
        current_time = events[idx][0]
        if prev_time is not None and current_time > prev_time and active > 0:
            segments.append((prev_time, current_time, active))
        while idx < len(events) and events[idx][0] == current_time:
            active += int(events[idx][1])
            idx += 1
        prev_time = current_time

    if not segments:
        return df.copy().sort_values(["Date", "Spieler"]).reset_index(drop=True)

    # Pick the interval that keeps the most rows ("most data"), not just most active players.
    scored_segments: list[tuple[pd.Timestamp, pd.Timestamp, int, int]] = []
    for start, end_exclusive, active_count in segments:
        row_count = int(((df["Date"] >= start) & (df["Date"] < end_exclusive)).sum())
        scored_segments.append((start, end_exclusive, active_count, row_count))

    best_start, best_end_exclusive, _active, _rows = max(
        scored_segments,
        key=lambda seg: (seg[3], seg[2], seg[1] - seg[0], -seg[0].value),
    )
    out = df[(df["Date"] >= best_start) & (df["Date"] < best_end_exclusive)].copy()
    return out.sort_values(["Date", "Spieler"]).reset_index(drop=True)


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
    s = s.sort_values("Date").drop_duplicates(subset=["Date"], keep="last")
    return s[["Date", "Total XP"]].reset_index(drop=True)


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


def inject_responsive_styles() -> None:
    st.markdown(
        """
        <style>
        :root { font-size: clamp(13px, 0.55vw + 10px, 18px); }
        .block-container { padding-top: 1rem; padding-bottom: 1.25rem; }
        @media (max-width: 1200px) {
          .block-container { padding-left: 1rem; padding-right: 1rem; }
        }
        @media (max-width: 860px) {
          .block-container { padding-left: 0.65rem; padding-right: 0.65rem; }
          h1 { font-size: 1.45rem !important; }
          h2, h3 { font-size: 1.2rem !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def select_date_range(
    label: str,
    min_date: date,
    max_date: date,
    key: str | None = None,
) -> tuple[date, date]:
    if min_date >= max_date:
        st.caption(f"{label}: only one snapshot date available ({min_date.isoformat()}).")
        return min_date, max_date
    slider_kwargs: dict[str, object] = {
        "label": label,
        "min_value": min_date,
        "max_value": max_date,
        "value": (min_date, max_date),
    }
    if key:
        slider_kwargs["key"] = key
    return st.slider(**slider_kwargs)


def render_xp_explorer_section(
    xp_subset_df: pd.DataFrame,
    key_prefix: str,
    medal_subset_df: pd.DataFrame | None = None,
    show_personal_activity: bool = False,
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
    common_interval_only = st.checkbox(
        "Use max-data interval (most selected-player rows)",
        value=True,
        key=f"{key_prefix}_common_interval",
    )

    df = xp_subset_df[xp_subset_df["Spieler"].isin(selected_players)].copy()
    if common_interval_only:
        df = restrict_to_common_interval(df)
    if df.empty:
        st.warning("No rows for selected filters.")
        return

    min_date = df["Date"].min().date()
    max_date = df["Date"].max().date()
    d_start, d_end = select_date_range(
        label="Date range",
        min_date=min_date,
        max_date=max_date,
        key=f"{key_prefix}_date_range",
    )
    df = df[(df["Date"] >= pd.Timestamp(d_start)) & (df["Date"] <= pd.Timestamp(d_end))].copy()
    if df.empty:
        st.warning("No rows in selected date range.")
        return

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
    default_leader = infer_default_gap_leader(df)
    default_idx = leader_options.index(default_leader) if default_leader in leader_options else 0
    leader_key = f"{key_prefix}_gap_leader"
    catchup_key = f"{key_prefix}_show_catchup_trends"
    if leader_key not in st.session_state or st.session_state.get(leader_key) not in leader_options:
        st.session_state[leader_key] = leader_options[default_idx]
    if catchup_key not in st.session_state:
        st.session_state[catchup_key] = True
    selected_leader = str(st.session_state.get(leader_key, leader_options[default_idx]))
    show_catchup_trends = bool(st.session_state.get(catchup_key, True))

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
        selected_leader = st.selectbox(
            "Gap/Trend Leader",
            options=leader_options,
            index=leader_options.index(selected_leader) if selected_leader in leader_options else default_idx,
            key=leader_key,
        )
    with controls_right:
        show_catchup_trends = st.checkbox(
            "Show catch-up trendlines",
            value=show_catchup_trends,
            key=catchup_key,
        )

    # Bottom row: total XP full width
    fig_total = px.line(
        df,
        x="Date",
        y="Total XP",
        color="Spieler",
        markers=True,
        title="Total XP Over Time",
    )
    trend_failures: list[str] = []
    latest_total_date = pd.to_datetime(df["Date"].max(), errors="coerce")
    if pd.isna(latest_total_date):
        latest_total_date = pd.Timestamp(d_end)
    auto_trend_end = pd.Timestamp(latest_total_date) + pd.DateOffset(years=1)
    if show_catchup_trends:
        color_by_player: dict[str, str | None] = {}
        for tr in fig_total.data:
            name = str(getattr(tr, "name", ""))
            color = getattr(getattr(tr, "line", None), "color", None)
            color_by_player[name] = color

        leader_series = df[df["Spieler"] == selected_leader][["Date", "Total XP"]].copy()
        longest_trend_end: pd.Timestamp | None = None
        fallback_players: list[tuple[str, pd.DataFrame, str | None]] = []
        for player, grp in df.groupby("Spieler", sort=True):
            player_name = str(player)
            if player_name == str(selected_leader):
                continue
            trend_trace, trend_reason = build_xp_catchup_projection_trace(
                grp[["Date", "Total XP"]],
                leader_series,
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
                fallback_players.append((player_name, grp[["Date", "Total XP"]].copy(), trend_reason))

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
            leader_series,
            str(selected_leader),
            color_by_player.get(str(selected_leader)),
            horizon_days=365,
            end_date=auto_trend_end,
        )
        if leader_trend_trace is not None:
            fig_total.add_trace(leader_trend_trace)
        elif leader_trend_reason:
            trend_failures.append(f"{selected_leader}: {leader_trend_reason}")

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
    fig_total.update_xaxes(range=[pd.Timestamp(d_start), pd.Timestamp(visibility_end)])
    y_range = autoscale_y_for_visible_x(
        fig_total,
        pd.Timestamp(d_start),
        pd.Timestamp(visibility_end),
        y_floor=0.0,
        padding_ratio=0.06,
    )
    if y_range is not None:
        fig_total.update_yaxes(range=[float(y_range[0]), float(y_range[1])], tickformat=",.0f")
    else:
        fig_total.update_yaxes(tickformat=",.0f")
    apply_total_xp_legend_order(fig_total, df)

    render_plotly_chart(fig_total, use_container_width=True, sort_legend=False)
    if show_catchup_trends and trend_failures:
        st.caption("Catch-up trendline status: " + " | ".join(trend_failures))

    if not show_personal_activity:
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
        existing["base_xp"] = existing["Lvl"].map(curve_map)
        existing["Total XP"] = pd.to_numeric(existing["base_xp"], errors="coerce") + pd.to_numeric(
            existing["XP Bar"], errors="coerce"
        )
        existing = existing.dropna(subset=["Date", "Spieler", "Total XP"]).copy()

    rows = new_df.drop_duplicates(subset=["Date", "Spieler"], keep="last").copy()
    rows["base_xp"] = rows["Lvl"].map(curve_map)
    for _, row in rows.iterrows():
        player = str(row["Spieler"]).strip()
        dt = pd.to_datetime(row["Date"], errors="coerce")
        lvl = pd.to_numeric(row["Lvl"], errors="coerce")
        xp_bar = pd.to_numeric(row["XP Bar"], errors="coerce")
        base_xp = pd.to_numeric(row["base_xp"], errors="coerce")
        if pd.isna(dt) or not player or pd.isna(lvl) or pd.isna(xp_bar):
            continue
        if pd.isna(base_xp):
            errors.append(f"{player} {pd.Timestamp(dt).date().isoformat()}: missing XP curve entry for level {int(lvl)}.")
            continue

        total_xp = int(base_xp) + int(xp_bar)
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

    existing = load_medal_snapshots(path)
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


def account_options_from_data(xp_df: pd.DataFrame, medal_df: pd.DataFrame) -> list[str]:
    players = set(xp_df["Spieler"].dropna().astype(str).tolist())
    accounts = set(medal_df["account"].dropna().astype(str).tolist())
    configured_groups = parse_groups(player_groups_path())
    group_accounts: set[str] = set()
    for names in configured_groups.values():
        for raw_name in names:
            name = str(raw_name).strip()
            if name:
                group_accounts.add(name)

    all_names = sorted(players | accounts | group_accounts | set(ACCOUNT_ORDER))
    ordered = [a for a in ACCOUNT_ORDER if a in all_names]
    fallback_order = ordered + [a for a in all_names if a not in ordered]
    return load_xp_input_order(fallback_order)


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


def build_xp_growth_figure(curve_map: dict[int, int], latest_df: pd.DataFrame) -> go.Figure | None:
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
                marker=dict(size=9, color="#ff4d4d"),
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


def accounts_for_selected_group(selected_group: str, groups: dict[str, list[str]], all_accounts: list[str]) -> list[str]:
    if selected_group == "All":
        return list(all_accounts)
    group_accounts = [str(a).strip() for a in groups.get(selected_group, []) if str(a).strip()]
    available = set(all_accounts)
    return [a for a in group_accounts if a in available]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(value).strip()).strip("_").lower()
    return slug or "group"


def _format_export_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.copy()
    for col in out.columns:
        col_l = str(col).lower()
        if "date" in col_l:
            dt = pd.to_datetime(out[col], errors="coerce")
            out[col] = dt.dt.strftime("%Y-%m-%d").where(dt.notna(), out[col].astype(str))
            continue
        if pd.api.types.is_numeric_dtype(out[col]):
            vals = pd.to_numeric(out[col], errors="coerce")
            if col_l == "pct_goal":
                out[col] = vals.map(lambda v: "" if pd.isna(v) else f"{float(v):.1f}")
            else:
                out[col] = vals.map(lambda v: "" if pd.isna(v) else f"{int(round(float(v))):,}")
    return out


def _df_section_html(title: str, df: pd.DataFrame) -> str:
    if df.empty:
        return f"<section><h2>{escape(title)}</h2><p>No data.</p></section>"
    out = _format_export_df(df)
    table_html = out.to_html(index=False, border=0, classes="report-table", escape=True)
    return f"<section><h2>{escape(title)}</h2>{table_html}</section>"


def _export_theme(mode: str) -> dict[str, object]:
    m = str(mode).strip().lower()
    if m == "light":
        return {
            "name": "Light",
            "template": "plotly_white",
            "paper_bg": "#ffffff",
            "plot_bg": "#ffffff",
            "font": "#0f172a",
            "grid": "rgba(15,23,42,0.12)",
            "line": "rgba(15,23,42,0.35)",
            "body_bg": "#f8fafc",
            "muted": "#475569",
            "card_bg": "#ffffff",
            "border": "#d0d7de",
            "table_bg": "#ffffff",
            "table_head": "#eef2f7",
            "colorway": ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#17becf", "#bcbd22", "#8c564b"],
            "max_width": "1400px",
            "base_font_size": "14px",
        }
    if m == "whatsapp":
        return {
            "name": "WhatsApp",
            "template": "plotly_white",
            "paper_bg": "#ffffff",
            "plot_bg": "#ffffff",
            "font": "#0b1f16",
            "grid": "rgba(11,31,22,0.10)",
            "line": "rgba(11,31,22,0.25)",
            "body_bg": "#ecfdf5",
            "muted": "#36524a",
            "card_bg": "#ffffff",
            "border": "#a7f3d0",
            "table_bg": "#ffffff",
            "table_head": "#d1fae5",
            "colorway": ["#0ea5a4", "#1d4ed8", "#16a34a", "#f59e0b", "#e11d48", "#7c3aed", "#0f766e", "#f97316"],
            "max_width": "980px",
            "base_font_size": "15px",
        }
    if m == "smartphone":
        return {
            "name": "Smartphone",
            "template": "plotly_white",
            "paper_bg": "#ffffff",
            "plot_bg": "#ffffff",
            "font": "#0f172a",
            "grid": "rgba(15,23,42,0.12)",
            "line": "rgba(15,23,42,0.30)",
            "body_bg": "#f8fafc",
            "muted": "#475569",
            "card_bg": "#ffffff",
            "border": "#d0d7de",
            "table_bg": "#ffffff",
            "table_head": "#eef2f7",
            "colorway": ["#0ea5a4", "#1d4ed8", "#16a34a", "#f59e0b", "#e11d48", "#7c3aed", "#0f766e", "#f97316"],
            "max_width": "430px",
            "base_font_size": "16px",
        }
    return {
        "name": "Dark",
        "template": "plotly_dark",
        "paper_bg": "#0b1220",
        "plot_bg": "#0f172a",
        "font": "#e5e7eb",
        "grid": "rgba(148,163,184,0.15)",
        "line": "rgba(148,163,184,0.35)",
        "body_bg": "#0b1220",
        "muted": "#b8c0cc",
        "card_bg": "#111827",
        "border": "#1f2937",
        "table_bg": "#0f172a",
        "table_head": "#1f2937",
        "colorway": ["#4fa3ff", "#22c55e", "#f59e0b", "#ef4444", "#a78bfa", "#14b8a6", "#f97316", "#eab308"],
        "max_width": "1400px",
        "base_font_size": "14px",
    }


def _style_export_figure(fig: go.Figure, mode: str) -> None:
    theme = _export_theme(mode)
    palette = [str(c) for c in theme["colorway"]]
    fig.update_layout(
        template=str(theme["template"]),
        paper_bgcolor=str(theme["paper_bg"]),
        plot_bgcolor=str(theme["plot_bg"]),
        font=dict(color=str(theme["font"])),
        colorway=list(theme["colorway"]),  # keep trace colors readable in exported HTML
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(
        gridcolor=str(theme["grid"]),
        zerolinecolor=str(theme["grid"]),
        linecolor=str(theme["line"]),
        automargin=True,
    )

    # Force readable trace colors in exported HTML across browsers/viewers.
    name_to_color: dict[str, str] = {}
    next_idx = 0
    for tr in fig.data:
        trace_name = str(getattr(tr, "name", "")).strip() or f"trace_{next_idx}"
        if trace_name not in name_to_color:
            name_to_color[trace_name] = palette[next_idx % len(palette)]
            next_idx += 1
        color = name_to_color[trace_name]
        trace_type = str(getattr(tr, "type", ""))
        if trace_type in {"scatter", "scattergl"}:
            tr.update(
                line=dict(color=color),
                marker=dict(color=color),
            )
        elif trace_type == "bar":
            tr.update(marker=dict(color=color))
    fig.update_yaxes(
        gridcolor=str(theme["grid"]),
        zerolinecolor=str(theme["grid"]),
        linecolor=str(theme["line"]),
        automargin=True,
    )


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
    dash_display_medal_df: pd.DataFrame,
    goals_df: pd.DataFrame,
    curve_map: dict[int, int],
    show_medals: bool,
    window_days: int,
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

    metric_cards: list[tuple[str, str, str]] = []
    if not dash_latest_xp_df.empty:
        leader_row = dash_latest_xp_df.sort_values("Total XP", ascending=False).iloc[0]
        metric_cards.append(
            (
                "XP Leader",
                f"{int(leader_row['Total XP']):,}",
                f"{leader_row['Spieler']} (Lvl {int(leader_row['Lvl'])})",
            )
        )
    else:
        metric_cards.append(("XP Leader", "-", "no data"))

    if not active_kpi_pool.empty:
        gain_leader = active_kpi_pool.sort_values([xp_gain_col, xp_per_day_col], ascending=[False, False]).iloc[0]
        metric_cards.append(
            (
                f"Top XP Gain ({w_label})",
                format_kpi_number(gain_leader[xp_gain_col], "XP"),
                winner_with_level(gain_leader["Spieler"]),
            )
        )
        gain_trailer = active_kpi_pool.sort_values([xp_gain_col, xp_per_day_col], ascending=[True, True]).iloc[0]
        metric_cards.append(
            (
                f"Least XP Gain ({w_label})",
                format_kpi_number(gain_trailer[xp_gain_col], "XP"),
                winner_with_level(gain_trailer["Spieler"]),
            )
        )
    elif not eligible_gain_pool.empty:
        metric_cards.append((f"Top XP Gain ({w_label})", f"No active players ({w_label})", f"all {xp_gain_col} = 0"))
        metric_cards.append((f"Least XP Gain ({w_label})", f"No active players ({w_label})", f"all {xp_gain_col} = 0"))
    else:
        metric_cards.append((f"Top XP Gain ({w_label})", "-", "no data"))
        metric_cards.append((f"Least XP Gain ({w_label})", "-", "no data"))

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
            metric_cards.append(("Team Platinum Total", f"{team_platinum_total:,}", " | ".join(breakdown)))
        else:
            metric_cards.append(("Team Platinum Total", "-", "no data"))
    else:
        if active_kpi_pool.empty:
            if not eligible_gain_pool.empty:
                metric_cards.append((f"Fastest {w_label} Pace", f"No active players ({w_label})", f"all {xp_gain_col} = 0"))
            else:
                metric_cards.append((f"Fastest {w_label} Pace", "-", "no data"))
        else:
            fastest = active_kpi_pool.sort_values([xp_per_day_col, xp_gain_col], ascending=[False, False]).iloc[0]
            metric_cards.append(
                (
                    f"Fastest {w_label} Pace",
                    format_kpi_number(fastest[xp_per_day_col], "XP/day"),
                    winner_with_level(fastest["Spieler"]),
                )
            )

        if eligible_baseline_pool.empty:
            metric_cards.append((f"Most Improved vs Baseline ({w_label})", "-", "no baseline-eligible data"))
            metric_cards.append((f"Most Declined vs Baseline ({w_label})", "-", "no baseline-eligible data"))
        elif baseline_headline_pool.empty:
            metric_cards.append(
                (
                    f"Most Improved vs Baseline ({w_label})",
                    "No improvements",
                    f"all {xp_gain_col} = 0 for baseline-eligible players",
                )
            )
            metric_cards.append(
                (
                    f"Most Declined vs Baseline ({w_label})",
                    "No decline",
                    f"all {xp_gain_col} = 0 for baseline-eligible players",
                )
            )
        else:
            improvements = baseline_headline_pool[baseline_headline_pool[delta_col] > 0].copy()
            if improvements.empty:
                metric_cards.append(
                    (
                        f"Most Improved vs Baseline ({w_label})",
                        "No improvements",
                        "all deltas <= 0",
                    )
                )
            else:
                improved = improvements.sort_values(delta_col, ascending=False).iloc[0]
                metric_cards.append(
                    (
                        f"Most Improved vs Baseline ({w_label})",
                        format_kpi_number(improved[xp_per_day_col], "XP/day"),
                        (
                            f"{winner_with_level(improved['Spieler'])} | "
                            f"{int(round(float(improved[delta_col]))):+,} XP/day vs baseline"
                        ),
                    )
                )
            declines = baseline_headline_pool[baseline_headline_pool[delta_col] < 0].copy()
            if declines.empty:
                metric_cards.append(
                    (
                        f"Most Declined vs Baseline ({w_label})",
                        "No decline",
                        "all deltas >= 0",
                    )
                )
            else:
                declined = declines.sort_values(delta_col, ascending=True).iloc[0]
                metric_cards.append(
                    (
                        f"Most Declined vs Baseline ({w_label})",
                        format_kpi_number(declined[xp_per_day_col], "XP/day"),
                        (
                            f"{winner_with_level(declined['Spieler'])} | "
                            f"{int(round(float(declined[delta_col]))):+,} XP/day vs baseline"
                        ),
                    )
                )

    if not dash_latest_xp_df.empty:
        latest_xp_date = pd.to_datetime(dash_latest_xp_df["Date"], errors="coerce").max()
        if pd.notna(latest_xp_date):
            days_ago = (pd.Timestamp.today().normalize() - latest_xp_date.normalize()).days
            metric_cards.append(("Last XP Snapshot", latest_xp_date.strftime("%Y-%m-%d"), f"{int(days_ago)} day(s) ago"))
        else:
            metric_cards.append(("Last XP Snapshot", "-", "no data"))
    else:
        metric_cards.append(("Last XP Snapshot", "-", "no data"))
    metric_cards.append(
        (
            f"Coverage ({w_label} / baseline)",
            f"{eligible_window}/{total_players}",
            f"{eligible_baseline_window}/{total_players} | active {active_kpi_count}/{total_players}",
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
        ].copy()
        fig_growth = build_xp_growth_figure(curve_map, dash_latest_xp_df)

        if not dash_recent_gain_df.empty:
            gain_top = dash_recent_gain_df.sort_values("xp_gain", ascending=False).head(10).copy()
            fig_gain = px.bar(
                gain_top.sort_values("xp_gain", ascending=True),
                x="xp_gain",
                y="Spieler",
                orientation="h",
                title=f"Top XP Gain ({w_label})",
                labels={"xp_gain": "XP Gain", "Spieler": "Account"},
            )
            gain_height = max(320, 34 * len(gain_top) + 80)
            fig_gain.update_layout(height=gain_height, margin=dict(l=150, r=30, t=45, b=35))
            fig_gain.update_xaxes(tickformat=",")
            fig_gain.update_yaxes(automargin=True)
            gain_view = gain_top[["Spieler", "xp_gain", "xp_per_day"]].copy()

    xp_explorer_df = dash_xp_df.copy()
    if not xp_explorer_df.empty:
        xp_explorer_df = restrict_to_common_interval(xp_explorer_df)
        if xp_explorer_df.empty:
            xp_explorer_df = dash_xp_df.copy()
        xp_explorer_df = xp_explorer_df.sort_values(["Date", "Spieler"]).copy()

        gain_over_time_df = build_xp_gain_over_time_df(xp_explorer_df)
        fig_xp_gain_over_time = px.line(
            gain_over_time_df,
            x="Date",
            y="XP Gain",
            color="Spieler",
            markers=True,
            title="XP Gain Over Time",
        )

        fig_xp_total = px.line(
            xp_explorer_df,
            x="Date",
            y="Total XP",
            color="Spieler",
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

        gap_df = build_gap_change_df(xp_explorer_df)
        if not gap_df.empty:
            fig_gap = px.line(
                gap_df,
                x="Date",
                y="Gap Change",
                color="Spieler",
                markers=True,
                title="Gap Change Since First Snapshot",
            )
            fig_gap.add_hline(
                y=0,
                line_dash="dash",
                annotation_text=gap_baseline_annotation_text(gap_df),
                annotation_position="bottom right",
            )

        pace_df = build_pace_df(xp_explorer_df)
        if not pace_df.empty:
            fig_pace = px.line(
                pace_df,
                x="Date",
                y="XP/day",
                color="Spieler",
                markers=True,
                title="Interval Pace (XP/day)",
            )

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

    sections: list[tuple[str, pd.DataFrame]] = [
        ("Current XP Ranking", ranking_view),
        (f"XP Gain Table (Last {w} Days)", gain_view),
    ]
    if show_medals:
        sections.append(("Latest Medal Status", latest_medals_view))
        sections.append(("Latest Achieved Platinum Medals", first_achieved_view))

    accounts_text = ", ".join([str(a) for a in selected_accounts]) if selected_accounts else "-"
    generated_at = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "metric_cards": metric_cards,
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
    dash_display_medal_df: pd.DataFrame,
    goals_df: pd.DataFrame,
    curve_map: dict[int, int],
    show_medals: bool,
    export_mode: str,
    window_days: int,
) -> str:
    def _render_payload_block(payload: dict[str, object], include_js: bool, mode: str) -> tuple[str, bool]:
        metric_cards = payload["metric_cards"]
        chart_items = payload["chart_items"]
        sections_data = payload["sections"]
        chart_blocks: list[str] = []
        include_plotly = include_js
        for chart_title, fig in chart_items:
            if fig is None:
                continue
            sort_legend_by_latest_y(fig)
            _style_export_figure(fig, mode)
            chart_blocks.append(f"<section><h2>{escape(chart_title)}</h2>")
            chart_blocks.append(
                fig.to_html(
                    full_html=False,
                    include_plotlyjs="inline" if include_plotly else False,
                    config={"displaylogo": False},
                )
            )
            chart_blocks.append("</section>")
            include_plotly = False

        cards_html = "".join(
            [
                (
                    "<div class='metric-card'>"
                    f"<div class='metric-label'>{escape(lbl)}</div>"
                    f"<div class='metric-value'>{escape(val)}</div>"
                    f"<div class='metric-delta'>{escape(delta)}</div>"
                    "</div>"
                )
                for (lbl, val, delta) in metric_cards
            ]
        )
        sections_html = "".join([_df_section_html(str(title), df) for (title, df) in sections_data])
        block_html = f"<div class='metrics'>{cards_html}</div>{''.join(chart_blocks)}{sections_html}"
        return block_html, include_plotly

    layout_theme = _export_theme(export_mode)
    dark_theme = _export_theme("dark")
    light_theme = _export_theme("light")
    default_theme_mode = "dark" if str(export_mode).strip().lower() == "dark" else "light"
    default_theme_label = "Dark" if default_theme_mode == "dark" else "Light"

    default_window = int(window_days)
    export_windows = [int(w) for w in DASHBOARD_WINDOW_OPTIONS]
    if default_window not in export_windows:
        export_windows = sorted(set(export_windows + [default_window]))

    payloads_by_window: dict[int, dict[str, object]] = {}
    for w in export_windows:
        payloads_by_window[w] = _build_dashboard_export_payload(
            selected_accounts=selected_accounts,
            dash_xp_df=dash_xp_df,
            dash_medal_df=dash_medal_df,
            dash_display_medal_df=dash_display_medal_df,
            goals_df=goals_df,
            curve_map=curve_map,
            show_medals=show_medals,
            window_days=w,
        )

    base_payload = payloads_by_window.get(default_window) or payloads_by_window[export_windows[0]]
    accounts_text = str(base_payload["accounts_text"])
    generated_at = str(base_payload["generated_at"])

    include_js = True
    window_panes: list[str] = []
    for w in export_windows:
        for theme_mode in ["dark", "light"]:
            block_html, include_js = _render_payload_block(payloads_by_window[w], include_js=include_js, mode=theme_mode)
            display_mode = "block" if int(w) == int(default_window) and theme_mode == default_theme_mode else "none"
            window_panes.append(
                (
                    f"<div class='window-pane theme-pane' "
                    f"id='window-pane-{int(w)}-{theme_mode}' "
                    f"data-window='{int(w)}' data-theme='{theme_mode}' "
                    f"style='display:{display_mode};'>{block_html}</div>"
                )
            )

    window_buttons = "".join(
        [
            (
                f"<button type='button' class='window-btn' id='window-btn-{int(w)}' "
                f"onclick='setWindow({int(w)})'>{int(w)}d</button>"
            )
            for w in export_windows
        ]
    )
    theme_buttons = "".join(
        [
            "<button type='button' class='theme-btn' id='theme-btn-dark' onclick=\"setTheme('dark')\">Dark</button>",
            "<button type='button' class='theme-btn' id='theme-btn-light' onclick=\"setTheme('light')\">Light</button>",
        ]
    )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{escape(dashboard_title)} - {escape(selected_group)}</title>
  <style>
    :root {{
      --body-bg: {dark_theme["body_bg"]};
      --font: {dark_theme["font"]};
      --muted: {dark_theme["muted"]};
      --card-bg: {dark_theme["card_bg"]};
      --border: {dark_theme["border"]};
      --table-bg: {dark_theme["table_bg"]};
      --table-head: {dark_theme["table_head"]};
      --line: {dark_theme["line"]};
    }}
    body.theme-dark {{
      --body-bg: {dark_theme["body_bg"]};
      --font: {dark_theme["font"]};
      --muted: {dark_theme["muted"]};
      --card-bg: {dark_theme["card_bg"]};
      --border: {dark_theme["border"]};
      --table-bg: {dark_theme["table_bg"]};
      --table-head: {dark_theme["table_head"]};
      --line: {dark_theme["line"]};
    }}
    body.theme-light {{
      --body-bg: {light_theme["body_bg"]};
      --font: {light_theme["font"]};
      --muted: {light_theme["muted"]};
      --card-bg: {light_theme["card_bg"]};
      --border: {light_theme["border"]};
      --table-bg: {light_theme["table_bg"]};
      --table-head: {light_theme["table_head"]};
      --line: {light_theme["line"]};
    }}
    body {{ background:var(--body-bg); color:var(--font); font-family:Segoe UI, Arial, sans-serif; margin:20px; font-size:{layout_theme["base_font_size"]}; }}
    .container {{ max-width:{layout_theme["max_width"]}; margin:0 auto; }}
    h1, h2 {{ margin:0 0 10px 0; }}
    p {{ color:var(--muted); }}
    .meta {{ margin-bottom:12px; }}
    .switch-row {{ display:flex; align-items:center; gap:10px; margin-bottom:14px; }}
    .switch-label {{ color:var(--muted); font-size:13px; }}
    .window-switch, .theme-switch {{ display:flex; gap:8px; }}
    .window-btn, .theme-btn {{ background:var(--card-bg); color:var(--font); border:1px solid var(--border); border-radius:8px; padding:4px 10px; cursor:pointer; font-size:13px; }}
    .window-btn.active, .theme-btn.active {{ background:var(--table-head); border-color:var(--line); font-weight:600; }}
    .metrics {{ display:grid; grid-template-columns:repeat(4,minmax(180px,1fr)); gap:12px; margin:14px 0 18px 0; }}
    .window-pane {{ width:100%; }}
    .metric-card {{ background:var(--card-bg); border:1px solid var(--border); border-radius:10px; padding:12px; }}
    .metric-label {{ color:var(--muted); font-size:12px; }}
    .metric-value {{ font-size:30px; margin:8px 0 6px 0; }}
    .metric-delta {{ color:var(--font); opacity:0.9; font-size:13px; min-height:16px; }}
    section {{ margin-bottom:18px; }}
    .report-table {{ width:100%; border-collapse:collapse; background:var(--table-bg); border:1px solid var(--border); }}
    .report-table th, .report-table td {{ border:1px solid var(--border); padding:6px 8px; text-align:left; }}
    .report-table th {{ background:var(--table-head); }}
    @media (max-width: 1000px) {{
      .metrics {{ grid-template-columns:repeat(2,minmax(160px,1fr)); }}
    }}
    @media (max-width: 520px) {{
      body {{ margin:10px; }}
      .metrics {{ grid-template-columns:1fr; }}
      .window-switch, .theme-switch {{ flex-wrap:wrap; }}
    }}
  </style>
</head>
<body class="theme-{default_theme_mode}">
  <div class="container">
  <h1>{escape(dashboard_title)}</h1>
  <div class="meta">
    <p><strong>Group:</strong> {escape(selected_group)}</p>
    <p><strong>Window:</strong> <span id="window-value">{int(default_window)}d</span></p>
    <p><strong>Theme:</strong> <span id="theme-value">{default_theme_label}</span></p>
    <p><strong>Accounts:</strong> {escape(accounts_text)}</p>
    <p><strong>Generated:</strong> {escape(generated_at)}</p>
  </div>
  <div class="switch-row">
    <span class="switch-label"><strong>Window:</strong></span>
    <div class="window-switch">{window_buttons}</div>
  </div>
  <div class="switch-row">
    <span class="switch-label"><strong>Theme:</strong></span>
    <div class="theme-switch">{theme_buttons}</div>
  </div>
  {''.join(window_panes)}
  </div>
  <script>
    const exportWindows = [{", ".join(str(int(w)) for w in export_windows)}];
    const exportThemes = ["dark", "light"];
    let activeWindow = {int(default_window)};
    let activeTheme = "{default_theme_mode}";
    function paneId(windowDays, themeMode) {{
      return `window-pane-${{windowDays}}-${{themeMode}}`;
    }}
    function resizePlotsInPane(windowDays, themeMode) {{
      const pane = document.getElementById(paneId(windowDays, themeMode));
      if (!pane || !window.Plotly || !window.Plotly.Plots) return;
      const plotEls = pane.querySelectorAll(".js-plotly-plot, .plotly-graph-div");
      plotEls.forEach((el) => {{
        try {{
          window.Plotly.Plots.resize(el);
        }} catch (_err) {{
          // no-op: keep export HTML resilient if one chart cannot be resized
        }}
      }});
    }}
    function applyThemeClass(themeMode) {{
      document.body.classList.toggle("theme-dark", themeMode === "dark");
      document.body.classList.toggle("theme-light", themeMode === "light");
    }}
    function renderState() {{
      exportWindows.forEach((w) => {{
        const winBtn = document.getElementById(`window-btn-${{w}}`);
        if (winBtn) winBtn.classList.toggle("active", Number(w) === Number(activeWindow));
        exportThemes.forEach((t) => {{
          const pane = document.getElementById(paneId(w, t));
          const active = Number(w) === Number(activeWindow) && t === activeTheme;
          if (pane) pane.style.display = active ? "block" : "none";
        }});
      }});
      exportThemes.forEach((t) => {{
        const themeBtn = document.getElementById(`theme-btn-${{t}}`);
        if (themeBtn) themeBtn.classList.toggle("active", t === activeTheme);
      }});
      const windowLabel = document.getElementById("window-value");
      if (windowLabel) windowLabel.textContent = `${{activeWindow}}d`;
      const themeLabel = document.getElementById("theme-value");
      if (themeLabel) themeLabel.textContent = activeTheme === "dark" ? "Dark" : "Light";
      if (window.requestAnimationFrame) {{
        window.requestAnimationFrame(() => resizePlotsInPane(activeWindow, activeTheme));
      }} else {{
        resizePlotsInPane(activeWindow, activeTheme);
      }}
      window.setTimeout(() => resizePlotsInPane(activeWindow, activeTheme), 60);
    }}
    function setWindow(windowDays) {{
      activeWindow = Number(windowDays);
      renderState();
    }}
    function setTheme(themeMode) {{
      activeTheme = themeMode === "dark" ? "dark" : "light";
      applyThemeClass(activeTheme);
      renderState();
    }}
    applyThemeClass(activeTheme);
    renderState();
  </script>
</body>
</html>
"""
    return html


def _figure_to_png_via_subprocess(fig: go.Figure, width: int, height: int, scale: int = 2) -> tuple[bytes | None, str | None]:
    script = r"""
import json
import sys
import plotly.graph_objects as go

w = int(sys.argv[1])
h = int(sys.argv[2])
s = int(sys.argv[3])
raw = sys.stdin.buffer.read().decode("utf-8")
fig = go.Figure(json.loads(raw))
out = fig.to_image(format="png", width=w, height=h, scale=s)
sys.stdout.buffer.write(out)
"""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script, str(int(width)), str(int(height)), str(int(scale))],
            input=fig.to_json().encode("utf-8"),
            capture_output=True,
            check=False,
            timeout=120,
        )
    except Exception as e:
        return None, str(e)
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", errors="ignore").strip()
        return None, err or f"subprocess exited with code {proc.returncode}"
    return bytes(proc.stdout or b""), None


def build_dashboard_export_png(
    dashboard_title: str,
    selected_group: str,
    selected_accounts: list[str],
    dash_xp_df: pd.DataFrame,
    dash_medal_df: pd.DataFrame,
    dash_display_medal_df: pd.DataFrame,
    goals_df: pd.DataFrame,
    curve_map: dict[int, int],
    show_medals: bool,
    export_mode: str,
    window_days: int,
) -> tuple[bytes | None, str | None]:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None, "Picture export requires `Pillow`. Install dependencies and retry."

    payload = _build_dashboard_export_payload(
        selected_accounts=selected_accounts,
        dash_xp_df=dash_xp_df,
        dash_medal_df=dash_medal_df,
        dash_display_medal_df=dash_display_medal_df,
        goals_df=goals_df,
        curve_map=curve_map,
        show_medals=show_medals,
        window_days=window_days,
    )
    theme = _export_theme(export_mode)
    chart_items: list[tuple[str, go.Figure | None]] = payload["chart_items"]
    sections_data: list[tuple[str, pd.DataFrame]] = payload["sections"]
    metric_cards: list[tuple[str, str, str]] = payload["metric_cards"]
    accounts_text = str(payload["accounts_text"])
    generated_at = str(payload["generated_at"])

    width = 900 if str(export_mode).strip().lower() == "smartphone" else 1800
    pad = 20
    bg = str(theme["body_bg"])
    fg = str(theme["font"])
    card_bg = str(theme["card_bg"])
    border = str(theme["border"])
    muted = str(theme["muted"])

    def _load_font(candidates: list[str], size: int) -> "ImageFont.ImageFont":
        for fp in candidates:
            try:
                p = Path(fp)
                if p.exists():
                    return ImageFont.truetype(str(p), size=size)
            except Exception:
                continue
        return ImageFont.load_default()

    font_title = _load_font(["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"], 36)
    font_section = _load_font(["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"], 24)
    font_body = _load_font(["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"], 18)
    font_mono = _load_font(["C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/cour.ttf"], 16)

    def _line_height(font_obj: "ImageFont.ImageFont") -> int:
        try:
            box = font_obj.getbbox("Ag")
            return max(16, (box[3] - box[1]) + 6)
        except Exception:
            return 22

    def text_block(
        title: str,
        lines: list[str],
        title_color: str | None = None,
        title_font: "ImageFont.ImageFont | None" = None,
        body_font: "ImageFont.ImageFont | None" = None,
    ) -> "Image.Image":
        tcol = title_color or fg
        tf = title_font or font_section
        bf = body_font or font_body
        title_h = _line_height(tf)
        line_h = _line_height(bf)
        body_rows = len(lines)
        block_h = pad * 2 + title_h + (body_rows * line_h if body_rows else 0)
        img = Image.new("RGB", (width, block_h), card_bg)
        draw = ImageDraw.Draw(img)
        draw.rectangle([(0, 0), (width - 1, block_h - 1)], outline=border, width=1)
        draw.text((pad, pad), title, fill=tcol, font=tf)
        y = pad + title_h
        for ln in lines:
            draw.text((pad, y), ln, fill=fg, font=bf)
            y += line_h
        return img

    blocks: list["Image.Image"] = []
    header_lines = [
        f"Group: {selected_group}",
        f"Window: {int(window_days)}d",
        f"Export Mode: {theme['name']}",
        f"Accounts: {accounts_text}",
        f"Generated: {generated_at}",
    ]
    blocks.append(text_block(dashboard_title, header_lines, title_color=fg, title_font=font_title, body_font=font_body))
    metric_lines = [f"{lbl}: {val} ({delta})" for (lbl, val, delta) in metric_cards]
    blocks.append(text_block("Metrics", metric_lines, title_color=muted, title_font=font_section, body_font=font_body))

    for chart_title, fig in chart_items:
        if fig is None:
            continue
        sort_legend_by_latest_y(fig)
        _style_export_figure(fig, export_mode)
        try:
            h = int(fig.layout.height) if getattr(fig.layout, "height", None) else 520
            png_bytes = fig.to_image(format="png", width=width, height=max(320, h), scale=2)
        except Exception as e:
            msg = str(e).strip()
            if "broadcast_args_to_dicts" in msg or "plotly.io._utils" in msg:
                png_bytes, sub_err = _figure_to_png_via_subprocess(fig, width=width, height=max(320, h), scale=2)
                if png_bytes:
                    pass
                else:
                    detail = f" ({sub_err})" if sub_err else ""
                    return None, (
                        "Picture export failed due to mixed Plotly/Kaleido runtime. "
                        f"Restart Streamlit after dependency updates (`python run_server.py`).{detail}"
                    )
            if "Chrome" in msg or "chrom" in msg.lower():
                return None, (
                    "Picture export needs Chrome for Kaleido v1. "
                    "Install Chrome and retry."
                )
            if msg:
                return None, f"Picture export failed: {msg}"
            return None, "Picture export failed while rendering Plotly images."
        chart_img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        if chart_img.width != width:
            new_h = int(chart_img.height * (width / chart_img.width))
            chart_img = chart_img.resize((width, new_h))
        blocks.append(chart_img)

    for sec_title, sec_df in sections_data:
        if sec_df.empty:
            blocks.append(text_block(sec_title, ["No data."], title_color=muted, title_font=font_section, body_font=font_body))
            continue
        formatted = _format_export_df(sec_df)
        preview_rows = min(len(formatted), 40)
        table_text = formatted.head(preview_rows).to_string(index=False).splitlines()
        lines = table_text
        if len(formatted) > preview_rows:
            lines += [f"... ({len(formatted) - preview_rows} more rows)"]
        blocks.append(text_block(sec_title, lines, title_color=muted, title_font=font_section, body_font=font_mono))

    total_h = pad
    for b in blocks:
        total_h += b.height + pad
    canvas = Image.new("RGB", (width + (pad * 2), total_h), bg)
    y = pad
    for b in blocks:
        canvas.paste(b, (pad, y))
        y += b.height + pad

    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue(), None


def render_dashboard_export_button(
    dashboard_title: str,
    selected_group: str,
    selected_accounts: list[str],
    dash_xp_df: pd.DataFrame,
    dash_medal_df: pd.DataFrame,
    dash_display_medal_df: pd.DataFrame,
    goals_df: pd.DataFrame,
    curve_map: dict[int, int],
    show_medals: bool,
    window_days: int,
    key: str,
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
            dash_display_medal_df=dash_display_medal_df,
            goals_df=goals_df,
            curve_map=curve_map,
            show_medals=show_medals,
            export_mode=export_mode,
            window_days=window_days,
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
        dash_display_medal_df=dash_display_medal_df,
        goals_df=goals_df,
        curve_map=curve_map,
        show_medals=show_medals,
        export_mode=export_mode,
        window_days=window_days,
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
    dash_display_medal_df: pd.DataFrame,
    goals_df: pd.DataFrame,
    curve_map: dict[int, int],
    show_medals: bool,
    window_days: int,
    window_state_key: str,
    show_30d_limited_hint: bool,
) -> None:
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

    if window_state_key not in st.session_state:
        st.session_state[window_state_key] = int(w)

    if show_medals:
        c1, c2, c3, c4, c5, c6 = st.columns([1, 1, 1, 1, 1, 0.9])
        last_snapshot_col = c5
        window_control_col = c6
    else:
        c1, c2, c3, c4, c5, c6, c7, c8 = st.columns([1, 1, 1, 1, 1, 1, 1, 0.9])
        last_snapshot_col = c7
        window_control_col = c8
    if not dash_latest_xp_df.empty:
        leader_row = dash_latest_xp_df.sort_values("Total XP", ascending=False).iloc[0]
        render_kpi_card(
            c1,
            "XP Leader",
            format_kpi_number(leader_row["Total XP"], "XP"),
            winner=winner_with_level(leader_row["Spieler"]),
            context=f"Level {int(leader_row['Lvl'])}",
            help_text="Latest total XP snapshot per player.",
        )
    else:
        render_kpi_card(c1, "XP Leader", "-", context="no data")

    if not active_kpi_pool.empty:
        gain_leader = active_kpi_pool.sort_values([xp_gain_col, xp_per_day_col], ascending=[False, False]).iloc[0]
        gain_to_date = pd.to_datetime(gain_leader[window_end_col], errors="coerce")
        render_kpi_card(
            c2,
            f"Top XP Gain ({w_label})",
            format_kpi_number(gain_leader[xp_gain_col], "XP"),
            winner=winner_with_level(gain_leader["Spieler"]),
            context=f"{format_kpi_number(gain_leader[xp_per_day_col], 'XP/day')} pace",
            help_text=(
                f"{w}-day rolling XP gain (xp_at(now) - xp_at(now-{w}d)).\n"
                f"Window end: {gain_to_date.strftime('%Y-%m-%d') if pd.notna(gain_to_date) else '-'}"
            ),
        )
    elif not eligible_gain_pool.empty:
        render_kpi_card(
            c2,
            f"Top XP Gain ({w_label})",
            f"No active players ({w_label})",
            context=f"all {xp_gain_col} = 0",
            delta_color="off",
        )
    else:
        render_kpi_card(c2, f"Top XP Gain ({w_label})", "-", context="no data")

    if not active_kpi_pool.empty:
        gain_trailer = active_kpi_pool.sort_values([xp_gain_col, xp_per_day_col], ascending=[True, True]).iloc[0]
        gain_trailer_to_date = pd.to_datetime(gain_trailer[window_end_col], errors="coerce")
        render_kpi_card(
            c3,
            f"Least XP Gain ({w_label})",
            format_kpi_number(gain_trailer[xp_gain_col], "XP"),
            winner=winner_with_level(gain_trailer["Spieler"]),
            context=f"{format_kpi_number(gain_trailer[xp_per_day_col], 'XP/day')} pace",
            help_text=(
                f"{w}-day rolling XP gain (xp_at(now) - xp_at(now-{w}d)).\n"
                f"Window end: {gain_trailer_to_date.strftime('%Y-%m-%d') if pd.notna(gain_trailer_to_date) else '-'}"
            ),
        )
    elif not eligible_gain_pool.empty:
        render_kpi_card(
            c3,
            f"Least XP Gain ({w_label})",
            f"No active players ({w_label})",
            context=f"all {xp_gain_col} = 0",
            delta_color="off",
        )
    else:
        render_kpi_card(c3, f"Least XP Gain ({w_label})", "-", context="no data")

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
            render_kpi_card(
                c4,
                "Team Platinum Total",
                format_kpi_number(team_platinum_total),
                context=" | ".join(breakdown) if breakdown else None,
            )
        else:
            render_kpi_card(c4, "Team Platinum Total", "-", context="no data")
    else:
        if active_kpi_pool.empty:
            if not eligible_gain_pool.empty:
                render_kpi_card(
                    c4,
                    f"Fastest {w_label} Pace",
                    f"No active players ({w_label})",
                    context=f"all {xp_gain_col} = 0",
                    delta_color="off",
                )
            else:
                render_kpi_card(c4, f"Fastest {w_label} Pace", "-", context="no data")
        else:
            fastest = active_kpi_pool.sort_values([xp_per_day_col, xp_gain_col], ascending=[False, False]).iloc[0]
            as_of = pd.to_datetime(fastest[window_end_col], errors="coerce")
            render_kpi_card(
                c4,
                f"Fastest {w_label} Pace",
                format_kpi_number(fastest[xp_per_day_col], "XP/day"),
                winner=winner_with_level(fastest["Spieler"]),
                context=f"{format_kpi_number(fastest[xp_gain_col], 'XP')} gained in {w_label}",
                help_text=(
                    f"{w}-day rolling pace.\n"
                    f"Window end: {as_of.strftime('%Y-%m-%d') if pd.notna(as_of) else '-'}"
                ),
            )

        if eligible_baseline_pool.empty:
            render_kpi_card(
                c5,
                f"Most Improved vs Baseline ({w_label})",
                "-",
                context="no baseline-eligible data",
                help_text=(
                    f"delta vs baseline where baseline is median of previous rolling {w_label} windows.\n"
                    f"Requires at least {BASELINE_MIN_WINDOWS_DEFAULT} prior windows."
                ),
            )
            render_kpi_card(
                c6,
                f"Most Declined vs Baseline ({w_label})",
                "-",
                context="no baseline-eligible data",
                help_text=(
                    "Shows a declined winner only if delta vs baseline is negative.\n"
                    f"Requires at least {BASELINE_MIN_WINDOWS_DEFAULT} prior windows."
                ),
            )
        elif baseline_headline_pool.empty:
            render_kpi_card(
                c5,
                f"Most Improved vs Baseline ({w_label})",
                "No improvements",
                context=f"all {xp_gain_col} = 0 for baseline-eligible players",
                delta_color="off",
            )
            render_kpi_card(
                c6,
                f"Most Declined vs Baseline ({w_label})",
                "No decline",
                context=f"all {xp_gain_col} = 0 for baseline-eligible players",
                delta_color="off",
            )
        else:
            baseline_as_of = pd.to_datetime(baseline_headline_pool[window_end_col], errors="coerce").max()
            improved_pool = baseline_headline_pool[baseline_headline_pool[delta_col] > 0].copy()
            if improved_pool.empty:
                render_kpi_card(
                    c5,
                    f"Most Improved vs Baseline ({w_label})",
                    "No improvements",
                    context="all deltas <= 0",
                    delta_color="off",
                    help_text=(
                        f"baseline = median of previous rolling {w_label} windows (excluding current).\n"
                        f"Window end: {baseline_as_of.strftime('%Y-%m-%d') if pd.notna(baseline_as_of) else '-'}"
                    ),
                )
            else:
                improved = improved_pool.sort_values(delta_col, ascending=False).iloc[0]
                improved_delta = float(improved[delta_col])
                improved_as_of = pd.to_datetime(improved[window_end_col], errors="coerce")
                render_kpi_card(
                    c5,
                    f"Most Improved vs Baseline ({w_label})",
                    format_kpi_number(improved[xp_per_day_col], "XP/day"),
                    winner=winner_with_level(improved["Spieler"]),
                    delta=f"{int(round(improved_delta)):+,} XP/day vs baseline",
                    help_text=(
                        f"baseline = median of previous rolling {w_label} windows (excluding current).\n"
                        f"Window end: {improved_as_of.strftime('%Y-%m-%d') if pd.notna(improved_as_of) else '-'}"
                    ),
                )

            declined_pool = baseline_headline_pool[baseline_headline_pool[delta_col] < 0].copy()
            if declined_pool.empty:
                render_kpi_card(
                    c6,
                    f"Most Declined vs Baseline ({w_label})",
                    "No decline",
                    context="all deltas >= 0",
                    delta_color="off",
                    help_text=(
                        f"baseline = median of previous rolling {w_label} windows (excluding current).\n"
                        f"Window end: {baseline_as_of.strftime('%Y-%m-%d') if pd.notna(baseline_as_of) else '-'}"
                    ),
                )
            else:
                declined = declined_pool.sort_values(delta_col, ascending=True).iloc[0]
                declined_delta = float(declined[delta_col])
                declined_as_of = pd.to_datetime(declined[window_end_col], errors="coerce")
                render_kpi_card(
                    c6,
                    f"Most Declined vs Baseline ({w_label})",
                    format_kpi_number(declined[xp_per_day_col], "XP/day"),
                    winner=winner_with_level(declined["Spieler"]),
                    delta=f"{int(round(declined_delta)):+,} XP/day vs baseline",
                    help_text=(
                        f"baseline = median of previous rolling {w_label} windows (excluding current).\n"
                        f"Window end: {declined_as_of.strftime('%Y-%m-%d') if pd.notna(declined_as_of) else '-'}"
                    ),
                )

    if not dash_latest_xp_df.empty:
        latest_xp_date = pd.to_datetime(dash_latest_xp_df["Date"], errors="coerce").max()
        if pd.notna(latest_xp_date):
            days_ago = (pd.Timestamp.today().normalize() - latest_xp_date.normalize()).days
            render_kpi_card(
                last_snapshot_col,
                "Last XP Snapshot",
                latest_xp_date.strftime("%Y-%m-%d"),
                delta=f"{int(days_ago)} day(s) ago",
                help_text="Latest snapshot date used in this dashboard selection.",
            )
        else:
            render_kpi_card(last_snapshot_col, "Last XP Snapshot", "-", context="no data")
    else:
        render_kpi_card(last_snapshot_col, "Last XP Snapshot", "-", context="no data")

    with window_control_col:
        st.caption("Window")
        st.segmented_control(
            "Window",
            options=[7, 30],
            key=window_state_key,
            format_func=lambda x: f"{int(x)}d",
            label_visibility="collapsed",
        )
        if show_30d_limited_hint:
            st.caption("30d limited coverage")

    st.caption(
        f"Eligible for {w_label} stats: {eligible_window}/{total_players} | "
        f"Eligible for baseline comparisons: {eligible_baseline_window}/{total_players} "
        f"(baseline requires >= {BASELINE_MIN_WINDOWS_DEFAULT} prior {w_label} windows) | "
        f"Active in {w_label} window ({xp_gain_col} > 0): {active_kpi_count}/{total_players}"
    )

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

        fig_growth = build_xp_growth_figure(curve_map, dash_latest_xp_df)
        if fig_growth is not None:
            render_plotly_chart(fig_growth, use_container_width=True)

        d_left, d_right = st.columns([1.05, 1.0])
        with d_left:
            st.subheader("Current XP Ranking")
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
            ].copy()
            ranking_styler = (
                ranking_view.style.format(
                    {
                        "rank": "{:.0f}",
                        "Lvl": "{:.0f}",
                        "Total XP": "{:,.0f}",
                        "gap_to_leader": "{:,.0f}",
                        xp_per_day_col: "{:,.0f}",
                        delta_col: "{:+,.0f}",
                        pct_col: "{:+.1%}",
                    },
                    na_rep="--",
                )
                .map(
                    lambda v: "background-color: rgba(16, 185, 129, 0.20);"
                    if pd.notna(v) and float(v) > 0
                    else ("background-color: rgba(239, 68, 68, 0.20);" if pd.notna(v) and float(v) < 0 else ""),
                    subset=[delta_col, pct_col],
                )
            )
            st.dataframe(
                ranking_styler,
                use_container_width=True,
                hide_index=True,
                height=380,
            )
        with d_right:
            st.subheader(f"XP Gain (Last {w} Days)")
            if dash_recent_gain_df.empty:
                st.info(f"Not enough history yet for {w}-day gain view.")
            else:
                gain_top = dash_recent_gain_df.sort_values("xp_gain", ascending=False).head(10).copy()
                fig_gain = px.bar(
                    gain_top.sort_values("xp_gain", ascending=True),
                    x="xp_gain",
                    y="Spieler",
                    orientation="h",
                    title=f"Top XP Gain ({w_label})",
                    labels={"xp_gain": "XP Gain", "Spieler": "Account"},
                )
                fig_gain.update_layout(height=300, margin=dict(l=20, r=20, t=40, b=20))
                render_plotly_chart(fig_gain, use_container_width=True)
                gain_view = gain_top[["Spieler", "xp_gain", "xp_per_day"]].copy()
                st.dataframe(
                    gain_view,
                    use_container_width=True,
                    hide_index=True,
                    height=210,
                    column_config={
                        "xp_gain": st.column_config.NumberColumn("XP Gain", format="%d"),
                        "xp_per_day": st.column_config.NumberColumn("XP/Day", format="%.0f"),
                    },
                )

st.set_page_config(page_title="PoGo Local Dashboard", layout="wide")
inject_responsive_styles()
st.title("PoGo Local Dashboard")
st.caption("Interactive XP + medal dashboard.")

curve_map = load_curve_map(total_xp_curve_path())
xp_df = load_xp_history(xp_history_path(), curve_map)
groups = parse_groups(player_groups_path())
medal_df = load_medal_snapshots(medal_snapshots_path())
goals_df = load_medal_goals(medals_config_path())
ensure_medal_explanations_file(medal_explanations_path(), goals_df)
medal_explanations_map = load_medal_explanations(medal_explanations_path())
display_medal_df = with_derived_platinum_rows(medal_df, goals_df)
all_accounts = account_options_from_data(xp_df, medal_df)
latest_xp_df = latest_xp_snapshot(xp_df)

pages = [
    "Dashboard Global",
    "Dashboard Personal",
    "Medal Explorer",
    "Data Input",
    "Last Inputs",
    "Pipelines",
    "Generated Files",
]
page = st.radio("Page", pages, horizontal=True)

if page == "Dashboard Global":
    st.subheader("Dashboard Global")
    all_dashboard_accounts = sorted(
        set(xp_df["Spieler"].dropna().astype(str).tolist()) | set(display_medal_df["account"].dropna().astype(str).tolist())
    )
    personal_group_names = {g for g in groups.keys() if str(g).strip().lower() in {"ich", "ownaccounts"}}
    dashboard_group_options = ["All"] + [g for g in groups.keys() if g and g != "All" and g not in personal_group_names]
    top_left, top_right = st.columns([3.6, 1.4])
    with top_left:
        selected_dashboard_group = st.radio(
            "Global Group",
            dashboard_group_options,
            index=0,
            horizontal=True,
            key="dashboard_global_group",
        )
    dashboard_accounts = accounts_for_selected_group(selected_dashboard_group, groups, all_dashboard_accounts)
    if not dashboard_accounts:
        st.info("No accounts found for the selected global group.")
    else:
        dash_xp_df = xp_df[xp_df["Spieler"].isin(dashboard_accounts)].copy()
        dash_medal_df = medal_df[medal_df["account"].isin(dashboard_accounts)].copy()
        dash_display_medal_df = display_medal_df[display_medal_df["account"].isin(dashboard_accounts)].copy()
        metrics_by_window = compute_metrics_by_window(dash_xp_df, window_options=DASHBOARD_WINDOW_OPTIONS)
        default_window_days = auto_default_window_days(metrics_by_window)
        window_key = f"dashboard_global_window_{_slugify(selected_dashboard_group)}"
        if window_key not in st.session_state:
            st.session_state[window_key] = int(default_window_days)
        else:
            st.session_state[window_key] = parse_window_days(st.session_state.get(window_key), fallback=default_window_days)
        eligible_30d_count = count_window_eligible(metrics_by_window.get(30, pd.DataFrame()), 30, baseline=False)
        show_30d_limited_hint = eligible_30d_count < MIN_ELIGIBLE_FOR_30D_DEFAULT
        selected_window_days = parse_window_days(st.session_state.get(window_key), fallback=default_window_days)
        with top_right:
            render_dashboard_export_button(
                dashboard_title="Dashboard Global",
                selected_group=selected_dashboard_group,
                selected_accounts=dashboard_accounts,
                dash_xp_df=dash_xp_df,
                dash_medal_df=dash_medal_df,
                dash_display_medal_df=dash_display_medal_df,
                goals_df=goals_df,
                curve_map=curve_map,
                show_medals=False,
                window_days=selected_window_days,
                key="export_dashboard_global",
            )
        render_dashboard_content(
            dash_xp_df=dash_xp_df,
            dash_medal_df=dash_medal_df,
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
        )

if page == "Dashboard Personal":
    st.subheader("Dashboard Personal")
    all_dashboard_accounts = sorted(
        set(xp_df["Spieler"].dropna().astype(str).tolist()) | set(display_medal_df["account"].dropna().astype(str).tolist())
    )
    personal_groups_by_key = {str(g).strip().lower(): g for g in groups.keys() if str(g).strip().lower() in {"ich", "ownaccounts"}}
    dashboard_group_options = [personal_groups_by_key[k] for k in ["ownaccounts", "ich"] if k in personal_groups_by_key]
    if not dashboard_group_options:
        st.info("No personal groups found. Add `Ich:` and/or `OwnAccounts:` to `inputs/config/player_groups.csv`.")
        st.stop()

    top_left, top_right = st.columns([3.6, 1.4])
    with top_left:
        selected_dashboard_group = st.radio(
            "Personal Group",
            dashboard_group_options,
            index=0,
            horizontal=True,
            key="dashboard_personal_group",
        )
    dashboard_accounts = accounts_for_selected_group(selected_dashboard_group, groups, all_dashboard_accounts)
    if not dashboard_accounts:
        st.info("No accounts found for the selected personal group.")
    else:
        dash_xp_df = xp_df[xp_df["Spieler"].isin(dashboard_accounts)].copy()
        dash_medal_df = medal_df[medal_df["account"].isin(dashboard_accounts)].copy()
        dash_display_medal_df = display_medal_df[display_medal_df["account"].isin(dashboard_accounts)].copy()
        metrics_by_window = compute_metrics_by_window(dash_xp_df, window_options=DASHBOARD_WINDOW_OPTIONS)
        default_window_days = auto_default_window_days(metrics_by_window)
        window_key = f"dashboard_personal_window_{_slugify(selected_dashboard_group)}"
        if window_key not in st.session_state:
            st.session_state[window_key] = int(default_window_days)
        else:
            st.session_state[window_key] = parse_window_days(st.session_state.get(window_key), fallback=default_window_days)
        eligible_30d_count = count_window_eligible(metrics_by_window.get(30, pd.DataFrame()), 30, baseline=False)
        show_30d_limited_hint = eligible_30d_count < MIN_ELIGIBLE_FOR_30D_DEFAULT
        selected_window_days = parse_window_days(st.session_state.get(window_key), fallback=default_window_days)
        with top_right:
            render_dashboard_export_button(
                dashboard_title="Dashboard Personal",
                selected_group=selected_dashboard_group,
                selected_accounts=dashboard_accounts,
                dash_xp_df=dash_xp_df,
                dash_medal_df=dash_medal_df,
                dash_display_medal_df=dash_display_medal_df,
                goals_df=goals_df,
                curve_map=curve_map,
                show_medals=True,
                window_days=selected_window_days,
                key="export_dashboard_personal",
            )
        render_dashboard_content(
            dash_xp_df=dash_xp_df,
            dash_medal_df=dash_medal_df,
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
        )

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
        selected_accounts = st.multiselect("Accounts", all_accounts, default=all_accounts[:3] or all_accounts)
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
                        markers=True,
                        title=f"Progress: {platinum_title}",
                    )
                    add_goal_and_trends(fig_platinum, platinum_df, DERIVED_MEDAL_ID, status_mode="in_chart")
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
                    ensure_account_in_xp_order(account_name, known_accounts=all_accounts)
                except Exception as exc:
                    st.error(f"Failed to add account: {exc}")
                else:
                    group_label = ", ".join(applied_groups) if applied_groups else "All"
                    st.success(f"Added account `{account_name}` (groups: {group_label}).")
                    st.rerun()

    tab_xp, tab_medal = st.tabs(["XP Snapshot Input", "Medal Snapshot Input"])

    with tab_xp:
        st.caption("Enter one snapshot date and update multiple accounts at once.")
        xp_date = st.date_input("XP Date", value=date.today(), key="xp_batch_date")
        raw_players = list(all_accounts) if all_accounts else list(ACCOUNT_ORDER)
        all_players = load_xp_input_order(raw_players)
        xp_on_date = set()
        if not xp_df.empty:
            xp_on_date = set(xp_df[xp_df["Date"].dt.date == xp_date]["Spieler"].astype(str).tolist())
        available_xp_accounts = [a for a in all_players if a not in xp_on_date]

        if xp_on_date:
            st.caption(f"Already entered for this date: {', '.join(sorted(xp_on_date))}")
        if available_xp_accounts:
            st.caption(f"Missing for this date: {', '.join(available_xp_accounts)}")

        selected_xp_accounts = st.multiselect(
            "Accounts to update (missing only for selected date)",
            options=available_xp_accounts,
            default=available_xp_accounts,
            key="xp_batch_accounts",
        )
        if not available_xp_accounts:
            st.success("XP snapshot complete for selected date. No missing accounts.")
        elif not selected_xp_accounts:
            st.info("Select at least one missing account.")
        else:
            latest_map: dict[str, tuple[int, int]] = {}
            if not xp_df.empty:
                latest_xp = xp_df.sort_values(["Spieler", "Date"]).groupby("Spieler", as_index=False).tail(1)
                for _, r in latest_xp.iterrows():
                    latest_map[str(r["Spieler"])] = (int(r["Lvl"]), int(r["XP Bar"]))

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

            xp_editor_rows = []
            for acc in selected_xp_accounts:
                lvl_default, xp_default = latest_map.get(acc, (1, 0))
                battles_default = latest_activity_map.get((str(acc), XP_TAB_ACTIVITY_MEDAL_IDS["battles_won"]), 0.0)
                distance_default = latest_activity_map.get((str(acc), XP_TAB_ACTIVITY_MEDAL_IDS["distance_walked"]), 0.0)
                caught_default = latest_activity_map.get((str(acc), XP_TAB_ACTIVITY_MEDAL_IDS["pokemon_caught"]), 0.0)
                xp_editor_rows.append(
                    {
                        "account": acc,
                        "lvl_last": int(lvl_default),
                        "xp_bar_last": int(xp_default),
                        "lvl": lvl_default,
                        "xp_bar": xp_default,
                        "battles_last": battles_default,
                        "distance_last": distance_default,
                        "caught_last": caught_default,
                    }
                )

            _, xp_input_col, _ = st.columns([0.24, 0.52, 0.24], gap="small")
            col_widths = [1.35, 0.65, 0.95, 0.2, 0.55, 0.2, 0.95, 0.95, 0.95, 0.95, 1.9]
            h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11 = xp_input_col.columns(col_widths, gap="small")
            h1.markdown("**Account**")
            h2.markdown("**Level (last Data)**")
            h3.markdown("**XPBar (last Data)**")
            h4.markdown("**-**")
            h5.markdown("**Level**")
            h6.markdown("**+**")
            h7.markdown("**XP Bar**")
            h8.markdown("**Battles Won**")
            h9.markdown("**Distance Walked**")
            h10.markdown("**Pokemon Caught**")
            h11.markdown("**Status**")

            xp_inputs: list[dict[str, object]] = []
            inline_xp_errors: list[str] = []
            xp_existing_for_validation = xp_df[["Date", "Spieler", "Lvl", "XP Bar"]].copy() if not xp_df.empty else pd.DataFrame(
                columns=["Date", "Spieler", "Lvl", "XP Bar"]
            )
            for row in xp_editor_rows:
                acc = str(row["account"])
                c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, c11 = xp_input_col.columns(col_widths, gap="small")
                account_slot = c1.empty()
                c2.markdown(f"`{int(row['lvl_last'])}`")
                c3.markdown(f"`{int(row['xp_bar_last']):,}`")
                lvl_state_key = f"xp_level_input_{xp_date.isoformat()}_{acc}"
                if lvl_state_key not in st.session_state:
                    st.session_state[lvl_state_key] = int(row["lvl"])
                else:
                    try:
                        current_lvl = int(st.session_state[lvl_state_key])
                    except Exception:
                        current_lvl = int(row["lvl"])
                    st.session_state[lvl_state_key] = max(1, min(100, current_lvl))
                dec_clicked = c4.button(
                    " ",
                    key=f"{lvl_state_key}_dec",
                    help="Decrease level",
                    icon=":material/remove:",
                    use_container_width=True,
                )
                if dec_clicked:
                    st.session_state[lvl_state_key] = max(1, int(st.session_state[lvl_state_key]) - 1)
                inc_clicked = c6.button(
                    " ",
                    key=f"{lvl_state_key}_inc",
                    help="Increase level",
                    icon=":material/add:",
                    use_container_width=True,
                )
                if inc_clicked:
                    st.session_state[lvl_state_key] = min(100, int(st.session_state[lvl_state_key]) + 1)
                lvl_value = c5.number_input(
                    "Level",
                    min_value=1,
                    max_value=100,
                    step=1,
                    format="%d",
                    key=lvl_state_key,
                    label_visibility="collapsed",
                )
                xp_bar_value = c7.text_input(
                    "XP Bar",
                    value=str(int(row["xp_bar"])),
                    key=f"xp_bar_input_{xp_date.isoformat()}_{acc}",
                    label_visibility="collapsed",
                )
                battles_value = c8.text_input(
                    "Battles Won",
                    value=str(int(float(row.get("battles_last", 0.0)))),
                    key=f"xp_battles_input_{xp_date.isoformat()}_{acc}",
                    label_visibility="collapsed",
                )
                distance_value = c9.text_input(
                    "Distance Walked",
                    value=str(int(float(row.get("distance_last", 0.0)))),
                    key=f"xp_distance_input_{xp_date.isoformat()}_{acc}",
                    label_visibility="collapsed",
                )
                caught_value = c10.text_input(
                    "Pokemon Caught",
                    value=str(int(float(row.get("caught_last", 0.0)))),
                    key=f"xp_caught_input_{xp_date.isoformat()}_{acc}",
                    label_visibility="collapsed",
                )
                row_errors: list[str] = []
                xp_bar_num = pd.to_numeric(xp_bar_value, errors="coerce")
                battles_num = pd.to_numeric(battles_value, errors="coerce")
                distance_num = pd.to_numeric(distance_value, errors="coerce")
                caught_num = pd.to_numeric(caught_value, errors="coerce")
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

                account_color = "#9ca3af" if row_changed else "inherit"
                account_slot.markdown(
                    f"<span style='color:{account_color}; font-weight:500'>{escape(acc)}</span>",
                    unsafe_allow_html=True,
                )
                if pd.isna(xp_bar_num) or int(xp_bar_num) < 0:
                    row_errors.append("XP Bar must be a number >= 0.")
                else:
                    row_df = pd.DataFrame(
                        [
                            {
                                "Date": pd.Timestamp(xp_date),
                                "Spieler": acc,
                                "Lvl": int(lvl_value),
                                "XP Bar": int(xp_bar_num),
                            }
                        ]
                    )
                    monotonic_errors = _validate_xp_rows_non_decreasing(xp_existing_for_validation, row_df, curve_map)
                    row_errors.extend(monotonic_errors)
                if pd.isna(battles_num) or float(battles_num) < 0:
                    row_errors.append("Battles Won must be a number >= 0.")
                if pd.isna(distance_num) or float(distance_num) < 0:
                    row_errors.append("Distance Walked must be a number >= 0.")
                if pd.isna(caught_num) or float(caught_num) < 0:
                    row_errors.append("Pokemon Caught must be a number >= 0.")
                if not row_errors:
                    medal_row_df = pd.DataFrame(
                        [
                            {
                                "date": pd.Timestamp(xp_date),
                                "account": acc,
                                "medal_id": XP_TAB_ACTIVITY_MEDAL_IDS["battles_won"],
                                "value": float(battles_num),
                            },
                            {
                                "date": pd.Timestamp(xp_date),
                                "account": acc,
                                "medal_id": XP_TAB_ACTIVITY_MEDAL_IDS["distance_walked"],
                                "value": float(distance_num),
                            },
                            {
                                "date": pd.Timestamp(xp_date),
                                "account": acc,
                                "medal_id": XP_TAB_ACTIVITY_MEDAL_IDS["pokemon_caught"],
                                "value": float(caught_num),
                            },
                        ]
                    )
                    medal_mono_errors = _validate_medal_rows_non_decreasing(medal_existing_for_validation, medal_row_df)
                    row_errors.extend(medal_mono_errors)

                if row_errors:
                    inline_xp_errors.extend(row_errors)
                    c11.markdown(
                        f"<span style='color:#ef4444; font-size:0.82rem'>{escape(row_errors[0])}</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    c11.markdown("<span style='color:#22c55e; font-size:0.82rem'>OK</span>", unsafe_allow_html=True)
                xp_inputs.append(
                    {
                        "account": acc,
                        "lvl": int(lvl_value),
                        "xp_bar": xp_bar_value,
                        "battles_won": battles_value,
                        "distance_walked": distance_value,
                        "pokemon_caught": caught_value,
                    }
                )

            if inline_xp_errors:
                st.caption("Fix row errors to enable saving.")
            if st.button("Save XP snapshot for selected accounts", key="xp_batch_save", disabled=bool(inline_xp_errors)):
                rows_to_write: list[dict[str, object]] = []
                medal_rows_to_write: list[dict[str, object]] = []
                errors: list[str] = []
                for r in xp_inputs:
                    acc = str(r.get("account", "")).strip()
                    lvl = pd.to_numeric(r.get("lvl"), errors="coerce")
                    xp_bar = pd.to_numeric(r.get("xp_bar"), errors="coerce")
                    battles_won = pd.to_numeric(r.get("battles_won"), errors="coerce")
                    distance_walked = pd.to_numeric(r.get("distance_walked"), errors="coerce")
                    pokemon_caught = pd.to_numeric(r.get("pokemon_caught"), errors="coerce")
                    if not acc:
                        errors.append("Missing account value.")
                        continue
                    if pd.isna(lvl) or int(lvl) < 1:
                        errors.append(f"{acc}: invalid level.")
                        continue
                    if pd.isna(xp_bar) or int(xp_bar) < 0:
                        errors.append(f"{acc}: invalid XP Bar.")
                        continue
                    if pd.isna(battles_won) or float(battles_won) < 0:
                        errors.append(f"{acc}: invalid Battles Won.")
                        continue
                    if pd.isna(distance_walked) or float(distance_walked) < 0:
                        errors.append(f"{acc}: invalid Distance Walked.")
                        continue
                    if pd.isna(pokemon_caught) or float(pokemon_caught) < 0:
                        errors.append(f"{acc}: invalid Pokemon Caught.")
                        continue
                    rows_to_write.append(
                        {
                            "Date": xp_date.isoformat(),
                            "Spieler": acc,
                            "Lvl": int(lvl),
                            "XP Bar": int(xp_bar),
                        }
                    )
                    medal_rows_to_write.extend(
                        [
                            {
                                "date": xp_date.isoformat(),
                                "account": acc,
                                "medal_id": XP_TAB_ACTIVITY_MEDAL_IDS["battles_won"],
                                "value": float(battles_won),
                            },
                            {
                                "date": xp_date.isoformat(),
                                "account": acc,
                                "medal_id": XP_TAB_ACTIVITY_MEDAL_IDS["distance_walked"],
                                "value": float(distance_walked),
                            },
                            {
                                "date": xp_date.isoformat(),
                                "account": acc,
                                "medal_id": XP_TAB_ACTIVITY_MEDAL_IDS["pokemon_caught"],
                                "value": float(pokemon_caught),
                            },
                        ]
                    )
                if errors:
                    st.error("\n".join(errors))
                else:
                    try:
                        written = upsert_xp_rows(xp_history_path(), rows_to_write)
                        written_medals = append_medal_rows(medal_snapshots_path(), medal_rows_to_write)
                    except ValueError as e:
                        st.error(str(e))
                    else:
                        st.success(
                            f"Saved XP snapshot rows: {written}. "
                            f"Saved activity medal rows: {written_medals} "
                            "(Battles Won, Distance Walked, Pokemon Caught)."
                        )

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
        account_scope_label = st.selectbox(
            "Medal input account scope",
            options=[
                "Core only (Thombay, Cerius, Thomzay)",
                "All accounts",
            ],
            index=0,
            key="medal_input_account_scope",
        )
        all_input_accounts = list(all_accounts) if all_accounts else list(ACCOUNT_ORDER)
        if account_scope_label.startswith("Core only"):
            allowed_accounts = list(dict.fromkeys([str(a).strip() for a in MEDAL_INPUT_CORE_ACCOUNTS if str(a).strip()]))
        else:
            allowed_accounts = all_input_accounts
        medal_on_date = set()
        if not medal_df.empty:
            medal_on_date = set(medal_df[medal_df["date"].dt.date == medal_date]["account"].astype(str).tolist())
        available_medal_accounts = [a for a in allowed_accounts if a not in medal_on_date]
        if medal_on_date:
            st.caption(f"Already entered for this date: {', '.join(sorted(medal_on_date))}")
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
