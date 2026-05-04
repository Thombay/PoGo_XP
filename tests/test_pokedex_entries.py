from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd  # type: ignore[import-untyped]

from webapp.app import (
    accounts_for_data_input,
    build_pokedex_category_snapshot_rows,
    build_xp_activity_snapshot_rows,
    load_input_inactive_marker,
    save_input_inactive_marker,
    upsert_pokedex_entry_rows,
    with_derived_pokedex_overall_rows,
    with_medal_derived_pokedex_rows,
)
from webapp.data_files import load_pokedex_entry_snapshots


class PokedexEntriesTest(unittest.TestCase):
    def test_input_inactive_marker_round_trips_xp_and_pokedex(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ui_preferences.json"

            save_input_inactive_marker("xp", "2026-01-01", "Thombay", True, path=path)
            save_input_inactive_marker("pokedex", "2026-01-01", "Thombay", True, "shiny", path=path)

            self.assertTrue(load_input_inactive_marker("xp", "2026-01-01", "Thombay", path=path))
            self.assertTrue(load_input_inactive_marker("pokedex", "2026-01-01", "Thombay", "shiny", path=path))

            save_input_inactive_marker("xp", "2026-01-01", "Thombay", False, path=path)
            save_input_inactive_marker("pokedex", "2026-01-01", "Thombay", False, "shiny", path=path)

            self.assertFalse(load_input_inactive_marker("xp", "2026-01-01", "Thombay", path=path))
            self.assertFalse(load_input_inactive_marker("pokedex", "2026-01-01", "Thombay", "shiny", path=path))

    def test_build_xp_activity_snapshot_rows_can_document_unchanged_inactive_row(self):
        xp_rows, activity_rows, medal_rows = build_xp_activity_snapshot_rows(
            "2026-01-01",
            "Thombay",
            50,
            12345,
            False,
            1000,
            12.5,
            250,
        )

        self.assertEqual(xp_rows[0]["Date"], "2026-01-01")
        self.assertEqual(xp_rows[0]["Spieler"], "Thombay")
        self.assertEqual(xp_rows[0]["Lvl"], 50)
        self.assertEqual(xp_rows[0]["XP Bar"], 12345)
        self.assertEqual(activity_rows[0]["battles_won"], 1000.0)
        self.assertEqual({row["medal_id"] for row in medal_rows}, {"jogger", "collector"})

    def test_build_pokedex_category_snapshot_rows_skips_derived_and_locked_cells(self):
        rows = build_pokedex_category_snapshot_rows(
            "2026-01-01",
            "Thombay",
            "shiny",
            {
                "overall": 99,
                "kanto": 10,
                "johto": 5,
                "hisui": 1,
            },
            entry_config={("shiny", "hisui"): {"locked": True, "max_value": 0, "notes": ""}},
        )

        self.assertEqual([(row["region"], row["value"]) for row in rows], [("kanto", 10.0), ("johto", 5.0)])

    def test_accounts_for_data_input_uses_enabled_config_rows(self):
        config = pd.DataFrame(
            [
                {"input_type": "xp", "account": "Thombay", "enabled": True, "notes": ""},
                {"input_type": "xp", "account": "Cerius", "enabled": False, "notes": ""},
                {"input_type": "medal", "account": "Cerius", "enabled": True, "notes": ""},
            ]
        )

        accounts = accounts_for_data_input("xp", ["Thombay", "Cerius", "Thomzay"], config)

        self.assertEqual(accounts, ["Thombay"])

    def test_accounts_for_data_input_returns_empty_when_type_absent(self):
        config = pd.DataFrame(
            [
                {"input_type": "xp", "account": "Thombay", "enabled": True, "notes": ""},
            ]
        )

        accounts = accounts_for_data_input("medal", ["Thombay", "Cerius"], config, fallback_accounts=["Thombay"])

        self.assertEqual(accounts, [])

    def test_upsert_pokedex_entry_rows_rejects_decreasing_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pokedex_entry_snapshots.csv"
            upsert_pokedex_entry_rows(
                path,
                [
                    {
                        "date": "2026-01-01",
                        "account": "Thombay",
                        "entry_type": "shiny",
                        "region": "kanto",
                        "value": 10,
                    }
                ],
            )

            with self.assertRaises(ValueError):
                upsert_pokedex_entry_rows(
                    path,
                    [
                        {
                            "date": "2026-02-01",
                            "account": "Thombay",
                            "entry_type": "shiny",
                            "region": "kanto",
                            "value": 9,
                        }
                    ],
                )

    def test_upsert_pokedex_entry_rows_skips_medal_derived_region_cells(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pokedex_entry_snapshots.csv"
            written = upsert_pokedex_entry_rows(
                path,
                [
                    {
                        "date": "2026-01-01",
                        "account": "Thombay",
                        "entry_type": "pokemon",
                        "region": "kanto",
                        "value": 151,
                    }
                ],
            )

            snapshots = load_pokedex_entry_snapshots(path)

        self.assertEqual(written, 0)
        self.assertTrue(snapshots.empty)

    def test_upsert_pokedex_entry_rows_skips_manual_overall_cells(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pokedex_entry_snapshots.csv"
            written = upsert_pokedex_entry_rows(
                path,
                [
                    {
                        "date": "2026-01-01",
                        "account": "Thombay",
                        "entry_type": "shiny",
                        "region": "overall",
                        "value": 999,
                    }
                ],
            )

            snapshots = load_pokedex_entry_snapshots(path)

        self.assertEqual(written, 0)
        self.assertTrue(snapshots.empty)

    def test_upsert_pokedex_entry_rows_rejects_locked_config_cells(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pokedex_entry_snapshots.csv"
            with self.assertRaises(ValueError):
                upsert_pokedex_entry_rows(
                    path,
                    [
                        {
                            "date": "2026-01-01",
                            "account": "Thombay",
                            "entry_type": "shiny",
                            "region": "hisui",
                            "value": 1,
                        }
                    ],
                    entry_config={("shiny", "hisui"): {"locked": True, "max_value": 0, "notes": ""}},
                )

    def test_upsert_pokedex_entry_rows_rejects_values_above_config_max(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pokedex_entry_snapshots.csv"
            with self.assertRaises(ValueError):
                upsert_pokedex_entry_rows(
                    path,
                    [
                        {
                            "date": "2026-01-01",
                            "account": "Thombay",
                            "entry_type": "mega",
                            "region": "kalos",
                            "value": 3,
                        }
                    ],
                    entry_config={("mega", "kalos"): {"locked": False, "max_value": 2, "notes": ""}},
                )

    def test_medal_region_rows_are_available_as_pokedex_pokemon_counts(self):
        pokedex = pd.DataFrame(columns=["date", "account", "entry_type", "region", "value"])
        medals = pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2026-01-01"),
                    "account": "Thombay",
                    "medal_id": "kanto",
                    "value": 151,
                }
            ]
        )

        combined = with_medal_derived_pokedex_rows(pokedex, medals)

        self.assertEqual(len(combined), 2)
        self.assertEqual(combined.iloc[0]["entry_type"], "pokemon")
        self.assertEqual(combined.iloc[0]["region"], "overall")
        self.assertEqual(float(combined.iloc[0]["value"]), 151.0)
        self.assertEqual(combined.iloc[1]["region"], "kanto")
        self.assertEqual(float(combined.iloc[1]["value"]), 151.0)

    def test_overall_rows_are_derived_from_region_sums(self):
        pokedex = pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2026-01-01"),
                    "account": "Thombay",
                    "entry_type": "shiny",
                    "region": "kanto",
                    "value": 10,
                },
                {
                    "date": pd.Timestamp("2026-01-01"),
                    "account": "Thombay",
                    "entry_type": "shiny",
                    "region": "johto",
                    "value": 5,
                },
                {
                    "date": pd.Timestamp("2026-01-01"),
                    "account": "Thombay",
                    "entry_type": "shiny",
                    "region": "overall",
                    "value": 999,
                },
            ]
        )

        combined = with_derived_pokedex_overall_rows(pokedex)
        overall = combined[(combined["entry_type"] == "shiny") & (combined["region"] == "overall")]

        self.assertEqual(len(overall), 1)
        self.assertEqual(float(overall.iloc[0]["value"]), 15.0)


if __name__ == "__main__":
    unittest.main()
