from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from webapp.data_files import (
    load_medal_goals,
    load_data_input_accounts,
    load_pokedex_entry_config,
    load_pokedex_entry_snapshots,
    load_pokemon_catalog,
    merge_pokemon_catalog,
    save_data_input_account_types,
)


class DataFilesTest(unittest.TestCase):
    def test_load_medal_goals_keeps_explanation_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "medal_goals.csv"
            pd.DataFrame(
                [
                    {
                        "medal_id": "Collector",
                        "display_name": "Collector",
                        "goal_value": "50000",
                        "explanation": "Pokemon caught",
                    }
                ]
            ).to_csv(path, index=False, encoding="utf-8-sig")

            goals = load_medal_goals(path)

        self.assertListEqual(goals.columns.tolist(), ["medal_id", "display_name", "goal_value", "explanation"])
        self.assertEqual(goals.iloc[0]["medal_id"], "collector")
        self.assertEqual(goals.iloc[0]["explanation"], "Pokemon caught")

    def test_load_medal_goals_accepts_legacy_file_without_explanation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "medal_goals.csv"
            pd.DataFrame(
                [{"medal_id": "jogger", "display_name": "Jogger", "goal_value": "10000"}]
            ).to_csv(path, index=False, encoding="utf-8-sig")

            goals = load_medal_goals(path)

        self.assertIn("explanation", goals.columns)
        self.assertEqual(goals.iloc[0]["explanation"], "")

    def test_load_pokedex_entry_snapshots_normalizes_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pokedex_entry_snapshots.csv"
            pd.DataFrame(
                [
                    {
                        "date": "2026-04-30",
                        "account": " Thombay ",
                        "entry_type": "Shiny",
                        "region": "Kanto",
                        "value": "12",
                    },
                    {
                        "date": "2026-04-30",
                        "account": "Thombay",
                        "entry_type": "ignored",
                        "region": "kanto",
                        "value": "99",
                    },
                    {
                        "date": "2026-04-30",
                        "account": "Cerius",
                        "entry_type": "Lucky",
                        "region": "Unidentified",
                        "value": "2",
                    },
                ]
            ).to_csv(path, index=False, encoding="utf-8-sig")

            snapshots = load_pokedex_entry_snapshots(
                path,
                account_order=["Thombay"],
                valid_entry_types={"shiny", "lucky"},
                valid_regions={"kanto", "unidentified"},
            )

        self.assertEqual(len(snapshots), 2)
        self.assertEqual(snapshots.iloc[0]["account"], "Thombay")
        self.assertEqual(snapshots.iloc[0]["entry_type"], "shiny")
        self.assertEqual(snapshots.iloc[0]["region"], "kanto")
        self.assertEqual(float(snapshots.iloc[0]["value"]), 12.0)
        self.assertEqual(snapshots.iloc[1]["region"], "unidentified")

    def test_load_pokedex_entry_config_normalizes_locked_and_max(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pokedex_entry_config.csv"
            pd.DataFrame(
                [
                    {
                        "entry_type": "Shiny",
                        "region": "Hisui",
                        "max_value": "0",
                        "locked": "true",
                        "notes": "No entries yet",
                    },
                    {
                        "entry_type": "Mega",
                        "region": "Kalos",
                        "max_value": "2",
                        "locked": "false",
                        "notes": "",
                    },
                ]
            ).to_csv(path, index=False, encoding="utf-8-sig")

            config = load_pokedex_entry_config(
                path,
                valid_entry_types={"shiny", "mega"},
                valid_regions={"hisui", "kalos"},
            )

        self.assertEqual(len(config), 2)
        self.assertTrue(bool(config[config["entry_type"] == "shiny"].iloc[0]["locked"]))
        self.assertEqual(float(config[config["entry_type"] == "mega"].iloc[0]["max_value"]), 2.0)

    def test_load_data_input_accounts_normalizes_enabled_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data_input_accounts.csv"
            pd.DataFrame(
                [
                    {"input_type": "XP", "account": " Thombay ", "enabled": "yes", "notes": ""},
                    {"input_type": "Medal", "account": "Cerius", "enabled": "false", "notes": "skip"},
                    {"input_type": "Other", "account": "Ignored", "enabled": "true", "notes": ""},
                ]
            ).to_csv(path, index=False, encoding="utf-8-sig")

            config = load_data_input_accounts(path, valid_input_types={"xp", "medal"})

        self.assertEqual(len(config), 2)
        self.assertEqual(config.iloc[0]["input_type"], "xp")
        self.assertEqual(config.iloc[0]["account"], "Thombay")
        self.assertTrue(bool(config.iloc[0]["enabled"]))
        self.assertFalse(bool(config.iloc[1]["enabled"]))

    def test_load_data_input_accounts_accepts_account_centric_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data_input_accounts.csv"
            pd.DataFrame(
                [
                    {"account": "Thombay", "input_types": "xp;medal;pokedex", "notes": ""},
                    {"account": "Cerius", "input_types": "xp", "notes": ""},
                    {"account": "Thomzay", "input_types": "", "notes": "disabled"},
                ]
            ).to_csv(path, index=False, encoding="utf-8-sig")

            config = load_data_input_accounts(path, valid_input_types={"xp", "medal", "pokedex"})

        self.assertEqual(len(config), 4)
        self.assertEqual(config[config["account"] == "Thombay"]["input_type"].tolist(), ["xp", "medal", "pokedex"])
        self.assertEqual(config[config["account"] == "Cerius"]["input_type"].tolist(), ["xp"])

    def test_save_data_input_account_types_writes_account_centric_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data_input_accounts.csv"
            pd.DataFrame(
                [
                    {"account": "Thombay", "input_types": "xp;medal", "notes": "main"},
                ]
            ).to_csv(path, index=False, encoding="utf-8-sig")

            save_data_input_account_types(
                path,
                "Cerius",
                ["pokedex", "xp"],
                type_order=["xp", "medal", "pokedex"],
            )

            raw = pd.read_csv(path, encoding="utf-8-sig")

        self.assertListEqual(raw.columns.tolist(), ["account", "input_types", "notes"])
        self.assertEqual(raw[raw["account"] == "Cerius"].iloc[0]["input_types"], "xp;pokedex")

    def test_load_pokemon_catalog_keeps_editable_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pokemon_catalog.csv"
            pd.DataFrame(
                [
                    {
                        "dex_number": "1",
                        "name": "Bulbasaur",
                        "german_name": "Bisasam",
                        "region": "kanto",
                        "type_1": "grass",
                        "type_2": "poison",
                        "available_in_pogo": "yes",
                        "extra_info": "starter",
                    }
                ]
            ).to_csv(path, index=False, encoding="utf-8-sig")

            catalog = load_pokemon_catalog(path)

        self.assertEqual(catalog.iloc[0]["available_in_pogo"], "yes")
        self.assertEqual(catalog.iloc[0]["german_name"], "Bisasam")
        self.assertEqual(catalog.iloc[0]["extra_info"], "starter")

    def test_merge_pokemon_catalog_preserves_editable_fields(self):
        seeded = pd.DataFrame(
            [
                {
                    "dex_number": 1,
                    "name": "Bulbasaur",
                    "german_name": "Bisasam",
                    "region": "kanto",
                    "type_1": "grass",
                    "type_2": "poison",
                    "available_in_pogo": "unknown",
                    "extra_info": "",
                }
            ]
        )
        existing = pd.DataFrame(
            [
                {
                    "dex_number": 1,
                    "name": "Old Bulbasaur",
                    "german_name": "Old Bisasam",
                    "region": "old",
                    "type_1": "old",
                    "type_2": "",
                    "available_in_pogo": "yes",
                    "extra_info": "keep this",
                }
            ]
        )

        merged = merge_pokemon_catalog(seeded, existing)

        self.assertEqual(merged.iloc[0]["name"], "Bulbasaur")
        self.assertEqual(merged.iloc[0]["german_name"], "Bisasam")
        self.assertEqual(merged.iloc[0]["available_in_pogo"], "yes")
        self.assertEqual(merged.iloc[0]["extra_info"], "keep this")


if __name__ == "__main__":
    unittest.main()
