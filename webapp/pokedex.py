from __future__ import annotations

import csv
import re
from collections.abc import Sequence
from datetime import date
from html import escape
from pathlib import Path

import pandas as pd

from webapp.data_files import (
    POKEDEX_CATEGORY_AVAILABILITY_COLUMNS,
    POKEDEX_SPECIES_ENTRY_COLUMNS,
    POKEMON_CATALOG_COLUMNS,
    load_pokedex_category_availability,
    load_pokedex_species_entries,
    parse_bool_text,
)

POKEAPI_OFFICIAL_ARTWORK_URL = (
    "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{dex}.png"
)
POKEAPI_SPRITE_FALLBACK_URL = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{dex}.png"

RELEASED_LIKE_ENTRY_TYPES = {"lucky", "xxl", "xxs", "hundo", "purified"}
SEEDED_AVAILABILITY_ENTRY_TYPES = {"shiny", "shadow", "mega"}

# National-dex regionals. Form-only regionals are intentionally omitted.
LOCATION_RESTRICTION_BY_DEX: dict[int, str] = {
    83: "East Asia",
    115: "Australia",
    122: "Europe",
    128: "Americas",
    214: "Latin America",
    222: "Tropics",
    313: "Europe, Asia, Australia",
    314: "Americas",
    324: "South Asia / Africa",
    335: "Europe, Asia, Australia",
    336: "Americas",
    337: "Americas",
    338: "Europe, Asia, Australia",
    369: "New Zealand / Oceania",
    357: "Africa / Mediterranean",
    417: "Alaska / Russia / Canada",
    439: "Europe",
    441: "Southern Hemisphere",
    455: "Southeast United States",
    480: "Asia-Pacific",
    481: "Europe / Middle East / Africa",
    482: "Americas",
    511: "Asia-Pacific",
    513: "Europe / Middle East / Africa",
    515: "Americas",
    538: "Europe / Middle East / Africa",
    539: "Americas",
    550: "Americas",
    556: "Southern United States / Mexico",
    561: "Africa / Mediterranean",
    626: "New York City area",
    631: "Europe, Asia, Australia",
    632: "Americas",
    701: "Mexico",
    707: "Western Europe",
    739: "Americas",
    740: "Americas",
    741: "Americas",
    764: "Hawaii",
    765: "Southern Hemisphere",
    766: "Northern Hemisphere",
    775: "Australia",
    874: "United Kingdom",
    875: "Antarctic / polar",
}


def pokemon_sprite_url(dex_number: object, *, official_artwork: bool = True) -> str:
    dex = pd.to_numeric(dex_number, errors="coerce")
    if pd.isna(dex) or int(dex) <= 0:
        return ""
    template = POKEAPI_OFFICIAL_ARTWORK_URL if official_artwork else POKEAPI_SPRITE_FALLBACK_URL
    return template.format(dex=int(dex))


