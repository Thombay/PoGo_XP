from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from shared.paths import pokedex_species_entries_path
from webapp.pokedex import (
    build_pokedex_atlas_cards,
    build_pokedex_missing_count_rows,
    pokedex_atlas_html,
    upsert_pokedex_species_rows,
)


def render_pokedex_dashboard_view(
    display_pokedex_df: pd.DataFrame,
    pokedex_entry_config_df: pd.DataFrame,
    pokemon_catalog_df: pd.DataFrame,
    species_df: pd.DataFrame,
    availability_df: pd.DataFrame,
    all_accounts: Sequence[str],
    xp_df: pd.DataFrame,
    *,
    entry_types: Sequence[str],
    entry_type_labels: dict[str, str],
    regions: Sequence[str],
    region_labels: dict[str, str],
    normalize_rows_fn: Callable[[pd.DataFrame], pd.DataFrame],
    latest_rows_fn: Callable[..., pd.DataFrame],
    trend_rows_fn: Callable[..., pd.DataFrame],
    region_breakdown_fn: Callable[..., pd.DataFrame],
    filter_rows_fn: Callable[..., pd.DataFrame],
    select_date_range_fn: Callable[..., tuple[date, date]],
    build_account_color_map_fn: Callable[..., dict[str, str]],
    render_account_color_legend_fn: Callable[..., Any],
    render_plotly_chart_fn: Callable[..., Any],
    format_kpi_number_fn: Callable[..., str],
) -> None:
    st.subheader("Pokédex Dashboard")
    st.caption(
        "Atlas lists come from species-level rows plus the Pokemon catalog. "
        "Count progress still comes from Pokédex Entry Snapshots. "
        "Artwork: PokeAPI. Availability and Community Days: pogoapi.net."
    )

    pokedex_dashboard_rows = normalize_rows_fn(display_pokedex_df)
    snapshot_accounts = (
        sorted(pokedex_dashboard_rows["account"].dropna().astype(str).unique().tolist())
        if not pokedex_dashboard_rows.empty
        else []
    )
    pokedex_dashboard_accounts = [a for a in all_accounts if a in set(snapshot_accounts)]
    if not pokedex_dashboard_accounts:
        pokedex_dashboard_accounts = snapshot_accounts or list(all_accounts)
    if not pokedex_dashboard_accounts:
        st.warning("No accounts found for the Pokédex dashboard.")
        return

    selected_pokedex_accounts = st.multiselect(
        "Accounts",
        options=pokedex_dashboard_accounts,
        default=pokedex_dashboard_accounts,
        key="pokedex_dashboard_accounts",
    )

    snapshot_entry_types = (
        set(pokedex_dashboard_rows["entry_type"].dropna().astype(str).tolist())
        if not pokedex_dashboard_rows.empty
        else set()
    )
    entry_type_options = [entry_type for entry_type in entry_types if entry_type in snapshot_entry_types] or list(entry_types)
    default_entry_types = [entry_type for entry_type in ["pokemon", "shiny", "lucky", "hundo"] if entry_type in entry_type_options]
    if not default_entry_types:
        default_entry_types = entry_type_options[:4]
    selected_pokedex_entry_types = st.multiselect(
        "Entry types",
        options=entry_type_options,
        default=default_entry_types,
        format_func=lambda value: entry_type_labels.get(str(value), str(value)),
        key="pokedex_dashboard_entry_types",
    )

    if pokedex_dashboard_rows.empty:
        pokedex_start_date = date.today()
        pokedex_end_date = date.today()
        st.info("No Pokédex Entry Snapshots yet. Atlas still uses the catalog and species-level lists.")
    else:
        min_pokedex_date = pokedex_dashboard_rows["date"].min().date()
        max_pokedex_date = pokedex_dashboard_rows["date"].max().date()
        pokedex_start_date, pokedex_end_date = select_date_range_fn(
            label="Date range",
            min_date=min_pokedex_date,
            max_date=max_pokedex_date,
            key="pokedex_dashboard_date_range",
        )

    view_mode = st.radio(
        "View mode",
        options=["Atlas", "Progress", "Detail"],
        horizontal=True,
        key="pokedex_atlas_view_mode",
    )

    if not selected_pokedex_accounts:
        st.info("Select at least one account.")
        return
    if not selected_pokedex_entry_types:
        st.info("Select at least one entry type.")
        return

    account_color_map = build_account_color_map_fn(
        selected_pokedex_accounts,
        xp_df[xp_df["Spieler"].isin(selected_pokedex_accounts)].copy() if not xp_df.empty and "Spieler" in xp_df.columns else xp_df,
    )
    render_account_color_legend_fn(selected_pokedex_accounts, account_color_map)

    missing_counts = build_pokedex_missing_count_rows(
        display_pokedex_df,
        pokedex_entry_config_df,
        accounts=selected_pokedex_accounts,
        entry_types=selected_pokedex_entry_types,
        regions=["overall"],
        start_date=pokedex_start_date,
        end_date=pokedex_end_date,
        entry_type_labels=entry_type_labels,
        region_labels=region_labels,
    )
    latest_snapshot = pd.to_datetime(
        filter_rows_fn(
            display_pokedex_df,
            accounts=selected_pokedex_accounts,
            start_date=pokedex_start_date,
            end_date=pokedex_end_date,
        ).get("date") if not pokedex_dashboard_rows.empty else pd.Series(dtype="datetime64[ns]"),
        errors="coerce",
    ).max()

    metric_cols = st.columns(6)
    metric_cols[0].metric(
        "Latest Snapshot",
        latest_snapshot.strftime("%Y-%m-%d") if pd.notna(latest_snapshot) else "-",
    )
    metric_cols[1].metric("Accounts", f"{len(selected_pokedex_accounts):,}")
    overall_missing = missing_counts[missing_counts["region"] == "overall"].copy() if not missing_counts.empty else missing_counts
    if overall_missing.empty:
        metric_cols[2].metric("Latest value", "-")
        metric_cols[3].metric("Target max", "-")
        metric_cols[4].metric("Missing", "-")
        metric_cols[5].metric("Progress", "-")
    else:
        latest_value = pd.to_numeric(overall_missing["value"], errors="coerce").sum()
        max_value = pd.to_numeric(overall_missing["max_value"], errors="coerce").sum()
        missing_value = pd.to_numeric(overall_missing["missing_count"], errors="coerce").sum()
        progress = float(latest_value) / float(max_value) if float(max_value) > 0 else 0.0
        metric_cols[2].metric("Latest value", format_kpi_number_fn(latest_value))
        metric_cols[3].metric("Target max", format_kpi_number_fn(max_value))
        metric_cols[4].metric("Missing", format_kpi_number_fn(missing_value))
        metric_cols[5].metric("Progress", f"{progress:.0%}")

    st.caption("Missing counts use Pokédex Entry Snapshots minus configured max values. Exact names come from species-level rows.")
    st.divider()

    if view_mode == "Atlas":
        _render_atlas_view(
            pokemon_catalog_df=pokemon_catalog_df,
            species_df=species_df,
            availability_df=availability_df,
            selected_accounts=selected_pokedex_accounts,
            selected_entry_types=selected_pokedex_entry_types,
            entry_type_labels=entry_type_labels,
            regions=regions,
            region_labels=region_labels,
            as_of_date=pokedex_end_date,
        )
        return

    if view_mode == "Progress":
        _render_progress_view(
            display_pokedex_df=display_pokedex_df,
            missing_counts=missing_counts,
            selected_accounts=selected_pokedex_accounts,
            selected_entry_types=selected_pokedex_entry_types,
            start_date=pokedex_start_date,
            end_date=pokedex_end_date,
            entry_type_labels=entry_type_labels,
            region_labels=region_labels,
            regions=regions,
            account_color_map=account_color_map,
            latest_rows_fn=latest_rows_fn,
            trend_rows_fn=trend_rows_fn,
            region_breakdown_fn=region_breakdown_fn,
            filter_rows_fn=filter_rows_fn,
            render_plotly_chart_fn=render_plotly_chart_fn,
        )
        return

    _render_detail_view(
        display_pokedex_df=display_pokedex_df,
        missing_counts=missing_counts,
        selected_accounts=selected_pokedex_accounts,
        selected_entry_types=selected_pokedex_entry_types,
        start_date=pokedex_start_date,
        end_date=pokedex_end_date,
        latest_rows_fn=latest_rows_fn,
    )


