from __future__ import annotations

import csv
import json
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

# Standard checklist columns, in the in-game Pokédex order.
# Mega and G-Max are on the same card badge, and their checkboxes use a separate entry dropdown.
ATLAS_ENTRY_KINDS: tuple[tuple[str, str], ...] = (
    ("pokemon", "Pokemon"),
    ("shiny", "Shiny"),
    ("hundo", "100%"),
    ("lucky", "Lucky"),
    ("xxl", "XXL"),
    ("xxs", "XXS"),
    ("shadow", "Shadow"),
    ("purified", "Purified"),
)
ATLAS_COMPARISON_KINDS: tuple[tuple[str, str], ...] = ATLAS_ENTRY_KINDS + (
    ("gmax", "G-Max"),
    ("mega", "Mega"),
)

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


def _positive_dex(raw: object) -> int | None:
    dex = pd.to_numeric(raw, errors="coerce")
    if pd.isna(dex) or int(dex) <= 0:
        return None
    return int(dex)


def _stripped_form(raw: object) -> str:
    if raw is None:
        return ""
    if isinstance(raw, float) and pd.isna(raw):
        return ""
    return str(raw).strip()


def _mega_form_records(payload: object) -> list[object]:
    if isinstance(payload, list):
        return list(payload)
    if not isinstance(payload, dict):
        return []
    records: list[object] = []
    for key, value in payload.items():
        if isinstance(value, dict):
            item = dict(value)
            if all(item.get(field) is None for field in ("pokemon_id", "id", "dex_number")):
                item["pokemon_id"] = key
            records.append(item)
        elif isinstance(value, list):
            records.extend(value)
    return records


def extract_mega_forms(payload: object) -> list[tuple[int, str]]:
    forms: list[tuple[int, str]] = []
    for item in _mega_form_records(payload):
        if not isinstance(item, dict):
            continue
        raw_dex = None
        for key in ("pokemon_id", "id", "dex_number"):
            if key in item and item[key] is not None:
                raw_dex = item[key]
                break
        dex = _positive_dex(raw_dex)
        if dex is None:
            continue
        forms.append((dex, _stripped_form(item.get("form", ""))))
    return forms


def _pvpoke_pokemon_records(payload: object) -> list[object]:
    if isinstance(payload, list):
        return list(payload)
    if isinstance(payload, dict):
        pokemon = payload.get("pokemon")
        if isinstance(pokemon, list):
            return list(pokemon)
    return []


def _pvpoke_species_id(item: dict[str, object]) -> str:
    return str(item.get("speciesId") or "").casefold()


def extract_pvpoke_released_dex_numbers(payload: object) -> set[int]:
    numbers: set[int] = set()
    for item in _pvpoke_pokemon_records(payload):
        if not isinstance(item, dict):
            continue
        species_id = _pvpoke_species_id(item)
        if species_id.endswith(("_mega_x", "_mega_y", "_mega")):
            continue
        dex = _positive_dex(item.get("dex"))
        if dex is None:
            continue
        numbers.add(dex)
    return numbers


def extract_pvpoke_mega_forms(payload: object) -> list[tuple[int, str]]:
    forms: set[tuple[int, str]] = set()
    for item in _pvpoke_pokemon_records(payload):
        if not isinstance(item, dict):
            continue
        species_id = _pvpoke_species_id(item)
        if species_id.endswith("_mega_x"):
            form = "X"
        elif species_id.endswith("_mega_y"):
            form = "Y"
        elif species_id.endswith("_mega"):
            form = "Normal"
        else:
            continue
        dex = _positive_dex(item.get("dex"))
        if dex is None:
            continue
        forms.add((dex, form))
    return sorted(forms, key=lambda pair: (pair[0], pair[1].casefold()))


def _game_master_templates(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, dict):
        templates = payload.get("template", payload)
    elif isinstance(payload, list):
        templates = payload
    else:
        return []
    if not isinstance(templates, list):
        return []
    return [item for item in templates if isinstance(item, dict)]