def normalize_pokemon_name(name: object) -> str:
    text = str(name or "").strip().lower()
    text = text.replace("♀", " f").replace("♂", " m")
    text = text.replace("’", "").replace("'", "").replace(".", " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def is_available_in_pogo(value: object) -> bool:
    text = str(value or "").strip().lower()
    if not text or text in {"unknown", "no", "false", "0", "n"}:
        return False
    return text in {"yes", "true", "1", "y", "available"}


def location_restriction_for_dex(dex_number: object) -> str:
    dex = pd.to_numeric(dex_number, errors="coerce")
    if pd.isna(dex):
        return ""
    return str(LOCATION_RESTRICTION_BY_DEX.get(int(dex), "")).strip()


def latest_community_day_by_dex(
    catalog_df: pd.DataFrame,
    community_days: Sequence[dict[str, object]] | None,
) -> dict[int, tuple[str, str]]:
    if catalog_df.empty or not community_days:
        return {}
    name_to_dex: dict[str, int] = {}
    for _, row in catalog_df.iterrows():
        dex = pd.to_numeric(row.get("dex_number"), errors="coerce")
        if pd.isna(dex):
            continue
        name_to_dex[normalize_pokemon_name(row.get("name"))] = int(dex)

    latest: dict[int, tuple[pd.Timestamp, str, str]] = {}
    for event in community_days:
        if not isinstance(event, dict):
            continue
        start = pd.to_datetime(event.get("start_date") or event.get("start") or "", errors="coerce")
        if pd.isna(start):
            continue
        boosted = event.get("boosted_pokemon") or event.get("featured_pokemon") or []
        if isinstance(boosted, str):
            boosted = [boosted]
        event_name = str(event.get("name") or "").strip()
        if not event_name:
            number = event.get("community_day_number")
            event_name = f"Community Day {number}" if number not in (None, "") else "Community Day"
        event_date = pd.Timestamp(start).date().isoformat()
        for raw_name in boosted:
            dex = name_to_dex.get(normalize_pokemon_name(raw_name))
            if dex is None:
                continue
            current = latest.get(dex)
            if current is None or start >= current[0]:
                latest[dex] = (pd.Timestamp(start), event_name, event_date)
    return {dex: (name, event_date) for dex, (_ts, name, event_date) in latest.items()}


def apply_catalog_community_fields(
    catalog_df: pd.DataFrame,
    *,
    released_dex_numbers: set[int] | None = None,
    community_days: Sequence[dict[str, object]] | None = None,
    location_map: dict[int, str] | None = None,
) -> pd.DataFrame:
    cols = POKEMON_CATALOG_COLUMNS
    if catalog_df.empty:
        return pd.DataFrame(columns=cols)
    out = catalog_df.copy()
    for col in cols:
        if col not in out.columns:
            out[col] = "" if col != "dex_number" else pd.NA
    out["dex_number"] = pd.to_numeric(out["dex_number"], errors="coerce")
    out = out.dropna(subset=["dex_number"]).copy()
    out["dex_number"] = out["dex_number"].astype(int)

    if released_dex_numbers is not None:
        out["available_in_pogo"] = out["dex_number"].map(lambda dex: "yes" if int(dex) in released_dex_numbers else "no")

    restrictions = location_map if location_map is not None else LOCATION_RESTRICTION_BY_DEX
    out["location_restriction"] = out.apply(
        lambda row: str(row.get("location_restriction") or "").strip() or str(restrictions.get(int(row["dex_number"]), "")).strip(),
        axis=1,
    )

    events = latest_community_day_by_dex(out, community_days)
    if events:
        out["last_event"] = out.apply(
            lambda row: str(row.get("last_event") or "").strip() or events.get(int(row["dex_number"]), ("", ""))[0],
            axis=1,
        )
        out["last_event_date"] = out.apply(
            lambda row: str(row.get("last_event_date") or "").strip() or events.get(int(row["dex_number"]), ("", ""))[1],
            axis=1,
        )
    else:
        out["last_event"] = out.get("last_event", "").fillna("").astype(str) if "last_event" in out.columns else ""
        out["last_event_date"] = (
            out.get("last_event_date", "").fillna("").astype(str) if "last_event_date" in out.columns else ""
        )

    for col in [c for c in cols if c != "dex_number"]:
        if col not in out.columns:
            out[col] = ""
        out[col] = out[col].fillna("").astype(str).str.strip()
    return out[cols].sort_values("dex_number").reset_index(drop=True)


def extract_pogoapi_dex_numbers(payload: object) -> set[int]:
    numbers: set[int] = set()

    def add_id(raw: object) -> None:
        dex = pd.to_numeric(raw, errors="coerce")
        if pd.notna(dex) and int(dex) > 0:
            numbers.add(int(dex))

    if isinstance(payload, dict):
        for key, value in payload.items():
            add_id(key)
            if isinstance(value, dict):
                add_id(value.get("id") or value.get("pokemon_id") or value.get("dex_number"))
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        add_id(item.get("id") or item.get("pokemon_id") or item.get("dex_number"))
                    else:
                        add_id(item)
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                add_id(item.get("id") or item.get("pokemon_id") or item.get("dex_number"))
            else:
                add_id(item)
    return numbers


def build_category_availability_rows(
    *,
    shiny_dex: set[int] | None = None,
    shadow_dex: set[int] | None = None,
    mega_dex: set[int] | None = None,
    gmax_dex: set[int] | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for entry_type, numbers in (
        ("shiny", shiny_dex or set()),
        ("shadow", shadow_dex or set()),
        ("mega", mega_dex or set()),
        ("gmax", gmax_dex or set()),
    ):
        for dex in sorted(numbers):
            rows.append({"entry_type": entry_type, "dex_number": int(dex), "available": True, "notes": ""})
    if not rows:
        return pd.DataFrame(columns=POKEDEX_CATEGORY_AVAILABILITY_COLUMNS)
    return pd.DataFrame(rows, columns=POKEDEX_CATEGORY_AVAILABILITY_COLUMNS)


def latest_pokedex_species_state(
    species_df: pd.DataFrame,
    *,
    accounts: Sequence[object] | None = None,
    entry_types: Sequence[object] | None = None,
    as_of_date: object | None = None,
) -> pd.DataFrame:
    cols = POKEDEX_SPECIES_ENTRY_COLUMNS
    if species_df.empty or not {"account", "entry_type", "dex_number", "date"}.issubset(species_df.columns):
        return pd.DataFrame(columns=cols)
    rows = species_df.copy()
    rows["date"] = pd.to_datetime(rows["date"], errors="coerce")
    rows["account"] = rows["account"].astype(str).str.strip()
    rows["entry_type"] = rows["entry_type"].astype(str).str.strip().str.lower()
    rows["dex_number"] = pd.to_numeric(rows["dex_number"], errors="coerce")
    rows = rows.dropna(subset=["date", "account", "entry_type", "dex_number"]).copy()
    rows["dex_number"] = rows["dex_number"].astype(int)
    if "registered" in rows.columns:
        if rows["registered"].dtype != bool:
            rows["registered"] = rows["registered"].map(parse_bool_text)
    else:
        rows["registered"] = False
    if "can_evolve_now" in rows.columns:
        if rows["can_evolve_now"].dtype != bool:
            rows["can_evolve_now"] = rows["can_evolve_now"].map(parse_bool_text)
    else:
        rows["can_evolve_now"] = False
    if "notes" not in rows.columns:
        rows["notes"] = ""
    rows["notes"] = rows["notes"].fillna("").astype(str).str.strip()

    if accounts is not None:
        account_set = {str(a).strip() for a in accounts if str(a).strip()}
        rows = rows[rows["account"].isin(account_set)].copy()
    if entry_types is not None:
        type_set = {str(t).strip().lower() for t in entry_types if str(t).strip()}
        rows = rows[rows["entry_type"].isin(type_set)].copy()
    as_of = pd.to_datetime(as_of_date, errors="coerce") if as_of_date is not None else pd.NaT
    if pd.notna(as_of):
        rows = rows[rows["date"] <= pd.Timestamp(as_of)].copy()
    if rows.empty:
        return pd.DataFrame(columns=cols)
    latest = rows.sort_values(["account", "entry_type", "dex_number", "date"]).groupby(
        ["account", "entry_type", "dex_number"],
        as_index=False,
    ).tail(1)
    return latest[cols].sort_values(["account", "entry_type", "dex_number"]).reset_index(drop=True)


def upsert_pokedex_species_rows(path: Path, rows: list[dict[str, object]]) -> int:
    if not rows:
        return 0
    new_df = pd.DataFrame(rows)
    for col in POKEDEX_SPECIES_ENTRY_COLUMNS:
        if col not in new_df.columns:
            if col in {"registered", "can_evolve_now"}:
                new_df[col] = False
            elif col == "notes":
                new_df[col] = ""
            else:
                new_df[col] = pd.NA
    new_df["date"] = pd.to_datetime(new_df["date"], errors="coerce")
    new_df["account"] = new_df["account"].astype(str).str.strip()
    new_df["entry_type"] = new_df["entry_type"].astype(str).str.strip().str.lower()
    new_df["dex_number"] = pd.to_numeric(new_df["dex_number"], errors="coerce")
    new_df["registered"] = new_df["registered"].map(lambda value: value if isinstance(value, bool) else parse_bool_text(value))
    new_df["can_evolve_now"] = new_df["can_evolve_now"].map(
        lambda value: value if isinstance(value, bool) else parse_bool_text(value)
    )
    new_df["notes"] = new_df["notes"].fillna("").astype(str).str.strip()
    new_df = new_df.dropna(subset=["date", "account", "entry_type", "dex_number"]).copy()
    new_df["dex_number"] = new_df["dex_number"].astype(int)
    new_df = new_df[(new_df["account"] != "") & (new_df["entry_type"] != "") & (new_df["dex_number"] > 0)].copy()
    new_df = new_df.drop_duplicates(subset=["date", "account", "entry_type", "dex_number"], keep="last")
    if new_df.empty:
        return 0

    existing = load_pokedex_species_entries(path)
    if existing.empty:
        combined = new_df[POKEDEX_SPECIES_ENTRY_COLUMNS].copy()
    else:
        combined = pd.concat([existing, new_df[POKEDEX_SPECIES_ENTRY_COLUMNS]], ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"], errors="coerce")
    combined = combined.dropna(subset=["date", "account", "entry_type", "dex_number"]).copy()
    combined["dex_number"] = pd.to_numeric(combined["dex_number"], errors="coerce").astype(int)
    combined = combined.sort_values(["account", "entry_type", "dex_number", "date"]).drop_duplicates(
        subset=["date", "account", "entry_type", "dex_number"],
        keep="last",
    )
    combined = combined.sort_values(["date", "account", "entry_type", "dex_number"]).reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = combined[POKEDEX_SPECIES_ENTRY_COLUMNS].copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out["registered"] = out["registered"].map(lambda value: "true" if bool(value) else "false")
    out["can_evolve_now"] = out["can_evolve_now"].map(lambda value: "true" if bool(value) else "false")
    out.to_csv(path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
    return int(len(new_df))


def released_catalog_dex_numbers(catalog_df: pd.DataFrame) -> set[int]:
    if catalog_df.empty or "dex_number" not in catalog_df.columns:
        return set()
    rows = catalog_df.copy()
    rows["dex_number"] = pd.to_numeric(rows["dex_number"], errors="coerce")
    rows = rows.dropna(subset=["dex_number"]).copy()
    if "available_in_pogo" in rows.columns:
        rows = rows[rows["available_in_pogo"].map(is_available_in_pogo)].copy()
    return set(rows["dex_number"].astype(int).tolist())


def category_target_dex_numbers(
    entry_type: object,
    catalog_df: pd.DataFrame,
    availability_df: pd.DataFrame | None = None,
) -> set[int]:
    entry = str(entry_type).strip().lower()
    if not entry:
        return set()
    catalog_dex: set[int] = set()
    if not catalog_df.empty and "dex_number" in catalog_df.columns:
        dex = pd.to_numeric(catalog_df["dex_number"], errors="coerce").dropna().astype(int)
        catalog_dex = set(dex.tolist())

    availability = availability_df if availability_df is not None else pd.DataFrame(columns=POKEDEX_CATEGORY_AVAILABILITY_COLUMNS)
    type_rows = pd.DataFrame(columns=POKEDEX_CATEGORY_AVAILABILITY_COLUMNS)
    if not availability.empty and {"entry_type", "dex_number", "available"}.issubset(availability.columns):
        type_rows = availability[availability["entry_type"].astype(str).str.strip().str.lower() == entry].copy()

    if entry == "pokemon":
        return catalog_dex

    if not type_rows.empty:
        available_rows = type_rows[type_rows["available"].map(lambda value: value if isinstance(value, bool) else parse_bool_text(value))]
        return set(pd.to_numeric(available_rows["dex_number"], errors="coerce").dropna().astype(int).tolist())

    if entry in RELEASED_LIKE_ENTRY_TYPES or entry in SEEDED_AVAILABILITY_ENTRY_TYPES:
        return released_catalog_dex_numbers(catalog_df)
    return set()


def enrich_species_with_catalog(species_df: pd.DataFrame, catalog_df: pd.DataFrame) -> pd.DataFrame:
    if species_df.empty:
        return species_df.copy()
    catalog_cols = ["dex_number", "name", "german_name", "region", "type_1", "type_2", "available_in_pogo"]
    extra_cols = [col for col in ["location_restriction", "last_event", "last_event_date", "extra_info"] if col in catalog_df.columns]
    keep = [col for col in catalog_cols + extra_cols if col in catalog_df.columns]
    catalog = catalog_df[keep].copy() if keep else pd.DataFrame(columns=["dex_number"])
    catalog["dex_number"] = pd.to_numeric(catalog["dex_number"], errors="coerce")
    catalog = catalog.dropna(subset=["dex_number"]).copy()
    catalog["dex_number"] = catalog["dex_number"].astype(int)
    out = species_df.copy()
    out["dex_number"] = pd.to_numeric(out["dex_number"], errors="coerce")
    out = out.dropna(subset=["dex_number"]).copy()
    out["dex_number"] = out["dex_number"].astype(int)
    return out.merge(catalog, on="dex_number", how="left")


def build_missing_pokemon_rows(
    catalog_df: pd.DataFrame,
    species_df: pd.DataFrame,
    *,
    account: object,
    entry_type: object,
    regions: Sequence[object] | None = None,
    availability_df: pd.DataFrame | None = None,
    as_of_date: object | None = None,
) -> pd.DataFrame:
    account_name = str(account).strip()
    entry = str(entry_type).strip().lower()
    if catalog_df.empty or not account_name or not entry:
        return pd.DataFrame(
            columns=[
                "account",
                "entry_type",
                "dex_number",
                "name",
                "german_name",
                "region",
                "registered",
                "available_in_pogo",
                "location_restriction",
                "last_event",
                "last_event_date",
                "notes",
            ]
        )
    targets = category_target_dex_numbers(entry, catalog_df, availability_df)
    catalog = catalog_df.copy()
    catalog["dex_number"] = pd.to_numeric(catalog["dex_number"], errors="coerce")
    catalog = catalog.dropna(subset=["dex_number"]).copy()
    catalog["dex_number"] = catalog["dex_number"].astype(int)
    catalog = catalog[catalog["dex_number"].isin(targets)].copy()
    if regions is not None:
        region_set = {str(r).strip().lower() for r in regions if str(r).strip() and str(r).strip().lower() != "overall"}
        if region_set and "region" in catalog.columns:
            catalog = catalog[catalog["region"].astype(str).str.strip().str.lower().isin(region_set)].copy()

    latest = latest_pokedex_species_state(
        species_df,
        accounts=[account_name],
        entry_types=[entry],
        as_of_date=as_of_date,
    )
    registered = set()
    notes_by_dex: dict[int, str] = {}
    if not latest.empty:
        registered_rows = latest[latest["registered"] == True]  # noqa: E712
        registered = set(registered_rows["dex_number"].astype(int).tolist())
        for _, row in latest.iterrows():
            notes_by_dex[int(row["dex_number"])] = str(row.get("notes") or "").strip()

    missing = catalog[~catalog["dex_number"].isin(registered)].copy()
    missing["account"] = account_name
    missing["entry_type"] = entry
    missing["registered"] = False
    missing["notes"] = missing["dex_number"].map(notes_by_dex).fillna("")
    keep = [
        "account",
        "entry_type",
        "dex_number",
        "name",
        "german_name",
        "region",
        "registered",
        "available_in_pogo",
        "location_restriction",
        "last_event",
        "last_event_date",
        "notes",
    ]
    for col in keep:
        if col not in missing.columns:
            missing[col] = "" if col != "registered" else False
    return missing[keep].sort_values(["region", "dex_number"]).reset_index(drop=True)


def build_pokedex_target_rows(
    config_df: pd.DataFrame,
    *,
    entry_types: Sequence[object] | None = None,
    regions: Sequence[object] | None = None,
    entry_type_labels: dict[str, str] | None = None,
    region_labels: dict[str, str] | None = None,
) -> pd.DataFrame:
    cols = ["entry_type", "region", "max_value", "locked", "notes", "entry_type_label", "region_label"]
    if config_df.empty or not {"entry_type", "region", "max_value"}.issubset(config_df.columns):
        return pd.DataFrame(columns=cols)
    rows = config_df.copy()
    rows["entry_type"] = rows["entry_type"].astype(str).str.strip().str.lower()
    rows["region"] = rows["region"].astype(str).str.strip().str.lower()
    rows["max_value"] = pd.to_numeric(rows["max_value"], errors="coerce").fillna(0.0)
    if "locked" in rows.columns:
        rows["locked"] = rows["locked"].map(lambda value: value if isinstance(value, bool) else parse_bool_text(value))
    else:
        rows["locked"] = False
    if "notes" not in rows.columns:
        rows["notes"] = ""
    rows["notes"] = rows["notes"].fillna("").astype(str).str.strip()
    if entry_types is not None:
        type_set = {str(t).strip().lower() for t in entry_types if str(t).strip()}
        rows = rows[rows["entry_type"].isin(type_set)].copy()
    regional = rows[rows["region"] != "overall"].copy()
    derived_overall = (
        regional.groupby("entry_type", as_index=False)["max_value"]
        .sum()
        .assign(region="overall", locked=True, notes="Derived as the sum of regional targets.")
    )
    combined = pd.concat([regional, derived_overall], ignore_index=True)
    if regions is not None:
        region_set = {str(r).strip().lower() for r in regions if str(r).strip()}
        combined = combined[combined["region"].isin(region_set)].copy()
    type_labels = entry_type_labels or {}
    region_label_map = region_labels or {}
    combined["entry_type_label"] = combined["entry_type"].map(lambda value: type_labels.get(value, value))
    combined["region_label"] = combined["region"].map(lambda value: region_label_map.get(value, value))
    return combined[cols].sort_values(["entry_type", "region"]).reset_index(drop=True)


def build_pokedex_missing_count_rows(
    pokedex_df: pd.DataFrame,
    config_df: pd.DataFrame,
    *,
    accounts: Sequence[object] | None = None,
    entry_types: Sequence[object] | None = None,
    regions: Sequence[object] | None = None,
    start_date: object | None = None,
    end_date: object | None = None,
    entry_type_labels: dict[str, str] | None = None,
    region_labels: dict[str, str] | None = None,
) -> pd.DataFrame:
    targets = build_pokedex_target_rows(
        config_df,
        entry_types=entry_types,
        regions=regions,
        entry_type_labels=entry_type_labels,
        region_labels=region_labels,
    )
    snapshot_cols = ["date", "account", "entry_type", "region", "value"]
    if targets.empty:
        return pd.DataFrame(
            columns=[
                *snapshot_cols,
                "max_value",
                "missing_count",
                "progress_pct",
                "entry_type_label",
                "region_label",
            ]
        )

    snapshots = pokedex_df.copy() if not pokedex_df.empty else pd.DataFrame(columns=snapshot_cols)
    for col in snapshot_cols:
        if col not in snapshots.columns:
            snapshots[col] = pd.NA
    snapshots = snapshots[snapshot_cols].copy()
    snapshots["date"] = pd.to_datetime(snapshots["date"], errors="coerce")
    snapshots["account"] = snapshots["account"].astype(str).str.strip()
    snapshots["entry_type"] = snapshots["entry_type"].astype(str).str.strip().str.lower()
    snapshots["region"] = snapshots["region"].astype(str).str.strip().str.lower()
    snapshots["value"] = pd.to_numeric(snapshots["value"], errors="coerce")
    snapshots = snapshots.dropna(subset=["date", "account", "entry_type", "region", "value"]).copy()
    snapshots = snapshots[snapshots["account"] != ""].copy()
    if accounts is not None:
        account_set = {str(a).strip() for a in accounts if str(a).strip()}
        snapshots = snapshots[snapshots["account"].isin(account_set)].copy()
    if entry_types is not None:
        type_set = {str(t).strip().lower() for t in entry_types if str(t).strip()}
        snapshots = snapshots[snapshots["entry_type"].isin(type_set)].copy()
    start_ts = pd.to_datetime(start_date, errors="coerce") if start_date is not None else pd.NaT
    end_ts = pd.to_datetime(end_date, errors="coerce") if end_date is not None else pd.NaT
    if pd.notna(start_ts):
        snapshots = snapshots[snapshots["date"] >= pd.Timestamp(start_ts)].copy()
    if pd.notna(end_ts):
        snapshots = snapshots[snapshots["date"] <= pd.Timestamp(end_ts)].copy()

    account_list = [str(a).strip() for a in (accounts or []) if str(a).strip()]
    if not account_list:
        account_list = sorted(snapshots["account"].dropna().astype(str).unique().tolist())
    if not account_list:
        return pd.DataFrame(
            columns=[
                *snapshot_cols,
                "max_value",
                "missing_count",
                "progress_pct",
                "entry_type_label",
                "region_label",
            ]
        )

    latest = pd.DataFrame(columns=snapshot_cols)
    if not snapshots.empty:
        latest = snapshots.sort_values(["account", "entry_type", "region", "date"]).groupby(
            ["account", "entry_type", "region"],
            as_index=False,
        ).tail(1)

    grid = (
        pd.MultiIndex.from_product(
            [account_list, targets["entry_type"].unique().tolist(), targets["region"].unique().tolist()],
            names=["account", "entry_type", "region"],
        )
        .to_frame(index=False)
    )
    grid = grid.merge(targets, on=["entry_type", "region"], how="inner")
    merged = grid.merge(
        latest[["account", "entry_type", "region", "date", "value"]],
        on=["account", "entry_type", "region"],
        how="left",
    )
    merged["value"] = pd.to_numeric(merged["value"], errors="coerce").fillna(0.0)
    merged["max_value"] = pd.to_numeric(merged["max_value"], errors="coerce").fillna(0.0)
    merged["missing_count"] = (merged["max_value"] - merged["value"]).clip(lower=0)
    merged["progress_pct"] = merged.apply(
        lambda row: float(row["value"]) / float(row["max_value"]) if float(row["max_value"]) > 0 else 0.0,
        axis=1,
    )
    return merged[
        [
            "date",
            "account",
            "entry_type",
            "region",
            "value",
            "max_value",
            "missing_count",
            "progress_pct",
            "entry_type_label",
            "region_label",
        ]
    ].sort_values(["account", "entry_type", "region"]).reset_index(drop=True)


def build_pokedex_atlas_cards(
    catalog_df: pd.DataFrame,
    species_df: pd.DataFrame,
    *,
    account: object,
    entry_type: object,
    region: object | None = None,
    availability_df: pd.DataFrame | None = None,
    search: object = "",
    status_filter: object = "all",
    as_of_date: object | None = None,
) -> pd.DataFrame:
    cols = [
        "dex_number",
        "name",
        "german_name",
        "region",
        "type_1",
        "type_2",
        "sprite_url",
        "available_in_pogo",
        "category_available",
        "registered",
        "location_restriction",
        "last_event",
        "last_event_date",
        "status",
        "notes",
    ]
    if catalog_df.empty:
        return pd.DataFrame(columns=cols)
    catalog = catalog_df.copy()
    catalog["dex_number"] = pd.to_numeric(catalog["dex_number"], errors="coerce")
    catalog = catalog.dropna(subset=["dex_number"]).copy()
    catalog["dex_number"] = catalog["dex_number"].astype(int)
    region_key = str(region or "").strip().lower()
    if region_key and region_key != "overall" and "region" in catalog.columns:
        catalog = catalog[catalog["region"].astype(str).str.strip().str.lower() == region_key].copy()

    account_name = str(account).strip()
    entry = str(entry_type).strip().lower()
    targets = category_target_dex_numbers(entry, catalog_df, availability_df)
    latest = latest_pokedex_species_state(
        species_df,
        accounts=[account_name] if account_name else [],
        entry_types=[entry] if entry else [],
        as_of_date=as_of_date,
    )
    registered_map: dict[int, bool] = {}
    notes_map: dict[int, str] = {}
    if not latest.empty:
        for _, row in latest.iterrows():
            dex = int(row["dex_number"])
            registered_map[dex] = bool(row.get("registered"))
            notes_map[dex] = str(row.get("notes") or "").strip()

    cards = catalog.copy()
    cards["sprite_url"] = cards["dex_number"].map(pokemon_sprite_url)
    cards["available_in_pogo"] = cards.get("available_in_pogo", "").fillna("").astype(str)
    cards["category_available"] = cards["dex_number"].map(lambda dex: int(dex) in targets)
    cards["registered"] = cards["dex_number"].map(lambda dex: bool(registered_map.get(int(dex), False)))
    cards["notes"] = cards["dex_number"].map(lambda dex: notes_map.get(int(dex), ""))
    if "location_restriction" not in cards.columns:
        cards["location_restriction"] = cards["dex_number"].map(location_restriction_for_dex)
    else:
        cards["location_restriction"] = cards["location_restriction"].fillna("").astype(str).str.strip()
        blank = cards["location_restriction"] == ""
        cards.loc[blank, "location_restriction"] = cards.loc[blank, "dex_number"].map(location_restriction_for_dex)
    for col in ["last_event", "last_event_date", "name", "german_name", "type_1", "type_2", "region"]:
        if col not in cards.columns:
            cards[col] = ""
        cards[col] = cards[col].fillna("").astype(str).str.strip()

    def status_for_row(row: pd.Series) -> str:
        if not bool(row["category_available"]):
            return "unavailable"
        if entry == "pokemon" and not is_available_in_pogo(row.get("available_in_pogo")):
            return "unavailable"
        if bool(row["registered"]):
            return "registered"
        return "missing"

    cards["status"] = cards.apply(status_for_row, axis=1)

    query = normalize_pokemon_name(search)
    if query:
        haystack = (
            cards["name"].map(normalize_pokemon_name)
            + " "
            + cards["german_name"].map(normalize_pokemon_name)
            + " "
            + cards["dex_number"].astype(str)
        )
        cards = cards[haystack.str.contains(query, regex=False)].copy()

    status_key = str(status_filter or "all").strip().lower()
    if status_key == "missing":
        cards = cards[cards["status"] == "missing"].copy()
    elif status_key in {"registered", "caught"}:
        cards = cards[cards["status"] == "registered"].copy()
    elif status_key in {"unavailable", "not in go", "not_available"}:
        cards = cards[cards["status"] == "unavailable"].copy()
    elif status_key in {"location restricted", "restricted", "regional"}:
        cards = cards[cards["location_restriction"].astype(str).str.strip() != ""].copy()

    return cards[cols].sort_values("dex_number").reset_index(drop=True)


def pokedex_atlas_html(cards_df: pd.DataFrame) -> str:
    if cards_df.empty:
        return '<div class="pogo-dex-empty">No Pokemon match the current Atlas filters.</div>'
    parts = ['<div class="pogo-dex-grid">']
    for _, row in cards_df.iterrows():
        dex = int(row["dex_number"])
        name = escape(str(row.get("name") or ""))
        german = escape(str(row.get("german_name") or ""))
        type_1 = str(row.get("type_1") or "").strip().lower()
        type_2 = str(row.get("type_2") or "").strip().lower()
        sprite = escape(str(row.get("sprite_url") or pokemon_sprite_url(dex)), quote=True)
        status = str(row.get("status") or "missing")
        location = str(row.get("location_restriction") or "").strip()
        last_event = str(row.get("last_event") or "").strip()
        last_event_date = str(row.get("last_event_date") or "").strip()
        type_chips = "".join(
            f'<span class="pogo-dex-type pogo-dex-type--{escape(t, quote=True)}">{escape(t.title())}</span>'
            for t in [type_1, type_2]
            if t
        )
        extra_bits: list[str] = []
        if location:
            extra_bits.append(f'<span class="pogo-dex-extra">Location: {escape(location)}</span>')
        if last_event:
            event_label = escape(last_event)
            if last_event_date:
                event_label += f" ({escape(last_event_date)})"
            extra_bits.append(f'<span class="pogo-dex-extra">Last event: {event_label}</span>')
        extras = "".join(extra_bits)
        parts.append(
            (
                f'<article class="pogo-dex-card pogo-dex-card--{escape(status, quote=True)} '
                f'pogo-dex-card-type--{escape(type_1 or "normal", quote=True)}">'
                f'<img class="pogo-dex-art" src="{sprite}" alt="{name}" loading="lazy">'
                f'<div class="pogo-dex-num">#{dex:04d}</div>'
                f'<div class="pogo-dex-name">{name}</div>'
                f'<div class="pogo-dex-german">{german}</div>'
                f'<div class="pogo-dex-types">{type_chips}</div>'
                f'<div class="pogo-dex-status">{escape(status.replace("_", " ").title())}</div>'
                f"{extras}"
                "</article>"
            )
        )
    parts.append("</div>")
    return "".join(parts)


def load_species_entries_or_empty(path: Path, valid_entry_types: set[str] | None = None) -> pd.DataFrame:
    return load_pokedex_species_entries(path, valid_entry_types=valid_entry_types)


def load_category_availability_or_empty(path: Path, valid_entry_types: set[str] | None = None) -> pd.DataFrame:
    return load_pokedex_category_availability(path, valid_entry_types=valid_entry_types)
