from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from shared.paths import manual_pokemon_availability_path, pokedex_species_entries_path
from webapp.data_files import (
    load_manual_pokemon_availability,
    load_manual_pokemon_availability_frame,
    save_manual_pokemon_availability,
)
from webapp.pokedex import (
    ATLAS_ENTRY_KINDS,
    build_atlas_snapshot_comparison,
    build_pokedex_atlas_cards,
    build_pokedex_missing_count_rows,
    build_species_missing_summary,
    filter_atlas_cards_by_release,
    pokedex_atlas_html,
    upsert_pokedex_species_rows,
)
from webapp.pokedex_sync import pokedex_sync_status_line, publish_local_species_save, run_configured_sync


def _show_pokedex_sync_result(result: dict[str, Any], *, saved_locally: bool = False) -> None:
    message = pokedex_sync_status_line(result)
    if saved_locally and (bool(result.get("skipped")) or not result.get("ok")):
        message = f"Saved locally. {message}"
    if result.get("ok"):
        st.success(message)
        return
    st.warning(message)


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
    if st.button("Sync", key="pokedex_dashboard_sync"):
        _show_pokedex_sync_result(run_configured_sync())
        st.rerun()

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
    default_entry_types = [entry_type for entry_type in ["pokemon", "shiny", "hundo", "lucky"] if entry_type in entry_type_options]
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
    # Snapshots lag behind species marks from the phone, so a range that ends at
    # the newest snapshot shows (and saves) the Atlas as of today.
    atlas_as_of_date = pokedex_end_date
    if pokedex_dashboard_rows.empty or pokedex_end_date >= max_pokedex_date:
        atlas_as_of_date = max(pokedex_end_date, date.today())

    view_mode = st.radio(
        "View mode",
        options=["Atlas", "Progress", "Detail"],
        horizontal=True,
        key="pokedex_atlas_view_mode",
    )

    if not selected_pokedex_accounts:
        st.info("Select at least one account.")
        return

    account_color_map = build_account_color_map_fn(
        selected_pokedex_accounts,
        xp_df[xp_df["Spieler"].isin(selected_pokedex_accounts)].copy() if not xp_df.empty and "Spieler" in xp_df.columns else xp_df,
    )
    render_account_color_legend_fn(selected_pokedex_accounts, account_color_map)

    species_missing = build_species_missing_summary(
        pokemon_catalog_df,
        species_df,
        accounts=selected_pokedex_accounts,
        availability_df=availability_df,
        as_of_date=atlas_as_of_date,
    )
    species_missing_table = _species_missing_table(selected_pokedex_accounts, species_missing)
    st.dataframe(
        species_missing_table,
        use_container_width=True,
        hide_index=True,
        column_config={
            label: st.column_config.NumberColumn(format="%d")
            for _kind_id, label in ATLAS_ENTRY_KINDS
        },
    )
    st.caption("Missing counts are unchecked species for that account and kind.")
    st.divider()

    if view_mode == "Atlas":
        _render_atlas_view(
            pokemon_catalog_df=pokemon_catalog_df,
            species_df=species_df,
            availability_df=availability_df,
            snapshots_df=display_pokedex_df,
            config_df=pokedex_entry_config_df,
            selected_accounts=selected_pokedex_accounts,
            selected_entry_types=selected_pokedex_entry_types,
            entry_type_labels=entry_type_labels,
            regions=regions,
            region_labels=region_labels,
            as_of_date=atlas_as_of_date,
        )
        return

    if not selected_pokedex_entry_types:
        st.info("Select at least one entry type.")
        return

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


def _registered_is_blank(value: object) -> bool:
    if value is None or value is pd.NA:
        return True
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return isinstance(missing, bool) and missing


def _missing_counts_by_kind(summary: pd.DataFrame) -> dict[tuple[str, str], int]:
    lookup: dict[tuple[str, str], int] = {}
    if summary is None or summary.empty:
        return lookup
    required = {"account", "entry_type", "missing_count"}
    if not required.issubset(summary.columns):
        return lookup
    cleaned = summary.loc[:, ["account", "entry_type", "missing_count"]].copy()
    cleaned["account"] = cleaned["account"].astype(str).str.strip()
    cleaned["entry_type"] = cleaned["entry_type"].astype(str).str.strip().str.lower()
    cleaned["missing_count"] = pd.to_numeric(cleaned["missing_count"], errors="coerce")
    cleaned = cleaned.dropna(subset=["missing_count"])
    cleaned = cleaned.drop_duplicates(subset=["account", "entry_type"], keep="last")
    for _, row in cleaned.iterrows():
        lookup[(str(row["account"]), str(row["entry_type"]))] = int(row["missing_count"])
    return lookup


