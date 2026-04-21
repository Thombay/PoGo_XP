from __future__ import annotations

import unittest

import pandas as pd

from webapp.app import (
    _carry_forward_xp_chart_rows,
    build_xp_catchup_projection_trace,
    build_xp_projection_series_map,
    restrict_to_common_interval,
)


class TrendProjectionTest(unittest.TestCase):
    def test_carry_forward_xp_chart_rows_fills_missing_snapshots_after_first_entry(self):
        df = pd.DataFrame(
            {
                "Date": pd.to_datetime(["2026-01-01", "2026-01-15", "2026-01-08"]),
                "Spieler": ["A", "A", "New"],
                "Total XP": [100.0, 180.0, 50.0],
            }
        )
        out = _carry_forward_xp_chart_rows(
            df,
            [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-08"), pd.Timestamp("2026-01-15")],
        )

        a = out[out["Spieler"] == "A"].reset_index(drop=True)
        new = out[out["Spieler"] == "New"].reset_index(drop=True)
        self.assertListEqual(a["Date"].dt.strftime("%Y-%m-%d").tolist(), ["2026-01-01", "2026-01-08", "2026-01-15"])
        self.assertListEqual(a["Total XP"].tolist(), [100.0, 100.0, 180.0])
        self.assertListEqual(new["Date"].dt.strftime("%Y-%m-%d").tolist(), ["2026-01-08", "2026-01-15"])
        self.assertListEqual(new["Total XP"].tolist(), [50.0, 50.0])

    def test_max_data_interval_uses_largest_starting_group_and_keeps_later_rows(self):
        rows = []
        for player in ["OldA", "OldB", "OldC"]:
            for dt in ["2019-01-01", "2026-03-01", "2026-04-01"]:
                rows.append((dt, player, 100.0))
        for player in [f"Main{i}" for i in range(20)]:
            for dt in ["2026-03-01", "2026-04-01"]:
                rows.append((dt, player, 100.0))
        rows.append(("2026-04-01", "NewOne", 100.0))
        df = pd.DataFrame(rows, columns=["Date", "Spieler", "Total XP"])
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

        out = restrict_to_common_interval(df)

        self.assertEqual(out["Date"].min(), pd.Timestamp("2026-03-01"))
        self.assertEqual(out["Date"].max(), pd.Timestamp("2026-04-01"))
        self.assertIn("NewOne", set(out["Spieler"].tolist()))
        self.assertFalse(bool((out["Date"] < pd.Timestamp("2026-03-01")).any()))

    def test_max_data_interval_keeps_main_cohort_when_single_account_starts_later(self):
        rows = []
        for player in ["OldA", "OldB", "OldC"]:
            for dt in ["2023-01-01", "2025-01-01", "2026-01-01"]:
                rows.append((dt, player, 100.0))
        for player in [f"Main{i}" for i in range(10)]:
            for dt in ["2025-01-01", "2026-01-01"]:
                rows.append((dt, player, 100.0))
        rows.append(("2026-01-01", "LateNew", 100.0))
        df = pd.DataFrame(rows, columns=["Date", "Spieler", "Total XP"])
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

        out = restrict_to_common_interval(df)

        self.assertEqual(out["Date"].min(), pd.Timestamp("2025-01-01"))
        self.assertEqual(out["Date"].max(), pd.Timestamp("2026-01-01"))
        self.assertIn("LateNew", set(out["Spieler"].tolist()))

    def test_max_data_interval_allows_small_later_additions(self):
        rows = []
        for player in [f"Feb{i}" for i in range(24)]:
            for dt in ["2026-02-10", "2026-03-01", "2026-04-01"]:
                rows.append((dt, player, 100.0))
        rows.extend([("2026-03-01", "MarchOnly", 100.0), ("2026-04-01", "MarchOnly", 100.0)])
        rows.append(("2026-04-01", "LateNew", 100.0))
        df = pd.DataFrame(rows, columns=["Date", "Spieler", "Total XP"])
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

        out = restrict_to_common_interval(df)

        self.assertEqual(out["Date"].min(), pd.Timestamp("2026-03-01"))
        self.assertEqual(out["Date"].max(), pd.Timestamp("2026-04-01"))
        self.assertIn("LateNew", set(out["Spieler"].tolist()))

    def test_projection_series_map_keeps_each_players_own_start(self):
        df = pd.DataFrame(
            {
                "Date": pd.to_datetime(
                    [
                        "2026-01-01",
                        "2026-02-01",
                        "2026-03-01",
                        "2026-01-01",
                        "2026-02-01",
                        "2026-03-01",
                        "2026-02-01",
                        "2026-03-01",
                    ]
                ),
                "Spieler": [
                    "Player",
                    "Player",
                    "Player",
                    "LeaderSlow",
                    "LeaderSlow",
                    "LeaderSlow",
                    "LeaderLate",
                    "LeaderLate",
                ],
                "Total XP": [0.0, 500.0, 1700.0, 2000.0, 2200.0, 2400.0, 1000.0, 2000.0],
            }
        )

        series_map = build_xp_projection_series_map(df)

        self.assertListEqual(
            series_map["Player"]["Date"].dt.strftime("%Y-%m-%d").tolist(),
            ["2026-01-01", "2026-02-01", "2026-03-01"],
        )
        self.assertListEqual(
            series_map["LeaderLate"]["Date"].dt.strftime("%Y-%m-%d").tolist(),
            ["2026-02-01", "2026-03-01"],
        )

    def test_switching_to_later_starting_leader_does_not_refit_player_from_that_date(self):
        df = pd.DataFrame(
            {
                "Date": pd.to_datetime(
                    [
                        "2026-01-01",
                        "2026-02-01",
                        "2026-03-01",
                        "2026-01-01",
                        "2026-02-01",
                        "2026-03-01",
                        "2026-02-01",
                        "2026-03-01",
                    ]
                ),
                "Spieler": [
                    "Player",
                    "Player",
                    "Player",
                    "LeaderSlow",
                    "LeaderSlow",
                    "LeaderSlow",
                    "LeaderLate",
                    "LeaderLate",
                ],
                "Total XP": [0.0, 500.0, 1700.0, 2000.0, 2200.0, 2400.0, 1000.0, 2000.0],
            }
        )

        series_map = build_xp_projection_series_map(df)

        slow_trace, slow_reason = build_xp_catchup_projection_trace(
            series_map["Player"],
            series_map["LeaderSlow"],
            "Player",
            "LeaderSlow",
        )
        late_trace, late_reason = build_xp_catchup_projection_trace(
            series_map["Player"],
            series_map["LeaderLate"],
            "Player",
            "LeaderLate",
        )

        self.assertIsNotNone(slow_trace, slow_reason)
        self.assertIsNone(late_trace)
        self.assertIsNotNone(late_reason)
        self.assertIn("does not close gap", late_reason)


if __name__ == "__main__":
    unittest.main()