def extract_gigantamax_dex_numbers(payload: object) -> set[int]:
    """Dex numbers that have a Gigantamax form.

    Older Game Master files put GIGANTAMAX in the template id. Current files list
    those species on the sourdough move map, and the move effect name starts with
    ``gmax_``. Zacian, Zamazenta, and Eternatus are on that map for other Max
    moves, so they stay out.
    """
    templates = _game_master_templates(payload)
    numbers: set[int] = set()
    id_pattern = re.compile(r"(?:FORMS_)?V(\d{4})_POKEMON_")
    species_pattern = re.compile(r"^V(\d{4})_POKEMON_([A-Z0-9_]+)$")
    dex_by_species: dict[str, int] = {}
    vfx_by_move: dict[str, str] = {}
    sourdough_rows: list[dict[str, object]] = []
    for item in templates:
        template_id = str(item.get("templateId") or "")
        if "GIGANTAMAX" in template_id.upper():
            match = id_pattern.search(template_id)
            if match:
                dex_number = int(match.group(1))
                if 1 <= dex_number <= 1025:
                    numbers.add(dex_number)
        species_match = species_pattern.match(template_id)
        if species_match:
            dex_by_species.setdefault(species_match.group(2), int(species_match.group(1)))
        data = item.get("data")
        if not isinstance(data, dict):
            data = item
        move = data.get("moveSettings") if isinstance(data, dict) else None
        if isinstance(move, dict):
            move_id = str(move.get("movementId") or "")
            if move_id:
                vfx_by_move[move_id] = str(move.get("vfxName") or "")
        settings = data.get("sourdoughMoveMappingSettings") if isinstance(data, dict) else None
        mappings = settings.get("mappings") if isinstance(settings, dict) else None
        if isinstance(mappings, list):
            sourdough_rows.extend(row for row in mappings if isinstance(row, dict))
    for row in sourdough_rows:
        vfx_name = vfx_by_move.get(str(row.get("move") or ""), "")
        if not vfx_name.lower().startswith("gmax_"):
            continue
        species = str(row.get("pokemonId") or "").strip().upper()
        dex_number = dex_by_species.get(species)
        if dex_number is None or not 1 <= dex_number <= 1025:
            continue
        numbers.add(dex_number)
    return numbers


