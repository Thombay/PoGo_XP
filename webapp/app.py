from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
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
    df = df[df["medal_id"] != "total_xp"].copy()
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
    new_df = new_df[new_df["medal_id"] != "total_xp"].copy()
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


def load_medal_input_order(goals: pd.DataFrame, account: str | None = None) -> list[str]:
    valid = [m for m in goals["medal_id"].astype(str).tolist() if m != "total_xp"]
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


st.set_page_config(page_title="PoGo Local Dashboard", layout="wide")
st.title("PoGo Local Dashboard")
st.caption("Interactive XP + medal dashboard with local CSV input.")

curve_map = load_curve_map(total_xp_curve_path())
xp_df = load_xp_history(xp_history_path(), curve_map)
groups = parse_groups(player_groups_path())
medal_df = load_medal_snapshots(medal_snapshots_path())
goals_df = load_medal_goals(medals_config_path())
all_accounts = account_options_from_data(xp_df, medal_df)

pages = ["Dashboard", "XP Explorer", "Medal Explorer", "Data Input", "Pipelines", "Generated Files"]
page = st.radio("Page", pages, horizontal=True)

if page == "Dashboard":
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("XP rows", f"{len(xp_df):,}")
    c2.metric("XP players", f"{xp_df['Spieler'].nunique():,}" if not xp_df.empty else "0")
    c3.metric("Medal rows", f"{len(medal_df):,}")
    c4.metric("Medal ids", f"{medal_df['medal_id'].nunique():,}" if not medal_df.empty else "0")

    if not xp_df.empty:
        st.subheader("Latest XP Snapshot")
        latest = xp_df.sort_values(["Spieler", "Date"]).groupby("Spieler", as_index=False).tail(1)
        latest = latest.sort_values("Total XP", ascending=False).reset_index(drop=True)
        st.dataframe(
            latest[["Date", "Spieler", "Lvl", "XP Bar", "Total XP"]],
            use_container_width=True,
            hide_index=True,
        )

    if not medal_df.empty and not goals_df.empty:
        st.subheader("Latest Medal Progress")
        latest_medals = medal_df.sort_values("date").groupby(["account", "medal_id"], as_index=False).tail(1)
        latest_medals = latest_medals.merge(goals_df, on="medal_id", how="left")
        latest_medals["pct_goal"] = (latest_medals["value"] / latest_medals["goal_value"] * 100).round(1)
        latest_medals["is_platinum"] = latest_medals["value"] >= latest_medals["goal_value"]
        st.dataframe(
            latest_medals[["date", "account", "medal_id", "display_name", "value", "goal_value", "pct_goal", "is_platinum"]],
            use_container_width=True,
            hide_index=True,
        )

if page == "XP Explorer":
    st.subheader("XP Explorer")
    if xp_df.empty:
        st.warning("No XP history data found.")
    else:
        group_names = list(groups.keys())
        if not group_names:
            group_names = ["All players"]
            groups = {"All players": sorted(xp_df["Spieler"].unique().tolist())}

        default_group = "3Accounts" if "3Accounts" in groups else group_names[0]
        selected_group = st.selectbox("Group", group_names, index=group_names.index(default_group))
        default_players = groups.get(selected_group, [])
        selected_players = st.multiselect(
            "Players",
            options=sorted(xp_df["Spieler"].unique().tolist()),
            default=[p for p in default_players if p in set(xp_df["Spieler"])],
        )
        common_interval_only = st.checkbox("Use common interval for all selected players", value=True)

        df = xp_df[xp_df["Spieler"].isin(selected_players)].copy()
        if common_interval_only:
            df = restrict_to_common_interval(df)
        if df.empty:
            st.warning("No rows for selected filters.")
        else:
            min_date = df["Date"].min().date()
            max_date = df["Date"].max().date()
            d_start, d_end = st.slider("Date range", min_value=min_date, max_value=max_date, value=(min_date, max_date))
            df = df[(df["Date"] >= pd.Timestamp(d_start)) & (df["Date"] <= pd.Timestamp(d_end))].copy()

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

