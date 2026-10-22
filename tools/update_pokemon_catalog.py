from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.paths import (
    pokedex_category_availability_path,
    pokemon_catalog_path,
)
from webapp.data_files import (
    POKEMON_CATALOG_COLUMNS,
    drop_superseded_blank_mega_forms,
    load_pokedex_category_availability,
    load_pokemon_catalog,
    merge_pokedex_category_availability,
    merge_pokemon_catalog,
)
from webapp.pokedex import (
    apply_catalog_community_fields,
    build_category_availability_rows,
    extract_gigantamax_dex_numbers,
    extract_mega_forms,
    extract_pogoapi_dex_numbers,
    extract_pvpoke_mega_forms,
)

POKEAPI_CSV_BASE = "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv"
POKEMINERS_GAME_MASTER_URL = (
    "https://raw.githubusercontent.com/PokeMiners/game_masters/master/latest/latest.json"
)
LEGACY_GAME_MASTER_URL = (
    "https://raw.githubusercontent.com/pokemongo-dev-contrib/pokemongo-game-master/"
    "master/versions/latest/V2_GAME_MASTER.json"
)
POGOAPI_BASE = "https://pogoapi.net/api/v1"
PVPOKE_POKEMON_URL = (
    "https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/data/gamemaster/pokemon.json"
)
MAX_DEX_NUMBER = 1025

REGION_BY_GENERATION_ID = {
    1: "kanto",
    2: "johto",
    3: "hoenn",
    4: "sinnoh",
    5: "unova",
    6: "kalos",
    7: "alola",
    8: "galar",
    9: "paldea",
}
UNIDENTIFIED_REGION_DEX_NUMBERS = {808, 809}


def _region_for_species(dex_number: int, generation_id: int) -> str:
    if int(dex_number) in UNIDENTIFIED_REGION_DEX_NUMBERS:
        return "unidentified"
    return REGION_BY_GENERATION_ID.get(int(generation_id), "")


def _read_url_text(url: str) -> str:
    request = Request(
        url,
        headers={"User-Agent": "PoGo_XP catalog updater (https://github.com/local/PoGo_XP)"},
    )
    with urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8")


def _read_json(url: str) -> object:
    return json.loads(_read_url_text(url))


def _read_pokeapi_csv(name: str) -> pd.DataFrame:
    text = _read_url_text(f"{POKEAPI_CSV_BASE}/{name}")
    return pd.read_csv(io.StringIO(text))


def _species_names(local_language_id: int) -> dict[int, str]:
    names = _read_pokeapi_csv("pokemon_species_names.csv")
    names = names[names["local_language_id"] == int(local_language_id)].copy()
    return dict(zip(names["pokemon_species_id"].astype(int), names["name"].astype(str)))


def _load_game_master_payload() -> object | None:
    for url in (POKEMINERS_GAME_MASTER_URL, LEGACY_GAME_MASTER_URL):
        try:
            return json.loads(_read_url_text(url))
        except Exception:
            continue
    return None


def _category_rows(existing: pd.DataFrame | None, entry_type: str) -> pd.DataFrame:
    if existing is None or existing.empty or "entry_type" not in existing.columns:
        return pd.DataFrame()
    entry = existing["entry_type"].astype(str).str.strip().str.lower()
    return existing.loc[entry == entry_type].copy()


def _prepend_category_rows(seeded: pd.DataFrame, existing: pd.DataFrame | None, entry_type: str) -> pd.DataFrame:
    kept = _category_rows(existing, entry_type)
    if kept.empty:
        return seeded
    return pd.concat([kept, seeded], ignore_index=True)


def preserve_unavailable_category_rows(
    seeded_availability: pd.DataFrame,
    existing_availability: pd.DataFrame | None = None,
    *,
    mega_forms: list[tuple[int, str]] | None = None,
    gmax_dex: set[int] | None = None,
) -> pd.DataFrame:
    """Keep saved mega rows, and keep gmax rows when that refresh produced none.

    Mega rows are copied into the seed because merge keeps only seeded rows.
    When ``mega_forms`` is non-empty, blank mega rows are removed for dexes that
    now have a non-blank form. Other mega rows stay. G-Max rows are copied only
    when ``gmax_dex`` is missing or empty.
    """
    seeded = seeded_availability.copy()
    seeded = _prepend_category_rows(seeded, existing_availability, "mega")
    if mega_forms:
        seeded = drop_superseded_blank_mega_forms(seeded)
    if not gmax_dex:
        seeded = _prepend_category_rows(seeded, existing_availability, "gmax")
    return seeded


