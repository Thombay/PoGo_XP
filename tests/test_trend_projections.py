from __future__ import annotations

import unittest

import pandas as pd

from webapp.app import build_xp_catchup_projection_trace, build_xp_projection_series_map


class TrendProjectionTest(unittest.TestCase):
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
