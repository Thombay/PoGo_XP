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
    medal_snapshots_path,
    medals_config_path,
    output_dir,
    player_groups_path,
    total_xp_curve_path,
    xp_history_path,
)

ACCOUNT_ORDER = ["Thombay", "Cerius", "Thomzay"]
DERIVED_MEDAL_ID = "platinum_medals"
EXCLUDED_MANUAL_MEDAL_IDS = {"total_xp", DERIVED_MEDAL_ID}
GOAL_ALIAS_BY_MEDAL_ID = {
    "distance_walked": "jogger",
    "pokemon_caught": "collector",
    "pokestops_visited": "backpacker",
    "pokestops_vistited": "backpacker",
}
EXCLUDED_MEDAL_GRAPH_IDS = {"distance_walked", "pokemon_caught", "pokestops_visited", "pokestops_vistited"}
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
    goals["goal_value"] = pd.to_numeric(goals["goal_value"], errors="coerce")
    goals = goals.dropna(subset=["medal_id", "goal_value"]).drop_duplicates(subset=["medal_id"], keep="last")

    source = source.merge(goals, on="medal_id", how="left")
    source = source.dropna(subset=["goal_value"]).copy()
    source = source.sort_values("date").drop_duplicates(["date", "account", "medal_id"], keep="last")
    source["reached"] = source["value"] >= source["goal_value"]

    platinum_counts = source.groupby(["date", "account"], as_index=False)["reached"].sum()
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


def _predict_goal_eta(series: pd.DataFrame, goal_value: float) -> pd.Timestamp | None:
    s = series.copy()
    s["date"] = pd.to_datetime(s["date"], errors="coerce")
    s["value"] = pd.to_numeric(s["value"], errors="coerce")
    s = s.dropna(subset=["date", "value"]).sort_values("date")
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
    s = series.copy()
    s["date"] = pd.to_datetime(s["date"], errors="coerce")
    s["value"] = pd.to_numeric(s["value"], errors="coerce")
    s = s.dropna(subset=["date", "value"]).sort_values("date")
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
    s = series.copy()
    s["Date"] = pd.to_datetime(s["Date"], errors="coerce")
    s["Total XP"] = pd.to_numeric(s["Total XP"], errors="coerce")
    s = s.dropna(subset=["Date", "Total XP"]).sort_values("Date")
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