def _load_pogoapi_payload(name: str) -> object:
    try:
        return _read_json(f"{POGOAPI_BASE}/{name}")
    except Exception:
        return None


def _load_pvpoke_pokemon() -> object | None:
    try:
        return _read_json(PVPOKE_POKEMON_URL)
    except Exception:
        return None


def _union_mega_forms(
    base: list[tuple[int, str]] | None,
    extra: list[tuple[int, str]],
) -> list[tuple[int, str]] | None:
    if base is None and not extra:
        return None
    seen: set[tuple[int, str]] = set()
    combined: list[tuple[int, str]] = []
    for dex, form in [*(base or []), *extra]:
        dex_number = int(dex)
        form_text = str(form).strip()
        key = (dex_number, form_text.casefold())
        if key in seen:
            continue
        seen.add(key)
        combined.append((dex_number, form_text))
    combined.sort(key=lambda pair: (pair[0], pair[1].casefold()))
    return combined


def load_pogoapi_seed_data() -> dict[str, object]:
    released = extract_pogoapi_dex_numbers(_load_pogoapi_payload("released_pokemon.json") or {})
    shiny = extract_pogoapi_dex_numbers(_load_pogoapi_payload("shiny_pokemon.json") or {})
    shadow = extract_pogoapi_dex_numbers(_load_pogoapi_payload("shadow_pokemon.json") or {})
    mega_payload = _load_pogoapi_payload("mega_pokemon.json")
    if mega_payload is None:
        mega_forms = None
    else:
        try:
            mega_forms = extract_mega_forms(mega_payload)
        except Exception:
            mega_forms = None
    game_master = _load_game_master_payload()
    if game_master is None:
        gmax_dex = None
    else:
        try:
            gmax_dex = extract_gigantamax_dex_numbers(game_master)
        except Exception:
            gmax_dex = None
    community_days = _load_pogoapi_payload("community_days.json")
    if not isinstance(community_days, list):
        community_days = []
    return {
        "released": released,
        "shiny": shiny,
        "shadow": shadow,
        "mega": extract_pogoapi_dex_numbers(mega_payload or {}),
        "mega_forms": mega_forms,
        "gmax": gmax_dex,
        "community_days": community_days,
    }


def pogoapi_released_dex_numbers(released: object) -> set[int]:
    if not isinstance(released, set) or not released:
        raise RuntimeError(
            "The PoGO API released_pokemon list was empty and the updater is refusing "
            "to refresh availability from the game master."
        )
    return {int(number) for number in released}


def build_seed_catalog(
    *,
    released_dex_numbers: set[int] | None = None,
    community_days: list[dict[str, object]] | None = None,
) -> pd.DataFrame:
    pogo_species_numbers = pogoapi_released_dex_numbers(released_dex_numbers)
    species = _read_pokeapi_csv("pokemon_species.csv")
    pokemon = _read_pokeapi_csv("pokemon.csv")
    pokemon_types = _read_pokeapi_csv("pokemon_types.csv")
    types = _read_pokeapi_csv("types.csv")
    english_names = _species_names(9)
    german_names = _species_names(6)

    species = species[species["id"].between(1, MAX_DEX_NUMBER)].copy()
    pokemon = pokemon[pokemon["is_default"] == 1].copy()
    type_names = dict(zip(types["id"].astype(int), types["identifier"].astype(str)))
    pokemon_by_species = pokemon.drop_duplicates("species_id").set_index("species_id")["id"].astype(int).to_dict()

    type_lookup: dict[int, dict[int, str]] = {}
    for _, row in pokemon_types.iterrows():
        pokemon_id = int(row["pokemon_id"])
        slot = int(row["slot"])
        type_lookup.setdefault(pokemon_id, {})[slot] = type_names.get(int(row["type_id"]), "")

    rows: list[dict[str, object]] = []
    for _, row in species.sort_values("id").iterrows():
        dex_number = int(row["id"])
        generation_id = int(row["generation_id"])
        pokemon_id = pokemon_by_species.get(dex_number)
        type_slots = type_lookup.get(int(pokemon_id), {}) if pokemon_id is not None else {}
        in_pogo = dex_number in pogo_species_numbers
        rows.append(
            {
                "dex_number": dex_number,
                "name": english_names.get(dex_number, str(row["identifier"]).replace("-", " ").title()),
                "german_name": german_names.get(dex_number, ""),
                "region": _region_for_species(dex_number, generation_id),
                "type_1": type_slots.get(1, ""),
                "type_2": type_slots.get(2, ""),
                "available_in_pogo": "yes" if in_pogo else "no",
                "location_restriction": "",
                "last_event": "",
                "last_event_date": "",
                "extra_info": "",
            }
        )
    seeded = pd.DataFrame(rows, columns=POKEMON_CATALOG_COLUMNS)
    return apply_catalog_community_fields(
        seeded,
        released_dex_numbers=set(pogo_species_numbers),
        community_days=community_days or [],
    )


