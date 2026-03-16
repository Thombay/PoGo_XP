from __future__ import annotations

import unittest

import pandas as pd

from webapp.app import build_account_color_map


class AccountColorMapTest(unittest.TestCase):
    def test_build_account_color_map_uses_latest_xp_order_within_scope(self):
        xp_df = pd.DataFrame(
            {
                "Date": pd.to_datetime(["2026-03-01", "2026-03-01", "2026-03-08", "2026-03-08"]),
                "Spieler": ["A", "B", "A", "B"],
                "Total XP": [100.0, 200.0, 300.0, 250.0],
            }
        )
        color_map = build_account_color_map(["A", "B"], xp_df)
        self.assertIn("A", color_map)
        self.assertIn("B", color_map)
        self.assertNotEqual(color_map["A"], color_map["B"])


if __name__ == "__main__":
    unittest.main()
