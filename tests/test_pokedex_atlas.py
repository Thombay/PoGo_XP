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
from webapp.pokedex import (
    ATLAS_ENTRY_KINDS,
    apply_catalog_community_fields,
    build_category_availability_rows,
    build_missing_pokemon_rows,
    build_pokedex_atlas_cards,
    build_pokedex_missing_count_rows,
    build_pokedex_target_rows,
    build_species_missing_summary,
    category_target_dex_numbers,
    extract_pogoapi_dex_numbers,
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
            ["date", "account", "entry_type", "dex_number", "registered", "can_evolve_now", "notes"],
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

    def test_atlas_cards_mark_unregistered_as_missing(self):
        self.assertEqual(
            ATLAS_ENTRY_KINDS,
            (
                ("pokemon", "Pokemon"),
                ("shiny", "Shiny"),
                ("lucky", "Lucky"),
                ("hundo", "100%"),
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


if __name__ == "__main__":
    unittest.main()