if page == "Medal Explorer":
    st.subheader("Medal Explorer")
    if medal_df.empty:
        st.warning("No medal snapshot data found.")
    else:
        selected_accounts = st.multiselect("Accounts", all_accounts, default=all_accounts[:3] or all_accounts)
        df = medal_df[medal_df["account"].isin(selected_accounts)].copy()
        if df.empty:
            st.warning("No rows for selected accounts.")
        else:
            min_date = df["date"].min().date()
            max_date = df["date"].max().date()
            d_start, d_end = st.slider("Date range", min_value=min_date, max_value=max_date, value=(min_date, max_date))
            df = df[(df["date"] >= pd.Timestamp(d_start)) & (df["date"] <= pd.Timestamp(d_end))].copy()

            medal_ids = sorted(df["medal_id"].unique().tolist())
            default_medal = "platinum_medals" if "platinum_medals" in medal_ids else medal_ids[0]
            selected_medal = st.selectbox("Medal", medal_ids, index=medal_ids.index(default_medal))

            line_df = df[df["medal_id"] == selected_medal].copy()
            if not line_df.empty:
                fig_medal = px.line(
                    line_df,
                    x="date",
                    y="value",
                    color="account",
                    markers=True,
                    title=f"Progress: {selected_medal}",
                )
                st.plotly_chart(fig_medal, use_container_width=True)

            if not goals_df.empty:
                latest = df.sort_values("date").groupby(["account", "medal_id"], as_index=False).tail(1)
                latest = latest.merge(goals_df, on="medal_id", how="left")
                latest["pct_goal"] = (latest["value"] / latest["goal_value"] * 100).round(1)
                latest["is_platinum"] = latest["value"] >= latest["goal_value"]
                st.dataframe(
                    latest[
                        [
                            "date",
                            "account",
                            "medal_id",
                            "display_name",
                            "value",
                            "goal_value",
                            "pct_goal",
                            "is_platinum",
                        ]
                    ].sort_values(["account", "medal_id"]),
                    use_container_width=True,
                    hide_index=True,
                )

                source = df.merge(goals_df[["medal_id", "goal_value"]], on="medal_id", how="left")
                source = source[source["medal_id"] != "platinum_medals"].copy()
                source = source.dropna(subset=["goal_value"])
                source["reached"] = source["value"] >= source["goal_value"]
                source = source.sort_values("date").drop_duplicates(["date", "account", "medal_id"], keep="last")
                platinum_counts = (
                    source.groupby(["date", "account"], as_index=False)["reached"].sum().rename(columns={"reached": "derived_platinum_count"})
                )
                if not platinum_counts.empty:
                    fig_plat = px.line(
                        platinum_counts,
                        x="date",
                        y="derived_platinum_count",
                        color="account",
                        markers=True,
                        title="Derived Platinum Medal Count",
                    )
                    st.plotly_chart(fig_plat, use_container_width=True)

if page == "Data Input":
    st.subheader("Data Input")
    tab_xp, tab_medal = st.tabs(["XP Snapshot Input", "Medal Snapshot Input"])

    with tab_xp:
        st.caption("Enter one snapshot date and update multiple accounts at once.")
        xp_date = st.date_input("XP Date", value=date.today(), key="xp_batch_date")
        all_players = sorted(xp_df["Spieler"].unique().tolist()) if not xp_df.empty else ACCOUNT_ORDER
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
                xp_editor_rows.append({"account": acc, "lvl": lvl_default, "xp_bar": xp_default})

            edited_xp = st.data_editor(
                pd.DataFrame(xp_editor_rows),
                hide_index=True,
                use_container_width=True,
                disabled=["account"],
                column_config={
                    "account": st.column_config.TextColumn("Account"),
                    "lvl": st.column_config.NumberColumn("Level", min_value=1, max_value=100, step=1),
                    "xp_bar": st.column_config.NumberColumn("XP Bar", min_value=0, step=1),
                },
                key="xp_batch_editor",
            )
            if st.button("Save XP snapshot for selected accounts", key="xp_batch_save"):
                rows_to_write: list[dict[str, object]] = []
                errors: list[str] = []
                for _, r in edited_xp.iterrows():
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

    with tab_medal:
        st.caption("Enter one full medal snapshot per account.")
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
            medal_order = load_medal_input_order(goals_df, account=medal_account)
            goals_map = goals_df.set_index("medal_id")[["display_name", "goal_value"]].to_dict("index")

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
                editor_rows.append(
                    {
                        "display_name": row_goal.get("display_name", medal_id),
                        "goal_value": row_goal.get("goal_value", 0),
                        "value": latest_vals.get(medal_id, 0.0),
                    }
                )
            edited_medals = st.data_editor(
                pd.DataFrame(editor_rows),
                hide_index=True,
                use_container_width=True,
                disabled=["display_name", "goal_value"],
                column_config={
                    "display_name": st.column_config.TextColumn("Display Name"),
                    "goal_value": st.column_config.NumberColumn("Goal"),
                    "value": st.column_config.NumberColumn("Value", step=1.0),
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
                    if medal_id == "total_xp":
                        errors.append("total_xp is not allowed in medal snapshots.")
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
