from __future__ import annotations

import unittest

import pandas as pd

from shared.data_intervals import carry_forward_value_rows, restrict_to_max_data_start_interval


class DataIntervalsTest(unittest.TestCase):
    def test_restrict_to_max_data_start_uses_plateau_start(self):
        rows = []
        for player in ["OldA", "OldB", "OldC"]:
            for dt in ["2019-01-01", "2026-03-01", "2026-04-01"]:
                rows.append((dt, player, 100.0))
        for player in [f"Main{i}" for i in range(20)]:
            for dt in ["2026-03-01", "2026-04-01"]:
                rows.append((dt, player, 100.0))
        rows.append(("2026-04-01", "LateNew", 100.0))
        df = pd.DataFrame(rows, columns=["Date", "Spieler", "Total XP"])

        out = restrict_to_max_data_start_interval(df, date_col="Date", group_col="Spieler")

        self.assertEqual(out["Date"].min(), pd.Timestamp("2026-03-01"))
        self.assertEqual(out["Date"].max(), pd.Timestamp("2026-04-01"))
        self.assertIn("LateNew", set(out["Spieler"].tolist()))

    def test_restrict_to_max_data_start_allows_one_late_account_without_resetting_window(self):
        rows = []
        for player in ["OldA", "OldB", "OldC"]:
            for dt in ["2023-01-01", "2025-01-01", "2026-01-01"]:
                rows.append((dt, player, 100.0))
        for player in [f"Main{i}" for i in range(10)]:
            for dt in ["2025-01-01", "2026-01-01"]:
                rows.append((dt, player, 100.0))
        rows.append(("2026-01-01", "LateNew", 100.0))
        df = pd.DataFrame(rows, columns=["Date", "Spieler", "Total XP"])

        out = restrict_to_max_data_start_interval(df, date_col="Date", group_col="Spieler")

        self.assertEqual(out["Date"].min(), pd.Timestamp("2025-01-01"))
        self.assertEqual(out["Date"].max(), pd.Timestamp("2026-01-01"))
        self.assertIn("LateNew", set(out["Spieler"].tolist()))
        self.assertFalse(bool((out["Date"] < pd.Timestamp("2025-01-01")).any()))

    def test_carry_forward_value_rows_starts_new_groups_at_first_real_entry(self):
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-01", "2026-01-15", "2026-01-08"]),
                "account": ["A", "A", "New"],
                "value": [100.0, 180.0, 50.0],
            }
        )

        out = carry_forward_value_rows(
            df,
            date_col="date",
            group_col="account",
            value_cols=["value"],
            chart_dates=[
                pd.Timestamp("2026-01-01"),
                pd.Timestamp("2026-01-08"),
                pd.Timestamp("2026-01-15"),
            ],
        )

        a = out[out["account"] == "A"].reset_index(drop=True)
        new = out[out["account"] == "New"].reset_index(drop=True)
        self.assertListEqual(a["date"].dt.strftime("%Y-%m-%d").tolist(), ["2026-01-01", "2026-01-08", "2026-01-15"])
        self.assertListEqual(a["value"].tolist(), [100.0, 100.0, 180.0])
        self.assertListEqual(new["date"].dt.strftime("%Y-%m-%d").tolist(), ["2026-01-08", "2026-01-15"])
        self.assertListEqual(new["value"].tolist(), [50.0, 50.0])


if __name__ == "__main__":
    unittest.main()