def _render_atlas_view(
    *,
    pokemon_catalog_df: pd.DataFrame,
    species_df: pd.DataFrame,
    availability_df: pd.DataFrame,
    selected_accounts: Sequence[str],
    selected_entry_types: Sequence[str],
    entry_type_labels: dict[str, str],
    regions: Sequence[str],
    region_labels: dict[str, str],
    as_of_date: object,
) -> None:
    if pokemon_catalog_df.empty:
        st.warning("No Pokemon catalog found. Run `python tools/update_pokemon_catalog.py`.")
        return

    atlas_col_1, atlas_col_2, atlas_col_3, atlas_col_4 = st.columns([1.1, 1.1, 1.4, 1.4])
    atlas_account = atlas_col_1.selectbox(
        "Atlas account",
        options=list(selected_accounts),
        key="pokedex_dashboard_atlas_account",
    )
    atlas_entry_type = atlas_col_2.selectbox(
        "Atlas entry type",
        options=list(selected_entry_types),
        format_func=lambda value: entry_type_labels.get(str(value), str(value)),
        key="pokedex_dashboard_atlas_entry_type",
    )
    region_options = [region for region in regions if region != "overall"]
    catalog_regions = (
        set(pokemon_catalog_df["region"].dropna().astype(str).str.strip().str.lower().tolist())
        if "region" in pokemon_catalog_df.columns
        else set()
    )
    region_options = [region for region in region_options if not catalog_regions or region in catalog_regions] or region_options
    default_region = "kanto" if "kanto" in region_options else region_options[0]
    atlas_region = atlas_col_3.selectbox(
        "Region",
        options=region_options,
        index=region_options.index(default_region) if default_region in region_options else 0,
        format_func=lambda value: region_labels.get(str(value), str(value)),
        key="pokedex_dashboard_atlas_region",
    )
    status_filter = atlas_col_4.selectbox(
        "Status",
        options=["all", "missing", "registered", "unavailable", "restricted"],
        format_func=lambda value: {
            "all": "All",
            "missing": "Missing",
            "registered": "Registered",
            "unavailable": "Not in GO",
            "restricted": "Location restricted",
        }.get(str(value), str(value)),
        key="pokedex_dashboard_atlas_status",
    )
    search = st.text_input("Search name or dex number", key="pokedex_dashboard_atlas_search")

    cards = build_pokedex_atlas_cards(
        pokemon_catalog_df,
        species_df,
        account=atlas_account,
        entry_type=atlas_entry_type,
        region=atlas_region,
        availability_df=availability_df,
        search=search,
        status_filter=status_filter,
        as_of_date=as_of_date,
    )
    counts = cards["status"].value_counts() if not cards.empty and "status" in cards.columns else pd.Series(dtype=int)
    summary_cols = st.columns(4)
    summary_cols[0].metric("Shown", f"{len(cards):,}")
    summary_cols[1].metric("Missing", f"{int(counts.get('missing', 0)):,}")
    summary_cols[2].metric("Registered", f"{int(counts.get('registered', 0)):,}")
    summary_cols[3].metric("Not in GO", f"{int(counts.get('unavailable', 0)):,}")

    st.markdown(pokedex_atlas_html(cards), unsafe_allow_html=True)

    with st.expander("Mark registered for this region", expanded=False):
        if cards.empty:
            st.info("Nothing to edit for the current Atlas filters.")
            return
        editor_source = cards[["dex_number", "name", "german_name", "status", "registered", "location_restriction", "last_event"]].copy()
        editor_source = editor_source.rename(
            columns={
                "dex_number": "Dex",
                "name": "Name",
                "german_name": "German",
                "status": "Status",
                "registered": "Registered",
                "location_restriction": "Location",
                "last_event": "Last event",
            }
        )
        edited = st.data_editor(
            editor_source,
            use_container_width=True,
            hide_index=True,
            disabled=["Dex", "Name", "German", "Status", "Location", "Last event"],
            column_config={"Registered": st.column_config.CheckboxColumn(default=False)},
            key="pokedex_dashboard_atlas_editor",
        )
        if st.button("Save species progress", type="primary", key="pokedex_dashboard_atlas_save"):
            save_date = pd.to_datetime(as_of_date, errors="coerce")
            if pd.isna(save_date):
                save_date = pd.Timestamp.today()
            rows = []
            for _, row in edited.iterrows():
                rows.append(
                    {
                        "date": pd.Timestamp(save_date).date().isoformat(),
                        "account": atlas_account,
                        "entry_type": atlas_entry_type,
                        "dex_number": int(row["Dex"]),
                        "registered": bool(row["Registered"]),
                        "can_evolve_now": False,
                        "notes": "",
                    }
                )
            written = upsert_pokedex_species_rows(pokedex_species_entries_path(), rows)
            st.success(f"Saved {written} species rows for {atlas_account}.")
            st.rerun()


