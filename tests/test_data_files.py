from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd  # type: ignore[import-untyped]

from webapp.data_files import (
    apply_manual_pokemon_availability,
    load_data_input_accounts,
    load_manual_pokemon_availability,
    load_manual_pokemon_availability_frame,
    load_medal_goals,
    load_pokedex_category_availability,
    load_pokedex_entry_config,
    load_pokedex_entry_snapshots,
    load_pokemon_catalog,
    load_pokemon_catalog_with_availability,
    merge_pokemon_catalog,
    save_data_input_account_types,
    save_manual_pokemon_availability,
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

    def test_load_category_availability_defaults_missing_form(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "legacy.csv"
            legacy.write_text(
                "entry_type,dex_number,available,notes\nmega,6,True,legacy\nshiny,1,False,keep\n",
                encoding="utf-8-sig",
            )
            loaded = load_pokedex_category_availability(legacy)

            formed = Path(tmp) / "formed.csv"
            formed.write_text(
                "entry_type,dex_number,form,available,notes\n"
                "mega,6,X,True,first\n"
                "mega,6,x,False,second\n"
                "mega,6,Y,True,y\n",
                encoding="utf-8-sig",
            )
            forms = load_pokedex_category_availability(formed)

        self.assertEqual(
            loaded.columns.tolist(),
            ["entry_type", "dex_number", "form", "available", "notes"],
        )
        self.assertEqual(set(loaded["form"].tolist()), {""})
        legacy_mega = loaded[loaded["entry_type"] == "mega"].iloc[0]
        self.assertEqual(int(legacy_mega["dex_number"]), 6)
        self.assertEqual(legacy_mega["form"], "")
        self.assertEqual(legacy_mega["notes"], "legacy")
        self.assertTrue(bool(legacy_mega["available"]))
        self.assertCountEqual(forms["form"].tolist(), ["x", "Y"])
        kept = forms[forms["form"].str.casefold() == "x"].iloc[0]
        self.assertEqual(kept["form"], "x")
        self.assertEqual(kept["notes"], "second")
        self.assertFalse(bool(kept["available"]))
        self.assertEqual(forms.loc[forms["form"] == "Y", "notes"].iloc[0], "y")

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
                    {
                        "date": "2026-04-30",
                        "account": "Thomzay",
                        "entry_type": "Pokemon",
                        "region": "Paldea",
                        "value": "103",
                    },
                ]
            ).to_csv(path, index=False, encoding="utf-8-sig")

            snapshots = load_pokedex_entry_snapshots(
                path,
                account_order=["Thombay"],
                valid_entry_types={"shiny", "lucky", "pokemon"},
                valid_regions={"kanto", "unidentified", "paldea"},
            )

        self.assertEqual(len(snapshots), 3)
        self.assertEqual(snapshots.iloc[0]["account"], "Thombay")
        self.assertEqual(snapshots.iloc[0]["entry_type"], "shiny")
        self.assertEqual(snapshots.iloc[0]["region"], "kanto")
        self.assertEqual(float(snapshots.iloc[0]["value"]), 12.0)
        self.assertEqual(snapshots.iloc[1]["region"], "unidentified")
        self.assertEqual(snapshots.iloc[2]["entry_type"], "pokemon")
        self.assertEqual(snapshots.iloc[2]["region"], "paldea")

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
        self.assertEqual(merged.iloc[0]["available_in_pogo"], "unknown")
        self.assertEqual(merged.iloc[0]["extra_info"], "keep this")

    def test_merge_pokemon_catalog_available_in_pogo_follows_seed(self):
        seeded = pd.DataFrame(
            [
                {
                    "dex_number": 1,
                    "name": "Bulbasaur",
                    "german_name": "Bisasam",
                    "region": "kanto",
                    "type_1": "grass",
                    "type_2": "poison",
                    "available_in_pogo": "yes",
                    "extra_info": "",
                },
                {
                    "dex_number": 2,
                    "name": "Ivysaur",
                    "german_name": "Bisaknosp",
                    "region": "kanto",
                    "type_1": "grass",
                    "type_2": "poison",
                    "available_in_pogo": "no",
                    "extra_info": "",
                },
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
                    "available_in_pogo": "no",
                    "extra_info": "keep this note",
                },
                {
                    "dex_number": 2,
                    "name": "Old Ivysaur",
                    "german_name": "Old Bisaknosp",
                    "region": "old",
                    "type_1": "old",
                    "type_2": "",
                    "available_in_pogo": "yes",
                    "extra_info": "",
                },
            ]
        )

        merged = merge_pokemon_catalog(seeded, existing)

        released = merged[merged["dex_number"] == 1].iloc[0]
        unreleased_saved_yes = merged[merged["dex_number"] == 2].iloc[0]
        self.assertEqual(released["available_in_pogo"], "yes")
        self.assertEqual(released["extra_info"], "keep this note")
        self.assertEqual(released["name"], "Bulbasaur")
        self.assertEqual(released["german_name"], "Bisasam")
        self.assertEqual(unreleased_saved_yes["available_in_pogo"], "no")
        self.assertEqual(unreleased_saved_yes["name"], "Ivysaur")

    def test_manual_pokemon_availability_overrides_yes_and_no(self):
        catalog = pd.DataFrame(
            [
                {"dex_number": 489, "name": "Phione", "available_in_pogo": "yes"},
                {"dex_number": 807, "name": "Zeraora", "available_in_pogo": "no"},
                {"dex_number": 1, "name": "Bulbasaur", "available_in_pogo": "yes"},
            ]
        )
        overrides = {489: "no", 807: "yes"}

        updated = apply_manual_pokemon_availability(catalog, overrides)

        self.assertEqual(updated["dex_number"].tolist(), [489, 807, 1])
        self.assertEqual(updated.loc[updated["dex_number"] == 489, "available_in_pogo"].iloc[0], "no")
        self.assertEqual(updated.loc[updated["dex_number"] == 807, "available_in_pogo"].iloc[0], "yes")
        self.assertEqual(updated.loc[updated["dex_number"] == 1, "available_in_pogo"].iloc[0], "yes")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manual_pokemon_availability.csv"
            path.write_text(
                "dex_number,available,notes\n"
                "489,no,Not released in Pokemon GO\n"
                "10,maybe,skip\n"
                "0,yes,invalid dex\n"
                "25,,blank available\n"
                "807,YES,keep\n",
                encoding="utf-8",
            )
            loaded = load_manual_pokemon_availability(path)
            missing = load_manual_pokemon_availability(Path(tmp) / "missing.csv")

        self.assertEqual(loaded, {489: "no", 807: "yes"})
        self.assertEqual(missing, {})

    def test_save_manual_pokemon_availability_merges_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manual_pokemon_availability.csv"
            path.write_text(
                "dex_number,available,notes\n"
                "489,no,Not released in Pokemon GO\n"
                "490,no,keep me\n",
                encoding="utf-8",
            )
            written = save_manual_pokemon_availability(
                path,
                [
                    {"dex_number": 489, "available": "catalog"},
                    {"dex_number": 807, "available": "yes", "notes": "early"},
                    {"dex_number": 1, "available": "catalog"},
                ],
            )
            loaded = load_manual_pokemon_availability(path)
            frame = load_manual_pokemon_availability_frame(path)

        self.assertEqual(written, 2)
        self.assertEqual(loaded, {490: "no", 807: "yes"})
        notes = {int(row.dex_number): str(row.notes) for row in frame.itertuples(index=False)}
        self.assertEqual(notes, {490: "keep me", 807: "early"})

    def test_save_manual_pokemon_availability_keeps_note_when_notes_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manual_pokemon_availability.csv"
            path.write_text(
                "dex_number,available,notes\n490,no,keep me\n",
                encoding="utf-8",
            )
            save_manual_pokemon_availability(path, [{"dex_number": 490, "available": "yes"}])
            frame = load_manual_pokemon_availability_frame(path)

        self.assertEqual(frame.iloc[0]["available"], "yes")
        self.assertEqual(frame.iloc[0]["notes"], "keep me")

    def test_save_manual_pokemon_availability_clears_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manual_pokemon_availability.csv"
            path.write_text(
                "dex_number,available,notes\n490,no,keep me\n",
                encoding="utf-8",
            )
            save_manual_pokemon_availability(path, [{"dex_number": 490, "available": "no", "notes": ""}])
            frame = load_manual_pokemon_availability_frame(path)

        self.assertEqual(frame.iloc[0]["available"], "no")
        self.assertEqual(frame.iloc[0]["notes"], "")

    def test_load_pokemon_catalog_with_availability_applies_override_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog_path = root / "pokemon_catalog.csv"
            override_path = root / "manual_pokemon_availability.csv"
            pd.DataFrame(
                [
                    {"dex_number": 489, "name": "Phione", "available_in_pogo": "yes"},
                    {"dex_number": 1, "name": "Bulbasaur", "available_in_pogo": "yes"},
                ]
            ).to_csv(catalog_path, index=False, encoding="utf-8-sig")
            override_path.write_text(
                "dex_number,available,notes\n489,no,held\n",
                encoding="utf-8",
            )
            loaded = load_pokemon_catalog_with_availability(catalog_path, override_path)

        phione = loaded.loc[loaded["dex_number"] == 489, "available_in_pogo"].iloc[0]
        bulbasaur = loaded.loc[loaded["dex_number"] == 1, "available_in_pogo"].iloc[0]
        self.assertEqual(phione, "no")
        self.assertEqual(bulbasaur, "yes")

    def test_save_manual_pokemon_availability_skips_invalid_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manual_pokemon_availability.csv"
            path.write_text(
                "dex_number,available,notes\n490,no,keep me\n",
                encoding="utf-8-sig",
            )
            written = save_manual_pokemon_availability(
                path,
                [{"dex_number": 490, "available": "maybe", "notes": "changed"}],
            )
            loaded = load_manual_pokemon_availability(path)
            frame = load_manual_pokemon_availability_frame(path)

        self.assertEqual(written, 1)
        self.assertEqual(loaded, {490: "no"})
        self.assertEqual(frame.iloc[0]["notes"], "keep me")


if __name__ == "__main__":
    unittest.main()