def _species_missing_table(accounts: Sequence[str], summary: pd.DataFrame) -> pd.DataFrame:
    lookup = _missing_counts_by_kind(summary)
    kind_labels = [label for _kind_id, label in ATLAS_ENTRY_KINDS]
    records: list[dict[str, object]] = []
    for account in accounts:
        account_name = str(account)
        record: dict[str, object] = {"Account": account_name}
        for kind_id, label in ATLAS_ENTRY_KINDS:
            record[label] = lookup.get((account_name.strip(), kind_id), 0)
        records.append(record)
    return pd.DataFrame(records, columns=["Account", *kind_labels])


def _checkbox_series(cards: pd.DataFrame, kind_id: str) -> pd.Series:
    column = f"registered_{kind_id}"
    if column not in cards.columns:
        return pd.Series(pd.NA, index=cards.index, dtype="boolean")
    values: list[object] = []
    for value in cards[column].tolist():
        values.append(pd.NA if _registered_is_blank(value) else bool(value))
    return pd.Series(values, index=cards.index, dtype="boolean")


def _text_series(cards: pd.DataFrame, column: str) -> pd.Series:
    if column not in cards.columns:
        return pd.Series([""] * len(cards), index=cards.index, dtype="object")
    return cards[column].fillna("").astype(str)


def _atlas_editor_frame(cards: pd.DataFrame) -> pd.DataFrame:
    frame = pd.DataFrame(index=cards.index)
    frame["Dex"] = pd.to_numeric(cards["dex_number"], errors="coerce").astype("Int64")
    frame["Name"] = _text_series(cards, "name")
    frame["German"] = _text_series(cards, "german_name")
    for kind_id, label in ATLAS_ENTRY_KINDS:
        frame[label] = _checkbox_series(cards, kind_id)
    frame["Location"] = _text_series(cards, "location_restriction")
    frame["Last event"] = _text_series(cards, "last_event")
    return frame


def _available_kinds_by_dex(cards: pd.DataFrame) -> dict[int, set[str]]:
    available: dict[int, set[str]] = {}
    for _, card in cards.iterrows():
        dex_number = pd.to_numeric(card.get("dex_number"), errors="coerce")
        if pd.isna(dex_number):
            continue
        kinds: set[str] = set()
        for kind_id, _label in ATLAS_ENTRY_KINDS:
            column = f"registered_{kind_id}"
            raw = card[column] if column in card.index else pd.NA
            if not _registered_is_blank(raw):
                kinds.add(kind_id)
        available[int(dex_number)] = kinds
    return available


def _species_row(
    *,
    save_date: date,
    account: object,
    entry_type: str,
    dex_number: int,
    form: str,
    registered: bool,
) -> dict[str, object]:
    return {
        "date": save_date.isoformat(),
        "account": str(account),
        "entry_type": entry_type,
        "dex_number": dex_number,
        "form": form,
        "registered": registered,
        "can_evolve_now": False,
        "notes": "",
    }


def _json_forms(raw: object) -> list[str]:
    try:
        loaded = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    return [str(item).strip() for item in loaded]


