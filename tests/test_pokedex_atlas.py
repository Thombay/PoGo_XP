from __future__ import annotations

import tempfile
import unittest
from datetime import date
from html import escape
from pathlib import Path

import pandas as pd  # type: ignore[import-untyped]

from webapp.data_files import (
    load_pokedex_species_entries,
    merge_pokedex_category_availability,
    merge_pokemon_catalog,
)
from tools.update_pokemon_catalog import preserve_unavailable_category_rows
from webapp.atlas_card_events import atlas_card_event_dex
from webapp.pokedex import (
    ATLAS_COMPARISON_KINDS,
    ATLAS_ENTRY_KINDS,
    apply_catalog_community_fields,
    build_category_availability_rows,
    build_missing_pokemon_rows,
    build_pokedex_atlas_cards,
    build_species_missing_summary,
    build_species_progress_rows,
    build_species_region_counts,
    category_target_dex_numbers,
    extract_gigantamax_dex_numbers,
    extract_mega_forms,
    extract_pogoapi_dex_numbers,
    extract_pvpoke_mega_forms,
    extract_pvpoke_released_dex_numbers,
    filter_atlas_cards_by_release,
    latest_community_day_by_dex,
    latest_pokedex_species_state,
    normalize_pokemon_name,
    pokedex_atlas_html,
    pokemon_sprite_url,
    compact_pokedex_species_rows,
    species_rows_delta_from_atlas_editor,
    species_rows_from_card_registration,
    upsert_pokedex_species_rows,
)


def _catalog_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "dex_number": 1,
                "name": "Bulbasaur",
                "german_name": "Bisasam",
                "region": "kanto",
                "type_1": "grass",
                "type_2": "poison",
                "available_in_pogo": "yes",
                "location_restriction": "",
                "last_event": "",
                "last_event_date": "",
                "extra_info": "",
            },
            {
                "dex_number": 2,
                "name": "Ivysaur",
                "german_name": "Bisaknosp",
                "region": "kanto",
                "type_1": "grass",
                "type_2": "poison",
                "available_in_pogo": "yes",
                "location_restriction": "",
                "last_event": "",
                "last_event_date": "",
                "extra_info": "",
            },
            {
                "dex_number": 83,
                "name": "Farfetch'd",
                "german_name": "Porenta",
                "region": "kanto",
                "type_1": "fighting",
                "type_2": "flying",
                "available_in_pogo": "yes",
                "location_restriction": "",
                "last_event": "",
                "last_event_date": "",
                "extra_info": "",
            },
            {
                "dex_number": 1025,
                "name": "Pecharunt",
                "german_name": "Infamomo",
                "region": "paldea",
                "type_1": "poison",
                "type_2": "ghost",
                "available_in_pogo": "no",
                "location_restriction": "",
                "last_event": "",
                "last_event_date": "",
                "extra_info": "",
            },
        ]
    )


def _mon(dex_number: int, name: str, region: str, available: str = "yes") -> dict[str, object]:
    return {
        "dex_number": dex_number,
        "name": name,
        "german_name": name,
        "region": region,
        "type_1": "grass",
        "type_2": "",
        "available_in_pogo": available,
        "location_restriction": "",
        "last_event": "",
        "last_event_date": "",
        "extra_info": "",
    }


def _species(
    account: str,
    entry_type: str,
    dex_number: int,
    registered: bool = True,
    date: str = "2026-04-01",
) -> dict[str, object]:
    return {
        "date": date,
        "account": account,
        "entry_type": entry_type,
        "dex_number": dex_number,
        "registered": registered,
        "can_evolve_now": False,
        "notes": "",
    }


def _availability(entries: list[tuple[str, int, bool]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"entry_type": entry_type, "dex_number": dex_number, "available": available, "notes": ""}
            for entry_type, dex_number, available in entries
        ]
    )