def update_catalog(
    path: Path | None = None,
    overwrite_editable: bool = False,
    availability_path: Path | None = None,
) -> pd.DataFrame:
    target = path or pokemon_catalog_path()
    pogoapi = load_pogoapi_seed_data()
    released_numbers = pogoapi_released_dex_numbers(pogoapi["released"])
    pvpoke_megas: list[tuple[int, str]] = []
    pvpoke_payload = _load_pvpoke_pokemon()
    if pvpoke_payload is not None:
        try:
            pvpoke_megas = extract_pvpoke_mega_forms(pvpoke_payload)
        except Exception:
            pvpoke_megas = []
    seeded = build_seed_catalog(
        released_dex_numbers=released_numbers,
        community_days=list(pogoapi["community_days"]),
    )
    existing = load_pokemon_catalog(target)
    merged = merge_pokemon_catalog(seeded, existing, preserve_editable=not overwrite_editable)
    merged = apply_catalog_community_fields(
        merged,
        community_days=list(pogoapi["community_days"]),
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(target, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)

    availability_target = availability_path or pokedex_category_availability_path()
    base_megas = pogoapi["mega_forms"] if isinstance(pogoapi["mega_forms"], list) else None
    mega_forms = _union_mega_forms(base_megas, pvpoke_megas)
    gmax_dex = pogoapi["gmax"]
    seeded_availability = build_category_availability_rows(
        shiny_dex=pogoapi["shiny"],
        shadow_dex=pogoapi["shadow"],
        mega_forms=mega_forms if isinstance(mega_forms, list) else None,
        gmax_dex=gmax_dex if gmax_dex else None,
    )
    existing_availability = load_pokedex_category_availability(availability_target)
    seeded_availability = preserve_unavailable_category_rows(
        seeded_availability,
        existing_availability,
        mega_forms=mega_forms if isinstance(mega_forms, list) else None,
        gmax_dex=gmax_dex if isinstance(gmax_dex, set) else None,
    )
    merged_availability = merge_pokedex_category_availability(
        seeded_availability,
        existing_availability,
        preserve_editable=not overwrite_editable,
    )
    availability_target.parent.mkdir(parents=True, exist_ok=True)
    merged_availability.to_csv(availability_target, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh inputs/reference/pokemon_catalog.csv from external Pokemon data.")
    parser.add_argument("--output", type=Path, default=pokemon_catalog_path(), help="Catalog CSV path to write.")
    parser.add_argument(
        "--availability-output",
        type=Path,
        default=pokedex_category_availability_path(),
        help="Category availability CSV path to write.",
    )
    parser.add_argument(
        "--overwrite-editable",
        action="store_true",
        help="Overwrite editable columns instead of preserving existing local edits.",
    )
    args = parser.parse_args()

    catalog = update_catalog(
        args.output,
        overwrite_editable=args.overwrite_editable,
        availability_path=args.availability_output,
    )
    print(f"Wrote {len(catalog)} Pokemon rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