def _render_progress_view(
    *,
    display_pokedex_df: pd.DataFrame,
    missing_counts: pd.DataFrame,
    selected_accounts: Sequence[str],
    selected_entry_types: Sequence[str],
    start_date: date,
    end_date: date,
    entry_type_labels: dict[str, str],
    region_labels: dict[str, str],
    regions: Sequence[str],
    account_color_map: dict[str, str],
    latest_rows_fn: Callable[..., pd.DataFrame],
    trend_rows_fn: Callable[..., pd.DataFrame],
    region_breakdown_fn: Callable[..., pd.DataFrame],
    filter_rows_fn: Callable[..., pd.DataFrame],
    render_plotly_chart_fn: Callable[..., Any],
) -> None:
    if display_pokedex_df.empty:
        st.info("Progress charts need saved Pokédex Entry Snapshots.")
        return

    latest_overall = latest_rows_fn(
        display_pokedex_df,
        accounts=selected_accounts,
        entry_types=selected_entry_types,
        regions=["overall"],
        start_date=start_date,
        end_date=end_date,
    )
    if latest_overall.empty:
        st.info("Latest comparison: no Overall rows for the selected filters.")
    else:
        fig_latest = px.bar(
            latest_overall,
            x="account",
            y="value",
            color="entry_type_label",
            barmode="group",
            category_orders={
                "entry_type_label": [entry_type_labels.get(entry_type, entry_type) for entry_type in selected_entry_types],
                "account": list(selected_accounts),
            },
            labels={"account": "Account", "value": "Value", "entry_type_label": "Entry Type"},
            title="Latest Overall Values by Account",
        )
        fig_latest.update_yaxes(tickformat=",.0f")
        fig_latest.update_layout(height=460)
        render_plotly_chart_fn(fig_latest, use_container_width=True, sort_legend=False)

    if not missing_counts.empty:
        fig_missing = px.bar(
            missing_counts,
            x="account",
            y="missing_count",
            color="entry_type_label",
            barmode="group",
            category_orders={
                "entry_type_label": [entry_type_labels.get(entry_type, entry_type) for entry_type in selected_entry_types],
                "account": list(selected_accounts),
            },
            labels={"account": "Account", "missing_count": "Missing", "entry_type_label": "Entry Type"},
            title="Missing Counts vs Configured Max",
        )
        fig_missing.update_yaxes(tickformat=",.0f")
        fig_missing.update_layout(height=420)
        render_plotly_chart_fn(fig_missing, use_container_width=True, sort_legend=False)

        progress_df = missing_counts.copy()
        progress_df["progress_pct_display"] = pd.to_numeric(progress_df["progress_pct"], errors="coerce") * 100
        fig_progress = px.bar(
            progress_df,
            x="account",
            y="progress_pct_display",
            color="entry_type_label",
            barmode="group",
            category_orders={
                "entry_type_label": [entry_type_labels.get(entry_type, entry_type) for entry_type in selected_entry_types],
                "account": list(selected_accounts),
            },
            labels={"account": "Account", "progress_pct_display": "Progress %", "entry_type_label": "Entry Type"},
            title="Progress Percent by Account",
        )
        fig_progress.update_yaxes(ticksuffix="%", rangemode="tozero")
        fig_progress.update_layout(height=420)
        render_plotly_chart_fn(fig_progress, use_container_width=True, sort_legend=False)

    trend_df = trend_rows_fn(
        display_pokedex_df,
        accounts=selected_accounts,
        entry_types=selected_entry_types,
        start_date=start_date,
        end_date=end_date,
    )
    if trend_df.empty:
        st.info("Progress over time: no Overall rows for the selected filters.")
    else:
        fig_trend = px.line(
            trend_df,
            x="date",
            y="value",
            color="account",
            line_dash="entry_type_label",
            color_discrete_map=account_color_map,
            markers=True,
            labels={"date": "Date", "value": "Value", "account": "Account", "entry_type_label": "Entry Type"},
            title="Overall Progress Over Time",
        )
        fig_trend.update_yaxes(tickformat=",.0f")
        fig_trend.update_layout(height=520)
        render_plotly_chart_fn(fig_trend, use_container_width=True)

    breakdown_col_1, breakdown_col_2, breakdown_col_3 = st.columns([1.1, 1.1, 1.0])
    breakdown_account = breakdown_col_1.selectbox(
        "Breakdown account",
        options=list(selected_accounts),
        key="pokedex_dashboard_breakdown_account",
    )
    breakdown_entry_type = breakdown_col_2.selectbox(
        "Breakdown entry type",
        options=list(selected_entry_types),
        format_func=lambda value: entry_type_labels.get(str(value), str(value)),
        key="pokedex_dashboard_breakdown_entry_type",
    )
    breakdown_rows_for_date = filter_rows_fn(
        display_pokedex_df,
        accounts=[breakdown_account],
        entry_types=[breakdown_entry_type],
        start_date=start_date,
        end_date=end_date,
    )
    if breakdown_rows_for_date.empty:
        st.info("Region breakdown: no rows for the selected account and entry type.")
        return
    latest_breakdown_date = breakdown_rows_for_date["date"].max().date()
    breakdown_date = breakdown_col_3.date_input(
        "As-of date",
        value=latest_breakdown_date,
        min_value=start_date,
        max_value=end_date,
        key="pokedex_dashboard_breakdown_date",
    )
    region_df = region_breakdown_fn(
        display_pokedex_df,
        account=breakdown_account,
        entry_type=breakdown_entry_type,
        as_of_date=breakdown_date,
    )
    if region_df.empty:
        st.info("Region breakdown: no regional rows at or before the selected date.")
        return
    fig_region = px.bar(
        region_df,
        x="region_label",
        y="value",
        color="region_label",
        category_orders={"region_label": [region_labels.get(region, region) for region in regions]},
        labels={"region_label": "Region", "value": "Value"},
        title=(
            f"{entry_type_labels.get(str(breakdown_entry_type), str(breakdown_entry_type))} "
            f"Region Breakdown for {breakdown_account}"
        ),
    )
    fig_region.update_yaxes(tickformat=",.0f")
    fig_region.update_layout(height=460, showlegend=False)
    render_plotly_chart_fn(fig_region, use_container_width=True, sort_legend=False)
    st.caption(f"Values are latest saved Pokédex Entry Counts at or before {breakdown_date.isoformat()}.")