def _evolutions(edges: list[tuple[int, int] | tuple[int, int, str]]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for edge in edges:
        source = edge[0]
        target = edge[1]
        form = edge[2] if len(edge) > 2 else ""
        rows.append(
            {
                "source_dex_number": source,
                "target_dex_number": target,
                "method": "",
                "source_form": form,
                "notes": "",
            }
        )
    return pd.DataFrame(rows)


def _iso_dates(frame: pd.DataFrame) -> list[str]:
    return pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d").tolist()


_SUMMARY_COLUMNS = [
    "account",
    "entry_type",
    "entry_type_label",
    "target_count",
    "registered_count",
    "missing_count",
]


class PokedexAtlasTest(unittest.TestCase):
    def test_load_species_entries_missing_file_returns_expected_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.csv"
            loaded = load_pokedex_species_entries(path)

        self.assertTrue(loaded.empty)
        self.assertEqual(
            loaded.columns.tolist(),
            ["date", "account", "entry_type", "dex_number", "form", "registered", "can_evolve_now", "notes"],
        )

    def test_load_species_entries_parses_boolean_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "species.csv"
            pd.DataFrame(
                [
                    {
                        "date": "2026-01-01",
                        "account": "Thombay",
                        "entry_type": "pokemon",
                        "dex_number": "1",
                        "registered": "yes",
                        "can_evolve_now": "0",
                        "notes": "starter",
                    }
                ]
            ).to_csv(path, index=False, encoding="utf-8-sig")
            loaded = load_pokedex_species_entries(path)

        self.assertTrue(bool(loaded.iloc[0]["registered"]))
        self.assertFalse(bool(loaded.iloc[0]["can_evolve_now"]))
        self.assertEqual(int(loaded.iloc[0]["dex_number"]), 1)
        self.assertEqual(loaded.iloc[0]["form"], "")

    def test_latest_species_state_keeps_newest_row(self):
        species = pd.DataFrame(
            [
                {
                    "date": "2026-01-01",
                    "account": "Thombay",
                    "entry_type": "pokemon",
                    "dex_number": 1,
                    "registered": False,
                    "can_evolve_now": False,
                    "notes": "old",
                },
                {
                    "date": "2026-02-01",
                    "account": "Thombay",
                    "entry_type": "pokemon",
                    "dex_number": 1,
                    "registered": True,
                    "can_evolve_now": True,
                    "notes": "new",
                },
            ]
        )

        latest = latest_pokedex_species_state(species, accounts=["Thombay"], entry_types=["pokemon"])

        self.assertEqual(len(latest), 1)
        self.assertTrue(bool(latest.iloc[0]["registered"]))
        self.assertEqual(latest.iloc[0]["notes"], "new")

    def test_missing_list_treats_absent_row_as_missing(self):
        catalog = _catalog_rows()
        species = pd.DataFrame(
            [
                {
                    "date": "2026-03-01",
                    "account": "Thombay",
                    "entry_type": "pokemon",
                    "dex_number": 1,
                    "registered": True,
                    "can_evolve_now": False,
                    "notes": "",
                }
            ]
        )

        missing = build_missing_pokemon_rows(
            catalog,
            species,
            account="Thombay",
            entry_type="pokemon",
            regions=["kanto"],
        )

        self.assertEqual(missing["dex_number"].tolist(), [2, 83])
        self.assertFalse(bool(missing["registered"].any()))

    def test_missing_list_does_not_need_aggregate_counts(self):
        missing = build_missing_pokemon_rows(
            _catalog_rows(),
            pd.DataFrame(columns=["date", "account", "entry_type", "dex_number", "registered", "can_evolve_now", "notes"]),
            account="Cerius",
            entry_type="pokemon",
        )
        self.assertEqual(set(missing["dex_number"].tolist()), {1, 2, 83, 1025})

    def test_shiny_targets_use_availability_rows(self):
        catalog = _catalog_rows()
        availability = pd.DataFrame(
            [
                {"entry_type": "shiny", "dex_number": 1, "available": True, "notes": ""},
                {"entry_type": "shiny", "dex_number": 83, "available": False, "notes": ""},
            ]
        )
        self.assertEqual(category_target_dex_numbers("shiny", catalog, availability), {1})
        self.assertEqual(category_target_dex_numbers("pokemon", catalog, availability), {1, 2, 83, 1025})

        missing = build_missing_pokemon_rows(
            catalog,
            pd.DataFrame(columns=["date", "account", "entry_type", "dex_number", "registered", "can_evolve_now", "notes"]),
            account="Thombay",
            entry_type="shiny",
            availability_df=availability,
        )
        self.assertEqual(missing["dex_number"].tolist(), [1])

    def test_merge_catalog_preserves_nonempty_last_event(self):
        seeded = _catalog_rows()
        seeded.loc[seeded["dex_number"] == 1, "last_event"] = "Community Day 99"
        seeded.loc[seeded["dex_number"] == 1, "last_event_date"] = "2026-01-01"
        existing = _catalog_rows()
        existing.loc[existing["dex_number"] == 1, "last_event"] = "Keep this"
        existing.loc[existing["dex_number"] == 1, "last_event_date"] = "2020-01-01"
        existing.loc[existing["dex_number"] == 1, "location_restriction"] = "Local note"

        merged = merge_pokemon_catalog(seeded, existing)
        row = merged[merged["dex_number"] == 1].iloc[0]
        self.assertEqual(row["last_event"], "Keep this")
        self.assertEqual(row["last_event_date"], "2020-01-01")
        self.assertEqual(row["location_restriction"], "Local note")

    def test_empty_existing_event_does_not_block_seed(self):
        seeded = _catalog_rows()
        seeded.loc[seeded["dex_number"] == 1, "last_event"] = "Community Day 1"
        existing = _catalog_rows()
        merged = merge_pokemon_catalog(seeded, existing)
        self.assertEqual(merged[merged["dex_number"] == 1].iloc[0]["last_event"], "Community Day 1")

    def test_sprite_url_and_community_day_name_matching(self):
        self.assertEqual(
            pokemon_sprite_url(25),
            "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/25.png",
        )
        self.assertEqual(normalize_pokemon_name("Farfetch’d"), normalize_pokemon_name("Farfetch'd"))
        catalog = _catalog_rows()
        events = latest_community_day_by_dex(
            catalog,
            [
                {
                    "community_day_number": 1,
                    "start_date": "2018-01-20",
                    "boosted_pokemon": ["Bulbasaur"],
                },
                {
                    "community_day_number": 40,
                    "start_date": "2024-08-24",
                    "boosted_pokemon": ["Farfetch'd"],
                },
                {
                    "community_day_number": 12,
                    "start_date": "2020-01-01",
                    "boosted_pokemon": ["Farfetch’d"],
                },
            ],
        )
        self.assertEqual(events[1], ("Community Day 1", "2018-01-20"))
        self.assertEqual(events[83][1], "2024-08-24")

        enriched = apply_catalog_community_fields(catalog, community_days=[{"start_date": "2024-08-24", "boosted_pokemon": ["Bulbasaur"]}])
        self.assertEqual(enriched[enriched["dex_number"] == 1].iloc[0]["last_event"], "Community Day")
        self.assertEqual(enriched[enriched["dex_number"] == 83].iloc[0]["location_restriction"], "East Asia")

    def test_pogoapi_id_extraction_and_category_availability_merge(self):
        numbers = extract_pogoapi_dex_numbers(
            {
                "1": {"id": 1, "name": "Bulbasaur"},
                "25": {"pokemon_id": 25, "name": "Pikachu"},
            }
        )
        self.assertEqual(numbers, {1, 25})
        seeded = build_category_availability_rows(shiny_dex={1, 4}, shadow_dex={1})
        existing = pd.DataFrame(
            [{"entry_type": "shiny", "dex_number": 1, "available": False, "notes": "keep notes"}]
        )
        merged = merge_pokedex_category_availability(seeded, existing)
        shiny_one = merged[(merged["entry_type"] == "shiny") & (merged["dex_number"] == 1)].iloc[0]
        self.assertFalse(bool(shiny_one["available"]))
        self.assertEqual(shiny_one["notes"], "keep notes")
        self.assertEqual(shiny_one["form"], "")

    def test_extract_mega_forms_keeps_each_form(self):
        payload = [
            {"pokemon_id": 6, "pokemon_name": "Charizard", "form": "X", "mega_name": "Mega Charizard X"},
            {"pokemon_id": 6, "pokemon_name": "Charizard", "form": "Y", "mega_name": "Mega Charizard Y"},
            {"pokemon_id": 6, "form": "Normal"},
            {"pokemon_id": 9},
            {"pokemon_id": 0, "form": "X"},
            {"id": -1, "form": "Y"},
        ]
        self.assertEqual(
            extract_mega_forms(payload),
            [(6, "X"), (6, "Y"), (6, "Normal"), (9, "")],
        )

    def test_extract_pvpoke_released_dex_numbers_and_mega_forms(self):
        payload = [
            {"dex": 807, "speciesId": "zeraora", "speciesName": "Zeraora"},
            {"dex": 6, "speciesId": "charizard", "speciesName": "Charizard"},
            {"dex": 26, "speciesId": "raichu", "speciesName": "Raichu"},
            {"dex": 26, "speciesId": "raichu_alolan", "speciesName": "Raichu (Alolan)"},
            {"dex": 26, "speciesId": "raichu_mega_x", "speciesName": "Raichu (Mega X)"},
            {"dex": 26, "speciesId": "RAICHU_MEGA_X", "speciesName": "Raichu (Mega X)"},
            {"dex": 149, "speciesId": "dragonite_mega", "speciesName": "Dragonite (Mega)"},
            {"dex": 150, "speciesId": "mewtwo_mega_y", "speciesName": "Mewtwo (Mega Y)"},
            "not-a-dict",
            {"dex": 0, "speciesId": "missingno"},
            {"speciesId": "no_dex"},
            {"dex": 0, "speciesId": "abomasnow_mega"},
            {"speciesId": "beedrill_mega"},
        ]
        released = extract_pvpoke_released_dex_numbers(payload)
        self.assertIn(807, released)
        self.assertIn(6, released)
        self.assertEqual(released, {6, 26, 807})
        self.assertEqual(
            extract_pvpoke_released_dex_numbers({"pokemon": payload}),
            {6, 26, 807},
        )
        self.assertEqual(extract_pvpoke_released_dex_numbers({"other": payload}), set())
        mega_only = [{"dex": 149, "speciesId": "dragonite_mega", "speciesName": "Dragonite (Mega)"}]
        self.assertNotIn(149, extract_pvpoke_released_dex_numbers(mega_only))
        self.assertEqual(
            extract_pvpoke_mega_forms(payload),
            [(26, "X"), (149, "Normal"), (150, "Y")],
        )
        self.assertEqual(extract_pvpoke_mega_forms([{"dex": 6, "speciesId": "charizard"}]), [])
        self.assertEqual(
            extract_pvpoke_mega_forms([{"dex": 6, "speciesId": "charizard_MEGA_X"}]),
            [(6, "X")],
        )

    def test_extract_gigantamax_dex_numbers(self):
        payload = {
            "template": [
                {"templateId": "FORMS_V0006_POKEMON_CHARIZARD_GIGANTAMAX"},
                {"templateId": "V0003_POKEMON_VENUSAUR"},
            ]
        }
        self.assertEqual(extract_gigantamax_dex_numbers(payload), {6})
        self.assertEqual(extract_gigantamax_dex_numbers(payload["template"]), {6})
        self.assertEqual(
            extract_gigantamax_dex_numbers(
                [
                    {"templateId": "FORMS_V0009_POKEMON_BLASTOISE_Gigantamax"},
                    {"templateId": "FORMS_V1026_POKEMON_FUTURE_GIGANTAMAX"},
                    {"templateId": "FORMS_V0000_POKEMON_MISSINGNO_GIGANTAMAX"},
                ]
            ),
            {9},
        )
        current = [
            {"templateId": "V0003_POKEMON_VENUSAUR"},
            {"templateId": "V0888_POKEMON_ZACIAN"},
            {"templateId": "VN_BM_045", "data": {"moveSettings": {"movementId": "VN_BM_045", "vfxName": "gmax_vinelash"}}},
            {"templateId": "VN_BM_060", "data": {"moveSettings": {"movementId": "VN_BM_060", "vfxName": "max_behemoth_blade"}}},
            {
                "templateId": "SOURDOUGH_MOVE_MAPPING_SETTINGS",
                "data": {
                    "sourdoughMoveMappingSettings": {
                        "mappings": [
                            {"pokemonId": "VENUSAUR", "move": "VN_BM_045"},
                            {"pokemonId": "ZACIAN", "move": "VN_BM_060"},
                            {"pokemonId": "NOT_IN_THE_MASTER", "move": "VN_BM_045"},
                        ]
                    }
                },
            },
        ]
        self.assertEqual(extract_gigantamax_dex_numbers(current), {3})

    def test_mega_forms_survive_merge_and_blank_mega_is_removed(self):
        seeded = build_category_availability_rows(
            shiny_dex={1},
            mega_dex={3},
            mega_forms=[(6, "Y"), (6, "X")],
            gmax_dex={6},
        )
        mega = seeded[seeded["entry_type"] == "mega"]
        self.assertEqual(mega["dex_number"].tolist(), [6, 6])
        self.assertEqual(mega["form"].tolist(), ["X", "Y"])
        self.assertTrue(mega["form"].tolist().count("X") == 1)
        self.assertEqual(seeded.loc[seeded["entry_type"] == "shiny", "form"].iloc[0], "")
        self.assertEqual(seeded.loc[seeded["entry_type"] == "gmax", "form"].iloc[0], "")
        self.assertNotIn(3, mega["dex_number"].tolist())

        existing = pd.DataFrame(
            [
                {"entry_type": "mega", "dex_number": 6, "form": "", "available": False, "notes": "legacy"},
                {"entry_type": "mega", "dex_number": 6, "form": "X", "available": False, "notes": "keep x"},
            ]
        )
        merged = merge_pokedex_category_availability(seeded, existing)
        merged_mega = merged[merged["entry_type"] == "mega"]
        self.assertEqual(merged_mega["form"].tolist(), ["X", "Y"])
        self.assertNotIn("", merged_mega["form"].tolist())
        kept_x = merged_mega[merged_mega["form"] == "X"].iloc[0]
        kept_y = merged_mega[merged_mega["form"] == "Y"].iloc[0]
        self.assertFalse(bool(kept_x["available"]))
        self.assertEqual(kept_x["notes"], "keep x")
        self.assertTrue(bool(kept_y["available"]))
        self.assertEqual(kept_y["notes"], "")

        with_blank = pd.concat(
            [
                seeded,
                pd.DataFrame(
                    [{"entry_type": "mega", "dex_number": 6, "form": "", "available": True, "notes": "blank"}]
                ),
            ],
            ignore_index=True,
        )
        merged_blank = merge_pokedex_category_availability(with_blank, existing)
        blank_mega = merged_blank[merged_blank["entry_type"] == "mega"]
        self.assertEqual(blank_mega["form"].tolist(), ["X", "Y"])
        self.assertEqual(merged_blank.loc[merged_blank["entry_type"] == "shiny", "form"].tolist(), [""])
        self.assertEqual(merged_blank.loc[merged_blank["entry_type"] == "gmax", "form"].tolist(), [""])

    def test_mega_dex_without_forms_keeps_blank_form(self):
        seeded = build_category_availability_rows(mega_dex={6})
        self.assertEqual(seeded.iloc[0]["form"], "")
        merged = merge_pokedex_category_availability(
            seeded,
            pd.DataFrame([{"entry_type": "mega", "dex_number": 6, "available": False, "notes": "legacy"}]),
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged.iloc[0]["form"], "")
        self.assertEqual(merged.iloc[0]["notes"], "legacy")
        self.assertFalse(bool(merged.iloc[0]["available"]))

    def test_failed_mega_and_gmax_seeds_keep_existing_rows(self):
        seeded = build_category_availability_rows(shiny_dex={1})
        existing = pd.DataFrame(
            [
                {"entry_type": "mega", "dex_number": 6, "form": "", "available": False, "notes": "mega"},
                {"entry_type": "mega", "dex_number": 3, "form": "", "available": True, "notes": "venusaur"},
                {"entry_type": "gmax", "dex_number": 6, "form": "", "available": False, "notes": "gmax"},
                {"entry_type": "shiny", "dex_number": 1, "available": False, "notes": "shiny"},
            ]
        )
        for mega_forms, gmax_dex in ((None, None), ([], set())):
            assembled = preserve_unavailable_category_rows(
                seeded,
                existing,
                mega_forms=mega_forms,
                gmax_dex=gmax_dex,
            )
            merged = merge_pokedex_category_availability(assembled, existing)
            mega = merged[merged["entry_type"] == "mega"].sort_values("dex_number")
            self.assertEqual(mega["dex_number"].tolist(), [3, 6])
            self.assertEqual(set(mega["form"].tolist()), {""})
            gmax = merged[merged["entry_type"] == "gmax"]
            self.assertEqual(int(gmax.iloc[0]["dex_number"]), 6)
            self.assertEqual(gmax.iloc[0]["notes"], "gmax")
            self.assertFalse(bool(gmax.iloc[0]["available"]))
            shiny = merged[(merged["entry_type"] == "shiny") & (merged["dex_number"] == 1)].iloc[0]
            self.assertEqual(shiny["form"], "")
            self.assertEqual(shiny["notes"], "shiny")
            self.assertFalse(bool(shiny["available"]))

    def test_formed_mega_seed_drops_only_matching_blank_mega_rows(self):
        seeded = build_category_availability_rows(mega_forms=[(6, "X"), (6, "Y")], gmax_dex={6})
        existing = pd.DataFrame(
            [
                {"entry_type": "mega", "dex_number": 6, "form": "", "available": False, "notes": "legacy"},
                {"entry_type": "mega", "dex_number": 3, "form": "", "available": False, "notes": "keep venusaur"},
                {"entry_type": "mega", "dex_number": 6, "form": "X", "available": False, "notes": "keep x"},
                {"entry_type": "gmax", "dex_number": 3, "form": "", "available": True, "notes": "old gmax"},
            ]
        )
        assembled = preserve_unavailable_category_rows(
            seeded,
            existing,
            mega_forms=[(6, "X"), (6, "Y")],
            gmax_dex={6},
        )
        merged = merge_pokedex_category_availability(assembled, existing)
        mega = merged[merged["entry_type"] == "mega"]
        self.assertEqual(sorted(mega["form"].tolist()), ["", "X", "Y"])
        venusaur = mega[mega["form"] == ""].iloc[0]
        self.assertEqual(int(venusaur["dex_number"]), 3)
        self.assertEqual(venusaur["notes"], "keep venusaur")
        charizard_x = mega[mega["form"] == "X"].iloc[0]
        self.assertFalse(bool(charizard_x["available"]))
        self.assertEqual(charizard_x["notes"], "keep x")
        charizard_y = mega[mega["form"] == "Y"].iloc[0]
        self.assertEqual(charizard_y["notes"], "")
        self.assertTrue(bool(charizard_y["available"]))
        gmax = merged[merged["entry_type"] == "gmax"]
        self.assertEqual(gmax["dex_number"].tolist(), [6])
        self.assertNotIn(3, gmax["dex_number"].tolist())

    def test_species_upsert_and_latest_keep_distinct_forms(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "species.csv"
            written = upsert_pokedex_species_rows(
                path,
                [
                    {
                        "date": "2026-01-01",
                        "account": "Thombay",
                        "entry_type": "mega",
                        "dex_number": 6,
                        "form": "X",
                        "registered": False,
                        "can_evolve_now": False,
                        "notes": "old",
                    },
                    {
                        "date": "2026-02-01",
                        "account": "Thombay",
                        "entry_type": "mega",
                        "dex_number": 6,
                        "form": "X",
                        "registered": False,
                        "can_evolve_now": False,
                        "notes": "loser",
                    },
                    {
                        "date": "2026-02-01",
                        "account": "Thombay",
                        "entry_type": "mega",
                        "dex_number": 6,
                        "form": "Y",
                        "registered": True,
                        "can_evolve_now": False,
                        "notes": "y",
                    },
                    {
                        "date": "2026-02-01",
                        "account": "Thombay",
                        "entry_type": "mega",
                        "dex_number": 6,
                        "form": "x",
                        "registered": True,
                        "can_evolve_now": False,
                        "notes": "winner",
                    },
                ],
            )
            loaded = load_pokedex_species_entries(path)

        self.assertEqual(written, 3)
        self.assertEqual(len(loaded), 3)
        january = loaded[pd.to_datetime(loaded["date"]).dt.strftime("%Y-%m-%d") == "2026-01-01"]
        self.assertEqual(january.iloc[0]["form"], "X")
        self.assertEqual(january.iloc[0]["notes"], "old")
        latest = latest_pokedex_species_state(loaded, accounts=["Thombay"], entry_types=["mega"])
        self.assertEqual(len(latest), 2)
        by_form = {str(row.form).casefold(): row for row in latest.itertuples(index=False)}
        self.assertEqual(set(by_form), {"x", "y"})
        self.assertEqual(by_form["x"].form, "x")
        self.assertEqual(by_form["x"].notes, "winner")
        self.assertTrue(bool(by_form["x"].registered))
        self.assertEqual(by_form["y"].notes, "y")
        self.assertTrue(bool(by_form["y"].registered))

    def test_atlas_cards_mark_unregistered_as_missing(self):
        self.assertEqual(
            ATLAS_ENTRY_KINDS,
            (
                ("pokemon", "Pokemon"),
                ("shiny", "Shiny"),
                ("hundo", "100%"),
                ("lucky", "Lucky"),
                ("xxl", "XXL"),
                ("xxs", "XXS"),
                ("shadow", "Shadow"),
                ("purified", "Purified"),
            ),
        )
        catalog = _catalog_rows()
        species = pd.DataFrame([_species("Thombay", "pokemon", 1)])
        cards = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            region="kanto",
        )
        by_dex = cards.set_index("dex_number")
        other_labels = ", ".join(label for kind, label in ATLAS_ENTRY_KINDS if kind != "pokemon")
        all_labels = ", ".join(label for _kind, label in ATLAS_ENTRY_KINDS)
        self.assertEqual(by_dex.loc[1, "status"], "missing")
        self.assertEqual(by_dex.loc[1, "status_label"], f"Missing: {other_labels}")
        self.assertEqual(by_dex.loc[1, "missing_kinds"], other_labels)
        self.assertEqual(by_dex.loc[1, "registered_pokemon"], True)
        self.assertEqual(bool(by_dex.loc[1, "registered"]), False)
        self.assertEqual(by_dex.loc[2, "status"], "missing")
        self.assertEqual(by_dex.loc[2, "status_label"], f"Missing: {all_labels}")
        self.assertEqual(by_dex.loc[2, "registered_pokemon"], False)
        self.assertTrue(str(by_dex.loc[1, "sprite_url"]).endswith("/1.png"))
        for kind, _label in ATLAS_ENTRY_KINDS:
            self.assertIn(f"registered_{kind}", cards.columns)
            self.assertEqual(cards[f"registered_{kind}"].dtype.name, "boolean")

        kanto_html = pokedex_atlas_html(cards)
        self.assertIn("XXL", kanto_html)
        self.assertNotIn("Xxl", kanto_html)
        self.assertIn("pogo-dex-card--missing", kanto_html)

        searched = build_pokedex_atlas_cards(catalog, species, account="Thombay", region="kanto", search="ivy")
        self.assertEqual(searched["dex_number"].tolist(), [2])

        paldea = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            region="paldea",
        )
        pecharunt = paldea.set_index("dex_number").loc[1025]
        self.assertEqual(pecharunt["status"], "unavailable")
        self.assertEqual(pecharunt["status_label"], "Not in GO")
        self.assertEqual(pecharunt["missing_kinds"], "")
        self.assertTrue(pd.isna(pecharunt["registered_pokemon"]))
        self.assertTrue(pd.isna(pecharunt["registered_shiny"]))
        paldea_html = pokedex_atlas_html(paldea)
        self.assertIn("Not in GO", paldea_html)
        self.assertNotIn("Not In Go", paldea_html)
        self.assertIn("pogo-dex-card--unavailable", paldea_html)

        unavailable = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            region="paldea",
            status_filter="not in go",
        )
        self.assertEqual(unavailable["dex_number"].tolist(), [1025])

    def test_shiny_registration_does_not_clear_pokemon_missing(self):
        catalog = pd.DataFrame([_mon(1, "Bulbasaur", "kanto")])
        species = pd.DataFrame([_species("Thombay", "shiny", 1)])
        summary = build_species_missing_summary(
            catalog,
            species,
            accounts=["Thombay"],
            regions=["overall", "Kanto"],
        )
        self.assertEqual(summary["entry_type"].tolist(), [kind for kind, _label in ATLAS_ENTRY_KINDS])
        pokemon = summary[summary["entry_type"] == "pokemon"].iloc[0]
        shiny = summary[summary["entry_type"] == "shiny"].iloc[0]
        self.assertEqual(int(pokemon["target_count"]), 1)
        self.assertEqual(int(pokemon["registered_count"]), 0)
        self.assertEqual(int(pokemon["missing_count"]), 1)
        self.assertEqual(int(shiny["registered_count"]), 1)
        self.assertEqual(int(shiny["missing_count"]), 0)

        cards = build_pokedex_atlas_cards(catalog, species, account="Thombay", region="Kanto")
        row = cards.set_index("dex_number").loc[1]
        self.assertEqual(row["registered_pokemon"], False)
        self.assertNotEqual(row["registered_pokemon"], True)
        self.assertEqual(row["registered_shiny"], True)
        self.assertEqual(row["status"], "missing")
        self.assertIn("Pokemon", row["status_label"])
        self.assertNotEqual(row["status_label"], "Missing: Shiny")
        self.assertNotIn("Shiny", row["missing_kinds"].split(", "))

    def test_species_without_shiny_availability_is_not_missing_shiny(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(25, "Pikachu", "kanto"),
            ]
        )
        availability = _availability([("shiny", 25, True)])
        summary = build_species_missing_summary(
            catalog,
            pd.DataFrame(),
            accounts=["Thombay"],
            regions=["kanto"],
            availability_df=availability,
        )
        shiny = summary[summary["entry_type"] == "shiny"].iloc[0]
        self.assertEqual(int(shiny["target_count"]), 1)
        self.assertEqual(int(shiny["missing_count"]), 1)

        cards = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame(),
            account="Thombay",
            region="Kanto",
            availability_df=availability,
        )
        by_dex = cards.set_index("dex_number")
        self.assertEqual(cards["registered_shiny"].dtype.name, "boolean")
        self.assertTrue(pd.isna(by_dex.loc[1, "registered_shiny"]))
        self.assertNotIn("Shiny", str(by_dex.loc[1, "missing_kinds"]).split(", "))
        self.assertNotIn("Shiny", str(by_dex.loc[1, "status_label"]))
        self.assertIn("Shiny", str(by_dex.loc[25, "missing_kinds"]).split(", "))
        self.assertEqual(by_dex.loc[25, "registered_shiny"], False)

    def test_not_in_go_species_is_not_missing_pokemon(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto", "yes"),
                _mon(1025, "Pecharunt", "paldea", "no"),
            ]
        )
        species = pd.DataFrame([_species("Thombay", "pokemon", 1025, registered=True)])
        availability = _availability([("shiny", 1025, True)])
        summary = build_species_missing_summary(
            catalog,
            species,
            accounts=["Thombay"],
            availability_df=availability,
        )
        pokemon = summary[summary["entry_type"] == "pokemon"].iloc[0]
        shiny = summary[summary["entry_type"] == "shiny"].iloc[0]
        self.assertEqual(int(pokemon["target_count"]), 1)
        self.assertEqual(int(pokemon["registered_count"]), 0)
        self.assertEqual(int(pokemon["missing_count"]), 1)
        self.assertEqual(int(shiny["target_count"]), 0)
        self.assertEqual(int(shiny["missing_count"]), 0)

        cards = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            availability_df=availability,
        )
        pecharunt = cards.set_index("dex_number").loc[1025]
        self.assertEqual(pecharunt["status"], "unavailable")
        self.assertEqual(pecharunt["status_label"], "Not in GO")
        self.assertEqual(cards["registered_pokemon"].dtype.name, "boolean")
        self.assertTrue(pd.isna(pecharunt["registered_pokemon"]))
        self.assertTrue(pd.isna(pecharunt["registered_shiny"]))

    def test_summary_keeps_accounts_and_kinds_separate(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(2, "Ivysaur", "kanto"),
            ]
        )
        species = pd.DataFrame([_species("Thombay", "pokemon", 1)])
        summary = build_species_missing_summary(
            catalog,
            species,
            accounts=["Thombay", "Cerius"],
            entry_types=["SHINY", "Pokemon", "mega", "gmax"],
        )
        self.assertEqual(summary.columns.tolist(), _SUMMARY_COLUMNS)
        self.assertEqual(len(summary), 8)
        self.assertEqual(summary["account"].tolist(), ["Thombay"] * 4 + ["Cerius"] * 4)
        self.assertEqual(
            summary["entry_type"].tolist(),
            ["pokemon", "shiny", "gmax", "mega", "pokemon", "shiny", "gmax", "mega"],
        )
        self.assertEqual(
            summary["entry_type_label"].tolist(),
            ["Pokemon", "Shiny", "G-Max", "Mega", "Pokemon", "Shiny", "G-Max", "Mega"],
        )
        counts = {
            (row.account, row.entry_type): int(row.missing_count)
            for row in summary.itertuples(index=False)
        }
        self.assertEqual(counts[("Thombay", "pokemon")], 1)
        self.assertEqual(counts[("Cerius", "pokemon")], 2)
        self.assertEqual(counts[("Thombay", "shiny")], 2)
        self.assertEqual(counts[("Cerius", "shiny")], 2)
        self.assertEqual(counts[("Thombay", "mega")], 0)
        self.assertEqual(counts[("Thombay", "gmax")], 0)
        self.assertEqual(counts[("Cerius", "mega")], 0)
        self.assertEqual(counts[("Cerius", "gmax")], 0)
        self.assertNotIn(3, summary["missing_count"].tolist())
        self.assertNotIn(4, summary["missing_count"].tolist())

    def test_summary_empty_catalog_or_no_accounts_returns_columns(self):
        empty_catalog = build_species_missing_summary(pd.DataFrame(), pd.DataFrame(), accounts=["Thombay"])
        self.assertTrue(empty_catalog.empty)
        self.assertEqual(empty_catalog.columns.tolist(), _SUMMARY_COLUMNS)
        no_accounts = build_species_missing_summary(_catalog_rows(), pd.DataFrame(), accounts=[])
        self.assertTrue(no_accounts.empty)
        self.assertEqual(no_accounts.columns.tolist(), _SUMMARY_COLUMNS)

    def test_card_missing_text_names_unchecked_kinds(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(2, "Ivysaur", "kanto"),
            ]
        )
        disabled = ["lucky", "hundo", "xxs", "shadow", "purified"]
        availability = _availability(
            [("shiny", 1, True), ("shiny", 2, True), ("xxl", 1, True), ("xxl", 2, True)]
            + [(kind, 1, False) for kind in disabled]
        )
        species = pd.DataFrame(
            [
                _species("Thombay", "shiny", 1),
                _species("Thombay", "pokemon", 2),
                _species("Thombay", "shiny", 2),
                _species("Thombay", "xxl", 2),
            ]
        )
        cards = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            region="kanto",
            availability_df=availability,
            entry_type="lucky",
        )
        by_dex = cards.set_index("dex_number")
        bulbasaur = by_dex.loc[1]
        self.assertEqual(bulbasaur["status"], "missing")
        self.assertTrue(str(bulbasaur["status_label"]).startswith("Missing: "))
        self.assertEqual(bulbasaur["status_label"], "Missing: Pokemon, XXL")
        self.assertEqual(bulbasaur["missing_kinds"], "Pokemon, XXL")
        self.assertIn("Pokemon", bulbasaur["status_label"])
        self.assertIn("XXL", bulbasaur["status_label"])
        self.assertNotIn("Shiny", bulbasaur["missing_kinds"].split(", "))
        self.assertEqual(bulbasaur["registered_pokemon"], False)
        self.assertEqual(bulbasaur["registered_shiny"], True)
        self.assertEqual(bulbasaur["registered_xxl"], False)
        self.assertEqual(bool(bulbasaur["registered"]), False)
        for kind in disabled:
            self.assertTrue(pd.isna(bulbasaur[f"registered_{kind}"]))

        ivysaur = by_dex.loc[2]
        self.assertEqual(ivysaur["status"], "registered")
        self.assertEqual(ivysaur["status_label"], "Registered")
        self.assertEqual(ivysaur["missing_kinds"], "")
        self.assertEqual(bool(ivysaur["registered"]), True)
        self.assertEqual(ivysaur["registered_pokemon"], True)
        self.assertEqual(ivysaur["registered_shiny"], True)
        self.assertEqual(ivysaur["registered_xxl"], True)
        self.assertTrue(pd.isna(ivysaur["registered_lucky"]))

        html = pokedex_atlas_html(cards)
        self.assertIn("Missing: Pokemon, XXL", html)
        self.assertIn("pogo-dex-card--missing", html)
        self.assertIn("pogo-dex-card--registered", html)
        self.assertNotIn("Xxl", html)

    def test_upsert_species_rows_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "species.csv"
            written = upsert_pokedex_species_rows(
                path,
                [
                    {
                        "date": "2026-05-01",
                        "account": "Thombay",
                        "entry_type": "pokemon",
                        "dex_number": 1,
                        "registered": True,
                        "can_evolve_now": False,
                        "notes": "",
                    }
                ],
            )
            loaded = load_pokedex_species_entries(path)

        self.assertEqual(written, 1)
        self.assertEqual(len(loaded), 1)
        self.assertTrue(bool(loaded.iloc[0]["registered"]))

    def test_card_lists_unchecked_mega_forms_and_gmax(self):
        catalog = pd.DataFrame(
            [
                _mon(3, "Venusaur", "kanto"),
                _mon(6, "Charizard", "kanto"),
            ]
        )
        availability = pd.DataFrame(
            [
                {"entry_type": "mega", "dex_number": 3, "form": "Normal", "available": True, "notes": ""},
                {"entry_type": "mega", "dex_number": 6, "form": "Y", "available": True, "notes": ""},
                {"entry_type": "mega", "dex_number": 6, "form": "X", "available": True, "notes": ""},
                {"entry_type": "gmax", "dex_number": 3, "form": "", "available": True, "notes": ""},
            ]
        )
        species = pd.DataFrame(
            [
                _species("Thombay", "pokemon", 3),
                _species("Thombay", "pokemon", 6),
            ]
        )
        for kind, _label in ATLAS_ENTRY_KINDS:
            if kind == "pokemon":
                continue
            species = pd.concat(
                [species, pd.DataFrame([_species("Thombay", kind, 3), _species("Thombay", kind, 6)])],
                ignore_index=True,
            )
        cards = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            region="kanto",
            availability_df=availability,
        )
        by_dex = cards.set_index("dex_number")
        self.assertEqual(by_dex.loc[3, "missing_kinds"], "Mega, G-Max")
        self.assertEqual(by_dex.loc[6, "missing_kinds"], "Mega X, Mega Y")
        self.assertNotIn("Mega X", by_dex.loc[3, "missing_kinds"])
        self.assertNotIn("G-Max", by_dex.loc[6, "missing_kinds"])
        self.assertEqual(by_dex.loc[6, "registered_mega"], False)
        self.assertTrue(pd.isna(by_dex.loc[6, "registered_gmax"]))

        mega_missing = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            region="kanto",
            availability_df=availability,
            kind_filter="mega",
            state_filter="missing",
        )
        self.assertEqual(mega_missing["dex_number"].tolist(), [3, 6])
        mega_y = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            region="kanto",
            availability_df=availability,
            search="mega y",
        )
        self.assertEqual(mega_y["dex_number"].tolist(), [6])

    def test_kind_and_state_filters(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(25, "Pikachu", "kanto"),
                _mon(83, "Farfetch'd", "kanto"),
            ]
        )
        catalog.loc[catalog["dex_number"] == 83, "location_restriction"] = "East Asia"
        availability = _availability([("shiny", 25, True), ("shiny", 83, True)])
        species = pd.DataFrame([_species("Thombay", "shiny", 83)])
        missing = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            region="kanto",
            availability_df=availability,
            kind_filter="shiny",
            state_filter="missing",
        )
        self.assertEqual(missing["dex_number"].tolist(), [25])
        unavailable = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            region="kanto",
            availability_df=availability,
            kind_filter="shiny",
            state_filter="not available",
        )
        self.assertEqual(unavailable["dex_number"].tolist(), [1])
        restricted = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            region="kanto",
            availability_df=availability,
            kind_filter="any",
            state_filter="restricted",
        )
        self.assertEqual(restricted["dex_number"].tolist(), [83])
        shiny_any = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            region="kanto",
            availability_df=availability,
            kind_filter="shiny",
            state_filter="any",
        )
        self.assertEqual(shiny_any["dex_number"].tolist(), [25, 83])
        mega_any = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            region="kanto",
            availability_df=availability,
            kind_filter="mega",
            state_filter="any",
        )
        self.assertEqual(mega_any["dex_number"].tolist(), [])

    def test_overall_cards_include_every_catalog_region(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(152, "Chikorita", "johto"),
            ]
        )
        overall = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame(),
            account="Thombay",
            region="overall",
        )
        self.assertEqual(overall["dex_number"].tolist(), [1, 152])

        kanto = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame(),
            account="Thombay",
            region="kanto",
        )
        self.assertEqual(kanto["dex_number"].tolist(), [1])

    def test_release_overrides_label_cards_and_filter_all_regions(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto", "yes"),
                _mon(25, "Pikachu", "kanto", "yes"),
                _mon(387, "Turtwig", "sinnoh", "no"),
            ]
        )
        overrides = {387: " No ", "25": "YES", 1: "maybe"}
        cards = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame(),
            account="Thombay",
            region=None,
            release_overrides=overrides,
        )
        overall = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame(),
            account="Thombay",
            region="overall",
            release_overrides=overrides,
        )
        self.assertEqual(overall["dex_number"].tolist(), cards["dex_number"].tolist())
        self.assertEqual(overall["release_override"].tolist(), cards["release_override"].tolist())
        columns = cards.columns.tolist()
        self.assertEqual(columns.index("release_override"), columns.index("available_in_pogo") + 1)

        by_dex = cards.set_index("dex_number")
        bulbasaur = by_dex.loc[1]
        self.assertNotIn("Manual", str(bulbasaur["status_label"]))
        self.assertEqual(bulbasaur["release_override"], "")
        self.assertEqual(bulbasaur["available_in_pogo"], "yes")

        turtwig = by_dex.loc[387]
        self.assertEqual(turtwig["status"], "unavailable")
        self.assertEqual(turtwig["status_label"], "Not in GO · Manual")
        self.assertEqual(turtwig["release_override"], "no")
        self.assertEqual(turtwig["available_in_pogo"], "no")

        pikachu = by_dex.loc[25]
        self.assertEqual(pikachu["status"], "missing")
        self.assertTrue(str(pikachu["status_label"]).endswith(" · Manual"))
        self.assertEqual(str(pikachu["status_label"]).count(" · Manual"), 1)
        self.assertEqual(pikachu["release_override"], "yes")
        self.assertEqual(pikachu["available_in_pogo"], "yes")

        in_go = filter_atlas_cards_by_release(cards, "in go")
        not_in_go = filter_atlas_cards_by_release(cards, "not in go")
        self.assertIsNot(in_go, cards)
        self.assertIn(25, in_go["dex_number"].tolist())
        self.assertNotIn(25, not_in_go["dex_number"].tolist())
        self.assertEqual(
            filter_atlas_cards_by_release(cards, "in_go")["dex_number"].tolist(),
            in_go["dex_number"].tolist(),
        )
        self.assertEqual(
            filter_atlas_cards_by_release(cards, "no")["dex_number"].tolist(),
            not_in_go["dex_number"].tolist(),
        )

        manual = filter_atlas_cards_by_release(cards, "manual override")
        self.assertEqual(manual["dex_number"].tolist(), [25, 387])
        self.assertEqual(set(manual["region"].astype(str)), {"kanto", "sinnoh"})
        self.assertIsNot(manual, cards)
        self.assertEqual(
            filter_atlas_cards_by_release(cards, "override")["dex_number"].tolist(),
            [25, 387],
        )

        self.assertIs(filter_atlas_cards_by_release(cards, "any"), cards)
        self.assertEqual(filter_atlas_cards_by_release(cards, "any")["dex_number"].tolist(), [1, 25, 387])
        self.assertIs(filter_atlas_cards_by_release(cards, "kanto"), cards)

        empty = cards.iloc[0:0]
        self.assertIs(filter_atlas_cards_by_release(empty, "in go"), empty)

        without_override = cards.drop(columns=["release_override"])
        missing_column = filter_atlas_cards_by_release(without_override, "manual")
        self.assertTrue(missing_column.empty)
        self.assertEqual(missing_column.columns.tolist(), without_override.columns.tolist())

        html = pokedex_atlas_html(cards)
        self.assertIn("Not in GO · Manual", html)

    def test_hundo_evolution_fill_path_names_registered_ancestor(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(2, "Ivysaur", "kanto"),
                _mon(3, "Venusaur", "kanto"),
            ]
        )
        species = pd.DataFrame([_species("Thombay", "hundo", 1)])
        evolutions = pd.DataFrame(
            [
                {"source_dex_number": 1, "target_dex_number": 2},
                {"source_dex_number": 2, "target_dex_number": 3},
                {"source_dex_number": 3, "target_dex_number": 3},
                {"source_dex_number": 0, "target_dex_number": 2},
                {"source_dex_number": "nope", "target_dex_number": 3},
            ]
        )
        cards = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            region="kanto",
            evolutions_df=evolutions,
        )
        columns = cards.columns.tolist()
        self.assertEqual(columns.index("fill_path"), columns.index("missing_kinds") + 1)
        self.assertNotIn("_evolution_kinds", columns)
        self.assertNotIn("_purify_reachable", columns)
        by_dex = cards.set_index("dex_number")
        self.assertEqual(by_dex.loc[1, "fill_path"], "")
        self.assertEqual(by_dex.loc[2, "fill_path"], "Via evolution from Bulbasaur: 100%")
        self.assertEqual(by_dex.loc[3, "fill_path"], "Via evolution from Bulbasaur: 100%")

    def test_closer_registered_hundo_replaces_farther_ancestor(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(2, "Ivysaur", "kanto"),
                _mon(3, "Venusaur", "kanto"),
            ]
        )
        species = pd.DataFrame(
            [
                _species("Thombay", "hundo", 1),
                _species("Thombay", "hundo", 2),
            ]
        )
        cards = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            region="kanto",
            evolutions_df=_evolutions([(1, 2), (2, 3)]),
        )
        self.assertEqual(cards.set_index("dex_number").loc[3, "fill_path"], "Via evolution from Ivysaur: 100%")

    def test_evolution_fill_does_not_cross_kinds(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(2, "Ivysaur", "kanto"),
            ]
        )
        shiny = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame([_species("Thombay", "shiny", 1)]),
            account="Thombay",
            evolutions_df=_evolutions([(1, 2)]),
        ).set_index("dex_number")
        self.assertEqual(shiny.loc[2, "fill_path"], "Via evolution from Bulbasaur: Shiny")
        self.assertNotIn("100%", shiny.loc[2, "fill_path"])

        hundo = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame([_species("Thombay", "hundo", 1)]),
            account="Thombay",
            evolutions_df=_evolutions([(1, 2)]),
        ).set_index("dex_number")
        self.assertEqual(hundo.loc[2, "fill_path"], "Via evolution from Bulbasaur: 100%")
        self.assertNotIn("Shiny", hundo.loc[2, "fill_path"])

        both = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame(
                [
                    _species("Thombay", "hundo", 1),
                    _species("Thombay", "shiny", 1),
                ]
            ),
            account="Thombay",
            evolutions_df=_evolutions([(1, 2)]),
        ).set_index("dex_number")
        self.assertEqual(both.loc[2, "fill_path"], "Via evolution from Bulbasaur: Shiny, 100%")

    def test_registered_hundo_has_blank_fill_path(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(2, "Ivysaur", "kanto"),
            ]
        )
        cards = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame(
                [
                    _species("Thombay", "hundo", 1),
                    _species("Thombay", "hundo", 2),
                ]
            ),
            account="Thombay",
            evolutions_df=_evolutions([(1, 2)]),
        )
        self.assertEqual(cards.set_index("dex_number").loc[2, "fill_path"], "")

    def test_target_not_in_go_has_no_fill_path(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto", "yes"),
                _mon(2, "Ivysaur", "kanto", "no"),
            ]
        )
        cards = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame([_species("Thombay", "hundo", 1)]),
            account="Thombay",
            evolutions_df=_evolutions([(1, 2)]),
        )
        ivysaur = cards.set_index("dex_number").loc[2]
        self.assertEqual(ivysaur["status"], "unavailable")
        self.assertEqual(ivysaur["fill_path"], "")

    def test_branching_eevee_evolutions_match_evolution_path_filter(self):
        catalog = pd.DataFrame(
            [
                _mon(133, "Eevee", "kanto"),
                _mon(134, "Vaporeon", "kanto"),
                _mon(135, "Jolteon", "kanto"),
                _mon(136, "Flareon", "kanto"),
            ]
        )
        species = pd.DataFrame([_species("Thombay", "hundo", 133)])
        evolutions = _evolutions([(133, 134), (133, 135), (133, 136)])
        cards = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            evolutions_df=evolutions,
        ).set_index("dex_number")
        for dex in (134, 135, 136):
            self.assertEqual(cards.loc[dex, "fill_path"], "Via evolution from Eevee: 100%")
        self.assertEqual(cards.loc[133, "fill_path"], "")

        evolved = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            evolutions_df=evolutions,
            kind_filter="hundo",
            path_filter="evolution",
        )
        self.assertEqual(evolved["dex_number"].tolist(), [134, 135, 136])
        via_evolution = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            evolutions_df=evolutions,
            kind_filter="hundo",
            path_filter="Via Evolution",
        )
        self.assertEqual(via_evolution["dex_number"].tolist(), [134, 135, 136])
        unknown = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            evolutions_df=evolutions,
            path_filter="nope",
        )
        self.assertEqual(unknown["dex_number"].tolist(), [133, 134, 135, 136])

    def test_same_dex_shadow_is_via_purify(self):
        catalog = pd.DataFrame([_mon(1, "Bulbasaur", "kanto")])
        species = pd.DataFrame([_species("Thombay", "shadow", 1)])
        cards = build_pokedex_atlas_cards(catalog, species, account="Thombay")
        self.assertEqual(cards.loc[0, "fill_path"], "Via purify")
        self.assertNotIn("then evolve", cards.loc[0, "fill_path"])
        found = build_pokedex_atlas_cards(catalog, species, account="Thombay", search="purify")
        self.assertEqual(found["dex_number"].tolist(), [1])

    def test_shadow_ancestor_purify_then_evolve(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(2, "Ivysaur", "kanto"),
            ]
        )
        species = pd.DataFrame([_species("Thombay", "shadow", 1)])
        cards = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            availability_df=_availability([("shadow", 1, True)]),
            evolutions_df=_evolutions([(1, 2)]),
        )
        self.assertEqual(
            cards.set_index("dex_number").loc[2, "fill_path"],
            "Via evolution from Bulbasaur: Shadow. Via purify from Bulbasaur, then evolve",
        )

    def test_shadow_without_ancestor_omits_purified_and_marks_unreleased(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(4, "Charmander", "kanto"),
            ]
        )
        cards = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame(),
            account="Thombay",
            availability_df=_availability([("shadow", 1, True)]),
        )
        by_dex = cards.set_index("dex_number")
        charmander = by_dex.loc[4]
        self.assertNotIn("Purified", str(charmander["missing_kinds"]).split(", "))
        self.assertIn("Shadow", str(charmander["unreleased_kinds"]).split(", "))
        self.assertNotIn("purify", str(charmander["fill_path"]).lower())
        bulbasaur = by_dex.loc[1]
        self.assertIn("Purified", str(bulbasaur["missing_kinds"]).split(", "))
        html = pokedex_atlas_html(cards[cards["dex_number"] == 4])
        self.assertIn("pogo-dex-status--unreleased", html)
        self.assertIn("Not released:", html)
        self.assertIn("Shadow", html)

    def test_shadow_evolution_releases_rapidash_shadow_and_purified(self):
        catalog = pd.DataFrame(
            [
                _mon(77, "Ponyta", "kanto"),
                _mon(78, "Rapidash", "kanto"),
            ]
        )
        cards = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame(),
            account="Thombay",
            availability_df=_availability([("shadow", 77, True)]),
            evolutions_df=_evolutions([(77, 78)]),
        )
        by_dex = cards.set_index("dex_number")
        rapidash = by_dex.loc[78]
        self.assertFalse(pd.isna(rapidash["registered_shadow"]))
        self.assertNotIn("Shadow", str(rapidash["unreleased_kinds"]).split(", "))
        self.assertIn("Purified", str(rapidash["missing_kinds"]).split(", "))
        ponyta = by_dex.loc[77]
        self.assertNotIn("Shadow", str(ponyta["unreleased_kinds"]).split(", "))

    def test_purified_ancestor_suppresses_purify_then_evolve(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(2, "Ivysaur", "kanto"),
            ]
        )
        species = pd.DataFrame(
            [
                _species("Thombay", "purified", 1),
                _species("Thombay", "shadow", 1),
            ]
        )
        cards = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            availability_df=_availability([("shadow", 1, True)]),
            evolutions_df=_evolutions([(1, 2)]),
        )
        ivysaur = cards.set_index("dex_number").loc[2, "fill_path"]
        self.assertEqual(ivysaur, "Via evolution from Bulbasaur: Shadow, Purified")
        self.assertNotIn("then evolve", ivysaur)

    def test_direct_shadow_and_purified_ancestor_combine(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(2, "Ivysaur", "kanto"),
            ]
        )
        species = pd.DataFrame(
            [
                _species("Thombay", "purified", 1),
                _species("Thombay", "shadow", 2),
            ]
        )
        cards = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            evolutions_df=_evolutions([(1, 2)]),
        )
        self.assertEqual(
            cards.set_index("dex_number").loc[2, "fill_path"],
            "Via evolution from Bulbasaur: Purified. Via purify",
        )

    def test_missing_mega_does_not_create_evolution_fill_path(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(3, "Venusaur", "kanto"),
            ]
        )
        availability = pd.DataFrame(
            [
                {"entry_type": "mega", "dex_number": 3, "form": "Normal", "available": True, "notes": ""},
            ]
        )
        evolutions = _evolutions([(1, 3)])
        registered_rows = [_species("Thombay", "hundo", 1)]
        for kind, _label in ATLAS_ENTRY_KINDS:
            registered_rows.append(_species("Thombay", kind, 3))
        registered = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame(registered_rows),
            account="Thombay",
            availability_df=availability,
            evolutions_df=evolutions,
        ).set_index("dex_number")
        self.assertEqual(registered.loc[3, "missing_kinds"], "Mega")
        self.assertEqual(registered.loc[3, "fill_path"], "")

        hundo_missing = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame([_species("Thombay", "hundo", 1)]),
            account="Thombay",
            availability_df=availability,
            evolutions_df=evolutions,
        ).set_index("dex_number")
        self.assertIn("Mega", hundo_missing.loc[3, "missing_kinds"])
        self.assertEqual(hundo_missing.loc[3, "fill_path"], "Via evolution from Bulbasaur: 100%")
        self.assertNotIn("Mega", hundo_missing.loc[3, "fill_path"])

    def test_hundo_purify_filter_does_not_match_purify_only_card(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(133, "Eevee", "kanto"),
                _mon(134, "Vaporeon", "kanto"),
                _mon(135, "Jolteon", "kanto"),
                _mon(136, "Flareon", "kanto"),
            ]
        )
        species = pd.DataFrame(
            [
                _species("Thombay", "shadow", 1),
                _species("Thombay", "hundo", 133),
            ]
        )
        evolutions = _evolutions([(133, 134), (133, 135), (133, 136)])
        hundo_cards = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            evolutions_df=evolutions,
            kind_filter="hundo",
        )
        self.assertIn(1, hundo_cards["dex_number"].tolist())
        self.assertEqual(
            build_pokedex_atlas_cards(
                catalog,
                species,
                account="Thombay",
                evolutions_df=evolutions,
            ).set_index("dex_number").loc[1, "fill_path"],
            "Via purify",
        )
        purify = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            evolutions_df=evolutions,
            kind_filter="hundo",
            path_filter="purify",
        )
        self.assertEqual(purify["dex_number"].tolist(), [])
        evolution = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            evolutions_df=evolutions,
            kind_filter="hundo",
            path_filter="evolution",
        )
        self.assertEqual(evolution["dex_number"].tolist(), [134, 135, 136])

    def test_cross_region_evolution_uses_full_catalog_name(self):
        catalog = pd.DataFrame(
            [
                _mon(57, "Primeape", "kanto"),
                _mon(979, "Annihilape", "paldea"),
            ]
        )
        cards = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame([_species("Thombay", "hundo", 57)]),
            account="Thombay",
            region="paldea",
            evolutions_df=_evolutions([(57, 979)]),
        )
        self.assertEqual(cards["dex_number"].tolist(), [979])
        self.assertEqual(cards.loc[0, "fill_path"], "Via evolution from Primeape: 100%")

    def test_source_form_prefixes_evolution_name(self):
        catalog = pd.DataFrame(
            [
                _mon(52, "Meowth", "kanto"),
                _mon(863, "Perrserker", "galar"),
            ]
        )
        species = pd.DataFrame([_species("Thombay", "pokemon", 52)])
        formed = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            region="galar",
            evolutions_df=_evolutions([(52, 863, "Galarian")]),
        )
        self.assertEqual(formed["dex_number"].tolist(), [863])
        self.assertEqual(formed.loc[0, "fill_path"], "Via evolution from Galarian Meowth: Pokemon")

        disagreed = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            region="galar",
            evolutions_df=pd.concat(
                [
                    _evolutions([(52, 863, "Galarian")]),
                    _evolutions([(52, 863, "")]),
                ],
                ignore_index=True,
            ),
        )
        self.assertEqual(disagreed.loc[0, "fill_path"], "Via evolution from Meowth: Pokemon")

        renamed = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            region="galar",
            evolutions_df=pd.concat(
                [
                    _evolutions([(52, 863, "Galarian")]),
                    _evolutions([(52, 863, "Alolan")]),
                ],
                ignore_index=True,
            ),
        )
        self.assertEqual(renamed.loc[0, "fill_path"], "Via evolution from Meowth: Pokemon")

    def test_atlas_html_includes_fill_path_span(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(2, "Ivysaur", "kanto"),
            ]
        )
        cards = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame([_species("Thombay", "hundo", 1)]),
            account="Thombay",
            evolutions_df=_evolutions([(1, 2)]),
        )
        ivysaur_html = pokedex_atlas_html(cards[cards["dex_number"] == 2])
        self.assertIn('class="pogo-dex-path"', ivysaur_html)
        self.assertIn("Via evolution from Bulbasaur: 100%", ivysaur_html)
        status_at = ivysaur_html.index('<div class="pogo-dex-status">')
        unreleased = str(cards.set_index("dex_number").loc[2, "unreleased_kinds"] or "").strip()
        if unreleased:
            between = (
                '</div><div class="pogo-dex-status pogo-dex-status--unreleased">'
                f"Not released: {escape(unreleased)}</div>"
            )
        else:
            between = "</div>"
        self.assertIn(
            f'{between}<span class="pogo-dex-path">Via evolution from Bulbasaur: 100%</span>',
            ivysaur_html[status_at:],
        )
        bulbasaur_html = pokedex_atlas_html(cards[cards["dex_number"] == 1])
        self.assertNotIn("pogo-dex-path", bulbasaur_html)

        escaped_catalog = pd.DataFrame([_mon(1, "Bulb<saur", "kanto"), _mon(2, "Ivysaur", "kanto")])
        escaped_cards = build_pokedex_atlas_cards(
            escaped_catalog,
            pd.DataFrame([_species("Thombay", "hundo", 1)]),
            account="Thombay",
            evolutions_df=_evolutions([(1, 2)]),
        )
        escaped_html = pokedex_atlas_html(escaped_cards[escaped_cards["dex_number"] == 2])
        self.assertIn("Via evolution from Bulb&lt;saur: 100%", escaped_html)
        self.assertNotIn("Bulb<saur", escaped_html)

    def test_search_matches_ancestor_named_in_fill_path(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(2, "Ivysaur", "kanto"),
            ]
        )
        species = pd.DataFrame([_species("Thombay", "hundo", 1)])
        evolutions = _evolutions([(1, 2)])
        found = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            search="bulbasaur",
            evolutions_df=evolutions,
        )
        self.assertEqual(found["dex_number"].tolist(), [1, 2])
        without_edge = build_pokedex_atlas_cards(
            catalog,
            species,
            account="Thombay",
            search="bulbasaur",
        )
        self.assertEqual(without_edge["dex_number"].tolist(), [1])

    def test_evolution_tie_breaks_to_lower_source_dex(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(2, "Ivysaur", "kanto"),
                _mon(3, "Venusaur", "kanto"),
            ]
        )
        cards = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame(
                [
                    _species("Thombay", "hundo", 1),
                    _species("Thombay", "hundo", 2),
                ]
            ),
            account="Thombay",
            evolutions_df=_evolutions([(1, 3), (2, 3)]),
        )
        self.assertEqual(cards.set_index("dex_number").loc[3, "fill_path"], "Via evolution from Bulbasaur: 100%")

    def test_unusable_middle_edge_blocks_evolution_fill(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto", "yes"),
                _mon(2, "Ivysaur", "kanto", "no"),
                _mon(3, "Venusaur", "kanto", "yes"),
            ]
        )
        cards = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame([_species("Thombay", "hundo", 1)]),
            account="Thombay",
            evolutions_df=_evolutions([(1, 2), (2, 3)]),
        )
        self.assertEqual(cards.set_index("dex_number").loc[3, "fill_path"], "")

    def test_evolution_groups_order_by_source_dex_then_kind(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(2, "Ivysaur", "kanto"),
                _mon(3, "Venusaur", "kanto"),
            ]
        )
        split = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame(
                [
                    _species("Thombay", "shiny", 1),
                    _species("Thombay", "hundo", 2),
                ]
            ),
            account="Thombay",
            evolutions_df=_evolutions([(1, 2), (2, 3)]),
        )
        self.assertEqual(
            split.set_index("dex_number").loc[3, "fill_path"],
            "Via evolution from Bulbasaur: Shiny. Via evolution from Ivysaur: 100%",
        )

    def test_purify_then_evolve_uses_source_form(self):
        catalog = pd.DataFrame(
            [
                _mon(52, "Meowth", "kanto"),
                _mon(863, "Perrserker", "galar"),
            ]
        )
        cards = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame([_species("Thombay", "shadow", 52)]),
            account="Thombay",
            region="galar",
            availability_df=_availability([("shadow", 52, True)]),
            evolutions_df=_evolutions([(52, 863, "Galarian")]),
        )
        self.assertEqual(
            cards.loc[0, "fill_path"],
            "Via evolution from Galarian Meowth: Shadow. Via purify from Galarian Meowth, then evolve",
        )

    def test_progress_ignores_dex_outside_target(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto", "yes"),
                _mon(2, "Ivysaur", "kanto", "no"),
                _mon(25, "Pikachu", "kanto", "yes"),
            ]
        )
        availability = _availability(
            [
                ("shiny", 1, True),
                ("shiny", 25, False),
            ]
        )
        species = pd.DataFrame(
            [
                _species("Thombay", "shiny", 1, True, "2026-03-01"),
                _species("Thombay", "shiny", 2, True, "2026-03-02"),
                _species("Thombay", "shiny", 25, True, "2026-03-03"),
                _species("Thombay", "pokemon", 2, True, "2026-03-04"),
                {**_species("Thombay", "pokemon", 1, True, "2026-03-05"), "form": "party"},
            ]
        )
        progress = build_species_progress_rows(
            catalog,
            species,
            accounts=["Thombay"],
            entry_types=["shiny", "pokemon"],
            start_date="2026-03-01",
            end_date="2026-03-31",
            availability_df=availability,
        )
        self.assertEqual(progress["entry_type"].tolist(), ["shiny"])
        self.assertEqual(_iso_dates(progress), ["2026-03-01"])
        self.assertEqual(int(progress.iloc[0]["registered_count"]), 1)
        self.assertEqual(int(progress.iloc[0]["target_count"]), 1)
        self.assertEqual(progress.iloc[0]["entry_type_label"], "Shiny")

        counted = build_species_region_counts(
            catalog,
            species,
            account="Thombay",
            availability_df=availability,
            as_of_date="2026-03-31",
        )
        kanto = counted[counted["region"] == "kanto"].set_index("entry_type")
        self.assertEqual(int(kanto.loc["pokemon", "registered_count"]), 0)
        self.assertEqual(int(kanto.loc["pokemon", "target_count"]), 2)
        self.assertEqual(int(kanto.loc["shiny", "registered_count"]), 1)
        self.assertEqual(int(kanto.loc["shiny", "target_count"]), 1)
        before = build_species_region_counts(
            catalog,
            species,
            account="Thombay",
            availability_df=availability,
            as_of_date="2026-02-01",
        )
        shiny_before = before[(before["entry_type"] == "shiny") & (before["region"] == "overall")].iloc[0]
        self.assertEqual(int(shiny_before["registered_count"]), 0)

    def test_progress_carries_registration_before_start_date(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(2, "Ivysaur", "kanto"),
            ]
        )
        species = pd.DataFrame(
            [
                _species("Thombay", "pokemon", 1, True, "2026-01-15"),
                _species("Thombay", "pokemon", 1, True, "2026-02-10"),
                _species("Thombay", "pokemon", 2, True, "2026-03-01"),
                _species("Thombay", "pokemon", 1, False, "2026-05-01"),
            ]
        )
        progress = build_species_progress_rows(
            catalog,
            species,
            accounts=["Thombay"],
            entry_types=["pokemon"],
            start_date="2026-02-01",
            end_date="2026-04-01",
        )
        self.assertEqual(_iso_dates(progress), ["2026-02-01", "2026-03-01"])
        self.assertEqual(progress["registered_count"].tolist(), [1, 2])
        self.assertEqual(progress["target_count"].tolist(), [2, 2])
        self.assertEqual(progress["account"].tolist(), ["Thombay", "Thombay"])
        self.assertEqual(progress["entry_type"].tolist(), ["pokemon", "pokemon"])
        self.assertEqual(progress["entry_type_label"].tolist(), ["Pokemon", "Pokemon"])

        open_ended = build_species_progress_rows(
            catalog,
            species,
            accounts=["Thombay"],
            entry_types=["pokemon"],
            end_date="2026-04-01",
        )
        self.assertEqual(_iso_dates(open_ended), ["2026-01-15", "2026-03-01"])
        self.assertEqual(open_ended["registered_count"].tolist(), [1, 2])

    def test_progress_registered_false_lowers_count(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(2, "Ivysaur", "kanto"),
            ]
        )
        species = pd.DataFrame(
            [
                _species("Thombay", "pokemon", 1, True, "2026-02-01"),
                _species("Thombay", "pokemon", 2, True, "2026-02-02"),
                _species("Thombay", "pokemon", 1, False, "2026-02-03"),
                _species("Thombay", "pokemon", 2, False, "2026-03-01"),
            ]
        )
        progress = build_species_progress_rows(
            catalog,
            species,
            accounts=["Thombay"],
            entry_types=["pokemon"],
            start_date="2026-02-01",
            end_date="2026-02-28",
        )
        self.assertEqual(_iso_dates(progress), ["2026-02-01", "2026-02-02", "2026-02-03"])
        self.assertEqual(progress["registered_count"].tolist(), [1, 2, 1])
        self.assertEqual(progress["target_count"].tolist(), [2, 2, 2])

    def test_progress_region_filter_excludes_other_regions(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(152, "Chikorita", "johto"),
            ]
        )
        species = pd.DataFrame(
            [
                _species("Thombay", "pokemon", 1, True, "2026-02-01"),
                _species("Thombay", "pokemon", 152, True, "2026-02-02"),
            ]
        )
        kanto = build_species_progress_rows(
            catalog,
            species,
            accounts=["Thombay"],
            entry_types=["pokemon"],
            regions=["kanto"],
            start_date="2026-02-01",
            end_date="2026-02-28",
        )
        self.assertEqual(_iso_dates(kanto), ["2026-02-01"])
        self.assertEqual(int(kanto.iloc[0]["registered_count"]), 1)
        self.assertEqual(int(kanto.iloc[0]["target_count"]), 1)

        mixed = build_species_progress_rows(
            catalog,
            species,
            accounts=["Thombay"],
            entry_types=["pokemon"],
            regions=["overall", "Kanto"],
            start_date="2026-02-01",
            end_date="2026-02-28",
        )
        self.assertEqual(mixed["registered_count"].tolist(), [1])
        self.assertEqual(int(mixed.iloc[0]["target_count"]), 1)

        overall = build_species_progress_rows(
            catalog,
            species,
            accounts=["Thombay"],
            entry_types=["pokemon"],
            regions=["overall"],
            start_date="2026-02-01",
            end_date="2026-02-28",
        )
        self.assertEqual(_iso_dates(overall), ["2026-02-01", "2026-02-02"])
        self.assertEqual(overall["registered_count"].tolist(), [1, 2])
        self.assertEqual(int(overall.iloc[0]["target_count"]), 2)

    def test_mega_forms_count_each_form(self):
        catalog = pd.DataFrame([_mon(6, "Charizard", "kanto")])
        availability = pd.DataFrame(
            [
                {"entry_type": "mega", "dex_number": 6, "form": "X", "available": True, "notes": ""},
                {"entry_type": "mega", "dex_number": 6, "form": "Y", "available": True, "notes": ""},
            ]
        )
        species = pd.DataFrame(
            [
                {**_species("Thombay", "mega", 6, True, "2026-02-01"), "form": "x"},
                {**_species("Thombay", "mega", 6, True, "2026-02-02"), "form": "Y"},
                {**_species("Thombay", "mega", 6, False, "2026-02-03"), "form": "X"},
                {**_species("Thombay", "mega", 6, True, "2026-02-04"), "form": "Z"},
            ]
        )
        progress = build_species_progress_rows(
            catalog,
            species,
            accounts=["Thombay"],
            entry_types=["mega"],
            start_date="2026-02-01",
            end_date="2026-02-28",
            availability_df=availability,
        )
        self.assertEqual(_iso_dates(progress), ["2026-02-01", "2026-02-02", "2026-02-03"])
        self.assertEqual(progress["registered_count"].tolist(), [1, 2, 1])
        self.assertEqual(progress["target_count"].tolist(), [2, 2, 2])
        self.assertEqual(progress.iloc[0]["entry_type_label"], "Mega")

        summary = build_species_missing_summary(
            catalog,
            species,
            accounts=["Thombay"],
            entry_types=["MEGA"],
            availability_df=availability,
        )
        self.assertEqual(summary["entry_type"].tolist(), ["mega"])
        self.assertEqual(int(summary.iloc[0]["registered_count"]), 1)
        self.assertEqual(int(summary.iloc[0]["target_count"]), 2)
        self.assertEqual(int(summary.iloc[0]["missing_count"]), 1)
        unchanged = build_species_missing_summary(
            catalog,
            species,
            accounts=["Thombay"],
            availability_df=availability,
        )
        self.assertEqual(unchanged["entry_type"].tolist(), [kind for kind, _label in ATLAS_ENTRY_KINDS])
        self.assertNotIn("mega", unchanged["entry_type"].tolist())

        counts = build_species_region_counts(
            catalog,
            species,
            account="Thombay",
            availability_df=availability,
        )
        mega = counts[counts["entry_type"] == "mega"].set_index("region")
        self.assertEqual(mega.index.tolist(), ["kanto", "overall"])
        self.assertEqual(int(mega.loc["kanto", "registered_count"]), 1)
        self.assertEqual(int(mega.loc["kanto", "target_count"]), 2)
        self.assertEqual(int(mega.loc["overall", "registered_count"]), 1)
        self.assertEqual(int(mega.loc["overall", "target_count"]), 2)

    def test_gmax_counts_blank_form_dex(self):
        catalog = pd.DataFrame(
            [
                _mon(3, "Venusaur", "kanto"),
                _mon(6, "Charizard", "kanto", "no"),
            ]
        )
        availability = pd.DataFrame(
            [
                {"entry_type": "gmax", "dex_number": 3, "form": "", "available": True, "notes": ""},
                {"entry_type": "gmax", "dex_number": 3, "form": "Gigantamax", "available": True, "notes": ""},
                {"entry_type": "gmax", "dex_number": 6, "form": "", "available": True, "notes": ""},
            ]
        )
        species = pd.DataFrame(
            [
                _species("Thombay", "gmax", 3, True, "2026-02-01"),
                {**_species("Thombay", "gmax", 3, True, "2026-02-02"), "form": "Gigantamax"},
                _species("Thombay", "gmax", 6, True, "2026-02-03"),
            ]
        )
        progress = build_species_progress_rows(
            catalog,
            species,
            accounts=["Thombay"],
            entry_types=["gmax"],
            start_date="2026-02-01",
            end_date="2026-02-28",
            availability_df=availability,
        )
        self.assertEqual(_iso_dates(progress), ["2026-02-01"])
        self.assertEqual(int(progress.iloc[0]["registered_count"]), 1)
        self.assertEqual(int(progress.iloc[0]["target_count"]), 1)
        self.assertEqual(progress.iloc[0]["entry_type_label"], "G-Max")

        formed_only = pd.DataFrame(
            [{**_species("Thombay", "gmax", 3, True, "2026-02-01"), "form": "Gigantamax"}]
        )
        formed_progress = build_species_progress_rows(
            catalog,
            formed_only,
            accounts=["Thombay"],
            entry_types=["gmax"],
            start_date="2026-02-01",
            end_date="2026-02-28",
            availability_df=availability,
        )
        self.assertTrue(formed_progress.empty)
        formed_counts = build_species_region_counts(
            catalog,
            formed_only,
            account="Thombay",
            availability_df=availability,
        )
        gmax = formed_counts[formed_counts["entry_type"] == "gmax"].set_index("region")
        self.assertEqual(int(gmax.loc["kanto", "registered_count"]), 0)
        self.assertEqual(int(gmax.loc["kanto", "target_count"]), 1)
        self.assertEqual(int(gmax.loc["overall", "target_count"]), 1)

        summary = build_species_missing_summary(
            catalog,
            species,
            accounts=["Thombay"],
            entry_types=["gmax"],
            availability_df=availability,
        )
        self.assertEqual(summary["entry_type"].tolist(), ["gmax"])
        self.assertEqual(int(summary.iloc[0]["registered_count"]), 1)
        self.assertEqual(int(summary.iloc[0]["target_count"]), 1)
        self.assertEqual(int(summary.iloc[0]["missing_count"]), 0)

    def test_region_counts_overall_equals_sum_of_regions(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(152, "Chikorita", "johto"),
                _mon(252, "Treecko", "hoenn"),
                _mon(999, "MissingNo", "unidentified"),
            ]
        )
        availability = _availability(
            [
                ("shiny", 1, True),
                ("shiny", 152, True),
                ("shiny", 999, True),
            ]
        )
        species = pd.DataFrame(
            [
                _species("Thombay", "shiny", 1, True, "2026-01-15"),
                _species("Thombay", "shiny", 152, True, "2026-01-15"),
                _species("Thombay", "shiny", 252, True, "2026-01-15"),
                _species("Thombay", "shiny", 999, True, "2026-01-15"),
            ]
        )
        counts = build_species_region_counts(
            catalog,
            species,
            account="Thombay",
            availability_df=availability,
        )
        self.assertEqual(
            counts["entry_type"].drop_duplicates().tolist(),
            [kind for kind, _label in ATLAS_COMPARISON_KINDS],
        )
        self.assertNotIn("unidentified", counts["region"].tolist())
        shiny = counts[counts["entry_type"] == "shiny"].set_index("region")
        self.assertEqual(shiny.index.tolist(), ["kanto", "johto", "hoenn", "overall"])
        self.assertEqual(int(shiny.loc["kanto", "registered_count"]), 1)
        self.assertEqual(int(shiny.loc["kanto", "target_count"]), 1)
        self.assertEqual(int(shiny.loc["johto", "registered_count"]), 1)
        self.assertEqual(int(shiny.loc["johto", "target_count"]), 1)
        self.assertEqual(int(shiny.loc["hoenn", "registered_count"]), 0)
        self.assertEqual(int(shiny.loc["hoenn", "target_count"]), 0)
        self.assertEqual(int(shiny.loc["overall", "registered_count"]), 2)
        self.assertEqual(int(shiny.loc["overall", "target_count"]), 2)
        self.assertEqual(shiny.loc["kanto", "entry_type_label"], "Shiny")
        pokemon = counts[counts["entry_type"] == "pokemon"].set_index("region")
        self.assertEqual(int(pokemon.loc["overall", "target_count"]), 3)
        self.assertEqual(int(pokemon.loc["overall", "registered_count"]), 0)

        filtered = build_species_region_counts(
            catalog,
            species,
            account="Thombay",
            availability_df=availability,
            regions=["kanto", "overall"],
        )
        filtered_shiny = filtered[filtered["entry_type"] == "shiny"]
        self.assertEqual(filtered_shiny["region"].tolist(), ["kanto", "overall"])
        overall = filtered_shiny[filtered_shiny["region"] == "overall"].iloc[0]
        self.assertEqual(int(overall["registered_count"]), 1)
        self.assertEqual(int(overall["target_count"]), 1)

        progress = build_species_progress_rows(
            catalog,
            species,
            accounts=["Thombay"],
            entry_types=["shiny"],
            start_date="2026-02-01",
            end_date="2026-02-28",
            availability_df=availability,
        )
        self.assertEqual(_iso_dates(progress), ["2026-02-01"])
        self.assertEqual(int(progress.iloc[0]["registered_count"]), 2)
        self.assertEqual(int(progress.iloc[0]["target_count"]), 2)

    def test_evolving_species_are_not_pending_mega_or_gmax_hosts(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(2, "Ivysaur", "kanto"),
                _mon(3, "Venusaur", "kanto"),
            ]
        )
        cards = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame(),
            account="Thombay",
            region="kanto",
            evolutions_df=_evolutions([(1, 2), (2, 3)]),
        )
        self.assertEqual(cards["mega_host"].dtype.name, "bool")
        self.assertEqual(cards["gmax_host"].dtype.name, "bool")
        by_dex = cards.set_index("dex_number")
        for dex in (1, 2):
            row = by_dex.loc[dex]
            unreleased = str(row["unreleased_kinds"]).split(", ")
            self.assertNotIn("Mega", unreleased)
            self.assertNotIn("G-Max", unreleased)
            self.assertFalse(bool(row["mega_host"]))
            self.assertFalse(bool(row["gmax_host"]))
        venusaur = by_dex.loc[3]
        venusaur_unreleased = str(venusaur["unreleased_kinds"]).split(", ")
        self.assertIn("Mega", venusaur_unreleased)
        self.assertIn("G-Max", venusaur_unreleased)
        self.assertTrue(bool(venusaur["mega_host"]))
        self.assertTrue(bool(venusaur["gmax_host"]))

    def test_final_stage_released_mega_and_gmax_stay_missing_hosts(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(2, "Ivysaur", "kanto"),
                _mon(3, "Venusaur", "kanto"),
            ]
        )
        cards = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame(),
            account="Thombay",
            region="kanto",
            availability_df=_availability([("mega", 3, True), ("gmax", 3, True)]),
            evolutions_df=_evolutions([(1, 2), (2, 3)]),
        )
        venusaur = cards.set_index("dex_number").loc[3]
        unreleased = str(venusaur["unreleased_kinds"]).split(", ")
        missing = str(venusaur["missing_kinds"]).split(", ")
        self.assertNotIn("Mega", unreleased)
        self.assertNotIn("G-Max", unreleased)
        self.assertIn("Mega", missing)
        self.assertIn("G-Max", missing)
        self.assertTrue(bool(venusaur["mega_host"]))
        self.assertTrue(bool(venusaur["gmax_host"]))

    def test_released_gmax_on_evolving_eevee_stays_a_gmax_host(self):
        catalog = pd.DataFrame(
            [
                _mon(133, "Eevee", "kanto"),
                _mon(134, "Vaporeon", "kanto"),
            ]
        )
        cards = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame(),
            account="Thombay",
            region="kanto",
            availability_df=_availability([("gmax", 133, True)]),
            evolutions_df=_evolutions([(133, 134)]),
        )
        eevee = cards.set_index("dex_number").loc[133]
        unreleased = str(eevee["unreleased_kinds"]).split(", ")
        missing = str(eevee["missing_kinds"]).split(", ")
        self.assertNotIn("G-Max", unreleased)
        self.assertTrue(bool(eevee["gmax_host"]))
        self.assertNotIn("Mega", unreleased)
        self.assertFalse(bool(eevee["mega_host"]))
        self.assertIn("G-Max", missing)

    def test_released_mega_on_evolving_bulbasaur_stays_a_mega_host(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(2, "Ivysaur", "kanto"),
            ]
        )
        cards = build_pokedex_atlas_cards(
            catalog,
            pd.DataFrame(),
            account="Thombay",
            region="kanto",
            availability_df=_availability([("mega", 1, True)]),
            evolutions_df=_evolutions([(1, 2)]),
        )
        bulbasaur = cards.set_index("dex_number").loc[1]
        unreleased = str(bulbasaur["unreleased_kinds"]).split(", ")
        missing = str(bulbasaur["missing_kinds"]).split(", ")
        self.assertTrue(bool(bulbasaur["mega_host"]))
        self.assertNotIn("Mega", unreleased)
        self.assertIn("Mega", missing)
        self.assertFalse(bool(bulbasaur["gmax_host"]))
        self.assertNotIn("G-Max", unreleased)


