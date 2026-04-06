from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from shared.xp_utils import (
    carry_forward_max_level_rows,
    is_max_level,
    max_configured_level,
    total_xp_from_level_input,
    xp_input_label,
)
from webapp.data_files import load_xp_history


class XpUtilsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.curve_map = {
            79: 190_000_000,
            80: 203_353_000,
        }

    def test_max_level_detection(self):
        self.assertEqual(max_configured_level(self.curve_map), 80)
        self.assertFalse(is_max_level(79, self.curve_map))
        self.assertTrue(is_max_level(80, self.curve_map))
        self.assertEqual(xp_input_label(80, self.curve_map), "XP Bar")

    def test_total_xp_from_regular_level_uses_base_plus_bar(self):
        self.assertEqual(total_xp_from_level_input(79, 12_345, self.curve_map), 190_012_345)

    def test_total_xp_from_max_level_still_uses_level_plus_bar(self):
        self.assertEqual(total_xp_from_level_input(80, 431_512_558, self.curve_map), 634_865_558)

    def test_load_xp_history_interprets_max_level_rows_as_level_plus_bar(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "xp_history.csv"
            path.write_text(
                "\n".join(
                    [
                        "Date;Spieler;Lvl;XP Bar",
                        "2026-04-01;Maxer;80;431512558",
                        "2026-04-01;Near;79;12345",
                    ]
                )
                + "\n",
                encoding="utf-8-sig",
            )

            loaded = load_xp_history(path, self.curve_map).set_index("Spieler")

            self.assertEqual(int(loaded.loc["Maxer", "Total XP"]), 634_865_558)
            self.assertEqual(int(loaded.loc["Near", "Total XP"]), 190_012_345)

    def test_carry_forward_max_level_rows_extends_last_known_total(self):
        df = pd.DataFrame(
            {
                "Date": pd.to_datetime(["2026-04-01", "2026-04-01", "2026-04-08"]),
                "Spieler": ["Maxer", "Near", "Near"],
                "Lvl": [80, 79, 79],
                "XP Bar": [431_512_558, 12_000, 20_000],
                "Total XP": [634_865_558, 190_012_000, 190_020_000],
            }
        )

        expanded = carry_forward_max_level_rows(df, self.curve_map)
        maxer_rows = expanded[expanded["Spieler"] == "Maxer"].sort_values("Date").reset_index(drop=True)

        self.assertEqual(len(maxer_rows), 2)
        self.assertEqual(maxer_rows["Date"].dt.strftime("%Y-%m-%d").tolist(), ["2026-04-01", "2026-04-08"])
        self.assertTrue((maxer_rows["Total XP"] == 634_865_558).all())


if __name__ == "__main__":
    unittest.main()
