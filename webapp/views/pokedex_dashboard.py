from __future__ import annotations

import inspect
import json
from collections.abc import Callable, Sequence
from datetime import date
from html import escape
from typing import Any, NamedTuple

import pandas as pd
import plotly.express as px
import streamlit as st

from shared.paths import (
    manual_category_availability_path,
    manual_pokemon_availability_path,
    pokedex_species_entries_path,
    pokemon_evolutions_path,
)
from webapp.category_release import (
    blank_kind_release_edit,
    load_manual_category_availability,
    mega_release_edits,
    save_manual_category_availability,
)
from webapp.data_files import (
    load_manual_pokemon_availability,
    load_manual_pokemon_availability_frame,
    load_pokemon_evolutions,
    save_manual_pokemon_availability,
)
from webapp.atlas_card_events import atlas_card_event, atlas_card_event_dex
from webapp.pokedex import (
    ATLAS_COMPARISON_KINDS,
    ATLAS_ENTRY_KINDS,
    build_pokedex_atlas_cards,
    build_species_missing_summary,
    build_species_progress_rows,
    build_species_region_counts,
    filter_atlas_cards_by_release,
    is_available_in_pogo,
    mega_badge_label,
    pokedex_atlas_html,
    species_rows_delta_from_atlas_editor,
    species_rows_from_card_registration,
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


SPECIES_COUNT_REGIONS: tuple[str, ...] = (
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
)


def _ordered_names(values: Sequence[object]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = str(value).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        ordered.append(name)
    return ordered


def _entry_type_label(kind: object, entry_type_labels: dict[str, str]) -> str:
    key = str(kind).strip().lower()
    if key in entry_type_labels:
        return str(entry_type_labels[key])
    for kind_id, label in ATLAS_COMPARISON_KINDS:
        if kind_id == key:
            return label
    return str(kind)


def _progress_entry_type_options(entry_types: Sequence[str]) -> list[str]:
    comparison_ids = [kind for kind, _label in ATLAS_COMPARISON_KINDS]
    passed = [str(item).strip().lower() for item in entry_types if str(item).strip()]
    if set(comparison_ids).issubset(passed):
        return [kind for kind in passed if kind in set(comparison_ids)]
    return comparison_ids


def _species_date_bounds(species_df: pd.DataFrame) -> tuple[date, date] | None:
    if species_df is None or species_df.empty or "date" not in species_df.columns:
        return None
    parsed = pd.to_datetime(species_df["date"], errors="coerce").dropna()
    if parsed.empty:
        return None
    return parsed.min().date(), parsed.max().date()


_FINISHED_KIND_STYLE = "background-color: #166534; color: #ecfdf5; font-weight: 700"


def _count_fraction(registered: object, target: object) -> str:
    registered_num = pd.to_numeric(registered, errors="coerce")
    target_num = pd.to_numeric(target, errors="coerce")
    registered_value = 0 if pd.isna(registered_num) else int(registered_num)
    target_value = 0 if pd.isna(target_num) else int(target_num)
    return f"{registered_value}/{target_value}"


def _fraction_is_complete(value: object) -> bool:
    text = str(value or "").strip()
    registered_text, separator, target_text = text.partition("/")
    if not separator:
        return False
    try:
        registered = int(registered_text)
        target = int(target_text)
    except ValueError:
        return False
    return target > 0 and registered >= target


def _species_region_count_html(counts: pd.DataFrame, region_labels: dict[str, str]) -> str:
    lookup: dict[tuple[str, str], str] = {}
    present: set[str] = set()
    if counts is not None and not counts.empty and {"entry_type", "region"}.issubset(counts.columns):
        for _, row in counts.iterrows():
            kind = str(row.get("entry_type", "")).strip().lower()
            region = str(row.get("region", "")).strip().lower()
            lookup[(kind, region)] = _count_fraction(row.get("registered_count"), row.get("target_count"))
            if region in SPECIES_COUNT_REGIONS:
                present.add(region)
    region_columns = [region for region in SPECIES_COUNT_REGIONS if region in present]
    headers = ["Kind", *[region_labels.get(region, region.title()) for region in region_columns], "All"]
    records: list[dict[str, str]] = []
    for kind, label in ATLAS_COMPARISON_KINDS:
        record = {"Kind": label}
        for region, header in zip(region_columns, headers[1:-1]):
            record[header] = lookup.get((kind, region), "0/0")
        record["All"] = lookup.get((kind, "overall"), "0/0")
        records.append(record)

    head = "".join(
        f'<th style="text-align:{"left" if header == "Kind" else "right"};padding:0.35rem 0.55rem;color:#94a3b8;font-weight:600">{escape(header)}</th>'
        for header in headers
    )
    body_rows: list[str] = []
    for record in records:
        kind_done = _fraction_is_complete(record.get("All"))
        cells: list[str] = []
        for header in headers:
            value = record.get(header, "")
            done = kind_done if header == "Kind" else _fraction_is_complete(value)
            style = "padding:0.4rem 0.55rem;" + ("text-align:left;" if header == "Kind" else "text-align:right;")
            if done:
                style += _FINISHED_KIND_STYLE
            cells.append(f'<td style="{style}">{escape(value)}</td>')
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<div style="overflow-x:auto">'
        '<table style="width:100%;border-collapse:collapse;font-size:0.95rem">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>"
    )


def _checked_as_of_caption(as_of: object) -> str:
    stamp = pd.to_datetime(as_of, errors="coerce")
    if pd.isna(stamp):
        return "Checked Atlas entries."
    return f"Checked Atlas entries as of {pd.Timestamp(stamp).date().isoformat()}."


def render_pokedex_dashboard_view(
    species_df: pd.DataFrame,
    pokemon_catalog_df: pd.DataFrame,
    availability_df: pd.DataFrame,
    accounts: Sequence[str],
    xp_df: pd.DataFrame,
    *,
    entry_types: Sequence[str],
    entry_type_labels: dict[str, str],
    regions: Sequence[str],
    region_labels: dict[str, str],
    select_date_range_fn: Callable[..., tuple[date, date]],
    build_account_color_map_fn: Callable[..., dict[str, str]],
    render_account_color_legend_fn: Callable[..., Any],
    render_plotly_chart_fn: Callable[..., Any],
) -> None:
    st.subheader("Pokédex Dashboard")
    st.caption(
        "Atlas lists and counts come from checked species entries plus the Pokemon catalog. "
        "Artwork: PokeAPI. Availability and Community Days: pogoapi.net."
    )
    if st.button("Sync", key="pokedex_dashboard_sync"):
        _show_pokedex_sync_result(run_configured_sync())
        st.rerun()

    dashboard_accounts = _ordered_names(accounts)
    if not dashboard_accounts:
        st.warning("No accounts found for the Pokédex dashboard.")
        return

    selected_pokedex_accounts = st.multiselect(
        "Accounts",
        options=dashboard_accounts,
        default=dashboard_accounts,
        key="pokedex_dashboard_species_accounts",
    )

    entry_type_options = _progress_entry_type_options(entry_types)
    default_entry_types = [
        entry_type for entry_type in ["pokemon", "shiny", "hundo", "lucky"] if entry_type in entry_type_options
    ]
    if not default_entry_types:
        default_entry_types = entry_type_options[:4]
    selected_pokedex_entry_types = st.multiselect(
        "Entry types",
        options=entry_type_options,
        default=default_entry_types,
        format_func=lambda value: _entry_type_label(value, entry_type_labels),
        key="pokedex_dashboard_entry_types",
    )

    species_bounds = _species_date_bounds(species_df)
    if species_bounds is None:
        pokedex_start_date = date.today()
        pokedex_end_date = date.today()
        st.info("No species entries yet. Counts use today.")
        atlas_as_of_date = max(pokedex_end_date, date.today())
    else:
        min_species_date, max_species_date = species_bounds
        pokedex_start_date, pokedex_end_date = select_date_range_fn(
            label="Date range",
            min_date=min_species_date,
            max_date=max_species_date,
            key="pokedex_dashboard_date_range",
        )
        # A range that ends at the newest species date shows the Atlas as of today.
        if pokedex_end_date >= max_species_date:
            atlas_as_of_date = max(pokedex_end_date, date.today())
        else:
            atlas_as_of_date = pokedex_end_date

    view_mode = st.radio(
        "View mode",
        options=["Atlas", "Progress"],
        horizontal=True,
        key="pokedex_dashboard_view_mode",
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

    _render_progress_view(
        pokemon_catalog_df=pokemon_catalog_df,
        species_df=species_df,
        availability_df=availability_df,
        selected_accounts=selected_pokedex_accounts,
        selected_entry_types=selected_pokedex_entry_types,
        start_date=pokedex_start_date,
        end_date=pokedex_end_date,
        entry_type_labels=entry_type_labels,
        region_labels=region_labels,
        regions=regions,
        account_color_map=account_color_map,
        render_plotly_chart_fn=render_plotly_chart_fn,
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


_ATLAS_REGISTRATION_NOTICE_KEY = "atlas_registration_notice"
_ATLAS_DIALOG_TOKEN_KEY = "atlas_dialog_token"
_ATLAS_CARD_OPEN_NONCE_KEY = "atlas_card_open_nonce"
_ATLAS_CARD_DISMISSED_NONCE_KEY = "atlas_card_dismissed_nonce"
_ATLAS_REG_KEY_PREFIX = "atlas_reg_"
# Installed Streamlit 1.45.1: st.dialog(title, *, width="small"). No on_dismiss.
_ATLAS_DIALOG_ON_DISMISS = "on_dismiss" in inspect.signature(st.dialog).parameters


def _delete_atlas_reg_widget_keys() -> None:
    for key in list(st.session_state.keys()):
        if str(key).startswith(_ATLAS_REG_KEY_PREFIX):
            del st.session_state[key]


def _close_atlas_registration_dialog() -> None:
    nonce = st.session_state.get(_ATLAS_CARD_OPEN_NONCE_KEY)
    if nonce is not None:
        st.session_state[_ATLAS_CARD_DISMISSED_NONCE_KEY] = nonce
    st.session_state.pop(_ATLAS_DIALOG_TOKEN_KEY, None)


def _clear_atlas_registration_dialog_state() -> None:
    _close_atlas_registration_dialog()
    _delete_atlas_reg_widget_keys()


def _dismiss_atlas_registration_dialog() -> None:
    """Clear registration dialog state and rerun.

    Streamlit 1.45.1 does not rerun the app when a dialog is dismissed, and
    ``st.dialog`` has no ``on_dismiss`` parameter to register this callable.
    """
    _clear_atlas_registration_dialog_state()
    st.rerun()


def _show_atlas_registration_notice() -> None:
    notice = st.session_state.pop(_ATLAS_REGISTRATION_NOTICE_KEY, None)
    if not isinstance(notice, dict):
        return
    if notice.get("release_only"):
        st.success("The release list was updated.")
    else:
        written = notice.get("written", 0)
        account = notice.get("account", "")
        st.success(f"Saved {written} species rows for {account}.")
    result = notice.get("result")
    if isinstance(result, dict):
        _show_pokedex_sync_result(result, saved_locally=True)


def _atlas_card_for_dex(cards: pd.DataFrame, dex: int) -> pd.Series | None:
    if cards.empty or "dex_number" not in cards.columns:
        return None
    dex_numbers = pd.to_numeric(cards["dex_number"], errors="coerce")
    matches = cards.loc[dex_numbers.eq(dex)]
    if matches.empty:
        return None
    return matches.iloc[0]


def _atlas_card_text(card: pd.Series, column: str) -> str:
    if column not in card.index:
        return ""
    value = card[column]
    if _registered_is_blank(value):
        return ""
    return str(value).strip()


def _atlas_reg_widget_key(account: object, dex: int, suffix: str) -> str:
    return f"{_ATLAS_REG_KEY_PREFIX}{account}_{dex}_{suffix}"


def _reset_atlas_registration_widgets(account: object, dex: int) -> None:
    token = f"{account}:{dex}"
    if st.session_state.get(_ATLAS_DIALOG_TOKEN_KEY) == token:
        return
    _delete_atlas_reg_widget_keys()
    st.session_state[_ATLAS_DIALOG_TOKEN_KEY] = token


class AtlasKindRelease(NamedTuple):
    released: bool
    editable: bool
    seed_available: bool
    detail: str


def _missing_scalar(value: object) -> bool:
    if value is None or value is pd.NA:
        return True
    if isinstance(value, (str, bytes)):
        return False
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return isinstance(missing, bool) and missing


def _text_key(value: object) -> str:
    if _missing_scalar(value):
        return ""
    return str(value).strip()


def _form_key(value: object) -> str:
    return _text_key(value).casefold()


def _coerce_release_bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    if _missing_scalar(value):
        return False
    return bool(value)


def _release_edit_deletes(value: object) -> bool:
    return _missing_scalar(value)


def _release_override_key(entry_type: object, dex: object, form: object) -> tuple[str, int, str] | None:
    kind = _text_key(entry_type).lower()
    if not kind:
        return None
    if isinstance(dex, bool) or _missing_scalar(dex):
        return None
    number = pd.to_numeric(dex, errors="coerce")
    if _missing_scalar(number):
        return None
    numeric = float(number)
    if numeric <= 0 or not numeric.is_integer():
        return None
    return kind, int(numeric), _form_key(form)


def _record_override_key(record: dict[str, object]) -> tuple[str, int, str] | None:
    return _release_override_key(
        record.get("entry_type", record.get("kind")),
        record.get("dex_number", record.get("dex")),
        record.get("form", ""),
    )


def _manual_override_available(manual: object) -> dict[tuple[str, int, str], bool]:
    if isinstance(manual, dict):
        indexed: dict[tuple[str, int, str], bool] = {}
        for key, value in manual.items():
            if isinstance(value, dict):
                identity = _record_override_key(value)
                if identity is None and isinstance(key, tuple) and len(key) == 3:
                    identity = _release_override_key(key[0], key[1], key[2])
                if identity is None:
                    continue
                indexed[identity] = _coerce_release_bool(value.get("available"))
                continue
            if isinstance(key, tuple) and len(key) == 3:
                identity = _release_override_key(key[0], key[1], key[2])
                if identity is None:
                    continue
                indexed[identity] = _coerce_release_bool(value)
        return indexed
    if isinstance(manual, pd.DataFrame):
        records = [] if manual.empty else manual.to_dict(orient="records")
    elif isinstance(manual, (list, tuple)):
        records = [item for item in manual if isinstance(item, dict)]
    else:
        return {}
    indexed = {}
    for record in records:
        identity = _record_override_key(record)
        if identity is None:
            continue
        indexed[identity] = _coerce_release_bool(record.get("available"))
    return indexed


def _release_edits_change_manual(edits: Sequence[dict[str, object]], manual: object) -> bool:
    """True when an edit would add, update, or delete a manual release row."""
    if not edits:
        return False
    current = _manual_override_available(manual)
    for edit in edits:
        if not isinstance(edit, dict) or "available" not in edit:
            return True
        identity = _record_override_key(edit)
        if identity is None:
            return True
        if _release_edit_deletes(edit.get("available")):
            if identity in current:
                return True
            continue
        wanted = _coerce_release_bool(edit.get("available"))
        if identity not in current or current[identity] != wanted:
            return True
    return False


def _availability_match_row(
    availability_df: pd.DataFrame | None,
    dex: int,
    entry_type: str,
    form: str = "",
) -> pd.Series | None:
    if availability_df is None or not isinstance(availability_df, pd.DataFrame) or availability_df.empty:
        return None
    if not {"entry_type", "dex_number"}.issubset(availability_df.columns):
        return None
    entry = availability_df["entry_type"].map(lambda value: _text_key(value).lower())
    dex_numbers = pd.to_numeric(availability_df["dex_number"], errors="coerce")
    if "form" in availability_df.columns:
        forms = availability_df["form"].map(_form_key)
    else:
        forms = pd.Series("", index=availability_df.index, dtype="object")
    mask = entry.eq(_text_key(entry_type).lower()) & dex_numbers.eq(int(dex)) & forms.eq(_form_key(form))
    matches = availability_df.loc[mask]
    if matches.empty:
        return None
    return matches.iloc[0]


def _atlas_kind_release_state(
    availability_df: pd.DataFrame | None,
    dex: int,
    entry_type: str,
    *,
    form: str = "",
) -> AtlasKindRelease:
    row = _availability_match_row(availability_df, dex, entry_type, form)
    if row is None:
        return AtlasKindRelease(released=False, editable=True, seed_available=False, detail="")
    source = _text_key(row["release_source"]).lower() if "release_source" in row.index else ""
    if source == "evolution":
        detail = _text_key(row["release_detail"]) if "release_detail" in row.index else ""
        return AtlasKindRelease(released=True, editable=False, seed_available=False, detail=detail)
    released = _coerce_release_bool(row["available"]) if "available" in row.index else False
    seed_available = _coerce_release_bool(row["seed_available"]) if "seed_available" in row.index else False
    return AtlasKindRelease(released=released, editable=True, seed_available=seed_available, detail="")


def _availability_has_released(availability_df: pd.DataFrame | None, dex: int, entry_type: str) -> bool:
    if availability_df is None or not isinstance(availability_df, pd.DataFrame) or availability_df.empty:
        return False
    if not {"entry_type", "dex_number", "available"}.issubset(availability_df.columns):
        return False
    entry = availability_df["entry_type"].map(lambda value: _text_key(value).lower())
    dex_numbers = pd.to_numeric(availability_df["dex_number"], errors="coerce")
    rows = availability_df.loc[entry.eq(_text_key(entry_type).lower()) & dex_numbers.eq(int(dex))]
    return any(_coerce_release_bool(value) for value in rows["available"].tolist())


def _atlas_mega_released_checked(card: pd.Series, availability_df: pd.DataFrame | None, dex: int) -> bool:
    if any(_json_forms(card.get("mega_forms"))):
        return True
    return _availability_has_released(availability_df, dex, "mega")


def _atlas_caught_default(card: pd.Series, kind: str) -> bool:
    registered_column = f"registered_{kind}"
    raw = card[registered_column] if registered_column in card.index else pd.NA
    if not _registered_is_blank(raw):
        return bool(raw)
    caught_column = f"caught_{kind}"
    if caught_column not in card.index or _registered_is_blank(card[caught_column]):
        return False
    return bool(card[caught_column])


def _atlas_species_not_in_go(card: pd.Series) -> bool:
    if "status" in card.index and not _registered_is_blank(card["status"]):
        if str(card["status"]).strip().lower() == "unavailable":
            return True
    available = card["available_in_pogo"] if "available_in_pogo" in card.index else None
    return not is_available_in_pogo(available)


def _atlas_release_checkbox(
    *,
    label: str,
    state: AtlasKindRelease,
    account: object,
    dex: int,
    suffix: str,
) -> bool:
    checked = bool(
        st.checkbox(
            label,
            value=state.released,
            disabled=not state.editable,
            key=_atlas_reg_widget_key(account, dex, suffix),
        )
    )
    if not state.editable and state.detail:
        st.caption(f"Via evolution from {state.detail}")
    if not state.editable:
        return state.released
    return checked


def _atlas_caught_checkbox(
    card: pd.Series,
    kind: str,
    *,
    label: str,
    account: object,
    dex: int,
    suffix: str | None = None,
) -> bool:
    return bool(
        st.checkbox(
            label,
            value=_atlas_caught_default(card, kind),
            key=_atlas_reg_widget_key(account, dex, kind if suffix is None else suffix),
        )
    )


def _atlas_form_host(card: pd.Series, column: str) -> bool:
    if column not in card.index:
        return True
    value = card[column]
    if _registered_is_blank(value):
        return True
    return bool(value)


def _decorate_atlas_registration_dialog(func: Callable[..., None]) -> Callable[..., None]:
    if _ATLAS_DIALOG_ON_DISMISS:
        return st.dialog("Registration", on_dismiss=_dismiss_atlas_registration_dialog)(func)
    return st.dialog("Registration")(func)


@_decorate_atlas_registration_dialog
def _atlas_registration_dialog(
    card: pd.Series,
    *,
    account: object,
    save_date: date,
    availability_df: pd.DataFrame,
) -> None:
    dex_number = pd.to_numeric(card.get("dex_number"), errors="coerce")
    if pd.isna(dex_number):
        st.write("Not in GO")
        return
    dex = int(dex_number)
    _reset_atlas_registration_widgets(account, dex)

    name = _atlas_card_text(card, "name")
    german = _atlas_card_text(card, "german_name")
    heading = f"#{dex:04d} {name}".strip()
    if german:
        heading = f"{heading} ({german})"
    st.subheader(heading, anchor=False)
    if _atlas_species_not_in_go(card):
        st.write("Not in GO")
        return

    kind_values: dict[str, bool] = {}
    release_choices: dict[str, tuple[AtlasKindRelease, bool]] = {}
    for kind_id, label in ATLAS_ENTRY_KINDS:
        if kind_id in {"shiny", "shadow"}:
            state = _atlas_kind_release_state(availability_df, dex, kind_id)
            released = _atlas_release_checkbox(
                label=f"{label} released",
                state=state,
                account=account,
                dex=dex,
                suffix=f"release_{kind_id}",
            )
            release_choices[kind_id] = (state, released)
            if released:
                kind_values[kind_id] = _atlas_caught_checkbox(
                    card,
                    kind_id,
                    label=label,
                    account=account,
                    dex=dex,
                )
            continue

        column = f"registered_{kind_id}"
        raw = card[column] if column in card.index else pd.NA
        unavailable = _registered_is_blank(raw)
        checked = st.checkbox(
            label,
            value=False if unavailable else bool(raw),
            disabled=unavailable,
            key=_atlas_reg_widget_key(account, dex, kind_id),
        )
        if not unavailable:
            kind_values[kind_id] = bool(checked)

    mega_host = _atlas_form_host(card, "mega_host")
    mega_values: dict[str, bool] | None = None
    if mega_host:
        mega_forms: list[str] = []
        seen_forms: set[str] = set()
        for form in _json_forms(card.get("mega_forms")):
            if not form or form in seen_forms:
                continue
            seen_forms.add(form)
            mega_forms.append(form)
        mega_released = bool(
            st.checkbox(
                "Mega released",
                value=_atlas_mega_released_checked(card, availability_df, dex),
                key=_atlas_reg_widget_key(account, dex, "release_mega"),
            )
        )
        if mega_released:
            if mega_forms:
                registered_forms = {form.casefold() for form in _json_forms(card.get("registered_mega_forms"))}
                mega_values = {}
                for form in mega_forms:
                    checked = st.checkbox(
                        mega_badge_label(form),
                        value=form.casefold() in registered_forms,
                        key=_atlas_reg_widget_key(account, dex, f"mega_{form}"),
                    )
                    mega_values[form] = bool(checked)
            else:
                normal_checked = st.checkbox(
                    mega_badge_label("Normal"),
                    value=False,
                    key=_atlas_reg_widget_key(account, dex, "mega_Normal"),
                )
                mega_values = {"Normal": bool(normal_checked)}

    gmax_host = _atlas_form_host(card, "gmax_host")
    gmax_value: bool | None = None
    if gmax_host:
        gmax_state = _atlas_kind_release_state(availability_df, dex, "gmax")
        gmax_released = _atlas_release_checkbox(
            label="G-Max released",
            state=gmax_state,
            account=account,
            dex=dex,
            suffix="release_gmax",
        )
        if gmax_released:
            gmax_value = _atlas_caught_checkbox(
                card,
                "gmax",
                label="G-Max",
                account=account,
                dex=dex,
                suffix="gmax",
            )

    if not st.button(
        "Save registration",
        type="primary",
        key=_atlas_reg_widget_key(account, dex, "save"),
    ):
        return

    edits: list[dict[str, object]] = []
    for kind_id in ("shiny", "shadow"):
        choice = release_choices.get(kind_id)
        if choice is None:
            continue
        state, want_released = choice
        if not state.editable:
            continue
        edits.append(
            blank_kind_release_edit(
                kind_id,
                dex,
                form="",
                want_released=want_released,
                seed_available=state.seed_available,
            )
        )
    if gmax_host:
        if gmax_state.editable:
            edits.append(
                blank_kind_release_edit(
                    "gmax",
                    dex,
                    form="",
                    want_released=gmax_released,
                    seed_available=gmax_state.seed_available,
                )
            )
    if mega_host:
        mega_edits = mega_release_edits(dex, mega_released, availability_df)
        if mega_edits:
            edits.extend(mega_edits)

    rows = species_rows_from_card_registration(
        card,
        account=account,
        save_date=save_date,
        kind_values=kind_values,
        mega_values=mega_values,
        gmax_value=gmax_value,
    )
    manual_path = manual_category_availability_path()
    overrides_changed = bool(edits) and _release_edits_change_manual(
        edits,
        load_manual_category_availability(manual_path),
    )
    if not overrides_changed and not rows:
        st.info("No species progress changed.")
        return
    if overrides_changed:
        save_manual_category_availability(manual_path, edits)

    written = upsert_pokedex_species_rows(pokedex_species_entries_path(), rows) if rows else 0
    st.session_state[_ATLAS_REGISTRATION_NOTICE_KEY] = {
        "written": written,
        "account": str(account),
        "result": publish_local_species_save(),
        "release_only": bool(overrides_changed and not rows),
    }
    # Widget keys are removed on the next run, before those widgets exist.
    # Deleting them here raises after the checkboxes are instantiated.
    _close_atlas_registration_dialog()
    st.rerun()


def _open_selected_atlas_registration(
    cards: pd.DataFrame,
    *,
    account: object,
    as_of_date: object,
    availability_df: pd.DataFrame,
) -> None:
    event = atlas_card_event()
    dex = atlas_card_event_dex(event)
    nonce = event.get("nonce") if isinstance(event, dict) else None
    if (
        dex is None
        or nonce is None
        or nonce == st.session_state.get(_ATLAS_CARD_DISMISSED_NONCE_KEY)
    ):
        _clear_atlas_registration_dialog_state()
        return
    card = _atlas_card_for_dex(cards, dex)
    if card is None:
        st.session_state[_ATLAS_CARD_DISMISSED_NONCE_KEY] = nonce
        _clear_atlas_registration_dialog_state()
        return
    st.session_state[_ATLAS_CARD_OPEN_NONCE_KEY] = nonce
    save_date = pd.to_datetime(as_of_date, errors="coerce")
    if pd.isna(save_date):
        save_date = pd.Timestamp.today()
    save_date = pd.Timestamp(save_date).date()
    _atlas_registration_dialog(
        card,
        account=account,
        save_date=save_date,
        availability_df=availability_df,
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
    _show_atlas_registration_notice()
    # Page-level entry types filter Progress only.
    del selected_entry_types, entry_type_labels

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
    path_labels = {
        "any": "Any",
        "evolution": "Via evolution",
        "purify": "Via purify",
        "either": "Via evolution or purify",
    }
    atlas_col_account, atlas_col_region = st.columns([1.1, 1.4])
    atlas_account = atlas_col_account.selectbox(
        "Atlas account",
        options=list(selected_accounts),
        key="pokedex_dashboard_species_atlas_account",
    )
    atlas_region = atlas_col_region.selectbox(
        "Region",
        options=region_options,
        index=region_options.index(default_region) if default_region in region_options else 0,
        format_func=atlas_region_label,
        key="pokedex_dashboard_atlas_region",
    )
    filter_col_kind, filter_col_state, filter_col_release, filter_col_fill = st.columns([1.2, 1.3, 1.4, 1.7])
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
    path_filter = filter_col_fill.selectbox(
        "Fill",
        options=list(path_labels),
        format_func=lambda value: path_labels.get(str(value), str(value)),
        key="pokedex_dashboard_atlas_path",
    )
    if release_filter != "override":
        st.caption("Fill uses registered checklist entries. One Pokémon can only take one evolution branch.")
    search = st.text_input("Search name, dex number, or form", key="pokedex_dashboard_atlas_search")

    region_counts = build_species_region_counts(
        pokemon_catalog_df,
        species_df,
        account=atlas_account,
        availability_df=availability_df,
        as_of_date=as_of_date,
    )
    st.markdown(
        _species_region_count_html(region_counts, region_labels),
        unsafe_allow_html=True,
    )
    st.caption(
        "Checked Atlas entries for this account. "
        "The region filter applies only to the cards below."
    )

    evolutions_df = load_pokemon_evolutions(pokemon_evolutions_path())
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
            evolutions_df=evolutions_df,
            path_filter="any",
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
            evolutions_df=evolutions_df,
            path_filter=path_filter,
        )
        cards = filter_atlas_cards_by_release(cards, release_filter)
    if release_filter == "override":
        st.caption("Manual override lists every saved release exception, in all regions.")
    st.caption(f"Showing {len(cards):,}")
    st.caption("Click a card to edit that species' registration.")
    st.markdown(pokedex_atlas_html(cards), unsafe_allow_html=True)
    _open_selected_atlas_registration(
        cards,
        account=atlas_account,
        as_of_date=as_of_date,
        availability_df=availability_df,
    )

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
            rows = species_rows_delta_from_atlas_editor(
                cards,
                edited,
                account=atlas_account,
                save_date=pd.Timestamp(save_date).date(),
                entry_mode=str(entry_mode),
            )
            if not rows:
                st.info("No species progress changed.")
            else:
                written = upsert_pokedex_species_rows(pokedex_species_entries_path(), rows)
                st.success(f"Saved {written} species rows for {atlas_account}.")
                _show_pokedex_sync_result(publish_local_species_save(), saved_locally=True)
                st.rerun()


def _label_order(frame: pd.DataFrame, selected_entry_types: Sequence[str], entry_type_labels: dict[str, str]) -> list[str]:
    labels_in_data: dict[str, str] = {}
    if frame is not None and not frame.empty and {"entry_type", "entry_type_label"}.issubset(frame.columns):
        for _, row in frame.iterrows():
            labels_in_data[str(row["entry_type"]).strip().lower()] = str(row["entry_type_label"])
    return [
        labels_in_data.get(str(kind).strip().lower(), _entry_type_label(kind, entry_type_labels))
        for kind in selected_entry_types
    ]


def _account_entry_bar(
    frame: pd.DataFrame,
    *,
    y: str,
    y_label: str,
    title: str,
    selected_accounts: Sequence[str],
    label_order: Sequence[str],
    height: int,
) -> Any:
    figure = px.bar(
        frame,
        x="account",
        y=y,
        color="entry_type_label",
        barmode="group",
        category_orders={
            "entry_type_label": list(label_order),
            "account": list(selected_accounts),
        },
        labels={"account": "Account", y: y_label, "entry_type_label": "Entry Type"},
        title=title,
    )
    figure.update_layout(height=height)
    return figure


def _render_progress_view(
    *,
    pokemon_catalog_df: pd.DataFrame,
    species_df: pd.DataFrame,
    availability_df: pd.DataFrame,
    selected_accounts: Sequence[str],
    selected_entry_types: Sequence[str],
    start_date: date,
    end_date: date,
    entry_type_labels: dict[str, str],
    region_labels: dict[str, str],
    regions: Sequence[str],
    account_color_map: dict[str, str],
    render_plotly_chart_fn: Callable[..., Any],
) -> None:
    summary = build_species_missing_summary(
        pokemon_catalog_df,
        species_df,
        accounts=selected_accounts,
        availability_df=availability_df,
        as_of_date=end_date,
        entry_types=selected_entry_types,
    )
    as_of_caption = _checked_as_of_caption(end_date)
    if summary.empty:
        st.info("No checked Atlas entry counts for the selected accounts and entry types.")
    else:
        label_order = _label_order(summary, selected_entry_types, entry_type_labels)
        fig_latest = _account_entry_bar(
            summary,
            y="registered_count",
            y_label="Registered",
            title="Latest Registered Counts by Account",
            selected_accounts=selected_accounts,
            label_order=label_order,
            height=460,
        )
        fig_latest.update_yaxes(tickformat=",.0f")
        render_plotly_chart_fn(fig_latest, use_container_width=True, sort_legend=False)
        st.caption(as_of_caption)

        fig_missing = _account_entry_bar(
            summary,
            y="missing_count",
            y_label="Missing",
            title="Missing Counts by Account",
            selected_accounts=selected_accounts,
            label_order=label_order,
            height=420,
        )
        fig_missing.update_yaxes(tickformat=",.0f")
        render_plotly_chart_fn(fig_missing, use_container_width=True, sort_legend=False)
        st.caption(f"Missing counts are catalog targets minus checked Atlas entries as of {end_date.isoformat()}.")

        progress_df = summary.copy()
        target = pd.to_numeric(progress_df["target_count"], errors="coerce")
        registered = pd.to_numeric(progress_df["registered_count"], errors="coerce")
        progress_df["progress_pct_display"] = registered / target.where(target > 0) * 100
        fig_progress = _account_entry_bar(
            progress_df,
            y="progress_pct_display",
            y_label="Progress %",
            title="Progress Percent by Account",
            selected_accounts=selected_accounts,
            label_order=label_order,
            height=420,
        )
        fig_progress.update_yaxes(ticksuffix="%", rangemode="tozero")
        render_plotly_chart_fn(fig_progress, use_container_width=True, sort_legend=False)
        st.caption(f"Progress percent is checked Atlas entries divided by the catalog target as of {end_date.isoformat()}.")

    trend_df = build_species_progress_rows(
        pokemon_catalog_df,
        species_df,
        accounts=selected_accounts,
        entry_types=selected_entry_types,
        start_date=start_date,
        end_date=end_date,
        availability_df=availability_df,
    )
    if trend_df.empty:
        st.info("No checked Atlas entries in the selected date range.")
    else:
        fig_trend = px.line(
            trend_df,
            x="date",
            y="registered_count",
            color="account",
            line_dash="entry_type_label",
            color_discrete_map=account_color_map,
            markers=True,
            labels={
                "date": "Date",
                "registered_count": "Registered",
                "account": "Account",
                "entry_type_label": "Entry Type",
            },
            title="Registered Counts Over Time",
        )
        fig_trend.update_yaxes(tickformat=",.0f")
        fig_trend.update_layout(height=520)
        render_plotly_chart_fn(fig_trend, use_container_width=True)
        st.caption("Lines are checked Atlas entries over time.")

    preferred_regions = [
        str(region).strip().lower()
        for region in regions
        if str(region).strip().lower() in set(SPECIES_COUNT_REGIONS)
    ] or list(SPECIES_COUNT_REGIONS)
    breakdown_col_1, breakdown_col_2, breakdown_col_3 = st.columns([1.1, 1.1, 1.0])
    breakdown_account = breakdown_col_1.selectbox(
        "Breakdown account",
        options=list(selected_accounts),
        key="pokedex_dashboard_species_breakdown_account",
    )
    breakdown_entry_type = breakdown_col_2.selectbox(
        "Breakdown entry type",
        options=list(selected_entry_types),
        format_func=lambda value: _entry_type_label(value, entry_type_labels),
        key="pokedex_dashboard_species_breakdown_entry_type",
    )
    breakdown_date = breakdown_col_3.date_input(
        "As-of date",
        value=end_date,
        min_value=start_date,
        max_value=end_date,
        key="pokedex_dashboard_species_breakdown_date",
    )
    region_counts = build_species_region_counts(
        pokemon_catalog_df,
        species_df,
        account=breakdown_account,
        availability_df=availability_df,
        as_of_date=breakdown_date,
    )
    region_df = region_counts
    if region_df is not None and not region_df.empty and {"entry_type", "region"}.issubset(region_df.columns):
        region_df = region_df.copy()
        region_df["entry_type"] = region_df["entry_type"].astype(str).str.strip().str.lower()
        region_df["region"] = region_df["region"].astype(str).str.strip().str.lower()
        region_df = region_df[
            (region_df["entry_type"] == str(breakdown_entry_type).strip().lower())
            & region_df["region"].isin(preferred_regions)
        ].copy()
        present_regions = set(region_df["region"].astype(str).tolist())
        region_order = [region for region in preferred_regions if region in present_regions]
    else:
        region_df = pd.DataFrame(columns=["region", "region_label", "registered_count"])
    if region_df.empty:
        st.info(f"No checked Atlas entries for that account and entry type as of {breakdown_date.isoformat()}.")
        return
    region_df["region_label"] = region_df["region"].map(lambda region: region_labels.get(str(region), str(region).title()))
    region_labels_order = [region_labels.get(region, region.title()) for region in region_order]
    fig_region = px.bar(
        region_df,
        x="region_label",
        y="registered_count",
        category_orders={"region_label": region_labels_order},
        labels={"region_label": "Region", "registered_count": "Registered"},
        title=(
            f"{_entry_type_label(breakdown_entry_type, entry_type_labels)} "
            f"by Region for {breakdown_account}"
        ),
    )
    fig_region.update_yaxes(tickformat=",.0f")
    fig_region.update_layout(height=460, showlegend=False)
    render_plotly_chart_fn(fig_region, use_container_width=True, sort_legend=False)
    st.caption(_checked_as_of_caption(breakdown_date))
