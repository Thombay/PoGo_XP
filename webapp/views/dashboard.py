from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from webapp.metrics import compute_player_kpis_window, recent_gain_table_from_metrics


def render_dashboard_content_view(
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
    *,
    account_order: Sequence[str],
    derived_medal_id: str,
    baseline_min_windows_default: int,
    window_col_fn: Callable[[str, int], str],
    latest_xp_snapshot_fn: Callable[[pd.DataFrame], pd.DataFrame],
    render_kpi_card_fn: Callable[..., Any],
    format_kpi_number_fn: Callable[[object, str], str],
    build_xp_growth_figure_fn: Callable[[dict[int, int], pd.DataFrame], Any],
    render_plotly_chart_fn: Callable[..., Any],
) -> None:
    w = int(window_days)
    w_label = f"{w}d"
    eligible_col = window_col_fn("eligible", w)
    eligible_baseline_col = window_col_fn("eligible_baseline", w)
    window_end_col = window_col_fn("window_end", w)
    xp_gain_col = window_col_fn("xp_gain", w)
    xp_per_day_col = window_col_fn("xp_per_day", w)
    delta_col = window_col_fn("delta_vs_baseline", w)
    pct_col = window_col_fn("pct_vs_baseline", w)

    dash_latest_xp_df = latest_xp_snapshot_fn(dash_xp_df)
    metrics_window_df = compute_player_kpis_window(
        dash_xp_df,
        window_days=w,
        baseline_min_windows=baseline_min_windows_default,
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
        c1, c2, c3, c4, c5, c6 = st.columns([1, 1, 1, 1, 1, 0.95])
        last_snapshot_col = c6
    else:
        c1, c2, c3, c4, c5, c6, c7 = st.columns([1, 1, 1, 1, 1, 1, 0.95])
        last_snapshot_col = c7
    if not dash_latest_xp_df.empty:
        leader_row = dash_latest_xp_df.sort_values("Total XP", ascending=False).iloc[0]
        render_kpi_card_fn(
            c1,
            "XP Leader",
            format_kpi_number_fn(leader_row["Total XP"], "XP"),
            winner=winner_with_level(leader_row["Spieler"]),
            context=f"Level {int(leader_row['Lvl'])}",
            help_text="Latest total XP snapshot per player.",
        )
    else:
        render_kpi_card_fn(c1, "XP Leader", "-", context="no data")

    if not active_kpi_pool.empty:
        gain_leader = active_kpi_pool.sort_values([xp_gain_col, xp_per_day_col], ascending=[False, False]).iloc[0]
        gain_to_date = pd.to_datetime(gain_leader[window_end_col], errors="coerce")
        render_kpi_card_fn(
            c2,
            f"Top XP Gain ({w_label})",
            format_kpi_number_fn(gain_leader[xp_gain_col], "XP"),
            winner=winner_with_level(gain_leader["Spieler"]),
            context=f"{format_kpi_number_fn(gain_leader[xp_per_day_col], 'XP/day')} pace",
            help_text=(
                f"{w}-day rolling XP gain (xp_at(now) - xp_at(now-{w}d)).\n"
                f"Window end: {gain_to_date.strftime('%Y-%m-%d') if pd.notna(gain_to_date) else '-'}"
            ),
        )
    elif not eligible_gain_pool.empty:
        render_kpi_card_fn(
            c2,
            f"Top XP Gain ({w_label})",
            f"No active players ({w_label})",
            context=f"all {xp_gain_col} = 0",
            delta_color="off",
        )
    else:
        render_kpi_card_fn(c2, f"Top XP Gain ({w_label})", "-", context="no data")

    if not active_kpi_pool.empty:
        gain_trailer = active_kpi_pool.sort_values([xp_gain_col, xp_per_day_col], ascending=[True, True]).iloc[0]
        gain_trailer_to_date = pd.to_datetime(gain_trailer[window_end_col], errors="coerce")
        render_kpi_card_fn(
            c3,
            f"Least XP Gain ({w_label})",
            format_kpi_number_fn(gain_trailer[xp_gain_col], "XP"),
            winner=winner_with_level(gain_trailer["Spieler"]),
            context=f"{format_kpi_number_fn(gain_trailer[xp_per_day_col], 'XP/day')} pace",
            help_text=(
                f"{w}-day rolling XP gain (xp_at(now) - xp_at(now-{w}d)).\n"
                f"Window end: {gain_trailer_to_date.strftime('%Y-%m-%d') if pd.notna(gain_trailer_to_date) else '-'}"
            ),
        )
    elif not eligible_gain_pool.empty:
        render_kpi_card_fn(
            c3,
            f"Least XP Gain ({w_label})",
            f"No active players ({w_label})",
            context=f"all {xp_gain_col} = 0",
            delta_color="off",
        )
    else:
        render_kpi_card_fn(c3, f"Least XP Gain ({w_label})", "-", context="no data")

    if show_medals:
        platinum_latest = dash_display_medal_df[dash_display_medal_df["medal_id"] == derived_medal_id].copy()
        if not platinum_latest.empty:
            platinum_latest = platinum_latest.sort_values("date").groupby("account", as_index=False).tail(1)
            team_platinum_total = int(pd.to_numeric(platinum_latest["value"], errors="coerce").fillna(0).sum())
            breakdown = []
            for acc in account_order:
                row = platinum_latest[platinum_latest["account"].astype(str) == acc]
                if not row.empty:
                    breakdown.append(f"{acc}:{int(float(row['value'].iloc[0]))}")
            render_kpi_card_fn(
                c4,
                "Team Platinum Total",
                format_kpi_number_fn(team_platinum_total),
                context=" | ".join(breakdown) if breakdown else None,
            )
        else:
            render_kpi_card_fn(c4, "Team Platinum Total", "-", context="no data")
    else:
        if active_kpi_pool.empty:
            if not eligible_gain_pool.empty:
                render_kpi_card_fn(
                    c4,
                    f"Fastest {w_label} Pace",
                    f"No active players ({w_label})",
                    context=f"all {xp_gain_col} = 0",
                    delta_color="off",
                )
            else:
                render_kpi_card_fn(c4, f"Fastest {w_label} Pace", "-", context="no data")
        else:
            fastest = active_kpi_pool.sort_values([xp_per_day_col, xp_gain_col], ascending=[False, False]).iloc[0]
            as_of = pd.to_datetime(fastest[window_end_col], errors="coerce")
            render_kpi_card_fn(
                c4,
                f"Fastest {w_label} Pace",
                format_kpi_number_fn(fastest[xp_per_day_col], "XP/day"),
                winner=winner_with_level(fastest["Spieler"]),
                context=f"{format_kpi_number_fn(fastest[xp_gain_col], 'XP')} gained in {w_label}",
                help_text=(
                    f"{w}-day rolling pace.\n"
                    f"Window end: {as_of.strftime('%Y-%m-%d') if pd.notna(as_of) else '-'}"
                ),
            )

        if eligible_baseline_pool.empty:
            render_kpi_card_fn(
                c5,
                f"Most Improved vs Baseline ({w_label})",
                "-",
                context="no baseline-eligible data",
                help_text=(
                    f"delta vs baseline where baseline is median of previous rolling {w_label} windows.\n"
                    f"Requires at least {baseline_min_windows_default} prior windows."
                ),
            )
            render_kpi_card_fn(
                c6,
                f"Most Declined vs Baseline ({w_label})",
                "-",
                context="no baseline-eligible data",
                help_text=(
                    "Shows a declined winner only if delta vs baseline is negative.\n"
                    f"Requires at least {baseline_min_windows_default} prior windows."
                ),
            )
        elif baseline_headline_pool.empty:
            render_kpi_card_fn(
                c5,
                f"Most Improved vs Baseline ({w_label})",
                "No improvements",
                context=f"all {xp_gain_col} = 0 for baseline-eligible players",
                delta_color="off",
            )
            render_kpi_card_fn(
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
                render_kpi_card_fn(
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
                render_kpi_card_fn(
                    c5,
                    f"Most Improved vs Baseline ({w_label})",
                    format_kpi_number_fn(improved[xp_per_day_col], "XP/day"),
                    winner=winner_with_level(improved["Spieler"]),
                    delta=f"{int(round(improved_delta)):+,} XP/day vs baseline",
                    help_text=(
                        f"baseline = median of previous rolling {w_label} windows (excluding current).\n"
                        f"Window end: {improved_as_of.strftime('%Y-%m-%d') if pd.notna(improved_as_of) else '-'}"
                    ),
                )

            declined_pool = baseline_headline_pool[baseline_headline_pool[delta_col] < 0].copy()
            if declined_pool.empty:
                render_kpi_card_fn(
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
                render_kpi_card_fn(
                    c6,
                    f"Most Declined vs Baseline ({w_label})",
                    format_kpi_number_fn(declined[xp_per_day_col], "XP/day"),
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
            render_kpi_card_fn(
                last_snapshot_col,
                "Last XP Snapshot",
                latest_xp_date.strftime("%Y-%m-%d"),
                delta=f"{int(days_ago)} day(s) ago",
                help_text="Latest snapshot date used in this dashboard selection.",
            )
        else:
            render_kpi_card_fn(last_snapshot_col, "Last XP Snapshot", "-", context="no data")
    else:
        render_kpi_card_fn(last_snapshot_col, "Last XP Snapshot", "-", context="no data")

    st.caption(
        f"Eligible for {w_label} stats: {eligible_window}/{total_players} | "
        f"Eligible for baseline comparisons: {eligible_baseline_window}/{total_players} "
        f"(baseline requires >= {baseline_min_windows_default} prior {w_label} windows) | "
        f"Active in {w_label} window ({xp_gain_col} > 0): {active_kpi_count}/{total_players}"
    )
    if show_30d_limited_hint:
        st.caption("30d limited coverage")

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

        fig_growth = build_xp_growth_figure_fn(curve_map, dash_latest_xp_df)
        if fig_growth is not None:
            render_plotly_chart_fn(fig_growth, use_container_width=True)

        d_left, d_right = st.columns([1.05, 1.0])
        with d_left:
            st.subheader(f"Current XP Ranking ({w_label})")
            xp_per_day_label = "XP/day"
            delta_label = "Delta vs Baseline"
            pct_label = "% vs Baseline"
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
                    xp_per_day_col: xp_per_day_label,
                    delta_col: delta_label,
                    pct_col: pct_label,
                }
            )

            ranking_styler = (
                ranking_view.style.format(
                    {
                        "Rank": "{:.0f}",
                        "Lvl": "{:.0f}",
                        "Total XP": "{:,.0f}",
                        "Gap to Leader": "{:,.0f}",
                        xp_per_day_label: "{:,.0f}",
                        delta_label: "{:+,.0f}",
                        pct_label: "{:+.1%}",
                    },
                    na_rep="--",
                )
                .map(
                    lambda v: "background-color: rgba(16, 185, 129, 0.20);"
                    if pd.notna(v) and float(v) > 0
                    else ("background-color: rgba(239, 68, 68, 0.20);" if pd.notna(v) and float(v) < 0 else ""),
                    subset=[delta_label, pct_label],
                )
            )
            with st.container(key="pogo_ranking_table"):
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
                render_plotly_chart_fn(fig_gain, use_container_width=True)
                gain_view = gain_top[["Spieler", "xp_gain", "xp_per_day"]].copy().rename(
                    columns={"xp_gain": "XP Gain", "xp_per_day": "XP/Day"}
                )
                gain_display = gain_view.copy()
                gain_display["XP Gain"] = pd.to_numeric(gain_display["XP Gain"], errors="coerce").map(
                    lambda v: "--" if pd.isna(v) else f"{int(round(float(v))):,}"
                )
                gain_display["XP/Day"] = pd.to_numeric(gain_display["XP/Day"], errors="coerce").map(
                    lambda v: "--" if pd.isna(v) else f"{int(round(float(v))):,}"
                )
                with st.container(key="pogo_ranking_table_gain"):
                    st.dataframe(
                        gain_display,
                        use_container_width=True,
                        hide_index=True,
                        height=210,
                    )
