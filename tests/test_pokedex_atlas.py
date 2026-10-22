from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd  # type: ignore[import-untyped]

from webapp.data_files import (
    load_pokedex_species_entries,
    merge_pokedex_category_availability,
    merge_pokemon_catalog,
)
from tools.update_pokemon_catalog import preserve_unavailable_category_rows
from webapp.pokedex import (
    ATLAS_ENTRY_KINDS,
    apply_catalog_community_fields,
    build_atlas_snapshot_comparison,
    build_category_availability_rows,
    build_missing_pokemon_rows,
    build_pokedex_atlas_cards,
    build_pokedex_missing_count_rows,
    build_pokedex_target_rows,
    build_species_missing_summary,
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

    def test_missing_counts_use_latest_snapshot_and_derived_overall(self):
        snapshots = pd.DataFrame(
            [
                {"date": "2026-01-01", "account": "Thombay", "entry_type": "pokemon", "region": "kanto", "value": 100},
                {"date": "2026-01-20", "account": "Thombay", "entry_type": "pokemon", "region": "kanto", "value": 140},
                {"date": "2026-01-20", "account": "Thombay", "entry_type": "pokemon", "region": "johto", "value": 80},
                {"date": "2026-01-20", "account": "Thombay", "entry_type": "pokemon", "region": "overall", "value": 220},
            ]
        )
        config = pd.DataFrame(
            [
                {"entry_type": "pokemon", "region": "kanto", "max_value": 151, "locked": False, "notes": ""},
                {"entry_type": "pokemon", "region": "johto", "max_value": 100, "locked": False, "notes": ""},
                {"entry_type": "pokemon", "region": "overall", "max_value": 9999, "locked": True, "notes": "ignored"},
            ]
        )

        targets = build_pokedex_target_rows(config, entry_types=["pokemon"])
        overall = targets[targets["region"] == "overall"].iloc[0]
        self.assertEqual(float(overall["max_value"]), 251.0)

        missing = build_pokedex_missing_count_rows(
            snapshots,
            config,
            accounts=["Thombay"],
            entry_types=["pokemon"],
            end_date="2026-01-31",
        )
        kanto = missing[(missing["region"] == "kanto")].iloc[0]
        overall_row = missing[(missing["region"] == "overall")].iloc[0]
        self.assertEqual(float(kanto["value"]), 140.0)
        self.assertEqual(float(kanto["missing_count"]), 11.0)
        self.assertEqual(float(overall_row["max_value"]), 251.0)
        self.assertEqual(float(overall_row["value"]), 220.0)
        self.assertEqual(float(overall_row["missing_count"]), 31.0)

    def test_missing_counts_use_zero_when_region_has_no_snapshot(self):
        snapshots = pd.DataFrame(
            [
                {"date": "2026-01-01", "account": "Thombay", "entry_type": "pokemon", "region": "kanto", "value": 10},
            ]
        )
        config = pd.DataFrame(
            [
                {"entry_type": "pokemon", "region": "kanto", "max_value": 151, "locked": False, "notes": ""},
                {"entry_type": "pokemon", "region": "johto", "max_value": 100, "locked": False, "notes": ""},
            ]
        )
        missing = build_pokedex_missing_count_rows(
            snapshots,
            config,
            accounts=["Thombay"],
            entry_types=["pokemon"],
            regions=["johto"],
        )
        self.assertEqual(len(missing), 1)
        self.assertEqual(float(missing.iloc[0]["value"]), 0.0)
        self.assertEqual(float(missing.iloc[0]["missing_count"]), 100.0)

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
        self.assertEqual(len(summary), 4)
        self.assertEqual(summary["account"].tolist(), ["Thombay", "Thombay", "Cerius", "Cerius"])
        self.assertEqual(summary["entry_type"].tolist(), ["pokemon", "shiny", "pokemon", "shiny"])
        self.assertEqual(summary["entry_type_label"].tolist(), ["Pokemon", "Shiny", "Pokemon", "Shiny"])
        counts = {
            (row.account, row.entry_type): int(row.missing_count)
            for row in summary.itertuples(index=False)
        }
        self.assertEqual(counts[("Thombay", "pokemon")], 1)
        self.assertEqual(counts[("Cerius", "pokemon")], 2)
        self.assertEqual(counts[("Thombay", "shiny")], 2)
        self.assertEqual(counts[("Cerius", "shiny")], 2)
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

    def test_snapshot_comparison_gap_sign(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(6, "Charizard", "kanto"),
            ]
        )
        availability = pd.DataFrame(
            [
                {"entry_type": "mega", "dex_number": 6, "form": "X", "available": True, "notes": ""},
                {"entry_type": "mega", "dex_number": 6, "form": "Y", "available": True, "notes": ""},
            ]
        )
        species = pd.DataFrame(
            [
                _species("Thombay", "pokemon", 1),
                _species("Thombay", "pokemon", 6),
                {**_species("Thombay", "mega", 6), "form": "X"},
                {**_species("Thombay", "mega", 6, registered=False), "form": "Y"},
            ]
        )
        snapshots = pd.DataFrame(
            [
                {"date": "2026-06-01", "account": "Thombay", "entry_type": "pokemon", "region": "kanto", "value": 1},
                {"date": "2026-06-11", "account": "Thombay", "entry_type": "pokemon", "region": "kanto", "value": 3},
                {"date": "2026-06-11", "account": "Thombay", "entry_type": "mega", "region": "kanto", "value": 0},
            ]
        )
        config = pd.DataFrame(
            [
                {"entry_type": "pokemon", "region": "kanto", "max_value": 151, "locked": False, "notes": ""},
                {"entry_type": "mega", "region": "kanto", "max_value": 17, "locked": False, "notes": ""},
            ]
        )
        comparison = build_atlas_snapshot_comparison(
            catalog,
            species,
            snapshots,
            config,
            account="Thombay",
            region="kanto",
            availability_df=availability,
            as_of_date="2026-06-11",
        ).set_index("entry_type")
        pokemon = comparison.loc["pokemon"]
        self.assertEqual(int(pokemon["snapshot_value"]), 3)
        self.assertEqual(int(pokemon["atlas_count"]), 2)
        self.assertEqual(int(pokemon["max_value"]), 151)
        self.assertEqual(int(pokemon["gap"]), 1)
        mega = comparison.loc["mega"]
        self.assertEqual(int(mega["atlas_count"]), 1)
        self.assertEqual(int(mega["snapshot_value"]), 0)
        self.assertEqual(int(mega["gap"]), -1)
        self.assertEqual(list(comparison.index).index("hundo"), 2)
        self.assertLess(list(comparison.index).index("hundo"), list(comparison.index).index("lucky"))

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

    def test_overall_snapshot_comparison_reads_overall_row(self):
        catalog = pd.DataFrame(
            [
                _mon(1, "Bulbasaur", "kanto"),
                _mon(152, "Chikorita", "johto"),
            ]
        )
        species = pd.DataFrame(
            [
                _species("Thombay", "pokemon", 1),
                _species("Thombay", "pokemon", 152),
            ]
        )
        snapshots = pd.DataFrame(
            [
                {"date": "2026-06-11", "account": "Thombay", "entry_type": "pokemon", "region": "kanto", "value": 1},
                {"date": "2026-06-11", "account": "Thombay", "entry_type": "pokemon", "region": "johto", "value": 1},
                {"date": "2026-06-11", "account": "Thombay", "entry_type": "pokemon", "region": "overall", "value": 40},
            ]
        )
        config = pd.DataFrame(
            [
                {"entry_type": "pokemon", "region": "kanto", "max_value": 151, "locked": False, "notes": ""},
                {"entry_type": "pokemon", "region": "johto", "max_value": 100, "locked": False, "notes": ""},
                {"entry_type": "pokemon", "region": "overall", "max_value": 251, "locked": False, "notes": ""},
            ]
        )
        comparison = build_atlas_snapshot_comparison(
            catalog,
            species,
            snapshots,
            config,
            account="Thombay",
            region="overall",
            as_of_date="2026-06-11",
        ).set_index("entry_type")
        pokemon = comparison.loc["pokemon"]
        self.assertEqual(int(pokemon["atlas_count"]), 2)
        self.assertEqual(int(pokemon["snapshot_value"]), 40)
        self.assertEqual(int(pokemon["max_value"]), 251)
        self.assertEqual(int(pokemon["gap"]), 38)

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


if __name__ == "__main__":
    unittest.main()
