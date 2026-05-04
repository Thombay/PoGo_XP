from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path
from urllib.request import urlopen

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.paths import pokemon_catalog_path
from webapp.data_files import POKEMON_CATALOG_COLUMNS, load_pokemon_catalog, merge_pokemon_catalog

POKEAPI_CSV_BASE = "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv"
POKEMINERS_GAME_MASTER_URL = (
    "https://raw.githubusercontent.com/pokemongo-dev-contrib/pokemongo-game-master/"
    "master/versions/latest/V2_GAME_MASTER.json"
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
    with urlopen(url, timeout=60) as response:
        return response.read().decode("utf-8")


def _read_pokeapi_csv(name: str) -> pd.DataFrame:
    text = _read_url_text(f"{POKEAPI_CSV_BASE}/{name}")
    return pd.read_csv(io.StringIO(text))


def _species_names(local_language_id: int) -> dict[int, str]:
    names = _read_pokeapi_csv("pokemon_species_names.csv")
    names = names[names["local_language_id"] == int(local_language_id)].copy()
    return dict(zip(names["pokemon_species_id"].astype(int), names["name"].astype(str)))


def _load_pogo_species_numbers() -> set[int]:
    try:
        payload = json.loads(_read_url_text(POKEMINERS_GAME_MASTER_URL))
    except Exception:
        return set()

    templates = payload.get("template", payload) if isinstance(payload, dict) else payload
    numbers: set[int] = set()
    for item in templates:
        if not isinstance(item, dict):
            continue
        template_id = str(item.get("templateId", ""))
        match = re.search(r"(?:FORMS_)?V(\d{4})_POKEMON_", template_id)
        if not match:
            continue
        dex_number = int(match.group(1))
        if 1 <= dex_number <= MAX_DEX_NUMBER:
            numbers.add(dex_number)
    return numbers


def build_seed_catalog() -> pd.DataFrame:
    species = _read_pokeapi_csv("pokemon_species.csv")
    pokemon = _read_pokeapi_csv("pokemon.csv")
    pokemon_types = _read_pokeapi_csv("pokemon_types.csv")
    types = _read_pokeapi_csv("types.csv")
    english_names = _species_names(9)
    german_names = _species_names(6)
    pogo_species_numbers = _load_pogo_species_numbers()

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
                "available_in_pogo": "yes" if in_pogo else "unknown",
                "extra_info": "",
            }
        )
    return pd.DataFrame(rows, columns=POKEMON_CATALOG_COLUMNS)


def update_catalog(path: Path | None = None, overwrite_editable: bool = False) -> pd.DataFrame:
    target = path or pokemon_catalog_path()
    seeded = build_seed_catalog()
    existing = load_pokemon_catalog(target)
    merged = merge_pokemon_catalog(seeded, existing, preserve_editable=not overwrite_editable)
    target.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(target, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh inputs/reference/pokemon_catalog.csv from external Pokemon data.")
    parser.add_argument("--output", type=Path, default=pokemon_catalog_path(), help="Catalog CSV path to write.")
    parser.add_argument(
        "--overwrite-editable",
        action="store_true",
        help="Overwrite editable columns instead of preserving existing local edits.",
    )
    args = parser.parse_args()

    catalog = update_catalog(args.output, overwrite_editable=args.overwrite_editable)
    print(f"Wrote {len(catalog)} Pokemon rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
