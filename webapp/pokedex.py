from __future__ import annotations

import csv
import json
import re
from collections import deque
from collections.abc import Sequence
from datetime import date
from html import escape
from pathlib import Path

import pandas as pd

from webapp.category_release import effective_category_availability
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
# Kinds another account can trade in. Shadow, 100%, and Mega are not tradeable.
TRADE_ENTRY_KINDS: tuple[tuple[str, str], ...] = (
    ("pokemon", "Pokemon"),
    ("shiny", "Shiny"),
    ("lucky", "Lucky"),
    ("xxl", "XXL"),
    ("xxs", "XXS"),
    ("purified", "Purified"),
    ("gmax", "G-Max"),
)
# g-max and gigantamax select G-Max. 100% is hundo and is intentionally absent.
_TRADE_KIND_ALIASES: dict[str, str] = {
    "g-max": "gmax",
    "gigantamax": "gmax",
}
ATLAS_COMPARISON_KINDS: tuple[tuple[str, str], ...] = ATLAS_ENTRY_KINDS + (
    ("gmax", "G-Max"),
    ("mega", "Mega"),
)
# Catalog regions that participate in species counts. Snapshot-only buckets such as
# "unidentified" are intentionally absent so All is the sum of these columns.
_CATALOG_COUNT_REGIONS: tuple[str, ...] = (
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


def _atlas_registered_is_blank(value: object) -> bool:
    if value is None or value is pd.NA:
        return True
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return isinstance(missing, bool) and missing


def _atlas_bool_from_checkbox(value: object) -> bool:
    return False if _atlas_registered_is_blank(value) else bool(value)


def _atlas_previous_caught(card: pd.Series, column: str) -> bool:
    if column not in card.index:
        return False
    raw = card[column]
    if _atlas_registered_is_blank(raw):
        return False
    return bool(raw)


def _atlas_json_form_list(raw: object) -> list[str]:
    try:
        loaded = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    return [str(item).strip() for item in loaded]


def _atlas_available_kinds_by_dex(cards: pd.DataFrame) -> dict[int, set[str]]:
    available: dict[int, set[str]] = {}
    for _, card in cards.iterrows():
        dex_number = pd.to_numeric(card.get("dex_number"), errors="coerce")
        if pd.isna(dex_number):
            continue
        kinds: set[str] = set()
        for kind_id, _label in ATLAS_ENTRY_KINDS:
            column = f"registered_{kind_id}"
            raw = card[column] if column in card.index else pd.NA
            if not _atlas_registered_is_blank(raw):
                kinds.add(kind_id)
        available[int(dex_number)] = kinds
    return available


def _pokedex_species_entry_row(
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


def species_rows_delta_from_atlas_editor(
    cards: pd.DataFrame,
    edited: pd.DataFrame,
    *,
    account: object,
    save_date: date,
    entry_mode: str = "standard",
) -> list[dict[str, object]]:
    mode = str(entry_mode or "standard").strip().lower()
    cards_by_dex: dict[int, pd.Series] = {}
    for _, card in cards.iterrows():
        dex_number = pd.to_numeric(card.get("dex_number"), errors="coerce")
        if pd.isna(dex_number):
            continue
        cards_by_dex[int(dex_number)] = card

    if mode == "mega":
        rows: list[dict[str, object]] = []
        for _, row in edited.iterrows():
            dex_number = pd.to_numeric(row.get("Dex"), errors="coerce")
            if pd.isna(dex_number):
                continue
            dex = int(dex_number)
            card = cards_by_dex.get(dex)
            if card is None:
                continue
            registered_forms = {form.casefold() for form in _atlas_json_form_list(card.get("registered_mega_forms"))}
            form = str(row.get("Form") or "").strip()
            edited_registered = _atlas_bool_from_checkbox(row["Registered"] if "Registered" in row.index else False)
            card_registered = form.casefold() in registered_forms
            if edited_registered == card_registered:
                continue
            rows.append(
                _pokedex_species_entry_row(
                    save_date=save_date,
                    account=account,
                    entry_type="mega",
                    dex_number=dex,
                    form=form,
                    registered=edited_registered,
                )
            )
        return rows

    if mode == "gmax":
        rows = []
        for _, row in edited.iterrows():
            dex_number = pd.to_numeric(row.get("Dex"), errors="coerce")
            if pd.isna(dex_number):
                continue
            dex = int(dex_number)
            card = cards_by_dex.get(dex)
            if card is None or _atlas_registered_is_blank(card.get("registered_gmax")):
                continue
            edited_registered = _atlas_bool_from_checkbox(row["Registered"] if "Registered" in row.index else False)
            card_registered = bool(card.get("registered_gmax"))
            if edited_registered == card_registered:
                continue
            rows.append(
                _pokedex_species_entry_row(
                    save_date=save_date,
                    account=account,
                    entry_type="gmax",
                    dex_number=dex,
                    form="",
                    registered=edited_registered,
                )
            )
        return rows

    available_by_dex = _atlas_available_kinds_by_dex(cards)
    rows = []
    for _, row in edited.iterrows():
        dex_number = pd.to_numeric(row.get("Dex"), errors="coerce")
        if pd.isna(dex_number):
            continue
        dex = int(dex_number)
        card = cards_by_dex.get(dex)
        if card is None:
            continue
        available = available_by_dex.get(dex, set())
        for kind_id, label in ATLAS_ENTRY_KINDS:
            if kind_id not in available:
                continue
            column = f"registered_{kind_id}"
            card_raw = card[column] if column in card.index else pd.NA
            card_registered = _atlas_bool_from_checkbox(card_raw)
            edited_registered = _atlas_bool_from_checkbox(row[label] if label in row.index else False)
            if edited_registered == card_registered:
                continue
            rows.append(
                _pokedex_species_entry_row(
                    save_date=save_date,
                    account=account,
                    entry_type=kind_id,
                    dex_number=dex,
                    form="",
                    registered=edited_registered,
                )
            )
    return rows


def species_rows_from_card_registration(
    card: pd.Series,
    *,
    account: object,
    save_date: date,
    kind_values: dict[str, bool],
    mega_values: dict[str, bool] | None = None,
    gmax_value: bool | None = None,
) -> list[dict[str, object]]:
    cards = pd.DataFrame([card])
    dex_number = pd.to_numeric(card.get("dex_number"), errors="coerce")
    if pd.isna(dex_number):
        return []
    dex = int(dex_number)
    name = str(card.get("name") or "")

    edited_row: dict[str, object] = {"Dex": dex}
    for kind_id, label in ATLAS_ENTRY_KINDS:
        if kind_id in kind_values:
            edited_row[label] = bool(kind_values[kind_id])
        else:
            column = f"registered_{kind_id}"
            raw = card[column] if column in card.index else pd.NA
            edited_row[label] = _atlas_bool_from_checkbox(raw)
    rows = species_rows_delta_from_atlas_editor(
        cards,
        pd.DataFrame([edited_row]),
        account=account,
        save_date=save_date,
        entry_mode="standard",
    )

    if mega_values is not None:
        registered_forms = {form.casefold() for form in _atlas_json_form_list(card.get("registered_mega_forms"))}
        mega_records: list[dict[str, object]] = []
        for form in _atlas_json_form_list(card.get("mega_forms")):
            if form in mega_values:
                registered = bool(mega_values[form])
            else:
                registered = form.casefold() in registered_forms
            mega_records.append({"Dex": dex, "Name": name, "Form": form, "Registered": registered})
        rows.extend(
            species_rows_delta_from_atlas_editor(
                cards,
                pd.DataFrame(mega_records, columns=["Dex", "Name", "Form", "Registered"]),
                account=account,
                save_date=save_date,
                entry_mode="mega",
            )
        )
        listed_forms = {form.casefold() for form in _atlas_json_form_list(card.get("mega_forms"))}
        for form, value in mega_values.items():
            token = str(form).strip()
            if token.casefold() in listed_forms or not bool(value):
                continue
            rows.append(
                _pokedex_species_entry_row(
                    save_date=save_date,
                    account=account,
                    entry_type="mega",
                    dex_number=dex,
                    form=token,
                    registered=True,
                )
            )

    if gmax_value is not None:
        rows.extend(
            species_rows_delta_from_atlas_editor(
                cards,
                pd.DataFrame([{"Dex": dex, "Name": name, "Registered": bool(gmax_value)}]),
                account=account,
                save_date=save_date,
                entry_mode="gmax",
            )
        )
        if _atlas_registered_is_blank(card.get("registered_gmax")):
            registered = bool(gmax_value)
            if registered != _atlas_previous_caught(card, "caught_gmax"):
                rows.append(
                    _pokedex_species_entry_row(
                        save_date=save_date,
                        account=account,
                        entry_type="gmax",
                        dex_number=dex,
                        form="",
                        registered=registered,
                    )
                )

    atlas_kind_ids = {kind_id for kind_id, _label in ATLAS_ENTRY_KINDS}
    for kind_id, value in kind_values.items():
        if kind_id not in atlas_kind_ids:
            continue
        column = f"registered_{kind_id}"
        raw = card[column] if column in card.index else pd.NA
        if not _atlas_registered_is_blank(raw):
            continue
        registered = bool(value)
        if registered == _atlas_previous_caught(card, f"caught_{kind_id}"):
            continue
        rows.append(
            _pokedex_species_entry_row(
                save_date=save_date,
                account=account,
                entry_type=kind_id,
                dex_number=dex,
                form="",
                registered=registered,
            )
        )
    return rows


def _normalize_species_history_frame(frame: pd.DataFrame) -> pd.DataFrame:
    cols = POKEDEX_SPECIES_ENTRY_COLUMNS
    if frame.empty:
        return pd.DataFrame(columns=cols)
    rows = frame.copy()
    for col in cols:
        if col not in rows.columns:
            if col in {"registered", "can_evolve_now"}:
                rows[col] = False
            elif col in {"notes", "form"}:
                rows[col] = ""
            else:
                rows[col] = pd.NA
    rows["date"] = pd.to_datetime(rows["date"], errors="coerce")
    rows["account"] = rows["account"].astype(str).str.strip()
    rows["entry_type"] = rows["entry_type"].astype(str).str.strip().str.lower()
    rows["dex_number"] = pd.to_numeric(rows["dex_number"], errors="coerce")
    rows = rows.dropna(subset=["date", "account", "entry_type", "dex_number"]).copy()
    rows["dex_number"] = rows["dex_number"].astype(int)
    if rows["registered"].dtype != bool:
        rows["registered"] = rows["registered"].map(parse_bool_text)
    if rows["can_evolve_now"].dtype != bool:
        rows["can_evolve_now"] = rows["can_evolve_now"].map(parse_bool_text)
    rows["notes"] = rows["notes"].fillna("").astype(str).str.strip()
    rows = _with_species_form(rows)
    return rows


def compact_pokedex_species_rows(frame: pd.DataFrame) -> pd.DataFrame:
    rows = _normalize_species_history_frame(frame)
    if rows.empty:
        return pd.DataFrame(columns=POKEDEX_SPECIES_ENTRY_COLUMNS)
    group_cols = ["account", "entry_type", "dex_number", "_form_key"]
    kept_frames: list[pd.DataFrame] = []
    for _key, group in rows.sort_values([*group_cols, "date"]).groupby(group_cols, sort=False):
        day_rows = group.sort_values("date").drop_duplicates(subset=["date"], keep="last")
        kept_indices: list[object] = []
        prev_state: tuple[bool, bool, str] | None = None
        for index, row in day_rows.iterrows():
            state = (bool(row["registered"]), bool(row["can_evolve_now"]), str(row["notes"]))
            if prev_state is None or state != prev_state:
                kept_indices.append(index)
                prev_state = state
        if not kept_indices:
            continue
        compact_group = day_rows.loc[kept_indices].copy()
        if len(compact_group) > 1:
            first = compact_group.iloc[0]
            if (
                not bool(first["registered"])
                and not bool(first["can_evolve_now"])
                and str(first["notes"]).strip() == ""
            ):
                compact_group = compact_group.iloc[1:].copy()
        if not compact_group.empty:
            kept_frames.append(compact_group)
    if not kept_frames:
        return pd.DataFrame(columns=POKEDEX_SPECIES_ENTRY_COLUMNS)
    out = pd.concat(kept_frames, ignore_index=True)
    out = out.drop(columns=["_form_key"])
    out = out[POKEDEX_SPECIES_ENTRY_COLUMNS].sort_values(["date", "account", "entry_type", "dex_number", "form"]).reset_index(
        drop=True
    )
    return out


def save_pokedex_species_entries(path: Path, frame: pd.DataFrame) -> None:
    if frame.empty:
        out = pd.DataFrame(columns=POKEDEX_SPECIES_ENTRY_COLUMNS)
    else:
        out = _normalize_species_history_frame(frame).drop(columns=["_form_key"])
        out = out[POKEDEX_SPECIES_ENTRY_COLUMNS].sort_values(["date", "account", "entry_type", "dex_number", "form"]).reset_index(
            drop=True
        )
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out["registered"] = out["registered"].map(lambda value: "true" if bool(value) else "false")
    out["can_evolve_now"] = out["can_evolve_now"].map(lambda value: "true" if bool(value) else "false")
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)


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
    return [(kind, label) for kind, label in ATLAS_COMPARISON_KINDS if kind in requested]


def _selected_comparison_kinds(entry_types: Sequence[object] | None) -> list[tuple[str, str]]:
    if entry_types is None:
        return list(ATLAS_COMPARISON_KINDS)
    requested = {str(item).strip().lower() for item in entry_types if str(item).strip()}
    return [(kind, label) for kind, label in ATLAS_COMPARISON_KINDS if kind in requested]


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


def _availability_has_shadow_rows(availability_df: pd.DataFrame | None) -> bool:
    if availability_df is None or availability_df.empty or "entry_type" not in availability_df.columns:
        return False
    entry_types = availability_df["entry_type"].astype(str).str.strip().str.lower()
    return bool(entry_types.eq("shadow").any())


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
    requested = [str(kind) for kind in kinds]
    compute = list(requested)
    has_shadow_rows = _availability_has_shadow_rows(availability_df)
    if has_shadow_rows and "shadow" not in compute:
        compute.append("shadow")
    targets: dict[str, set[int]] = {}
    for kind in compute:
        raw = category_target_dex_numbers(kind, catalog, availability_df)
        targets[str(kind)] = {int(dex) for dex in raw if int(dex) in catalog_dex and int(dex) in in_go}
    if has_shadow_rows:
        targets["purified"] = set(targets.get("shadow", set()))
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


def _catalog_dex_numbers(catalog: pd.DataFrame) -> set[int]:
    if catalog.empty or "dex_number" not in catalog.columns:
        return set()
    return set(catalog["dex_number"].astype(int).tolist())


def _mega_target_forms(catalog: pd.DataFrame, availability_df: pd.DataFrame | None) -> list[tuple[int, str]]:
    """Available Mega forms whose dex is in this catalog and in GO, as (dex, casefolded form)."""
    if catalog.empty:
        return []
    in_go = _in_go_dex_numbers(catalog)
    catalog_dex = _catalog_dex_numbers(catalog)
    found: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for dex, forms in _available_form_map(availability_df, "mega").items():
        if dex not in catalog_dex or dex not in in_go:
            continue
        for form in forms:
            key = (int(dex), str(form).casefold())
            if key in seen:
                continue
            seen.add(key)
            found.append(key)
    return found


def _gmax_target_dexes(catalog: pd.DataFrame, availability_df: pd.DataFrame | None) -> set[int]:
    """Dex numbers with an available G-Max form that are in this catalog and in GO."""
    if catalog.empty:
        return set()
    in_go = _in_go_dex_numbers(catalog)
    catalog_dex = _catalog_dex_numbers(catalog)
    return {
        int(dex)
        for dex in _available_form_map(availability_df, "gmax")
        if int(dex) in catalog_dex and int(dex) in in_go
    }


def _target_keys_for_kind(
    kind: str,
    catalog: pd.DataFrame,
    availability_df: pd.DataFrame | None,
) -> set[object]:
    if kind == "mega":
        return set(_mega_target_forms(catalog, availability_df))
    if kind == "gmax":
        return set(_gmax_target_dexes(catalog, availability_df))
    return set(_atlas_targets_by_kind(catalog, availability_df, [kind]).get(kind, set()))


def _registered_form_keys_by_account(
    species_df: pd.DataFrame,
    accounts: Sequence[str],
    entry_type: str,
    as_of_date: object | None,
    *,
    blank_only: bool,
) -> dict[str, set[tuple[int, str]]]:
    found: dict[str, set[tuple[int, str]]] = {}
    if not accounts:
        return found
    latest = latest_pokedex_species_state(
        species_df,
        accounts=list(accounts),
        entry_types=[entry_type],
        as_of_date=as_of_date,
    )
    if latest.empty:
        return found
    for row in latest.itertuples(index=False):
        if not bool(row.registered):
            continue
        form = str(getattr(row, "form", "") or "").strip()
        if blank_only and form != "":
            continue
        found.setdefault(str(row.account), set()).add((int(row.dex_number), form.casefold()))
    return found


def _counting_catalog(catalog_df: pd.DataFrame, regions: Sequence[object] | None) -> pd.DataFrame:
    """Catalog rows in the ten counted regions, optionally limited to ``regions``.

    ``overall`` in the filter means no extra limit. Dex outside the ten regions are dropped
    so an overall total matches the sum of regional rows.
    """
    catalog = _prepare_atlas_catalog(catalog_df, regions)
    if catalog.empty or "dex_number" not in catalog.columns:
        columns = list(catalog.columns) if len(getattr(catalog, "columns", [])) else ["dex_number", "region"]
        return pd.DataFrame(columns=columns)
    catalog = catalog.copy()
    if "region" not in catalog.columns:
        catalog["region"] = ""
    catalog["region"] = catalog["region"].fillna("").astype(str).str.strip().str.lower()
    catalog = catalog[catalog["region"].isin(_CATALOG_COUNT_REGIONS)].copy()
    if catalog.empty:
        return catalog
    return catalog.drop_duplicates(subset=["dex_number"], keep="first").reset_index(drop=True)


def _present_count_regions(catalog: pd.DataFrame) -> list[str]:
    if catalog.empty or "region" not in catalog.columns:
        return []
    present = set(catalog["region"].astype(str).tolist())
    return [region for region in _CATALOG_COUNT_REGIONS if region in present]


def _normalize_day(value: object | None) -> pd.Timestamp:
    if value is None:
        return pd.NaT
    stamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(stamp):
        return pd.NaT
    return pd.Timestamp(stamp).normalize()


def _normalize_species_history(species_df: pd.DataFrame) -> pd.DataFrame:
    columns = ["date", "account", "entry_type", "dex_number", "form_key", "registered", "seq"]
    if species_df.empty or not {"account", "entry_type", "dex_number", "date"}.issubset(species_df.columns):
        return pd.DataFrame(columns=columns)
    rows = species_df.copy()
    rows["_seq"] = range(len(rows))
    rows["date"] = pd.to_datetime(rows["date"], errors="coerce")
    if pd.api.types.is_datetime64_any_dtype(rows["date"]):
        rows["date"] = rows["date"].dt.normalize()
    rows["account"] = rows["account"].astype(str).str.strip()
    rows["entry_type"] = rows["entry_type"].astype(str).str.strip().str.lower()
    rows["dex_number"] = pd.to_numeric(rows["dex_number"], errors="coerce")
    rows = rows.dropna(subset=["date", "account", "entry_type", "dex_number"]).copy()
    if rows.empty:
        return pd.DataFrame(columns=columns)
    rows["dex_number"] = rows["dex_number"].astype(int)
    rows = rows[(rows["account"] != "") & (rows["entry_type"] != "") & (rows["dex_number"] > 0)].copy()
    known = {kind for kind, _label in ATLAS_COMPARISON_KINDS}
    rows = rows[rows["entry_type"].isin(known)].copy()
    if rows.empty:
        return pd.DataFrame(columns=columns)
    if "registered" in rows.columns:
        rows["registered"] = rows["registered"].map(lambda value: value if isinstance(value, bool) else parse_bool_text(value))
    else:
        rows["registered"] = False
    rows = _with_species_form(rows)
    rows["form_key"] = rows["_form_key"]
    rows["seq"] = rows["_seq"]
    rows = rows.sort_values(["date", "seq"], kind="mergesort")
    return rows[columns].reset_index(drop=True)


def _events_for_kind(
    history: pd.DataFrame,
    kind: str,
    keys: set[object],
) -> list[tuple[pd.Timestamp, object, bool, int]]:
    if history.empty or not keys:
        return []
    events: list[tuple[pd.Timestamp, object, bool, int]] = []
    matched = history[history["entry_type"] == kind]
    for row in matched.itertuples(index=False):
        dex = int(row.dex_number)
        form_key = str(row.form_key)
        if kind == "mega":
            key: object = (dex, form_key)
        else:
            if form_key != "":
                continue
            key = dex
        if key not in keys:
            continue
        events.append((pd.Timestamp(row.date), key, bool(row.registered), int(row.seq)))
    events.sort(key=lambda event: (event[0], event[3]))
    return events


def _points_from_events(
    events: list[tuple[pd.Timestamp, object, bool, int]],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> list[tuple[pd.Timestamp, int]]:
    """Opening point on the window anchor, then one point per later day the count changes."""
    if pd.notna(start) and pd.notna(end) and start > end:
        return []

    usable = [event for event in events if pd.isna(end) or event[0] <= end]
    state: dict[object, bool] = {}

    def current() -> int:
        return sum(1 for value in state.values() if value)

    def apply(batch: list[tuple[pd.Timestamp, object, bool, int]]) -> None:
        for _stamp, key, registered, _seq in batch:
            state[key] = bool(registered)

    def daily_counts(batch: list[tuple[pd.Timestamp, object, bool, int]]) -> list[tuple[pd.Timestamp, int]]:
        grouped: list[tuple[pd.Timestamp, int]] = []
        index = 0
        while index < len(batch):
            day = batch[index][0]
            day_rows: list[tuple[pd.Timestamp, object, bool, int]] = []
            while index < len(batch) and batch[index][0] == day:
                day_rows.append(batch[index])
                index += 1
            apply(day_rows)
            grouped.append((day, current()))
        return grouped

    if pd.notna(start):
        apply([event for event in usable if event[0] < start])
        opening = current()
        daily = daily_counts([event for event in usable if event[0] >= start])
        if daily and daily[0][0] == start:
            anchor_count = daily[0][1]
            rest = daily[1:]
        else:
            anchor_count = opening
            rest = daily
        later_change = anchor_count != opening or any(count != anchor_count for _day, count in rest)
        if opening <= 0 and not later_change:
            return []
        points = [(start, anchor_count)]
        previous = anchor_count
        for day, count in rest:
            if count != previous:
                points.append((day, count))
                previous = count
        return points

    daily = daily_counts(usable)
    if not daily or all(count == 0 for _day, count in daily):
        return []
    points = [(daily[0][0], daily[0][1])]
    previous = daily[0][1]
    for day, count in daily[1:]:
        if count != previous:
            points.append((day, count))
            previous = count
    return points


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
    standard_ids = [kind for kind in kind_ids if kind not in {"mega", "gmax"}]
    targets = _atlas_targets_by_kind(catalog, availability_df, standard_ids)
    registered = _registered_dex_by_account_kind(species_df, account_list, standard_ids, targets, as_of_date)
    mega_target_set = set(_mega_target_forms(catalog, availability_df)) if "mega" in kind_ids else set()
    gmax_targets = _gmax_target_dexes(catalog, availability_df) if "gmax" in kind_ids else set()
    mega_registered = (
        _registered_form_keys_by_account(species_df, account_list, "mega", as_of_date, blank_only=False)
        if "mega" in kind_ids
        else {}
    )
    gmax_registered = (
        _registered_form_keys_by_account(species_df, account_list, "gmax", as_of_date, blank_only=True)
        if "gmax" in kind_ids
        else {}
    )
    rows: list[dict[str, object]] = []
    for account_name in account_list:
        for kind, label in kinds:
            if kind == "mega":
                target_count = len(mega_target_set)
                registered_count = len(mega_registered.get(account_name, set()) & mega_target_set)
            elif kind == "gmax":
                target_count = len(gmax_targets)
                registered_count = len(
                    {dex for dex, _form in gmax_registered.get(account_name, set()) if dex in gmax_targets}
                )
            else:
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


_SPECIES_REGION_COUNT_COLUMNS = [
    "entry_type",
    "entry_type_label",
    "region",
    "registered_count",
    "target_count",
]

_SPECIES_PROGRESS_COLUMNS = [
    "date",
    "account",
    "entry_type",
    "entry_type_label",
    "registered_count",
    "target_count",
]


def _kind_region_counts(
    kind: str,
    region_catalog: pd.DataFrame,
    availability_df: pd.DataFrame | None,
    registered: dict[tuple[str, int, str], bool],
) -> tuple[int, int]:
    if kind == "mega":
        forms = _mega_target_forms(region_catalog, availability_df)
        registered_count = sum(1 for dex, form_key in forms if registered.get((kind, dex, form_key), False))
        return registered_count, len(forms)
    if kind == "gmax":
        targets = _gmax_target_dexes(region_catalog, availability_df)
        registered_count = sum(1 for dex in targets if registered.get((kind, int(dex), ""), False))
        return registered_count, len(targets)
    targets = _atlas_targets_by_kind(region_catalog, availability_df, [kind]).get(kind, set())
    registered_count = sum(1 for dex in targets if registered.get((kind, int(dex), ""), False))
    return registered_count, len(targets)


def build_species_region_counts(
    catalog_df: pd.DataFrame,
    species_df: pd.DataFrame,
    *,
    account: object,
    availability_df: pd.DataFrame | None = None,
    as_of_date: object | None = None,
    regions: Sequence[object] | None = None,
) -> pd.DataFrame:
    columns = list(_SPECIES_REGION_COUNT_COLUMNS)
    catalog = _counting_catalog(catalog_df, regions)
    present = _present_count_regions(catalog)
    if not present:
        return pd.DataFrame(columns=columns)
    account_name = str(account or "").strip()
    kind_ids = [kind for kind, _label in ATLAS_COMPARISON_KINDS]
    registered = _registration_index(species_df, account_name, kind_ids, as_of_date)
    rows: list[dict[str, object]] = []
    for kind, label in ATLAS_COMPARISON_KINDS:
        registered_total = 0
        target_total = 0
        for region in present:
            region_catalog = catalog[catalog["region"] == region]
            registered_count, target_count = _kind_region_counts(kind, region_catalog, availability_df, registered)
            registered_total += registered_count
            target_total += target_count
            rows.append(
                {
                    "entry_type": kind,
                    "entry_type_label": label,
                    "region": region,
                    "registered_count": registered_count,
                    "target_count": target_count,
                }
            )
        rows.append(
            {
                "entry_type": kind,
                "entry_type_label": label,
                "region": "overall",
                "registered_count": registered_total,
                "target_count": target_total,
            }
        )
    counts = pd.DataFrame(rows, columns=columns)
    counts["registered_count"] = counts["registered_count"].astype(int)
    counts["target_count"] = counts["target_count"].astype(int)
    return counts


def build_species_progress_rows(
    catalog_df: pd.DataFrame,
    species_df: pd.DataFrame,
    *,
    accounts: Sequence[object],
    entry_types: Sequence[object] | None = None,
    regions: Sequence[object] | None = None,
    start_date: object | None = None,
    end_date: object | None = None,
    availability_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    columns = list(_SPECIES_PROGRESS_COLUMNS)
    empty = pd.DataFrame(columns=columns)
    account_list = _ordered_unique_text(accounts)
    kinds = _selected_comparison_kinds(entry_types)
    catalog = _counting_catalog(catalog_df, regions)
    if not account_list or not kinds or catalog.empty:
        return empty
    history = _normalize_species_history(species_df)
    start = _normalize_day(start_date)
    end = _normalize_day(end_date)
    rows: list[dict[str, object]] = []
    for account_name in account_list:
        account_history = history[history["account"] == account_name] if not history.empty else history
        for kind, label in kinds:
            keys = _target_keys_for_kind(kind, catalog, availability_df)
            target_count = len(keys)
            events = _events_for_kind(account_history, kind, keys)
            for point_date, registered_count in _points_from_events(events, start, end):
                rows.append(
                    {
                        "date": point_date,
                        "account": account_name,
                        "entry_type": kind,
                        "entry_type_label": label,
                        "registered_count": registered_count,
                        "target_count": target_count,
                    }
                )
    if not rows:
        return empty
    progress = pd.DataFrame(rows, columns=columns)
    progress["date"] = pd.to_datetime(progress["date"])
    progress["registered_count"] = progress["registered_count"].astype(int)
    progress["target_count"] = progress["target_count"].astype(int)
    return progress.sort_values(["date", "account", "entry_type"], kind="mergesort").reset_index(drop=True)


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
        "fill_path",
        "notes",
        "mega_forms",
        "registered_mega_forms",
        "registered_mega",
        "registered_gmax",
        *[f"registered_{kind}" for kind, _label in ATLAS_ENTRY_KINDS],
        *[f"caught_{kind}" for kind, _label in ATLAS_ENTRY_KINDS],
        "caught_gmax",
        "unreleased_kinds",
        "mega_host",
        "gmax_host",
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


_ATLAS_KIND_LABELS: dict[str, str] = {kind: label for kind, label in ATLAS_ENTRY_KINDS}
_ATLAS_KIND_ORDER: dict[str, int] = {kind: index for index, (kind, _label) in enumerate(ATLAS_ENTRY_KINDS)}


def _evolution_positive_dex(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return None
    dex = int(number)
    if dex <= 0 or float(number) != float(dex):
        return None
    return dex


def _text_or_blank(value: object) -> str:
    if value is None or isinstance(value, bool):
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        return ""
    return str(value).strip()


def _catalog_names(catalog: pd.DataFrame) -> dict[int, str]:
    names: dict[int, str] = {}
    if catalog.empty or "dex_number" not in catalog.columns:
        return names
    raw_names = catalog["name"].tolist() if "name" in catalog.columns else [""] * len(catalog)
    for dex_raw, name_raw in zip(catalog["dex_number"].tolist(), raw_names, strict=True):
        dex = _evolution_positive_dex(dex_raw)
        if dex is None:
            continue
        text = _text_or_blank(name_raw)
        if dex not in names or (not names[dex] and text):
            names[dex] = text
    return names


def _evolution_predecessors(
    evolutions_df: pd.DataFrame | None,
    in_go: set[int],
) -> dict[int, list[tuple[int, str]]]:
    predecessors: dict[int, list[tuple[int, str]]] = {}
    if evolutions_df is None or evolutions_df.empty or not in_go:
        return predecessors
    total = len(evolutions_df)
    sources = (
        evolutions_df["source_dex_number"].tolist()
        if "source_dex_number" in evolutions_df.columns
        else [None] * total
    )
    targets = (
        evolutions_df["target_dex_number"].tolist()
        if "target_dex_number" in evolutions_df.columns
        else [None] * total
    )
    forms = evolutions_df["source_form"].tolist() if "source_form" in evolutions_df.columns else [""] * total
    seen: set[tuple[int, int, str]] = set()
    for source_raw, target_raw, form_raw in zip(sources, targets, forms, strict=True):
        source = _evolution_positive_dex(source_raw)
        target = _evolution_positive_dex(target_raw)
        if source is None or target is None or source == target:
            continue
        if source not in in_go or target not in in_go:
            continue
        form = _text_or_blank(form_raw)
        key = (source, target, form)
        if key in seen:
            continue
        seen.add(key)
        predecessors.setdefault(target, []).append((source, form))
    return predecessors


def _evolution_sources(
    evolutions_df: pd.DataFrame | None,
    in_go: set[int],
) -> set[int]:
    evolving: set[int] = set()
    if evolutions_df is None or evolutions_df.empty or not in_go:
        return evolving
    total = len(evolutions_df)
    sources = (
        evolutions_df["source_dex_number"].tolist()
        if "source_dex_number" in evolutions_df.columns
        else [None] * total
    )
    targets = (
        evolutions_df["target_dex_number"].tolist()
        if "target_dex_number" in evolutions_df.columns
        else [None] * total
    )
    for source_raw, target_raw in zip(sources, targets, strict=True):
        source = _evolution_positive_dex(source_raw)
        target = _evolution_positive_dex(target_raw)
        if source is None or target is None or source == target:
            continue
        if source not in in_go or target not in in_go:
            continue
        evolving.add(source)
    return evolving


def _source_display_name(catalog_name: str, forms: list[str]) -> str:
    cleaned = [_text_or_blank(form) for form in forms]
    if cleaned and all(cleaned) and len(set(cleaned)) == 1:
        return f"{cleaned[0]} {catalog_name}".strip()
    return catalog_name


def _nearest_registered_ancestor(
    start: int,
    registered: set[int],
    predecessors: dict[int, list[tuple[int, str]]],
    names: dict[int, str],
) -> tuple[int, str] | None:
    """Nearest registered pre-evolution. Distance wins, then lower source dex.

    Registered ancestors are not expanded, so a path does not continue past them.
    The rest of that BFS level still runs, and a nearer ancestor on another branch wins.
    """
    queue: deque[int] = deque([start])
    distance: dict[int, int] = {start: 0}
    hop_forms: dict[int, list[str]] = {}
    best: tuple[int, int] | None = None

    while queue:
        node = queue.popleft()
        node_distance = distance[node]
        if best is not None and node_distance > best[0]:
            break
        if node != start and node in registered:
            candidate = (node_distance, node)
            if best is None or candidate < best:
                best = candidate
            continue
        grouped: dict[int, list[str]] = {}
        for source, form in predecessors.get(node, []):
            grouped.setdefault(source, []).append(form)
        for source in sorted(grouped):
            next_distance = node_distance + 1
            if source not in distance:
                distance[source] = next_distance
                hop_forms[source] = list(grouped[source])
                queue.append(source)
            elif distance[source] == next_distance:
                hop_forms.setdefault(source, []).extend(grouped[source])

    if best is None:
        return None
    _ancestor_distance, ancestor = best
    display = _source_display_name(names.get(ancestor, ""), hop_forms.get(ancestor, []))
    return ancestor, display


def _species_fill_path(
    dex: int,
    missing_kinds: list[tuple[str, str]],
    registered_by_kind: dict[str, set[int]],
    predecessors: dict[int, list[tuple[int, str]]],
    names: dict[int, str],
) -> tuple[str, str, bool]:
    """Return the fill sentence, evolution-reachable kind keys, and purify reachability.

    Mega and G-Max are never evolution fills. Purify fills only a missing purified kind.
    """
    grouped: dict[tuple[int, str], list[tuple[str, str]]] = {}
    for kind, label in missing_kinds:
        if kind not in _ATLAS_KIND_ORDER:
            continue
        hit = _nearest_registered_ancestor(dex, registered_by_kind.get(kind, set()), predecessors, names)
        if hit is None:
            continue
        source_dex, display = hit
        grouped.setdefault((source_dex, display), []).append((kind, label))

    sentences: list[str] = []
    reached: list[str] = []
    for source_dex, display in sorted(grouped):
        items = sorted(grouped[(source_dex, display)], key=lambda item: _ATLAS_KIND_ORDER[item[0]])
        reached.extend(kind for kind, _label in items)
        label_text = ", ".join(_ATLAS_KIND_LABELS[kind] for kind, _label in items)
        sentences.append(f"Via evolution from {display}: {label_text}")

    purify_reachable = False
    purified_missing = any(kind == "purified" for kind, _label in missing_kinds)
    if purified_missing:
        if dex in registered_by_kind.get("shadow", set()):
            sentences.append("Via purify")
            purify_reachable = True
        elif "purified" not in reached:
            shadow_hit = _nearest_registered_ancestor(
                dex,
                registered_by_kind.get("shadow", set()),
                predecessors,
                names,
            )
            if shadow_hit is not None:
                sentences.append(f"Via purify from {shadow_hit[1]}, then evolve")
                purify_reachable = True
    return ". ".join(sentences), ",".join(reached), purify_reachable


def _alias_path_filter(value: object) -> str:
    if value is None:
        return "any"
    text = str(value).strip().lower()
    aliases = {
        "": "any",
        "any": "any",
        "all": "any",
        "blank": "any",
        "evolution": "evolution",
        "via evolution": "evolution",
        "purify": "purify",
        "via purify": "purify",
        "either": "either",
        "via evolution or purify": "either",
        "both": "either",
        "trade": "trade",
        "via trade": "trade",
    }
    return aliases.get(text, "any")


def _path_matches(evolution_kinds: object, purify_reachable: object, path_key: str, kind_key: str) -> bool:
    if path_key == "any":
        return True
    kinds = {part for part in str(evolution_kinds or "").split(",") if part}
    evolution_match = bool(kinds) if kind_key == "any" else kind_key in kinds
    purify_match = bool(purify_reachable) and kind_key in {"any", "purified"}
    if path_key == "evolution":
        return evolution_match
    if path_key == "purify":
        return purify_match
    if path_key == "either":
        return evolution_match or purify_match
    return True


def _trade_fill_sentence(trade_sources: object) -> str:
    if _atlas_registered_is_blank(trade_sources):
        return ""
    lines = [line.strip() for line in str(trade_sources).split("\n") if line.strip()]
    if not lines:
        return ""
    return ". ".join(f"Via trade from {line}" for line in lines)


def _merge_trade_fill_paths(cards: pd.DataFrame) -> pd.DataFrame:
    """Append donor lines to fill_path so Fill and the name search can find trades."""
    if "trade_sources" not in cards.columns or "fill_path" not in cards.columns or cards.empty:
        return cards
    merged: list[str] = []
    for existing, extra in zip(cards["fill_path"].tolist(), cards["trade_sources"].map(_trade_fill_sentence).tolist(), strict=True):
        base = "" if _atlas_registered_is_blank(existing) else str(existing).strip()
        extra_text = "" if _atlas_registered_is_blank(extra) else str(extra).strip()
        if base and extra_text:
            merged.append(f"{base}. {extra_text}")
        else:
            merged.append(base or extra_text)
    cards["fill_path"] = merged
    return cards


def _display_fill_path(fill_path: object, *, hide_trade: bool) -> str:
    text = "" if _atlas_registered_is_blank(fill_path) else str(fill_path).strip()
    if not text or not hide_trade:
        return text
    kept = [
        part.strip()
        for part in text.split(". ")
        if part.strip() and not part.strip().casefold().startswith("via trade from ")
    ]
    return ". ".join(kept)


def _filter_cards_by_path(cards: pd.DataFrame, path_filter: object, kind_key: str) -> pd.DataFrame:
    path_key = _alias_path_filter(path_filter)
    if path_key == "any" or cards.empty:
        return cards
    if path_key == "trade":
        if "trade_sources" not in cards.columns:
            return cards.iloc[0:0].copy()
        text = cards["trade_sources"].map(_trade_fill_sentence)
        return cards.loc[text.ne("")].copy()
    mask = [
        _path_matches(evolution_kinds, purify_reachable, path_key, kind_key)
        for evolution_kinds, purify_reachable in zip(
            cards["_evolution_kinds"].tolist(),
            cards["_purify_reachable"].tolist(),
            strict=True,
        )
    ]
    return cards.loc[pd.Series(mask, index=cards.index)].copy()


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
    evolutions_df: pd.DataFrame | None = None,
    path_filter: object | None = None,
) -> pd.DataFrame:
    # entry_type is ignored. kind_filter and state_filter select cards.
    # When both are omitted, status_filter keeps the previous single-status behavior.
    # evolutions_df and path_filter are optional; omitted arguments leave existing callers unchanged.
    _ = entry_type
    cols = _atlas_card_columns()
    normalized_overrides = _normalize_release_overrides(release_overrides)
    if catalog_df.empty or "dex_number" not in catalog_df.columns:
        return pd.DataFrame(columns=cols)
    full_catalog = _prepare_atlas_catalog(catalog_df, None)
    region_key = str(region or "").strip().lower()
    region_filter = None if not region_key or region_key == "overall" else [region_key]
    catalog = _prepare_atlas_catalog(full_catalog, region_filter)
    if catalog.empty:
        return pd.DataFrame(columns=cols)
    ancestor_names = _catalog_names(full_catalog)
    predecessors = _evolution_predecessors(evolutions_df, _in_go_dex_numbers(full_catalog))
    evolution_sources = _evolution_sources(evolutions_df, _in_go_dex_numbers(full_catalog))
    availability_df = effective_category_availability(
        availability_df,
        evolutions=evolutions_df,
        in_go=_in_go_dex_numbers(full_catalog),
        names=ancestor_names,
    )

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
    caught_by_kind: dict[str, list[bool]] = {kind: [] for kind in kind_ids}
    caught_gmax_values: list[bool] = []
    unreleased_kind_values: list[str] = []
    mega_host_values: list[bool] = []
    gmax_host_values: list[bool] = []
    mega_form_values: list[str] = []
    registered_mega_form_values: list[str] = []
    registered_mega_values: list[object] = []
    registered_gmax_values: list[object] = []
    form_search_values: list[str] = []
    fill_paths: list[str] = []
    evolution_kind_values: list[str] = []
    purify_reachable_values: list[bool] = []
    for dex, species_in_go in zip(cards["dex_number"].astype(int).tolist(), in_go.tolist(), strict=True):
        missing_labels: list[str] = []
        missing_evolution: list[tuple[str, str]] = []
        available_kinds = 0
        registered_kinds = 0
        for kind, label in ATLAS_ENTRY_KINDS:
            caught_by_kind[kind].append(dex in registered_by_kind[kind])
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
                missing_evolution.append((kind, label))
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
        caught_gmax_values.append(dex in registered_gmax)
        mega_host = bool(species_in_go) and (dex not in evolution_sources or bool(species_mega_forms))
        gmax_host = bool(species_in_go) and (dex not in evolution_sources or gmax_available)
        mega_host_values.append(mega_host)
        gmax_host_values.append(gmax_host)
        if species_in_go:
            unreleased_labels: list[str] = []
            if dex not in targets.get("shiny", set()):
                unreleased_labels.append("Shiny")
            if dex not in targets.get("shadow", set()):
                unreleased_labels.append("Shadow")
            if mega_host and not species_mega_forms:
                unreleased_labels.append("Mega")
            if gmax_host and not gmax_available:
                unreleased_labels.append("G-Max")
            unreleased_kind_values.append(", ".join(unreleased_labels))
        else:
            unreleased_kind_values.append("")
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
        fill_path, reached_kinds, purify_reachable = _species_fill_path(
            dex,
            missing_evolution,
            registered_by_kind,
            predecessors,
            ancestor_names,
        )
        fill_paths.append(fill_path)
        evolution_kind_values.append(reached_kinds)
        purify_reachable_values.append(purify_reachable)

    cards["status"] = statuses
    cards["status_label"] = status_labels
    cards["release_override"] = release_override_values
    cards["missing_kinds"] = missing_kind_values
    cards["fill_path"] = fill_paths
    cards["_evolution_kinds"] = evolution_kind_values
    cards["_purify_reachable"] = purify_reachable_values
    cards["category_available"] = category_available
    cards["registered"] = [status == "registered" for status in statuses]
    cards["mega_forms"] = mega_form_values
    cards["registered_mega_forms"] = registered_mega_form_values
    cards["registered_mega"] = pd.array(registered_mega_values, dtype="boolean")
    cards["registered_gmax"] = pd.array(registered_gmax_values, dtype="boolean")
    cards["form_search"] = form_search_values
    for kind in kind_ids:
        cards[f"registered_{kind}"] = pd.array(per_kind_values[kind], dtype="boolean")
        cards[f"caught_{kind}"] = caught_by_kind[kind]
    cards["caught_gmax"] = caught_gmax_values
    cards["unreleased_kinds"] = unreleased_kind_values
    cards["mega_host"] = mega_host_values
    cards["gmax_host"] = gmax_host_values

    kind_key, state_key = _resolved_kind_state(kind_filter, state_filter, status_filter)
    cards = annotate_trade_sources(
        cards,
        species_df,
        account=account,
        as_of_date=as_of_date,
        kind=kind_key,
    )
    cards = _merge_trade_fill_paths(cards)

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
            + " "
            + cards["fill_path"].map(normalize_pokemon_name)
        )
        cards = cards[haystack.str.contains(query, regex=False)].copy()

    cards = _filter_atlas_cards(cards, kind_key, state_key)
    cards = _filter_cards_by_path(cards, path_filter, kind_key)
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
    if cards.empty or state == "any":
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
    if state == "any":
        return pd.Series(True, index=cards.index)
    if state == "available":
        return states.map(lambda item: item is not None)
    return pd.Series(False, index=cards.index)


def _selected_trade_entry_kinds(kind: object) -> list[tuple[str, str]] | None:
    if kind is None or _atlas_registered_is_blank(kind):
        return list(TRADE_ENTRY_KINDS)
    text = str(kind).strip().casefold()
    if text in {"", "any", "all"}:
        return list(TRADE_ENTRY_KINDS)
    resolved = _TRADE_KIND_ALIASES.get(text, text)
    for kind_id, label in TRADE_ENTRY_KINDS:
        if resolved == kind_id or resolved == label.casefold():
            return [(kind_id, label)]
    return None


# Preferred donor order. Every other account in the species rows can still donate.
_TRADE_DONOR_SORT_RANK: dict[str, int] = {
    "thombay": 0,
    "cerius": 1,
    "thomzay": 2,
}


def _trade_account_key(account: object) -> str:
    return _text_or_blank(account).casefold()


def _trade_donor_sort_key(name: str) -> tuple[int, str]:
    key = name.casefold()
    return (_TRADE_DONOR_SORT_RANK.get(key, len(_TRADE_DONOR_SORT_RANK)), key)


def _trade_account_spellings(species_df: pd.DataFrame, as_of_date: object | None = None) -> dict[str, str]:
    """Map each case-insensitive account to the spelling on its latest species row."""
    if (
        not isinstance(species_df, pd.DataFrame)
        or species_df.empty
        or not {"account", "date"}.issubset(species_df.columns)
    ):
        return {}
    spelling = [_text_or_blank(value) for value in species_df["account"].tolist()]
    frame = pd.DataFrame(
        {
            "key": [value.casefold() for value in spelling],
            "spelling": spelling,
            "date": pd.to_datetime(species_df["date"], errors="coerce").tolist(),
            "pos": range(len(spelling)),
        }
    )
    frame = frame.loc[frame["key"].ne("") & frame["date"].notna()]
    as_of = pd.to_datetime(as_of_date, errors="coerce") if as_of_date is not None else pd.NaT
    if pd.notna(as_of):
        frame = frame.loc[frame["date"] <= pd.Timestamp(as_of)]
    if frame.empty:
        return {}
    frame = frame.sort_values(["key", "date", "pos"], na_position="first")
    latest = frame.groupby("key", sort=False).tail(1)
    return dict(zip(latest["key"].tolist(), latest["spelling"].tolist(), strict=True))


def _species_with_trade_account_spellings(species_df: pd.DataFrame, spellings: dict[str, str]) -> pd.DataFrame:
    if species_df.empty or "account" not in species_df.columns or not spellings:
        return species_df
    rows = species_df.copy()
    rows["account"] = rows["account"].map(
        lambda value: spellings.get(_trade_account_key(value), _text_or_blank(value))
    )
    return rows


def _trade_donors_for_account(
    species_df: pd.DataFrame,
    account: object,
    as_of_date: object | None = None,
) -> list[str]:
    viewer = _trade_account_key(account)
    names = [
        spelling
        for key, spelling in _trade_account_spellings(species_df, as_of_date).items()
        if key and key != viewer
    ]
    names.sort(key=_trade_donor_sort_key)
    return names


def _trade_value_is_true(value: object) -> bool:
    if _atlas_registered_is_blank(value):
        return False
    try:
        return bool(value) is True
    except (TypeError, ValueError):
        return False


def _trade_kind_is_missing(value: object) -> bool:
    if _atlas_registered_is_blank(value):
        return False
    try:
        return bool(value) is False
    except (TypeError, ValueError):
        return False


def _registered_trade_donor_kinds(
    species_df: pd.DataFrame,
    donors: Sequence[str],
    kinds: Sequence[tuple[str, str]],
    as_of_date: object | None,
) -> set[tuple[str, int, str]]:
    owned: set[tuple[str, int, str]] = set()
    if not isinstance(species_df, pd.DataFrame) or not donors or not kinds:
        return owned
    latest = latest_pokedex_species_state(
        species_df,
        accounts=list(donors),
        entry_types=[kind_id for kind_id, _label in kinds],
        as_of_date=as_of_date,
    )
    if latest.empty:
        return owned
    canonical = {name.casefold(): name for name in donors}
    selected = {kind_id for kind_id, _label in kinds}
    for row in latest.itertuples(index=False):
        if _text_or_blank(getattr(row, "form", "")):
            continue
        if not _trade_value_is_true(getattr(row, "registered", False)):
            continue
        donor = canonical.get(str(getattr(row, "account", "") or "").strip().casefold())
        kind_id = str(getattr(row, "entry_type", "") or "").strip().casefold()
        dex = _evolution_positive_dex(getattr(row, "dex_number", None))
        if donor is None or kind_id not in selected or dex is None:
            continue
        owned.add((donor, dex, kind_id))
    return owned


def annotate_trade_sources(
    cards: pd.DataFrame,
    species_df: pd.DataFrame,
    *,
    account: object,
    as_of_date: object | None = None,
    kind: object = "any",
) -> pd.DataFrame:
    out = cards.copy()
    if out.empty:
        out["trade_sources"] = ""
        return out
    kinds = _selected_trade_entry_kinds(kind)
    donors = _trade_donors_for_account(species_df, account, as_of_date)
    if not kinds or not donors:
        out["trade_sources"] = ""
        return out
    spellings = {name.casefold(): name for name in donors}
    owned = _registered_trade_donor_kinds(
        _species_with_trade_account_spellings(species_df, spellings),
        donors,
        kinds,
        as_of_date,
    )
    dex_values = out["dex_number"].tolist() if "dex_number" in out.columns else [None] * len(out)
    missing_flags: dict[str, list[bool]] = {}
    for kind_id, _label in kinds:
        column = _kind_registered_column(kind_id)
        if column in out.columns:
            missing_flags[kind_id] = [_trade_kind_is_missing(value) for value in out[column].tolist()]
        else:
            missing_flags[kind_id] = [False] * len(out)
    texts: list[str] = []
    for row_index, dex_value in enumerate(dex_values):
        dex = _evolution_positive_dex(dex_value)
        lines: list[str] = []
        if dex is not None:
            for donor in donors:
                labels = [
                    label
                    for kind_id, label in kinds
                    if missing_flags[kind_id][row_index] and (donor, dex, kind_id) in owned
                ]
                if labels:
                    lines.append(f"{donor}: {', '.join(labels)}")
        texts.append("\n".join(lines))
    out["trade_sources"] = texts
    return out


def _atlas_trade_status_lines(row: pd.Series) -> list[str]:
    if "trade_sources" not in row.index:
        return []
    raw = row["trade_sources"]
    if _atlas_registered_is_blank(raw):
        return []
    text = str(raw).strip()
    if not text:
        return []
    return [line.strip() for line in text.split("\n") if line.strip()]


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
        trade_lines = _atlas_trade_status_lines(row)
        if trade_lines:
            status_html = "".join(
                f'<div class="pogo-dex-status">{escape(line)}</div>' for line in trade_lines
            )
        else:
            status_html = f'<div class="pogo-dex-status">{escape(badge)}</div>'
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
        fill_path = _display_fill_path(row.get("fill_path"), hide_trade=bool(trade_lines))
        path_html = f'<span class="pogo-dex-path">{escape(fill_path)}</span>' if fill_path else ""
        unreleased_text = _text_or_blank(row.get("unreleased_kinds"))
        unreleased_html = ""
        if unreleased_text:
            unreleased_html = (
                '<div class="pogo-dex-status pogo-dex-status--unreleased">'
                f"Not released: {escape(unreleased_text)}</div>"
            )
        parts.append(
            (
                f'<a class="pogo-dex-card-link" href="#atlas-dex-{dex}" data-atlas-dex="{dex}">'
                f'<article class="pogo-dex-card pogo-dex-card--{escape(status, quote=True)} '
                f'pogo-dex-card-type--{escape(type_1 or "normal", quote=True)}">'
                f'<img class="pogo-dex-art" src="{sprite}" alt="{name}" loading="lazy">'
                f'<div class="pogo-dex-num">#{dex:04d}</div>'
                f'<div class="pogo-dex-name">{name}</div>'
                f'<div class="pogo-dex-german">{german}</div>'
                f'<div class="pogo-dex-types">{type_chips}</div>'
                f"{status_html}"
                f"{unreleased_html}"
                f"{path_html}"
                f"{extras}"
                "</article>"
                "</a>"
            )
        )
    parts.append("</div>")
    return "".join(parts)


def load_species_entries_or_empty(path: Path, valid_entry_types: set[str] | None = None) -> pd.DataFrame:
    return load_pokedex_species_entries(path, valid_entry_types=valid_entry_types)


def load_category_availability_or_empty(path: Path, valid_entry_types: set[str] | None = None) -> pd.DataFrame:
    return load_pokedex_category_availability(path, valid_entry_types=valid_entry_types)