def build_category_availability_rows(
    *,
    shiny_dex: set[int] | None = None,
    shadow_dex: set[int] | None = None,
    mega_dex: set[int] | None = None,
    gmax_dex: set[int] | None = None,
    mega_forms: Sequence[tuple[int, str]] | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    def add_row(entry_type: str, dex: int, form: str) -> None:
        rows.append(
            {
                "entry_type": entry_type,
                "dex_number": int(dex),
                "form": form,
                "available": True,
                "notes": "",
            }
        )

    for entry_type, numbers in (
        ("shiny", shiny_dex or set()),
        ("shadow", shadow_dex or set()),
    ):
        for dex in sorted(numbers):
            add_row(entry_type, int(dex), "")

    if mega_forms is None:
        for dex in sorted(mega_dex or set()):
            add_row("mega", int(dex), "")
    else:
        normalized_forms: list[tuple[int, str]] = []
        for dex, form in mega_forms:
            dex_number = _positive_dex(dex)
            if dex_number is None:
                continue
            normalized_forms.append((dex_number, _stripped_form(form)))
        normalized_forms.sort(key=lambda pair: (pair[0], pair[1].casefold()))
        for dex_number, form_text in normalized_forms:
            add_row("mega", dex_number, form_text)

    for dex in sorted(gmax_dex or set()):
        add_row("gmax", int(dex), "")

    if not rows:
        return pd.DataFrame(columns=POKEDEX_CATEGORY_AVAILABILITY_COLUMNS)
    return pd.DataFrame(rows, columns=POKEDEX_CATEGORY_AVAILABILITY_COLUMNS)


def _with_species_form(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "form" not in out.columns:
        out["form"] = ""
    out["form"] = out["form"].fillna("").astype(str).str.strip()
    out["_form_key"] = out["form"].str.casefold()
    return out


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
    rows = _with_species_form(rows)

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
    latest = rows.sort_values(["account", "entry_type", "dex_number", "_form_key", "date"]).groupby(
        ["account", "entry_type", "dex_number", "_form_key"],
        as_index=False,
    ).tail(1)
    return latest[cols].sort_values(["account", "entry_type", "dex_number", "form"]).reset_index(drop=True)


def upsert_pokedex_species_rows(path: Path, rows: list[dict[str, object]]) -> int:
    if not rows:
        return 0
    new_df = pd.DataFrame(rows)
    for col in POKEDEX_SPECIES_ENTRY_COLUMNS:
        if col not in new_df.columns:
            if col in {"registered", "can_evolve_now"}:
                new_df[col] = False
            elif col in {"notes", "form"}:
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
    new_df = _with_species_form(new_df)
    new_df = new_df.drop_duplicates(
        subset=["date", "account", "entry_type", "dex_number", "_form_key"],
        keep="last",
    )
    new_df = new_df.drop(columns=["_form_key"])
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
    combined = _with_species_form(combined)
    combined = combined.sort_values(["account", "entry_type", "dex_number", "_form_key", "date"]).drop_duplicates(
        subset=["date", "account", "entry_type", "dex_number", "_form_key"],
        keep="last",
    )
    combined = combined.drop(columns=["_form_key"])
    combined = combined.sort_values(["date", "account", "entry_type", "dex_number", "form"]).reset_index(drop=True)
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


def _ordered_unique_text(values: Sequence[object] | None) -> list[str]:
    if not values:
        return []
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _selected_atlas_kinds(entry_types: Sequence[object] | None) -> list[tuple[str, str]]:
    if entry_types is None:
        return list(ATLAS_ENTRY_KINDS)
    requested = {str(item).strip().lower() for item in entry_types if str(item).strip()}
    return [(kind, label) for kind, label in ATLAS_ENTRY_KINDS if kind in requested]


def _prepare_atlas_catalog(catalog_df: pd.DataFrame, regions: Sequence[object] | None) -> pd.DataFrame:
    if catalog_df.empty or "dex_number" not in catalog_df.columns:
        columns = list(catalog_df.columns) if len(getattr(catalog_df, "columns", [])) else ["dex_number"]
        return pd.DataFrame(columns=columns)
    catalog = catalog_df.copy()
    catalog["dex_number"] = pd.to_numeric(catalog["dex_number"], errors="coerce")
    catalog = catalog.dropna(subset=["dex_number"]).copy()
    if catalog.empty:
        return catalog
    catalog["dex_number"] = catalog["dex_number"].astype(int)
    if regions is not None and "region" in catalog.columns:
        region_set = {
            str(region).strip().lower()
            for region in regions
            if str(region).strip() and str(region).strip().lower() != "overall"
        }
        if region_set:
            catalog = catalog[catalog["region"].astype(str).str.strip().str.lower().isin(region_set)].copy()
    return catalog


def _in_go_dex_numbers(catalog: pd.DataFrame) -> set[int]:
    if catalog.empty or "dex_number" not in catalog.columns or "available_in_pogo" not in catalog.columns:
        return set()
    available = catalog["available_in_pogo"].map(is_available_in_pogo).astype(bool)
    return set(catalog.loc[available, "dex_number"].astype(int).tolist())


def _atlas_targets_by_kind(
    catalog: pd.DataFrame,
    availability_df: pd.DataFrame | None,
    kinds: Sequence[str],
) -> dict[str, set[int]]:
    in_go = _in_go_dex_numbers(catalog)
    if catalog.empty or "dex_number" not in catalog.columns:
        catalog_dex: set[int] = set()
    else:
        catalog_dex = set(catalog["dex_number"].astype(int).tolist())
    targets: dict[str, set[int]] = {}
    for kind in kinds:
        raw = category_target_dex_numbers(kind, catalog, availability_df)
        targets[str(kind)] = {int(dex) for dex in raw if int(dex) in catalog_dex and int(dex) in in_go}
    return targets


_SPECIES_MISSING_SUMMARY_COLUMNS = [
    "account",
    "entry_type",
    "entry_type_label",
    "target_count",
    "registered_count",
    "missing_count",
]


def _registered_dex_by_account_kind(
    species_df: pd.DataFrame,
    accounts: Sequence[str],
    kinds: Sequence[str],
    targets_by_kind: dict[str, set[int]],
    as_of_date: object | None,
) -> dict[tuple[str, str], set[int]]:
    found: dict[tuple[str, str], set[int]] = {}
    if not accounts or not kinds:
        return found
    latest = latest_pokedex_species_state(
        species_df,
        accounts=list(accounts),
        entry_types=list(kinds),
        as_of_date=as_of_date,
    )
    if latest.empty:
        return found
    registered_rows = latest[latest["registered"] == True]  # noqa: E712
    for row in registered_rows.itertuples(index=False):
        account_name = str(row.account)
        kind = str(row.entry_type)
        dex = int(row.dex_number)
        if dex not in targets_by_kind.get(kind, set()):
            continue
        found.setdefault((account_name, kind), set()).add(dex)
    return found


def build_species_missing_summary(
    catalog_df: pd.DataFrame,
    species_df: pd.DataFrame,
    *,
    accounts: Sequence[object],
    regions: Sequence[object] | None = None,
    availability_df: pd.DataFrame | None = None,
    as_of_date: object | None = None,
    entry_types: Sequence[object] | None = None,
) -> pd.DataFrame:
    columns = list(_SPECIES_MISSING_SUMMARY_COLUMNS)
    empty = pd.DataFrame(columns=columns)
    account_list = _ordered_unique_text(accounts)
    if not account_list or catalog_df.empty or "dex_number" not in catalog_df.columns:
        return empty
    base = _prepare_atlas_catalog(catalog_df, None)
    if base.empty:
        return empty
    kinds = _selected_atlas_kinds(entry_types)
    if not kinds:
        return empty
    catalog = _prepare_atlas_catalog(base, regions)
    kind_ids = [kind for kind, _label in kinds]
    targets = _atlas_targets_by_kind(catalog, availability_df, kind_ids)
    registered = _registered_dex_by_account_kind(species_df, account_list, kind_ids, targets, as_of_date)
    rows: list[dict[str, object]] = []
    for account_name in account_list:
        for kind, label in kinds:
            target_count = len(targets.get(kind, set()))
            registered_count = len(registered.get((account_name, kind), set()))
            rows.append(
                {
                    "account": account_name,
                    "entry_type": kind,
                    "entry_type_label": label,
                    "target_count": target_count,
                    "registered_count": registered_count,
                    "missing_count": max(target_count - registered_count, 0),
                }
            )
    summary = pd.DataFrame(rows, columns=columns)
    for column in ("target_count", "registered_count", "missing_count"):
        summary[column] = summary[column].astype(int)
    return summary


def mega_badge_label(form: object) -> str:
    token = str(form or "").strip()
    if not token or token.casefold() == "normal":
        return "Mega"
    return f"Mega {token}"


def _checked_state(value: object) -> bool | None:
    if value is None or value is pd.NA:
        return None
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return None
    if isinstance(missing, bool) and missing:
        return None
    return bool(value)


def _available_form_map(availability_df: pd.DataFrame | None, entry_type: str) -> dict[int, list[str]]:
    found: dict[int, list[str]] = {}
    if availability_df is None or availability_df.empty:
        return found
    if not {"entry_type", "dex_number", "available"}.issubset(availability_df.columns):
        return found
    rows = availability_df.copy()
    rows["entry_type"] = rows["entry_type"].astype(str).str.strip().str.lower()
    rows = rows[rows["entry_type"] == str(entry_type).strip().lower()].copy()
    if rows.empty:
        return found
    if "form" not in rows.columns:
        rows["form"] = ""
    rows["form"] = rows["form"].fillna("").astype(str).str.strip()
    rows["dex_number"] = pd.to_numeric(rows["dex_number"], errors="coerce")
    rows = rows.dropna(subset=["dex_number"]).copy()
    available = rows["available"].map(lambda value: value if isinstance(value, bool) else parse_bool_text(value))
    rows = rows[available.astype(bool)].copy()
    for dex_number, form in zip(rows["dex_number"].astype(int).tolist(), rows["form"].tolist(), strict=True):
        forms = found.setdefault(int(dex_number), [])
        if form not in forms:
            forms.append(form)
    for forms in found.values():
        forms.sort(key=str.casefold)
    return found


def _registration_index(
    species_df: pd.DataFrame,
    account: str,
    kinds: Sequence[str],
    as_of_date: object | None,
) -> dict[tuple[str, int, str], bool]:
    index: dict[tuple[str, int, str], bool] = {}
    if not account or not kinds:
        return index
    latest = latest_pokedex_species_state(
        species_df,
        accounts=[account],
        entry_types=list(kinds),
        as_of_date=as_of_date,
    )
    if latest.empty:
        return index
    for row in latest.itertuples(index=False):
        form = str(getattr(row, "form", "") or "").strip().casefold()
        index[(str(row.entry_type), int(row.dex_number), form)] = bool(row.registered)
    return index


def _legacy_kind_state(status_filter: object) -> tuple[str, str]:
    status_key = str(status_filter or "all").strip().lower()
    if status_key == "missing":
        return "any", "missing"
    if status_key in {"registered", "caught", "existing"}:
        return "any", "registered"
    if status_key in {"unavailable", "not in go", "not_available", "not available"}:
        return "any", "unavailable"
    if status_key in {"location restricted", "restricted", "regional"}:
        return "any", "restricted"
    return "any", "any"


def _alias_kind(value: object) -> str:
    text = str(value or "any").strip().lower()
    aliases = {
        "": "any",
        "all": "any",
        "100%": "hundo",
        "100": "hundo",
        "g-max": "gmax",
        "gigantamax": "gmax",
    }
    return aliases.get(text, text)


def _alias_state(value: object) -> str:
    text = str(value or "any").strip().lower()
    aliases = {
        "": "any",
        "all": "any",
        "existing": "registered",
        "caught": "registered",
        "not available": "unavailable",
        "not in go": "unavailable",
        "not_available": "unavailable",
        "location restricted": "restricted",
        "regional": "restricted",
    }
    return aliases.get(text, text)


def _resolved_kind_state(
    kind_filter: object | None,
    state_filter: object | None,
    status_filter: object,
) -> tuple[str, str]:
    if kind_filter is None and state_filter is None:
        return _legacy_kind_state(status_filter)
    return _alias_kind(kind_filter), _alias_state(state_filter)


_COMPARISON_COLUMNS = [
    "entry_type",
    "entry_type_label",
    "snapshot_value",
    "atlas_count",
    "max_value",
    "gap",
]


def _latest_snapshot_values(
    snapshots_df: pd.DataFrame | None,
    account: str,
    region: str,
    as_of_date: object | None,
) -> dict[str, int]:
    if snapshots_df is None or snapshots_df.empty:
        return {}
    required = {"date", "account", "entry_type", "region", "value"}
    if not required.issubset(snapshots_df.columns):
        return {}
    rows = snapshots_df.loc[:, list(required)].copy()
    rows["date"] = pd.to_datetime(rows["date"], errors="coerce")
    rows["account"] = rows["account"].astype(str).str.strip()
    rows["entry_type"] = rows["entry_type"].astype(str).str.strip().str.lower()
    rows["region"] = rows["region"].astype(str).str.strip().str.lower()
    rows["value"] = pd.to_numeric(rows["value"], errors="coerce")
    rows = rows.dropna(subset=["date", "value"]).copy()
    rows = rows[(rows["account"] == account) & (rows["region"] == region)].copy()
    as_of = pd.to_datetime(as_of_date, errors="coerce") if as_of_date is not None else pd.NaT
    if pd.notna(as_of):
        rows = rows[rows["date"] <= pd.Timestamp(as_of)].copy()
    if rows.empty:
        return {}
    latest = rows.sort_values("date").groupby("entry_type", as_index=False).tail(1)
    values: dict[str, int] = {}
    for row in latest.itertuples(index=False):
        number = float(row.value)
        values[str(row.entry_type)] = int(number) if number == int(number) else int(number)
    return values


def _config_max_values(config_df: pd.DataFrame | None, region: str) -> dict[str, int]:
    if config_df is None or config_df.empty or not {"entry_type", "region", "max_value"}.issubset(config_df.columns):
        return {}
    rows = config_df.copy()
    rows["entry_type"] = rows["entry_type"].astype(str).str.strip().str.lower()
    rows["region"] = rows["region"].astype(str).str.strip().str.lower()
    rows["max_value"] = pd.to_numeric(rows["max_value"], errors="coerce")
    rows = rows[(rows["region"] == region) & rows["max_value"].notna()].copy()
    values: dict[str, int] = {}
    for row in rows.itertuples(index=False):
        number = float(row.max_value)
        values[str(row.entry_type)] = int(number) if number == int(number) else int(number)
    return values


def build_atlas_snapshot_comparison(
    catalog_df: pd.DataFrame,
    species_df: pd.DataFrame,
    snapshots_df: pd.DataFrame | None,
    config_df: pd.DataFrame | None,
    *,
    account: object,
    region: object,
    availability_df: pd.DataFrame | None = None,
    as_of_date: object | None = None,
    entry_type_labels: dict[str, str] | None = None,
) -> pd.DataFrame:
    columns = list(_COMPARISON_COLUMNS)
    empty = pd.DataFrame(columns=columns)
    account_name = str(account or "").strip()
    region_key = str(region or "").strip().lower()
    if not account_name or catalog_df.empty or "dex_number" not in catalog_df.columns:
        return empty
    region_filter = None if not region_key or region_key == "overall" else [region_key]
    catalog = _prepare_atlas_catalog(catalog_df, region_filter)
    if catalog.empty:
        return empty
    in_go = _in_go_dex_numbers(catalog)
    catalog_dex = set(catalog["dex_number"].astype(int).tolist())
    kind_ids = [kind for kind, _label in ATLAS_COMPARISON_KINDS]
    targets = _atlas_targets_by_kind(catalog, availability_df, [kind for kind, _label in ATLAS_COMPARISON_KINDS if kind != "mega"])
    registered = _registration_index(species_df, account_name, kind_ids, as_of_date)
    mega_forms = _available_form_map(availability_df, "mega")
    snapshots = _latest_snapshot_values(snapshots_df, account_name, region_key, as_of_date)
    maximums = _config_max_values(config_df, region_key)
    labels = entry_type_labels or {}
    rows: list[dict[str, object]] = []
    for kind, fallback_label in ATLAS_COMPARISON_KINDS:
        if kind == "mega":
            atlas_count = 0
            for dex, forms in mega_forms.items():
                if dex not in catalog_dex or dex not in in_go:
                    continue
                for form in forms:
                    if registered.get((kind, dex, form.casefold()), False):
                        atlas_count += 1
        else:
            atlas_count = sum(
                1
                for dex in targets.get(kind, set())
                if registered.get((kind, int(dex), ""), False)
            )
        snapshot_value = snapshots.get(kind)
        max_value = maximums.get(kind)
        gap = None if snapshot_value is None else int(snapshot_value) - int(atlas_count)
        rows.append(
            {
                "entry_type": kind,
                "entry_type_label": labels.get(kind, fallback_label),
                "snapshot_value": snapshot_value,
                "atlas_count": int(atlas_count),
                "max_value": max_value,
                "gap": gap,
            }
        )
    comparison = pd.DataFrame(rows, columns=columns)
    for column in ("snapshot_value", "atlas_count", "max_value", "gap"):
        comparison[column] = pd.array(
            [_nullable_int(value) for value in comparison[column].tolist()],
            dtype="Int64",
        )
    return comparison


def _nullable_int(value: object) -> object:
    if value is None or value is pd.NA:
        return pd.NA
    try:
        if bool(pd.isna(value)):
            return pd.NA
    except (TypeError, ValueError):
        return pd.NA
    return int(value)


def _atlas_card_columns() -> list[str]:
    return [
        "dex_number",
        "name",
        "german_name",
        "region",
        "type_1",
        "type_2",
        "sprite_url",
        "available_in_pogo",
        "release_override",
        "category_available",
        "registered",
        "location_restriction",
        "last_event",
        "last_event_date",
        "status",
        "status_label",
        "missing_kinds",
        "notes",
        "mega_forms",
        "registered_mega_forms",
        "registered_mega",
        "registered_gmax",
        *[f"registered_{kind}" for kind, _label in ATLAS_ENTRY_KINDS],
    ]


_MANUAL_RELEASE_SUFFIX = " · Manual"


def _normalize_release_overrides(release_overrides: dict[int, str] | None) -> dict[int, str]:
    if not release_overrides:
        return {}
    normalized: dict[int, str] = {}
    for key, value in release_overrides.items():
        if isinstance(key, bool):
            continue
        try:
            dex = int(key)
        except (TypeError, ValueError):
            continue
        text = str(value or "").strip().casefold()
        if text in {"yes", "no"}:
            normalized[dex] = text
    return normalized


def build_pokedex_atlas_cards(
    catalog_df: pd.DataFrame,
    species_df: pd.DataFrame,
    *,
    account: object,
    region: object | None = None,
    availability_df: pd.DataFrame | None = None,
    search: object = "",
    status_filter: object = "all",
    kind_filter: object | None = None,
    state_filter: object | None = None,
    as_of_date: object | None = None,
    entry_type: object | None = None,
    release_overrides: dict[int, str] | None = None,
) -> pd.DataFrame:
    # entry_type is ignored. kind_filter and state_filter select cards.
    # When both are omitted, status_filter keeps the previous single-status behavior.
    _ = entry_type
    cols = _atlas_card_columns()
    normalized_overrides = _normalize_release_overrides(release_overrides)
    if catalog_df.empty or "dex_number" not in catalog_df.columns:
        return pd.DataFrame(columns=cols)
    region_key = str(region or "").strip().lower()
    region_filter = None if not region_key or region_key == "overall" else [region_key]
    catalog = _prepare_atlas_catalog(catalog_df, region_filter)
    if catalog.empty:
        return pd.DataFrame(columns=cols)

    kind_ids = [kind for kind, _label in ATLAS_ENTRY_KINDS]
    targets = _atlas_targets_by_kind(catalog, availability_df, kind_ids)
    account_name = str(account).strip()
    latest = latest_pokedex_species_state(
        species_df,
        accounts=[account_name] if account_name else [],
        entry_types=[*kind_ids, "mega", "gmax"],
        as_of_date=as_of_date,
    )
    registered_by_kind = {kind: set() for kind in kind_ids}
    registered_mega: dict[int, set[str]] = {}
    registered_gmax: set[int] = set()
    notes_map: dict[int, str] = {}
    if not latest.empty:
        for row in latest.itertuples(index=False):
            dex = int(row.dex_number)
            kind = str(row.entry_type)
            form_key = str(getattr(row, "form", "") or "").strip().casefold()
            if kind == "pokemon" and form_key == "":
                notes_map[dex] = str(getattr(row, "notes", "") or "").strip()
            if bool(row.registered) and kind in registered_by_kind and form_key == "":
                registered_by_kind[kind].add(dex)
            if bool(row.registered) and kind == "mega":
                registered_mega.setdefault(dex, set()).add(form_key)
            if bool(row.registered) and kind == "gmax" and form_key == "":
                registered_gmax.add(dex)
    mega_forms_by_dex = _available_form_map(availability_df, "mega")
    gmax_by_dex = _available_form_map(availability_df, "gmax")

    cards = catalog.copy()
    cards["sprite_url"] = cards["dex_number"].map(pokemon_sprite_url)
    if "available_in_pogo" in cards.columns:
        in_go = cards["available_in_pogo"].map(is_available_in_pogo).astype(bool)
    else:
        in_go = pd.Series(False, index=cards.index)
        cards["available_in_pogo"] = ""
    cards["available_in_pogo"] = cards["available_in_pogo"].fillna("").astype(str)
    cards["notes"] = cards["dex_number"].map(lambda dex: notes_map.get(int(dex), "")).fillna("")
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

    statuses: list[str] = []
    status_labels: list[str] = []
    release_override_values: list[str] = []
    missing_kind_values: list[str] = []
    category_available: list[bool] = []
    per_kind_values: dict[str, list[object]] = {kind: [] for kind in kind_ids}
    mega_form_values: list[str] = []
    registered_mega_form_values: list[str] = []
    registered_mega_values: list[object] = []
    registered_gmax_values: list[object] = []
    form_search_values: list[str] = []
    for dex, species_in_go in zip(cards["dex_number"].astype(int).tolist(), in_go.tolist(), strict=True):
        missing_labels: list[str] = []
        available_kinds = 0
        registered_kinds = 0
        for kind, label in ATLAS_ENTRY_KINDS:
            kind_available = bool(species_in_go) and dex in targets.get(kind, set())
            if not kind_available:
                per_kind_values[kind].append(pd.NA)
                continue
            available_kinds += 1
            is_registered = dex in registered_by_kind[kind]
            per_kind_values[kind].append(bool(is_registered))
            if is_registered:
                registered_kinds += 1
            else:
                missing_labels.append(label)
        species_mega_forms = list(mega_forms_by_dex.get(dex, [])) if species_in_go else []
        registered_forms = [
            form for form in species_mega_forms if form.casefold() in registered_mega.get(dex, set())
        ]
        if species_mega_forms:
            available_kinds += len(species_mega_forms)
            registered_kinds += len(registered_forms)
            for form in species_mega_forms:
                if form not in registered_forms:
                    missing_labels.append(mega_badge_label(form))
            registered_mega_values.append(len(registered_forms) == len(species_mega_forms))
        else:
            registered_mega_values.append(pd.NA)
        gmax_available = bool(species_in_go) and dex in gmax_by_dex
        if gmax_available:
            available_kinds += 1
            if dex in registered_gmax:
                registered_kinds += 1
                registered_gmax_values.append(True)
            else:
                missing_labels.append("G-Max")
                registered_gmax_values.append(False)
        else:
            registered_gmax_values.append(pd.NA)
        mega_form_values.append(json.dumps(species_mega_forms))
        registered_mega_form_values.append(json.dumps(registered_forms))
        search_bits = [mega_badge_label(form) for form in species_mega_forms]
        if gmax_available:
            search_bits.append("G-Max")
        form_search_values.append(" ".join(search_bits))
        pokemon_available = bool(species_in_go) and dex in targets.get("pokemon", set())
        if not species_in_go:
            status = "unavailable"
            status_label = "Not in GO"
            missing_text = ""
        elif pokemon_available and available_kinds > 0 and registered_kinds == available_kinds:
            status = "registered"
            status_label = "Registered"
            missing_text = ""
        else:
            status = "missing"
            missing_text = ", ".join(missing_labels)
            status_label = f"Missing: {missing_text}" if missing_text else "Missing"
        override = normalized_overrides.get(dex, "")
        if override and not status_label.endswith(_MANUAL_RELEASE_SUFFIX):
            status_label = f"{status_label}{_MANUAL_RELEASE_SUFFIX}"
        statuses.append(status)
        status_labels.append(status_label)
        release_override_values.append(override)
        missing_kind_values.append(missing_text)
        category_available.append(bool(available_kinds))

    cards["status"] = statuses
    cards["status_label"] = status_labels
    cards["release_override"] = release_override_values
    cards["missing_kinds"] = missing_kind_values
    cards["category_available"] = category_available
    cards["registered"] = [status == "registered" for status in statuses]
    cards["mega_forms"] = mega_form_values
    cards["registered_mega_forms"] = registered_mega_form_values
    cards["registered_mega"] = pd.array(registered_mega_values, dtype="boolean")
    cards["registered_gmax"] = pd.array(registered_gmax_values, dtype="boolean")
    cards["form_search"] = form_search_values
    for kind in kind_ids:
        cards[f"registered_{kind}"] = pd.array(per_kind_values[kind], dtype="boolean")

    query = normalize_pokemon_name(search)
    if query:
        haystack = (
            cards["name"].map(normalize_pokemon_name)
            + " "
            + cards["german_name"].map(normalize_pokemon_name)
            + " "
            + cards["dex_number"].astype(str)
            + " "
            + cards["form_search"].map(normalize_pokemon_name)
        )
        cards = cards[haystack.str.contains(query, regex=False)].copy()

    kind_key, state_key = _resolved_kind_state(kind_filter, state_filter, status_filter)
    cards = _filter_atlas_cards(cards, kind_key, state_key)
    return cards[cols].sort_values("dex_number").reset_index(drop=True)


def filter_atlas_cards_by_release(cards: pd.DataFrame, release_filter: object) -> pd.DataFrame:
    if cards.empty:
        return cards
    key = str(release_filter or "").strip().casefold().replace("_", " ")
    if key in {"in go", "yes"}:
        return cards.loc[_atlas_released_mask(cards)].copy()
    if key in {"not in go", "no"}:
        return cards.loc[~_atlas_released_mask(cards)].copy()
    if key in {"manual override", "manual", "override"}:
        if "release_override" not in cards.columns:
            return cards.iloc[0:0].copy()
        flag = cards["release_override"].map(lambda value: str(value or "").strip().casefold())
        return cards.loc[flag.isin(["yes", "no"])].copy()
    return cards


def _atlas_released_mask(cards: pd.DataFrame) -> pd.Series:
    if "available_in_pogo" not in cards.columns:
        return pd.Series(False, index=cards.index)
    return cards["available_in_pogo"].map(is_available_in_pogo).astype(bool)


def _filter_atlas_cards(cards: pd.DataFrame, kind: str, state: str) -> pd.DataFrame:
    if cards.empty or (kind == "any" and state == "any"):
        return cards
    if state == "restricted":
        mask = cards["location_restriction"].astype(str).str.strip() != ""
        if kind != "any":
            mask = mask & _kind_state_mask(cards, kind, "available")
        return cards[mask].copy()
    if kind == "any":
        if state == "missing":
            return cards[cards["status"] == "missing"].copy()
        if state == "registered":
            return cards[cards["status"] == "registered"].copy()
        if state == "unavailable":
            return cards[cards["status"] == "unavailable"].copy()
        return cards
    return cards[_kind_state_mask(cards, kind, state)].copy()


def _kind_registered_column(kind: str) -> str:
    if kind == "mega":
        return "registered_mega"
    if kind == "gmax":
        return "registered_gmax"
    return f"registered_{kind}"


def _kind_state_mask(cards: pd.DataFrame, kind: str, state: str) -> pd.Series:
    column = _kind_registered_column(kind)
    if column not in cards.columns:
        return pd.Series(False, index=cards.index)
    states = cards[column].map(_checked_state)
    if state == "missing":
        return states.map(lambda item: item is False)
    if state in {"registered", "existing"}:
        return states.map(lambda item: item is True)
    if state in {"unavailable", "not available"}:
        return states.map(lambda item: item is None)
    if state in {"any", "available"}:
        return states.map(lambda item: item is not None)
    return pd.Series(False, index=cards.index)


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
        status = str(row.get("status") or "missing").strip() or "missing"
        badge = str(row.get("status_label") or "").strip()
        if not badge:
            badge = status.replace("_", " ").title()
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
                f'<div class="pogo-dex-status">{escape(badge)}</div>'
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