def restrict_to_common_interval(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    ranges = df.groupby("Spieler")["Date"].agg(["min", "max"])
    if ranges.empty:
        return df.copy()
    start = ranges["min"].max()
    end = ranges["max"].min()
    if pd.isna(start) or pd.isna(end) or start > end:
        return df.iloc[0:0].copy()
    out = df[(df["Date"] >= start) & (df["Date"] <= end)].copy()
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


def build_gap_change_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.sort_values(["Date", "Spieler"]).copy()
    out["Gap"] = out.groupby("Date")["Total XP"].transform("max") - out["Total XP"]
    out["Gap Change"] = out["Gap"] - out.groupby("Spieler")["Gap"].transform("first")
    return out


def build_pace_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.sort_values(["Spieler", "Date"]).copy()
    out["Days Delta"] = out.groupby("Spieler")["Date"].diff().dt.total_seconds() / 86_400
    out["XP Delta"] = out.groupby("Spieler")["Total XP"].diff()
    out["XP/day"] = out["XP Delta"] / out["Days Delta"]
    out = out[out["Days Delta"] > 0].copy()
    return out


def render_xp_explorer_section(xp_subset_df: pd.DataFrame, key_prefix: str) -> None:
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
        "Use common interval for all selected players",
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
    d_start, d_end = st.slider(
        "Date range",
        min_value=min_date,
        max_value=max_date,
        value=(min_date, max_date),
        key=f"{key_prefix}_date_range",
    )
    df = df[(df["Date"] >= pd.Timestamp(d_start)) & (df["Date"] <= pd.Timestamp(d_end))].copy()
    if df.empty:
        st.warning("No rows in selected date range.")
        return

    fig_total = px.line(
        df,
        x="Date",
        y="Total XP",
        color="Spieler",
        markers=True,
        title="Total XP Over Time",
    )
    st.plotly_chart(fig_total, use_container_width=True)

    col_a, col_b = st.columns(2)
    with col_a:
        rank_df = build_rank_df(df)
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
        st.plotly_chart(fig_rank, use_container_width=True)

    with col_b:
        gap_df = build_gap_change_df(df)
        fig_gap = px.line(
            gap_df,
            x="Date",
            y="Gap Change",
            color="Spieler",
            markers=True,
            title="Gap Change Since First Snapshot",
        )
        fig_gap.add_hline(y=0, line_dash="dash")
        st.plotly_chart(fig_gap, use_container_width=True)

    pace_df = build_pace_df(df)
    if not pace_df.empty:
        fig_pace = px.line(
            pace_df,
            x="Date",
            y="XP/day",
            color="Spieler",
            markers=True,
            title="Interval Pace (XP/day)",
        )
        st.plotly_chart(fig_pace, use_container_width=True)


def append_xp_row(path: Path, row_date: date, account: str, level: int, xp_bar: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not path.exists() or path.stat().st_size == 0
    with open(path, "a", encoding="utf-8") as f:
        if needs_header:
            f.write("Date;Spieler;Lvl;XP Bar\n")
        f.write(f"{row_date.isoformat()};{account};{level};{xp_bar}\n")


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
    if new_df.empty:
        return 0

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
    all_names = sorted(players | accounts)
    ordered = [a for a in ACCOUNT_ORDER if a in all_names]
    return ordered + [a for a in all_names if a not in ordered]


def latest_xp_snapshot(xp_df: pd.DataFrame) -> pd.DataFrame:
    cols = ["Date", "Spieler", "Lvl", "XP Bar", "Total XP"]
    if xp_df.empty:
        return pd.DataFrame(columns=cols)
    latest = xp_df.sort_values(["Spieler", "Date"]).groupby("Spieler", as_index=False).tail(1)
    latest = latest.sort_values("Total XP", ascending=False).reset_index(drop=True)
    return latest[cols].copy()


def xp_recent_gain(xp_df: pd.DataFrame, days: int = 30) -> pd.DataFrame:
    cols = ["Spieler", "from_date", "to_date", "xp_gain", "xp_per_day"]
    if xp_df.empty:
        return pd.DataFrame(columns=cols)

    d = xp_df.sort_values(["Spieler", "Date"]).copy()
    end_rows = d.groupby("Spieler", as_index=False).tail(1)[["Spieler", "Date", "Total XP"]].copy()
    end_rows = end_rows.rename(columns={"Date": "to_date", "Total XP": "to_total_xp"})
    start_target = end_rows.copy()
    start_target["from_target"] = start_target["to_date"] - pd.to_timedelta(days, unit="D")

    merged = pd.merge_asof(
        start_target.sort_values("from_target"),
        d[["Spieler", "Date", "Total XP"]].sort_values("Date"),
        left_on="from_target",
        right_on="Date",
        by="Spieler",
        direction="backward",
    )
    merged = merged.rename(columns={"Date": "from_date", "Total XP": "from_total_xp"})
    out = end_rows.merge(merged[["Spieler", "from_date", "from_total_xp"]], on="Spieler", how="left")
    out = out.dropna(subset=["from_date", "from_total_xp", "to_total_xp"]).copy()
    out["xp_gain"] = out["to_total_xp"] - out["from_total_xp"]
    out["days"] = (out["to_date"] - out["from_date"]).dt.total_seconds() / 86_400
    out = out[out["days"] > 0].copy()
    out["xp_per_day"] = out["xp_gain"] / out["days"]
    out = out.sort_values("xp_gain", ascending=False)
    return out[cols].reset_index(drop=True)


def top_newcomer(xp_df: pd.DataFrame) -> dict[str, object] | None:
    if xp_df.empty:
        return None

    d = xp_df.sort_values(["Spieler", "Date"]).copy()
    d["Date"] = pd.to_datetime(d["Date"], errors="coerce")
    d["Total XP"] = pd.to_numeric(d["Total XP"], errors="coerce")
    d = d.dropna(subset=["Date", "Spieler", "Total XP"]).copy()
    d["days_delta"] = d.groupby("Spieler")["Date"].diff().dt.total_seconds() / 86_400
    d["xp_delta"] = d.groupby("Spieler")["Total XP"].diff()
    d["xp_per_day"] = d["xp_delta"] / d["days_delta"]
    intervals = d[(d["days_delta"] > 0) & d["xp_per_day"].notna()].copy()
    if intervals.empty:
        return None

    candidates: list[dict[str, object]] = []
    for player, grp in intervals.groupby("Spieler", sort=True):
        g = grp.sort_values("Date").reset_index(drop=True)
        if len(g) < 2:
            continue
        current_pace = float(g.iloc[-1]["xp_per_day"])
        baseline_pace = float(g.iloc[:-1]["xp_per_day"].median())
        if pd.isna(current_pace) or pd.isna(baseline_pace):
            continue
        if baseline_pace <= 0:
            continue
        improvement = current_pace - baseline_pace
        ratio = current_pace / baseline_pace if baseline_pace > 0 else pd.NA
        candidates.append(
            {
                "spieler": str(player),
                "current_pace": current_pace,
                "baseline_pace": baseline_pace,
                "improvement": improvement,
                "ratio": ratio,
                "as_of": pd.to_datetime(g.iloc[-1]["Date"]),
            }
        )
    if not candidates:
        return None
    ranked = pd.DataFrame(candidates).sort_values(["improvement", "ratio"], ascending=[False, False]).reset_index(drop=True)
    row = ranked.iloc[0]
    if float(row["improvement"]) <= 0:
        return None
    return {
        "spieler": str(row["spieler"]),
        "current_pace": float(row["current_pace"]),
        "baseline_pace": float(row["baseline_pace"]),
        "improvement": float(row["improvement"]),
        "ratio": float(row["ratio"]),
        "as_of": pd.to_datetime(row["as_of"]),
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


def _build_dashboard_export_payload(
    selected_accounts: list[str],
    dash_xp_df: pd.DataFrame,
    dash_medal_df: pd.DataFrame,
    dash_display_medal_df: pd.DataFrame,
    goals_df: pd.DataFrame,
    curve_map: dict[int, int],
    show_medals: bool,
) -> dict[str, object]:
    dash_latest_xp_df = latest_xp_snapshot(dash_xp_df)
    dash_recent_gain_df = xp_recent_gain(dash_xp_df, days=30)

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

    if not dash_recent_gain_df.empty:
        gain_leader = dash_recent_gain_df.sort_values("xp_gain", ascending=False).iloc[0]
        metric_cards.append(("Top 30d XP Gain", f"{int(gain_leader['xp_gain']):,}", str(gain_leader["Spieler"])))
    else:
        metric_cards.append(("Top 30d XP Gain", "-", "no data"))

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
        newcomer = top_newcomer(dash_xp_df)
        if newcomer is None:
            metric_cards.append(("Most Improved Pace", "-", "no data"))
        else:
            metric_cards.append(
                (
                    "Most Improved Pace",
                    str(newcomer["spieler"]),
                    (
                        f"{int(round(float(newcomer['current_pace']))):,} XP/day "
                        f"({int(round(float(newcomer['improvement']))):+,} vs own median)"
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

    ranking_view = pd.DataFrame()
    gain_view = pd.DataFrame()
    fig_growth = None
    fig_gain = None
    fig_xp_total = None
    fig_rank = None
    fig_gap = None
    fig_pace = None
    if not dash_latest_xp_df.empty:
        ranking_df = dash_latest_xp_df.sort_values("Total XP", ascending=False).reset_index(drop=True).copy()
        ranking_df["rank"] = range(1, len(ranking_df) + 1)
        leader_xp = float(ranking_df["Total XP"].iloc[0]) if not ranking_df.empty else 0.0
        ranking_df["gap_to_leader"] = leader_xp - ranking_df["Total XP"]
        if not dash_recent_gain_df.empty:
            gain_map = dash_recent_gain_df.set_index("Spieler")["xp_per_day"].to_dict()
            ranking_df["xp_per_day_30d"] = ranking_df["Spieler"].map(gain_map)
        else:
            ranking_df["xp_per_day_30d"] = pd.NA
        ranking_view = ranking_df[["rank", "Spieler", "Lvl", "Total XP", "gap_to_leader", "xp_per_day_30d"]].copy()
        fig_growth = build_xp_growth_figure(curve_map, dash_latest_xp_df)

        if not dash_recent_gain_df.empty:
            gain_top = dash_recent_gain_df.sort_values("xp_gain", ascending=False).head(10).copy()
            fig_gain = px.bar(
                gain_top.sort_values("xp_gain", ascending=True),
                x="xp_gain",
                y="Spieler",
                orientation="h",
                title="Top XP Gain (30d)",
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
            fig_gap.add_hline(y=0, line_dash="dash")

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
        ("XP Gain (Last 30 Days)", fig_gain),
        ("XP Explorer: Total XP Over Time", fig_xp_total),
        ("XP Explorer: Rank Over Time (Step)", fig_rank),
        ("XP Explorer: Gap Change Since First Snapshot", fig_gap),
        ("XP Explorer: Interval Pace (XP/day)", fig_pace),
    ]

    sections: list[tuple[str, pd.DataFrame]] = [
        ("Current XP Ranking", ranking_view),
        ("XP Gain Table (Last 30 Days)", gain_view),
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
) -> str:
    theme = _export_theme(export_mode)
    payload = _build_dashboard_export_payload(
        selected_accounts=selected_accounts,
        dash_xp_df=dash_xp_df,
        dash_medal_df=dash_medal_df,
        dash_display_medal_df=dash_display_medal_df,
        goals_df=goals_df,
        curve_map=curve_map,
        show_medals=show_medals,
    )
    metric_cards = payload["metric_cards"]
    chart_items = payload["chart_items"]
    sections_data = payload["sections"]
    accounts_text = str(payload["accounts_text"])
    generated_at = str(payload["generated_at"])

    chart_blocks: list[str] = []
    include_js = True
    for chart_title, fig in chart_items:
        if fig is None:
            continue
        _style_export_figure(fig, export_mode)
        chart_blocks.append(f"<section><h2>{escape(chart_title)}</h2>")
        chart_blocks.append(
            fig.to_html(
                full_html=False,
                include_plotlyjs="inline" if include_js else False,
                config={"displaylogo": False},
            )
        )
        chart_blocks.append("</section>")
        include_js = False

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
    sections = [_df_section_html(str(title), df) for (title, df) in sections_data]
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{escape(dashboard_title)} - {escape(selected_group)}</title>
  <style>
    body {{ background:{theme["body_bg"]}; color:{theme["font"]}; font-family:Segoe UI, Arial, sans-serif; margin:20px; font-size:{theme["base_font_size"]}; }}
    .container {{ max-width:{theme["max_width"]}; margin:0 auto; }}
    h1, h2 {{ margin:0 0 10px 0; }}
    p {{ color:{theme["muted"]}; }}
    .meta {{ margin-bottom:18px; }}
    .metrics {{ display:grid; grid-template-columns:repeat(4,minmax(180px,1fr)); gap:12px; margin:14px 0 18px 0; }}
    .metric-card {{ background:{theme["card_bg"]}; border:1px solid {theme["border"]}; border-radius:10px; padding:12px; }}
    .metric-label {{ color:{theme["muted"]}; font-size:12px; }}
    .metric-value {{ font-size:30px; margin:8px 0 6px 0; }}
    .metric-delta {{ color:{theme["font"]}; opacity:0.9; font-size:13px; min-height:16px; }}
    section {{ margin-bottom:18px; }}
    .report-table {{ width:100%; border-collapse:collapse; background:{theme["table_bg"]}; border:1px solid {theme["border"]}; }}
    .report-table th, .report-table td {{ border:1px solid {theme["border"]}; padding:6px 8px; text-align:left; }}
    .report-table th {{ background:{theme["table_head"]}; }}
    @media (max-width: 1000px) {{
      .metrics {{ grid-template-columns:repeat(2,minmax(160px,1fr)); }}
    }}
  </style>
</head>
<body>
  <div class="container">
  <h1>{escape(dashboard_title)}</h1>
  <div class="meta">
    <p><strong>Group:</strong> {escape(selected_group)}</p>
    <p><strong>Export Mode:</strong> {escape(str(theme["name"]))}</p>
    <p><strong>Accounts:</strong> {escape(accounts_text)}</p>
    <p><strong>Generated:</strong> {escape(generated_at)}</p>
  </div>
  <div class="metrics">{cards_html}</div>
  {''.join(chart_blocks)}
  {''.join(sections)}
  </div>
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
    )
    theme = _export_theme(export_mode)
    chart_items: list[tuple[str, go.Figure | None]] = payload["chart_items"]
    sections_data: list[tuple[str, pd.DataFrame]] = payload["sections"]
    metric_cards: list[tuple[str, str, str]] = payload["metric_cards"]
    accounts_text = str(payload["accounts_text"])
    generated_at = str(payload["generated_at"])

    width = 1800
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
    key: str,
) -> None:
    mode_options = ["Dark", "Light", "WhatsApp"]
    mode_label = st.selectbox("Export Mode", options=mode_options, index=0, key=f"{key}_mode")
    export_mode = str(mode_label).strip().lower()
    export_format = st.selectbox("Export Format", options=["HTML", "Picture (PNG)"], index=0, key=f"{key}_format")
    stamp = pd.Timestamp.now().strftime("%Y-%m-%d")
    base_name = f"{stamp}_{_slugify(selected_group)}_{_slugify(dashboard_title)}_{_slugify(export_mode)}"

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
        )
        if png_err:
            st.warning(png_err)
        st.download_button(
            "Export This Group (PNG)",
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
    )
    st.download_button(
        "Export This Group (HTML)",
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
) -> None:
    dash_latest_xp_df = latest_xp_snapshot(dash_xp_df)
    dash_recent_gain_df = xp_recent_gain(dash_xp_df, days=30)

    c1, c2, c3, c4 = st.columns(4)
    if not dash_latest_xp_df.empty:
        leader_row = dash_latest_xp_df.sort_values("Total XP", ascending=False).iloc[0]
        c1.metric(
            "XP Leader",
            f"{int(leader_row['Total XP']):,}",
            delta=f"{leader_row['Spieler']} (Lvl {int(leader_row['Lvl'])})",
        )
    else:
        c1.metric("XP Leader", "-", delta="no data")

    if not dash_recent_gain_df.empty:
        gain_leader = dash_recent_gain_df.sort_values("xp_gain", ascending=False).iloc[0]
        c2.metric(
            "Top 30d XP Gain",
            f"{int(gain_leader['xp_gain']):,}",
            delta=str(gain_leader["Spieler"]),
        )
    else:
        c2.metric("Top 30d XP Gain", "-", delta="no data")

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
            c3.metric("Team Platinum Total", f"{team_platinum_total:,}", delta=" | ".join(breakdown) if breakdown else None)
        else:
            c3.metric("Team Platinum Total", "-", delta="no data")
    else:
        newcomer = top_newcomer(dash_xp_df)
        if newcomer is None:
            c3.metric("Most Improved Pace", "-", delta="no data")
        else:
            c3.metric(
                "Most Improved Pace",
                newcomer["spieler"],
                delta=(
                    f"{int(round(float(newcomer['current_pace']))):,} XP/day "
                    f"({int(round(float(newcomer['improvement']))):+,} vs own median)"
                ),
            )

    if not dash_latest_xp_df.empty:
        latest_xp_date = pd.to_datetime(dash_latest_xp_df["Date"], errors="coerce").max()
        if pd.notna(latest_xp_date):
            days_ago = (pd.Timestamp.today().normalize() - latest_xp_date.normalize()).days
            c4.metric("Last XP Snapshot", latest_xp_date.strftime("%Y-%m-%d"), delta=f"{int(days_ago)} day(s) ago")
        else:
            c4.metric("Last XP Snapshot", "-", delta="no data")
    else:
        c4.metric("Last XP Snapshot", "-", delta="no data")

    if not dash_latest_xp_df.empty:
        ranking_df = dash_latest_xp_df.sort_values("Total XP", ascending=False).reset_index(drop=True).copy()
        ranking_df["rank"] = range(1, len(ranking_df) + 1)
        leader_xp = float(ranking_df["Total XP"].iloc[0]) if not ranking_df.empty else 0.0
        ranking_df["gap_to_leader"] = leader_xp - ranking_df["Total XP"]
        if not dash_recent_gain_df.empty:
            gain_map = dash_recent_gain_df.set_index("Spieler")["xp_per_day"].to_dict()
            ranking_df["xp_per_day_30d"] = ranking_df["Spieler"].map(gain_map)
        else:
            ranking_df["xp_per_day_30d"] = pd.NA

        fig_growth = build_xp_growth_figure(curve_map, dash_latest_xp_df)
        if fig_growth is not None:
            st.plotly_chart(fig_growth, use_container_width=True)

        d_left, d_right = st.columns([1.05, 1.0])
        with d_left:
            st.subheader("Current XP Ranking")
            ranking_view = ranking_df[["rank", "Spieler", "Lvl", "Total XP", "gap_to_leader", "xp_per_day_30d"]].copy()
            st.dataframe(
                ranking_view,
                use_container_width=True,
                hide_index=True,
                height=380,
                column_config={
                    "rank": st.column_config.NumberColumn("Rank", format="%d"),
                    "Total XP": st.column_config.NumberColumn("Total XP", format="%d"),
                    "gap_to_leader": st.column_config.NumberColumn("Gap to #1", format="%d"),
                    "xp_per_day_30d": st.column_config.NumberColumn("XP/Day (30d)", format="%.0f"),
                },
            )
        with d_right:
            st.subheader("XP Gain (Last 30 Days)")
            if dash_recent_gain_df.empty:
                st.info("Not enough history yet for 30-day gain view.")
            else:
                gain_top = dash_recent_gain_df.sort_values("xp_gain", ascending=False).head(10).copy()
                fig_gain = px.bar(
                    gain_top.sort_values("xp_gain", ascending=True),
                    x="xp_gain",
                    y="Spieler",
                    orientation="h",
                    title="Top XP Gain (30d)",
                    labels={"xp_gain": "XP Gain", "Spieler": "Account"},
                )
                fig_gain.update_layout(height=300, margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig_gain, use_container_width=True)
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

    if show_medals and not dash_display_medal_df.empty and not goals_df.empty:
        st.subheader("Latest Medal Status")
        latest_medals = dash_display_medal_df.sort_values("date").groupby(["account", "medal_id"], as_index=False).tail(1)
        latest_medals = latest_medals.merge(goals_df, on="medal_id", how="left")
        latest_medals["pct_goal"] = (latest_medals["value"] / latest_medals["goal_value"] * 100).round(1)
        latest_medals["is_platinum"] = latest_medals["value"] >= latest_medals["goal_value"]
        platinum_now = latest_medals[latest_medals["medal_id"] == DERIVED_MEDAL_ID][["account", "value"]].copy()
        platinum_now = platinum_now.rename(columns={"value": "platinum_count"})
        if not platinum_now.empty:
            ordered_accounts = [a for a in ACCOUNT_ORDER if a in set(platinum_now["account"].astype(str))]
            ordered_accounts += [
                a for a in sorted(platinum_now["account"].astype(str).unique().tolist()) if a not in ordered_accounts
            ]
            cols = st.columns(max(1, len(ordered_accounts)))
            for idx, acc in enumerate(ordered_accounts):
                row = platinum_now[platinum_now["account"].astype(str) == acc]
                if row.empty:
                    cols[idx].metric(f"{acc} Platinum", "0")
                else:
                    cols[idx].metric(f"{acc} Platinum", f"{int(float(row['platinum_count'].iloc[0]))}")

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
            st.info("No achieved platinum medals found yet.")
        else:
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

            st.dataframe(
                first_achieved[["achieved_date", "account", "display_name", "value_at_achievement", "goal_value"]],
                use_container_width=True,
                hide_index=True,
            )


st.set_page_config(page_title="PoGo Local Dashboard", layout="wide")
st.title("PoGo Local Dashboard")
st.caption("Interactive XP + medal dashboard.")

curve_map = load_curve_map(total_xp_curve_path())
xp_df = load_xp_history(xp_history_path(), curve_map)
groups = parse_groups(player_groups_path())
medal_df = load_medal_snapshots(medal_snapshots_path())
goals_df = load_medal_goals(medals_config_path())
display_medal_df = with_derived_platinum_rows(medal_df, goals_df)
all_accounts = account_options_from_data(xp_df, medal_df)
latest_xp_df = latest_xp_snapshot(xp_df)
recent_gain_df = xp_recent_gain(xp_df, days=30)

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
            key="export_dashboard_global",
        )
        render_dashboard_content(
            dash_xp_df=dash_xp_df,
            dash_medal_df=dash_medal_df,
            dash_display_medal_df=dash_display_medal_df,
            goals_df=goals_df,
            curve_map=curve_map,
            show_medals=False,
        )
        st.divider()
        render_xp_explorer_section(dash_xp_df, key_prefix="dashboard_global_xp_explorer")

if page == "Dashboard Personal":
    st.subheader("Dashboard Personal")
    all_dashboard_accounts = sorted(
        set(xp_df["Spieler"].dropna().astype(str).tolist()) | set(display_medal_df["account"].dropna().astype(str).tolist())
    )
    personal_group_options = [g for g in groups.keys() if str(g).strip().lower() in {"ich", "ownaccounts"}]
    dashboard_group_options = ["All"] + personal_group_options
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
            key="export_dashboard_personal",
        )
        render_dashboard_content(
            dash_xp_df=dash_xp_df,
            dash_medal_df=dash_medal_df,
            dash_display_medal_df=dash_display_medal_df,
            goals_df=goals_df,
            curve_map=curve_map,
            show_medals=True,
        )
        st.divider()
        render_xp_explorer_section(dash_xp_df, key_prefix="dashboard_personal_xp_explorer")

if page == "Medal Explorer":
    st.subheader("Medal Explorer")
    if display_medal_df.empty:
        st.warning("No medal snapshot data found.")
    else:
        selected_accounts = st.multiselect("Accounts", all_accounts, default=all_accounts[:3] or all_accounts)
        df = display_medal_df[display_medal_df["account"].isin(selected_accounts)].copy()
        if df.empty:
            st.warning("No rows for selected accounts.")
        else:
            min_date = df["date"].min().date()
            max_date = df["date"].max().date()
            d_start, d_end = st.slider("Date range", min_value=min_date, max_value=max_date, value=(min_date, max_date))
            df = df[(df["date"] >= pd.Timestamp(d_start)) & (df["date"] <= pd.Timestamp(d_end))].copy()

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

            show_goal_trends = st.checkbox(
                "Show trend-to-goal lines (legend selectable; platinum uses medal-completion trends)",
                value=False,
                key="show_medal_goal_trends",
            )

            def add_goal_and_trends(fig_medal: go.Figure, line_df: pd.DataFrame, medal_id: str) -> None:
                goal_lookup_id = goal_medal_id_for(medal_id)
                goal_val = goals_map.get(goal_lookup_id)
                if goal_val is None or pd.isna(goal_val):
                    return
                goal_val_f = float(goal_val)

                fig_medal.add_hline(
                    y=goal_val_f,
                    line_dash="dash",
                    line_color="gray",
                    annotation_text=f"Goal: {goal_val:g}",
                    annotation_position="top left",
                )
                y_max_data = pd.to_numeric(line_df.get("value"), errors="coerce").max()
                if pd.notna(y_max_data):
                    y_top = max(float(y_max_data), goal_val_f)
                    if y_top <= 0:
                        y_top = 1.0
                    fig_medal.update_yaxes(range=[0, y_top * 1.05])
                if not show_goal_trends:
                    return
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

            medal_ids_available = set(df["medal_id"].astype(str).tolist())

            # Full-width platinum chart on top.
            if DERIVED_MEDAL_ID in medal_ids_available:
                platinum_df = df[df["medal_id"] == DERIVED_MEDAL_ID].copy()
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
                    add_goal_and_trends(fig_platinum, platinum_df, DERIVED_MEDAL_ID)
                    fig_platinum.update_layout(height=520)
                    st.plotly_chart(fig_platinum, use_container_width=True)

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
                    fig_xp.add_hline(
                        y=xp_goal_value,
                        line_dash="dash",
                        line_color="gray",
                        annotation_text=f"Goal L{xp_goal_level}: {int(xp_goal_value):,}",
                        annotation_position="top left",
                    )
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
                fig_xp.update_layout(height=460)
                y_max_xp = pd.to_numeric(xp_line_df["Total XP"], errors="coerce").max()
                if xp_goal_value is not None:
                    y_max_xp = max(float(y_max_xp), xp_goal_value)
                if pd.notna(y_max_xp):
                    y_top_xp = max(1.0, float(y_max_xp) * 1.05)
                    fig_xp.update_yaxes(range=[0, y_top_xp], tickformat=",.0f")
                else:
                    fig_xp.update_yaxes(tickformat=",.0f")
                st.plotly_chart(fig_xp, use_container_width=True)

            medals_for_grid = {
                m for m in medal_ids_available if m not in EXCLUDED_MEDAL_GRAPH_IDS and m != DERIVED_MEDAL_ID
            }
            thombay_order = load_medal_input_order(goals_df, account="Thombay")
            medal_ids = [m for m in thombay_order if m in medals_for_grid]
            medal_ids += sorted([m for m in medals_for_grid if m not in medal_ids])

            selected_medals = st.multiselect(
                "Medals",
                options=medal_ids,
                default=medal_ids,
                help="All medals are selected by default. Click legend items in each chart to show/hide accounts.",
            )
            selected_medals = [m for m in medal_ids if m in set(selected_medals)]

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
                            title=f"Progress: {title_label}",
                        )
                        add_goal_and_trends(fig_medal, line_df, medal_id)
                        fig_medal.update_layout(height=320)
                        with row_cols[col_idx]:
                            st.plotly_chart(fig_medal, use_container_width=True)

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
    tab_xp, tab_medal = st.tabs(["XP Snapshot Input", "Medal Snapshot Input"])

    with tab_xp:
        st.caption("Enter one snapshot date and update multiple accounts at once.")
        xp_date = st.date_input("XP Date", value=date.today(), key="xp_batch_date")
        raw_players = sorted(xp_df["Spieler"].unique().tolist()) if not xp_df.empty else ACCOUNT_ORDER
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

            xp_editor_rows = []
            for acc in selected_xp_accounts:
                lvl_default, xp_default = latest_map.get(acc, (1, 0))
                xp_editor_rows.append(
                    {
                        "account": acc,
                        "lvl_last": int(lvl_default),
                        "xp_bar_last": int(xp_default),
                        "lvl": lvl_default,
                        "xp_bar": xp_default,
                    }
                )

            _, xp_input_col, _ = st.columns([0.28, 0.44, 0.28], gap="small")
            col_widths = [1.45, 0.7, 1.0, 0.85, 1.2]
            h1, h2, h3, h4, h5 = xp_input_col.columns(col_widths, gap="small")
            h1.markdown("**Account**")
            h2.markdown("**Level (last Data)**")
            h3.markdown("**XPBar (last Data)**")
            h4.markdown("**Level**")
            h5.markdown("**XP Bar**")

            xp_inputs: list[dict[str, object]] = []
            for row in xp_editor_rows:
                acc = str(row["account"])
                c1, c2, c3, c4, c5 = xp_input_col.columns(col_widths, gap="small")
                c1.write(acc)
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
                lvl_value = c4.number_input(
                    "Level",
                    min_value=1,
                    max_value=100,
                    step=1,
                    key=lvl_state_key,
                    label_visibility="collapsed",
                )
                xp_bar_value = c5.text_input(
                    "XP Bar",
                    value=str(int(row["xp_bar"])),
                    key=f"xp_bar_input_{xp_date.isoformat()}_{acc}",
                    label_visibility="collapsed",
                )
                xp_inputs.append({"account": acc, "lvl": int(lvl_value), "xp_bar": xp_bar_value})

            if st.button("Save XP snapshot for selected accounts", key="xp_batch_save"):
                rows_to_write: list[dict[str, object]] = []
                errors: list[str] = []
                for r in xp_inputs:
                    acc = str(r.get("account", "")).strip()
                    lvl = pd.to_numeric(r.get("lvl"), errors="coerce")
                    xp_bar = pd.to_numeric(r.get("xp_bar"), errors="coerce")
                    if not acc:
                        errors.append("Missing account value.")
                        continue
                    if pd.isna(lvl) or int(lvl) < 1:
                        errors.append(f"{acc}: invalid level.")
                        continue
                    if pd.isna(xp_bar) or int(xp_bar) < 0:
                        errors.append(f"{acc}: invalid XP Bar.")
                        continue
                    rows_to_write.append(
                        {
                            "Date": xp_date.isoformat(),
                            "Spieler": acc,
                            "Lvl": int(lvl),
                            "XP Bar": int(xp_bar),
                        }
                    )
                if errors:
                    st.error("\n".join(errors))
                else:
                    written = upsert_xp_rows(xp_history_path(), rows_to_write)
                    st.success(f"Saved XP snapshot rows: {written}")

        if all_players:
            st.markdown("Input order for XP accounts")
            st.caption("Move one account to a target position; all others are shifted automatically.")
            xp_order = load_xp_input_order(all_players)

            xp_order_labels: list[str] = []
            xp_label_to_account: dict[str, str] = {}
            for i, account_name in enumerate(xp_order, start=1):
                label = f"{i}. {account_name}"
                xp_order_labels.append(label)
                xp_label_to_account[label] = account_name

            c_xp_move_1, c_xp_move_2, c_xp_move_3 = st.columns([2, 1, 1])
            with c_xp_move_1:
                xp_move_label = st.selectbox("Account to move", options=xp_order_labels, key="xp_move_label")
            with c_xp_move_2:
                xp_move_to = st.number_input(
                    "Move to position",
                    min_value=1,
                    max_value=max(1, len(xp_order)),
                    value=1,
                    step=1,
                    key="xp_move_to",
                )
            with c_xp_move_3:
                st.write("")
                st.write("")
                xp_apply_move = st.button("Apply Move", key="xp_apply_move")

            if xp_apply_move and xp_order:
                moving_account = xp_label_to_account.get(xp_move_label, "")
                if moving_account in xp_order:
                    new_order = [a for a in xp_order if a != moving_account]
                    insert_idx = int(xp_move_to) - 1
                    new_order.insert(insert_idx, moving_account)
                    save_xp_input_order(new_order)
                    st.success("Updated XP input order.")
                    st.rerun()

            xp_order_preview = [{"position": i, "account": acc} for i, acc in enumerate(xp_order, start=1)]
            st.dataframe(pd.DataFrame(xp_order_preview), use_container_width=True, hide_index=True)

    with tab_medal:
        st.caption("Enter one full medal snapshot per account.")
        st.caption("`Platinum Medals` is derived automatically from medals that reached their goal.")
        medal_date = st.date_input("Medal Date", value=date.today(), key="medal_full_date")
        allowed_accounts = [a for a in ACCOUNT_ORDER]
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
                        "display_name": row_goal.get("display_name", medal_id),
                        "goal_value": row_goal.get("goal_value", 0),
                        "last_input_value": last_input_value,
                        "value": last_input_value,
                    }
                )
            _, medal_input_col, _ = st.columns([0.24, 0.52, 0.24], gap="small")
            with medal_input_col:
                edited_medals = st.data_editor(
                    pd.DataFrame(editor_rows),
                    hide_index=True,
                    use_container_width=True,
                    disabled=["display_name", "goal_value", "last_input_value"],
                    height=520,
                    column_config={
                        "display_name": st.column_config.TextColumn("Display Name", width="medium"),
                        "goal_value": st.column_config.NumberColumn("Goal", width="small"),
                        "last_input_value": st.column_config.NumberColumn("Last Input Value", width="small"),
                        "value": st.column_config.NumberColumn("Value", step=1.0, width="small"),
                    },
                    key=f"medal_full_editor_{medal_account}",
                )
            if st.button("Save full medal snapshot for account", key="save_full_medal_snapshot"):
                rows_to_write: list[dict[str, object]] = []
                errors: list[str] = []
                if len(edited_medals) != len(medal_order_for_account):
                    errors.append("Editor row count mismatch. Reload and try again.")
                for idx, (_, r) in enumerate(edited_medals.iterrows()):
                    if idx >= len(medal_order_for_account):
                        break
                    medal_id = str(medal_order_for_account[idx]).strip().lower()
                    value = pd.to_numeric(r.get("value"), errors="coerce")
                    if not medal_id:
                        errors.append("Missing medal_id.")
                        continue
                    if medal_id in EXCLUDED_MANUAL_MEDAL_IDS:
                        errors.append(f"{medal_id} is derived and not allowed in medal snapshots.")
                        continue
                    if pd.isna(value):
                        errors.append(f"{medal_id}: value is empty.")
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
                    written = append_medal_rows(medal_snapshots_path(), rows_to_write)
                    st.success(f"Saved medal snapshot rows: {written} for {medal_account}")

            medal_order = load_medal_input_order(goals_df, account=medal_account)
            st.markdown(f"Input order for `{medal_account}`")
            st.caption("Move one medal to a target position; all others are shifted automatically.")

            order_labels: list[str] = []
            label_to_medal: dict[str, str] = {}
            for i, medal_id in enumerate(medal_order, start=1):
                display_name = goals_map.get(medal_id, {}).get("display_name", medal_id)
                label = f"{i}. {display_name}"
                order_labels.append(label)
                label_to_medal[label] = medal_id

            c_move_1, c_move_2, c_move_3 = st.columns([2, 1, 1])
            with c_move_1:
                move_label = st.selectbox("Medal to move", options=order_labels, key=f"move_label_{medal_account}")
            with c_move_2:
                move_to = st.number_input(
                    "Move to position",
                    min_value=1,
                    max_value=max(1, len(medal_order)),
                    value=1,
                    step=1,
                    key=f"move_to_{medal_account}",
                )
            with c_move_3:
                st.write("")
                st.write("")
                apply_move = st.button("Apply Move", key=f"apply_move_{medal_account}")

            if apply_move and medal_order:
                moving_medal_id = label_to_medal.get(move_label, "")
                if moving_medal_id in medal_order:
                    new_order = [m for m in medal_order if m != moving_medal_id]
                    insert_idx = int(move_to) - 1
                    new_order.insert(insert_idx, moving_medal_id)
                    save_medal_input_order(medal_account, new_order)
                    st.success(f"Updated order for {medal_account}.")
                    st.rerun()

            order_preview_rows = []
            for i, medal_id in enumerate(medal_order, start=1):
                display_name = goals_map.get(medal_id, {}).get("display_name", medal_id)
                order_preview_rows.append({"position": i, "display_name": display_name})
            st.dataframe(pd.DataFrame(order_preview_rows), use_container_width=True, hide_index=True)

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