def _atlas_test_card(dex_number: int, name: str, registered: dict[str, object]) -> dict[str, object]:
    card: dict[str, object] = {"dex_number": dex_number, "name": name}
    for kind_id, _label in ATLAS_ENTRY_KINDS:
        card[f"registered_{kind_id}"] = registered.get(kind_id, pd.NA)
    return card


def _atlas_test_editor_row(dex_number: int, name: str, kinds: dict[str, bool]) -> dict[str, object]:
    row: dict[str, object] = {
        "Dex": dex_number,
        "Name": name,
        "German": name,
        "Location": "",
        "Last event": "",
    }
    for kind_id, label in ATLAS_ENTRY_KINDS:
        row[label] = kinds.get(kind_id, False)
    return row


class PokedexAtlasDeltaSaveTests(unittest.TestCase):
    def test_unchanged_grid_writes_nothing(self):
        cards = pd.DataFrame([_atlas_test_card(1, "Bulbasaur", {"pokemon": True, "shiny": False})])
        edited = pd.DataFrame([_atlas_test_editor_row(1, "Bulbasaur", {"pokemon": True, "shiny": False})])
        rows = species_rows_delta_from_atlas_editor(
            cards,
            edited,
            account="Thombay",
            save_date=date(2026, 11, 5),
        )
        self.assertEqual(rows, [])

    def test_new_catch_writes_true_row(self):
        cards = pd.DataFrame([_atlas_test_card(1, "Bulbasaur", {"pokemon": False})])
        edited = pd.DataFrame([_atlas_test_editor_row(1, "Bulbasaur", {"pokemon": True})])
        rows = species_rows_delta_from_atlas_editor(
            cards,
            edited,
            account="Thombay",
            save_date=date(2026, 11, 5),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entry_type"], "pokemon")
        self.assertEqual(rows[0]["dex_number"], 1)
        self.assertTrue(rows[0]["registered"])

    def test_uncheck_writes_false_row(self):
        cards = pd.DataFrame([_atlas_test_card(1, "Bulbasaur", {"pokemon": True})])
        edited = pd.DataFrame([_atlas_test_editor_row(1, "Bulbasaur", {"pokemon": False})])
        rows = species_rows_delta_from_atlas_editor(
            cards,
            edited,
            account="Thombay",
            save_date=date(2026, 11, 5),
        )
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["registered"])

    def test_still_false_writes_nothing(self):
        cards = pd.DataFrame([_atlas_test_card(1, "Bulbasaur", {"pokemon": False})])
        edited = pd.DataFrame([_atlas_test_editor_row(1, "Bulbasaur", {"pokemon": False})])
        rows = species_rows_delta_from_atlas_editor(
            cards,
            edited,
            account="Thombay",
            save_date=date(2026, 11, 5),
        )
        self.assertEqual(rows, [])

    def test_unavailable_kind_is_skipped(self):
        cards = pd.DataFrame([_atlas_test_card(1, "Bulbasaur", {"pokemon": True})])
        edited = pd.DataFrame([_atlas_test_editor_row(1, "Bulbasaur", {"pokemon": True, "shiny": True})])
        rows = species_rows_delta_from_atlas_editor(
            cards,
            edited,
            account="Thombay",
            save_date=date(2026, 11, 5),
        )
        self.assertEqual(rows, [])

    def test_pokedex_atlas_html_wraps_card_in_dex_link(self):
        cards = build_pokedex_atlas_cards(
            pd.DataFrame([_mon(1, "Bulbasaur", "kanto")]),
            pd.DataFrame([_species("Thombay", "pokemon", 1)]),
            account="Thombay",
        )
        html = pokedex_atlas_html(cards[cards["dex_number"] == 1])
        self.assertIn('class="pogo-dex-card-link"', html)
        self.assertIn('href="#atlas-dex-1"', html)
        self.assertIn('data-atlas-dex="1"', html)
        self.assertNotIn("?atlas_dex=", html)
        self.assertIn("pogo-dex-card--missing", html)
        self.assertIn(
            '<a class="pogo-dex-card-link" href="#atlas-dex-1" data-atlas-dex="1"><article class="pogo-dex-card pogo-dex-card--missing',
            html,
        )
        empty_html = pokedex_atlas_html(cards.iloc[0:0])
        self.assertEqual(
            empty_html,
            '<div class="pogo-dex-empty">No Pokemon match the current Atlas filters.</div>',
        )
        self.assertNotIn("pogo-dex-card-link", empty_html)

    def test_atlas_card_event_dex(self):
        self.assertIsNone(atlas_card_event_dex(None))
        self.assertIsNone(atlas_card_event_dex({}))
        self.assertIsNone(atlas_card_event_dex({"dex": None, "nonce": 1}))
        self.assertIsNone(atlas_card_event_dex({"dex": True, "nonce": 1}))
        self.assertIsNone(atlas_card_event_dex({"dex": 0, "nonce": 1}))
        self.assertEqual(atlas_card_event_dex({"dex": 25, "nonce": 1}), 25)
        self.assertEqual(atlas_card_event_dex({"dex": 25.0, "nonce": 1}), 25)

    def test_card_registration_writes_shiny_true_row(self):
        card = pd.Series(_atlas_test_card(1, "Bulbasaur", {"pokemon": True, "shiny": False, "shadow": False}))
        rows = species_rows_from_card_registration(
            card,
            account="Thombay",
            save_date=date(2026, 11, 5),
            kind_values={"pokemon": True, "shiny": True, "shadow": False},
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entry_type"], "shiny")
        self.assertIs(rows[0]["registered"], True)
        self.assertEqual(rows[0]["dex_number"], 1)
        self.assertEqual(rows[0]["account"], "Thombay")
        self.assertEqual(rows[0]["form"], "")

    def test_card_registration_unchanged_kinds_write_nothing(self):
        card = pd.Series(_atlas_test_card(1, "Bulbasaur", {"pokemon": True, "shiny": False}))
        rows = species_rows_from_card_registration(
            card,
            account="Thombay",
            save_date=date(2026, 11, 5),
            kind_values={"pokemon": True, "shiny": False},
        )
        self.assertEqual(rows, [])

    def test_card_registration_writes_unavailable_shiny_when_caught_differs(self):
        card = pd.Series(_atlas_test_card(1, "Bulbasaur", {"pokemon": True}))
        rows = species_rows_from_card_registration(
            card,
            account="Thombay",
            save_date=date(2026, 11, 5),
            kind_values={"pokemon": True, "shiny": True},
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entry_type"], "shiny")
        self.assertIs(rows[0]["registered"], True)
        self.assertEqual(rows[0]["form"], "")
        self.assertEqual(rows[0]["dex_number"], 1)

    def test_blank_shadow_follows_caught_flag_and_available_kind_stays_quiet(self):
        raw = _atlas_test_card(1, "Bulbasaur", {"pokemon": True})
        raw["caught_shadow"] = True
        card = pd.Series(raw)
        held = species_rows_from_card_registration(
            card,
            account="Thombay",
            save_date=date(2026, 11, 5),
            kind_values={"shadow": True, "pokemon": True},
        )
        self.assertEqual(held, [])
        cleared = species_rows_from_card_registration(
            card,
            account="Thombay",
            save_date=date(2026, 11, 5),
            kind_values={"shadow": False, "pokemon": True},
        )
        self.assertEqual(len(cleared), 1)
        self.assertEqual(cleared[0]["entry_type"], "shadow")
        self.assertIs(cleared[0]["registered"], False)
        self.assertEqual(cleared[0]["form"], "")
        unchanged = species_rows_from_card_registration(
            pd.Series(_atlas_test_card(1, "Bulbasaur", {"pokemon": True, "shiny": False})),
            account="Thombay",
            save_date=date(2026, 11, 5),
            kind_values={"pokemon": True, "shiny": False},
        )
        self.assertEqual(unchanged, [])

    def test_card_registration_writes_mega_form_row(self):
        raw = _atlas_test_card(6, "Charizard", {"pokemon": True})
        raw["mega_forms"] = '["X", "Y"]'
        raw["registered_mega_forms"] = '["X"]'
        card = pd.Series(raw)
        rows = species_rows_from_card_registration(
            card,
            account="Thombay",
            save_date=date(2026, 11, 5),
            kind_values={"pokemon": True},
            mega_values={"X": True, "Y": True},
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entry_type"], "mega")
        self.assertEqual(rows[0]["form"], "Y")
        self.assertIs(rows[0]["registered"], True)
        self.assertEqual(rows[0]["dex_number"], 6)
        self.assertEqual(rows[0]["account"], "Thombay")

    def test_card_registration_writes_gmax_and_shadow_rows(self):
        raw = _atlas_test_card(3, "Venusaur", {"pokemon": True, "shadow": False})
        raw["registered_gmax"] = False
        card = pd.Series(raw)
        rows = species_rows_from_card_registration(
            card,
            account="Thombay",
            save_date=date(2026, 11, 5),
            kind_values={"pokemon": True, "shadow": True},
            gmax_value=True,
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["entry_type"], "shadow")
        self.assertIs(rows[0]["registered"], True)
        self.assertEqual(rows[0]["form"], "")
        self.assertEqual(rows[0]["dex_number"], 3)
        self.assertEqual(rows[0]["account"], "Thombay")
        self.assertEqual(rows[1]["entry_type"], "gmax")
        self.assertEqual(rows[1]["form"], "")
        self.assertIs(rows[1]["registered"], True)
        self.assertEqual(rows[1]["dex_number"], 3)
        self.assertEqual(rows[1]["account"], "Thombay")


class PokedexSpeciesCompactTests(unittest.TestCase):
    def _row(
        self,
        day: str,
        *,
        registered: bool = True,
        notes: str = "",
        can_evolve_now: bool = False,
    ) -> dict[str, object]:
        return {
            "date": day,
            "account": "Thombay",
            "entry_type": "pokemon",
            "dex_number": 1,
            "form": "",
            "registered": registered,
            "can_evolve_now": can_evolve_now,
            "notes": notes,
        }

    def test_repeat_true_is_dropped(self):
        frame = pd.DataFrame([self._row("2026-01-01"), self._row("2026-01-02")])
        compact = compact_pokedex_species_rows(frame)
        self.assertEqual(compact["date"].dt.strftime("%Y-%m-%d").tolist(), ["2026-01-01"])

    def test_leading_false_is_dropped(self):
        frame = pd.DataFrame([self._row("2026-01-01", registered=False), self._row("2026-01-02")])
        compact = compact_pokedex_species_rows(frame)
        self.assertEqual(compact["date"].dt.strftime("%Y-%m-%d").tolist(), ["2026-01-02"])

    def test_true_then_false_is_kept(self):
        frame = pd.DataFrame([self._row("2026-01-01"), self._row("2026-01-02", registered=False)])
        compact = compact_pokedex_species_rows(frame)
        self.assertEqual(compact["date"].dt.strftime("%Y-%m-%d").tolist(), ["2026-01-01", "2026-01-02"])
        self.assertEqual(compact["registered"].tolist(), [True, False])

    def test_notes_change_is_kept(self):
        frame = pd.DataFrame([self._row("2026-01-01"), self._row("2026-01-02", notes="evolve soon")])
        compact = compact_pokedex_species_rows(frame)
        self.assertEqual(len(compact), 2)
        self.assertEqual(compact.iloc[1]["notes"], "evolve soon")


if __name__ == "__main__":
    unittest.main()