def _render_detail_view(
    *,
    display_pokedex_df: pd.DataFrame,
    missing_counts: pd.DataFrame,
    selected_accounts: Sequence[str],
    selected_entry_types: Sequence[str],
    start_date: date,
    end_date: date,
    latest_rows_fn: Callable[..., pd.DataFrame],
) -> None:
    st.markdown("Latest snapshot detail")
    detail_df = latest_rows_fn(
        display_pokedex_df,
        accounts=selected_accounts,
        entry_types=selected_entry_types,
        start_date=start_date,
        end_date=end_date,
    )
    if detail_df.empty:
        st.info("No snapshot detail rows for the selected filters.")
    else:
        detail_view = detail_df.rename(
            columns={
                "date": "Date",
                "account": "Account",
                "entry_type_label": "Entry Type",
                "region_label": "Region",
                "value": "Value",
            }
        )[["Date", "Account", "Entry Type", "Region", "Value"]].copy()
        detail_view["Date"] = pd.to_datetime(detail_view["Date"], errors="coerce").dt.date.astype(str)
        st.dataframe(
            detail_view,
            use_container_width=True,
            hide_index=True,
            column_config={"Value": st.column_config.NumberColumn(format="%d")},
        )

    st.markdown("Missing counts vs configured max")
    if missing_counts.empty:
        st.info("No missing-count rows for the selected filters.")
        return
    missing_view = missing_counts.rename(
        columns={
            "date": "Date",
            "account": "Account",
            "entry_type_label": "Entry Type",
            "region_label": "Region",
            "value": "Latest",
            "max_value": "Max",
            "missing_count": "Missing",
            "progress_pct": "Progress",
        }
    )[["Date", "Account", "Entry Type", "Region", "Latest", "Max", "Missing", "Progress"]].copy()
    missing_view["Date"] = pd.to_datetime(missing_view["Date"], errors="coerce").dt.date.astype(str)
    missing_view["Progress"] = pd.to_numeric(missing_view["Progress"], errors="coerce").map(
        lambda value: "-" if pd.isna(value) else f"{float(value):.0%}"
    )
    st.dataframe(missing_view, use_container_width=True, hide_index=True)