def _mega_editor_frame(cards: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for _, card in cards.iterrows():
        if _registered_is_blank(card.get("registered_mega")):
            continue
        dex_number = pd.to_numeric(card.get("dex_number"), errors="coerce")
        if pd.isna(dex_number):
            continue
        registered_forms = {form.casefold() for form in _json_forms(card.get("registered_mega_forms"))}
        for form in _json_forms(card.get("mega_forms")):
            records.append(
                {
                    "Dex": int(dex_number),
                    "Name": str(card.get("name") or ""),
                    "Form": form,
                    "Registered": form.casefold() in registered_forms,
                }
            )
    if not records:
        return pd.DataFrame(columns=["Dex", "Name", "Form", "Registered"])
    return pd.DataFrame(records)


def _gmax_editor_frame(cards: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for _, card in cards.iterrows():
        if _registered_is_blank(card.get("registered_gmax")):
            continue
        dex_number = pd.to_numeric(card.get("dex_number"), errors="coerce")
        if pd.isna(dex_number):
            continue
        records.append(
            {
                "Dex": int(dex_number),
                "Name": str(card.get("name") or ""),
                "Registered": bool(card.get("registered_gmax")),
            }
        )
    if not records:
        return pd.DataFrame(columns=["Dex", "Name", "Registered"])
    return pd.DataFrame(records)


def _release_notes_by_dex(frame: pd.DataFrame) -> dict[int, str]:
    notes: dict[int, str] = {}
    if frame.empty or "dex_number" not in frame.columns:
        return notes
    note_column = frame["notes"] if "notes" in frame.columns else pd.Series("", index=frame.index)
    for dex_raw, note in zip(frame["dex_number"].tolist(), note_column.tolist()):
        dex_number = pd.to_numeric(dex_raw, errors="coerce")
        if pd.isna(dex_number):
            continue
        text = "" if pd.isna(note) else str(note).strip()
        notes[int(dex_number)] = text
    return notes


def _release_editor_label(value: object) -> str:
    flag = str(value or "").strip().casefold()
    if flag == "yes":
        return "In GO"
    if flag == "no":
        return "Not in GO"
    return "Catalog"


def _release_editor_frame(cards: pd.DataFrame, notes_by_dex: dict[int, str]) -> pd.DataFrame:
    columns = ["Dex", "Name", "Release", "Notes"]
    records: list[dict[str, object]] = []
    for _, card in cards.iterrows():
        dex_number = pd.to_numeric(card.get("dex_number"), errors="coerce")
        if pd.isna(dex_number):
            continue
        dex = int(dex_number)
        records.append(
            {
                "Dex": dex,
                "Name": str(card.get("name") or ""),
                "Release": _release_editor_label(card.get("release_override", "")),
                "Notes": str(notes_by_dex.get(dex, "") or ""),
            }
        )
    if not records:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(records, columns=columns)


def _species_rows_from_editor(
    cards: pd.DataFrame,
    edited: pd.DataFrame,
    *,
    account: object,
    save_date: date,
    entry_mode: str = "standard",
) -> list[dict[str, object]]:
    mode = str(entry_mode or "standard").strip().lower()
    if mode == "mega":
        rows: list[dict[str, object]] = []
        for _, row in edited.iterrows():
            dex_number = pd.to_numeric(row.get("Dex"), errors="coerce")
            if pd.isna(dex_number):
                continue
            edited_value = row["Registered"] if "Registered" in row.index else False
            rows.append(
                _species_row(
                    save_date=save_date,
                    account=account,
                    entry_type="mega",
                    dex_number=int(dex_number),
                    form=str(row.get("Form") or "").strip(),
                    registered=False if _registered_is_blank(edited_value) else bool(edited_value),
                )
            )
        return rows
    if mode == "gmax":
        rows = []
        for _, row in edited.iterrows():
            dex_number = pd.to_numeric(row.get("Dex"), errors="coerce")
            if pd.isna(dex_number):
                continue
            edited_value = row["Registered"] if "Registered" in row.index else False
            rows.append(
                _species_row(
                    save_date=save_date,
                    account=account,
                    entry_type="gmax",
                    dex_number=int(dex_number),
                    form="",
                    registered=False if _registered_is_blank(edited_value) else bool(edited_value),
                )
            )
        return rows
    available_by_dex = _available_kinds_by_dex(cards)
    rows = []
    for _, row in edited.iterrows():
        dex_number = pd.to_numeric(row.get("Dex"), errors="coerce")
        if pd.isna(dex_number):
            continue
        dex = int(dex_number)
        available = available_by_dex.get(dex, set())
        for kind_id, label in ATLAS_ENTRY_KINDS:
            if kind_id not in available:
                continue
            edited_value = row[label] if label in row.index else False
            rows.append(
                _species_row(
                    save_date=save_date,
                    account=account,
                    entry_type=kind_id,
                    dex_number=dex,
                    form="",
                    registered=False if _registered_is_blank(edited_value) else bool(edited_value),
                )
            )
    return rows


def _release_available_value(value: object) -> str:
    label = str(value or "").strip().casefold()
    if label == "in go":
        return "yes"
    if label == "not in go":
        return "no"
    return "catalog"


def _release_edits_from_editor(edited: pd.DataFrame) -> list[dict[str, object]]:
    edits: list[dict[str, object]] = []
    for _, row in edited.iterrows():
        dex_number = pd.to_numeric(row.get("Dex"), errors="coerce")
        if pd.isna(dex_number):
            continue
        raw_notes = row["Notes"] if "Notes" in row.index else ""
        notes = "" if pd.isna(raw_notes) else str(raw_notes).strip()
        edits.append(
            {
                "dex_number": int(dex_number),
                "available": _release_available_value(row.get("Release")),
                "notes": notes,
            }
        )
    return edits


def _atlas_kind_labels() -> dict[str, str]:
    return {
        "any": "Any",
        **{kind_id: label for kind_id, label in ATLAS_ENTRY_KINDS},
        "mega": "Mega",
        "gmax": "G-Max",
    }


def _comparison_table(comparison: pd.DataFrame) -> pd.DataFrame:
    if comparison.empty:
        return pd.DataFrame(columns=["Kind", "Snapshot", "Atlas", "Max", "Gap"])
    view = comparison.loc[:, ["entry_type_label", "snapshot_value", "atlas_count", "max_value", "gap"]].copy()
    return view.rename(
        columns={
            "entry_type_label": "Kind",
            "snapshot_value": "Snapshot",
            "atlas_count": "Atlas",
            "max_value": "Max",
            "gap": "Gap",
        }
    )


def _render_atlas_view(
    *,
    pokemon_catalog_df: pd.DataFrame,
    species_df: pd.DataFrame,
    availability_df: pd.DataFrame,
    snapshots_df: pd.DataFrame,
    config_df: pd.DataFrame,
    selected_accounts: Sequence[str],
    selected_entry_types: Sequence[str],
    entry_type_labels: dict[str, str],
    regions: Sequence[str],
    region_labels: dict[str, str],
    as_of_date: object,
) -> None:
    # Page-level entry types filter Progress and Detail only.
    del selected_entry_types

    if pokemon_catalog_df.empty:
        st.warning("No Pokemon catalog found. Run `python tools/update_pokemon_catalog.py`.")
        return

    region_options = [region for region in regions if region != "overall"]
    catalog_regions = (
        set(pokemon_catalog_df["region"].dropna().astype(str).str.strip().str.lower().tolist())
        if "region" in pokemon_catalog_df.columns
        else set()
    )
    region_options = [region for region in region_options if not catalog_regions or region in catalog_regions] or region_options
    default_region = "kanto" if "kanto" in region_options else (region_options[0] if region_options else "overall")
    region_options = ["overall", *region_options]

    def atlas_region_label(value: object) -> str:
        text = str(value)
        if text == "overall":
            return "All regions"
        return region_labels.get(text, text)

    kind_labels = _atlas_kind_labels()
    kind_options = ["any", *[kind_id for kind_id, _label in ATLAS_ENTRY_KINDS], "mega", "gmax"]
    state_labels = {
        "any": "Any",
        "missing": "Missing",
        "registered": "Registered",
        "unavailable": "Not available",
        "restricted": "Location restricted",
    }
    release_labels = {
        "any": "Any",
        "in_go": "In GO",
        "not_in_go": "Not in GO",
        "override": "Manual override",
    }
    atlas_col_account, atlas_col_region = st.columns([1.1, 1.4])
    atlas_account = atlas_col_account.selectbox(
        "Atlas account",
        options=list(selected_accounts),
        key="pokedex_dashboard_atlas_account",
    )
    atlas_region = atlas_col_region.selectbox(
        "Region",
        options=region_options,
        index=region_options.index(default_region) if default_region in region_options else 0,
        format_func=atlas_region_label,
        key="pokedex_dashboard_atlas_region",
    )
    filter_col_kind, filter_col_state, filter_col_release = st.columns([1.2, 1.3, 1.4])
    kind_filter = filter_col_kind.selectbox(
        "Kind",
        options=kind_options,
        format_func=lambda value: kind_labels.get(str(value), str(value)),
        key="pokedex_dashboard_atlas_kind",
    )
    state_filter = filter_col_state.selectbox(
        "State",
        options=list(state_labels),
        format_func=lambda value: state_labels.get(str(value), str(value)),
        key="pokedex_dashboard_atlas_state",
    )
    release_filter = filter_col_release.selectbox(
        "Release",
        options=list(release_labels),
        format_func=lambda value: release_labels.get(str(value), str(value)),
        key="pokedex_dashboard_atlas_release",
    )
    search = st.text_input("Search name, dex number, or form", key="pokedex_dashboard_atlas_search")

    comparison = build_atlas_snapshot_comparison(
        pokemon_catalog_df,
        species_df,
        snapshots_df,
        config_df,
        account=atlas_account,
        region=atlas_region,
        availability_df=availability_df,
        as_of_date=as_of_date,
        entry_type_labels=entry_type_labels,
    )
    st.dataframe(
        _comparison_table(comparison),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Snapshot": st.column_config.NumberColumn(format="%d"),
            "Atlas": st.column_config.NumberColumn(format="%d"),
            "Max": st.column_config.NumberColumn(format="%d"),
            "Gap": st.column_config.NumberColumn(format="%+d"),
        },
    )
    st.caption(
        "Gap is the saved Pokédex count minus checked Atlas entries. "
        "A positive gap means the saved count is ahead of the checklist. "
        "A negative gap means the checklist is ahead of the saved count."
    )

    override_path = manual_pokemon_availability_path()
    release_overrides = load_manual_pokemon_availability(override_path)
    release_notes = _release_notes_by_dex(load_manual_pokemon_availability_frame(override_path))
    if release_filter == "override":
        cards = build_pokedex_atlas_cards(
            pokemon_catalog_df,
            species_df,
            account=atlas_account,
            region="overall",
            availability_df=availability_df,
            search=search,
            kind_filter="any",
            state_filter="any",
            as_of_date=as_of_date,
            release_overrides=release_overrides,
        )
        cards = filter_atlas_cards_by_release(cards, "manual override")
    else:
        cards = build_pokedex_atlas_cards(
            pokemon_catalog_df,
            species_df,
            account=atlas_account,
            region=atlas_region,
            availability_df=availability_df,
            search=search,
            kind_filter=kind_filter,
            state_filter=state_filter,
            as_of_date=as_of_date,
            release_overrides=release_overrides,
        )
        cards = filter_atlas_cards_by_release(cards, release_filter)
    if release_filter == "override":
        st.caption("Manual override lists every saved release exception, in all regions.")
    st.caption(f"Showing {len(cards):,}")
    st.markdown(pokedex_atlas_html(cards), unsafe_allow_html=True)

    region_name = atlas_region_label(atlas_region)
    if release_filter == "override":
        expander_title = f"Edit {atlas_account} · manual overrides, all regions"
    else:
        expander_title = f"Mark registered for {atlas_account} in {region_name}"
    with st.expander(expander_title, expanded=False):
        entry_mode = st.selectbox(
            "Entry",
            options=["standard", "mega", "gmax", "release"],
            format_func=lambda value: {
                "standard": "Standard",
                "mega": "Mega",
                "gmax": "G-Max",
                "release": "Release",
            }.get(str(value), str(value)),
            key="pokedex_dashboard_atlas_entry_mode",
        )
        if entry_mode == "release":
            editor_source = _release_editor_frame(cards, release_notes)
            disabled = ["Dex", "Name"]
            column_config = {
                "Release": st.column_config.SelectboxColumn(
                    options=["Catalog", "In GO", "Not in GO"],
                    required=True,
                ),
                "Notes": st.column_config.TextColumn(),
            }
        elif entry_mode == "mega":
            editor_source = _mega_editor_frame(cards)
            disabled = ["Dex", "Name", "Form"]
            column_config = {"Registered": st.column_config.CheckboxColumn(width="small")}
        elif entry_mode == "gmax":
            editor_source = _gmax_editor_frame(cards)
            disabled = ["Dex", "Name"]
            column_config = {"Registered": st.column_config.CheckboxColumn(width="small")}
        else:
            editor_source = _atlas_editor_frame(cards)
            disabled = ["Dex", "Name", "German", "Location", "Last event"]
            column_config = {
                label: st.column_config.CheckboxColumn(width="small")
                for _kind_id, label in ATLAS_ENTRY_KINDS
            }
        if editor_source.empty:
            st.info("Nothing to edit for the current Atlas filters.")
            return
        edited = st.data_editor(
            editor_source,
            use_container_width=True,
            hide_index=True,
            disabled=disabled,
            column_config=column_config,
            key=f"pokedex_dashboard_atlas_editor_{atlas_account}_{atlas_region}_{release_filter}_{entry_mode}",
        )
        if entry_mode == "release":
            if st.button("Save release overrides", type="primary", key="pokedex_dashboard_atlas_save_release"):
                edits = _release_edits_from_editor(edited)
                written = save_manual_pokemon_availability(override_path, edits)
                st.success(f"Release override list now has {written} species.")
                st.rerun()
        elif st.button("Save species progress", type="primary", key="pokedex_dashboard_atlas_save"):
            save_date = pd.to_datetime(as_of_date, errors="coerce")
            if pd.isna(save_date):
                save_date = pd.Timestamp.today()
            rows = _species_rows_from_editor(
                cards,
                edited,
                account=atlas_account,
                save_date=pd.Timestamp(save_date).date(),
                entry_mode=str(entry_mode),
            )
            written = upsert_pokedex_species_rows(pokedex_species_entries_path(), rows)
            st.success(f"Saved {written} species rows for {atlas_account}.")
            _show_pokedex_sync_result(publish_local_species_save(), saved_locally=True)
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
