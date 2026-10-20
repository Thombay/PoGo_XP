from __future__ import annotations

import re
import unittest

import pandas as pd  # type: ignore[import-untyped]

from webapp.app import (
    _carry_forward_xp_chart_rows,
    build_player_trend_projection_trace,
    build_selected_leader_trend_trace,
    build_xp_catchup_projection_trace,
    build_xp_projection_series_map,
    restrict_to_common_interval,
)


def _ols_slope_intercept(series: pd.DataFrame) -> tuple[float, float]:
    x = series["Date"].map(pd.Timestamp.toordinal).astype(float)
    y = series["Total XP"].astype(float)
    x_mean = float(x.mean())
    y_mean = float(y.mean())
    denom = float(((x - x_mean) ** 2).sum())
    slope = float(((x - x_mean) * (y - y_mean)).sum() / denom)
    intercept = y_mean - slope * x_mean
    return slope, intercept


def _off_fit_projection_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Same end date. Player's last point is below the fit; the leader is nearly on its fit."""
    dates = pd.to_datetime(["2026-01-01", "2026-01-11", "2026-01-21", "2026-01-31"])
    player = pd.DataFrame({"Date": dates, "Total XP": [0.0, 1000.0, 2000.0, 1500.0]})
    leader = pd.DataFrame({"Date": dates, "Total XP": [5000.0, 5400.0, 5800.0, 6205.0]})
    return player, leader


def _legend_date(name: object) -> pd.Timestamp:
    found = re.findall(r"\d{4}-\d{2}-\d{2}", str(name))
    if not found:
        raise AssertionError(f"legend name has no ISO date: {name!r}")
    return pd.Timestamp(found[-1])


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

    def test_common_interval_uses_row_dense_window_over_latest_single_snapshot(self):
        rows = []
        for player in ["OldA", "OldB", "OldC"]:
            for dt in ["2019-01-01", "2026-03-01", "2026-03-15", "2026-04-01"]:
                rows.append((dt, player, 100.0))
        for player in [f"Main{i}" for i in range(20)]:
            for dt in ["2026-03-01", "2026-03-15", "2026-04-01"]:
                rows.append((dt, player, 100.0))
        rows.append(("2026-04-01", "NewOne", 100.0))
        df = pd.DataFrame(rows, columns=["Date", "Spieler", "Total XP"])
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

        out = restrict_to_common_interval(df)

        self.assertEqual(out["Date"].min(), pd.Timestamp("2026-03-01"))
        self.assertEqual(out["Date"].max(), pd.Timestamp("2026-03-15"))
        self.assertNotIn("NewOne", set(out["Spieler"].tolist()))
        self.assertFalse(bool((out["Date"] < pd.Timestamp("2026-03-01")).any()))

    def test_common_interval_keeps_longer_main_cohort_when_single_account_starts_later(self):
        rows = []
        for player in ["OldA", "OldB", "OldC"]:
            for dt in ["2023-01-01", "2025-01-01", "2025-06-01", "2026-01-01"]:
                rows.append((dt, player, 100.0))
        for player in [f"Main{i}" for i in range(10)]:
            for dt in ["2025-01-01", "2025-06-01", "2026-01-01"]:
                rows.append((dt, player, 100.0))
        rows.append(("2026-01-01", "LateNew", 100.0))
        df = pd.DataFrame(rows, columns=["Date", "Spieler", "Total XP"])
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

        out = restrict_to_common_interval(df)

        self.assertEqual(out["Date"].min(), pd.Timestamp("2025-01-01"))
        self.assertEqual(out["Date"].max(), pd.Timestamp("2025-06-01"))
        self.assertNotIn("LateNew", set(out["Spieler"].tolist()))

    def test_common_interval_prefers_longer_shared_window_over_small_later_additions(self):
        rows = []
        for player in [f"Feb{i}" for i in range(24)]:
            for dt in ["2026-02-10", "2026-03-01", "2026-03-15", "2026-04-01"]:
                rows.append((dt, player, 100.0))
        rows.extend(
            [
                ("2026-03-01", "MarchOnly", 100.0),
                ("2026-03-15", "MarchOnly", 100.0),
                ("2026-04-01", "MarchOnly", 100.0),
            ]
        )
        rows.append(("2026-04-01", "LateNew", 100.0))
        df = pd.DataFrame(rows, columns=["Date", "Spieler", "Total XP"])
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

        out = restrict_to_common_interval(df)

        self.assertEqual(out["Date"].min(), pd.Timestamp("2026-03-01"))
        self.assertEqual(out["Date"].max(), pd.Timestamp("2026-03-15"))
        self.assertNotIn("LateNew", set(out["Spieler"].tolist()))

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

    def test_catchup_line_starts_at_last_actual_and_meets_on_anchored_rays(self):
        player, leader = _off_fit_projection_frames()
        player_slope, player_intercept = _ols_slope_intercept(player)
        leader_slope, leader_intercept = _ols_slope_intercept(leader)
        player_last_date = pd.Timestamp(player["Date"].iloc[-1])
        leader_last_date = pd.Timestamp(leader["Date"].iloc[-1])
        player_last_actual = float(player["Total XP"].iloc[-1])
        leader_last_actual = float(leader["Total XP"].iloc[-1])
        player_last_ordinal = float(player_last_date.toordinal())
        leader_last_ordinal = float(leader_last_date.toordinal())

        self.assertEqual(player_last_date, leader_last_date)
        self.assertGreater(player_slope, leader_slope)
        self.assertGreater(leader_last_actual, player_last_actual)
        self.assertLess(player_last_actual, player_intercept + player_slope * player_last_ordinal)
        self.assertLess(abs(leader_last_actual - (leader_intercept + leader_slope * leader_last_ordinal)), 5.0)

        rel_slope = player_slope - leader_slope
        actual_gap = leader_last_actual - player_last_actual
        target_x = (
            actual_gap + player_slope * player_last_ordinal - leader_slope * leader_last_ordinal
        ) / rel_slope
        anchored_eta = pd.Timestamp.fromordinal(int(round(target_x)))
        same_date_eta = player_last_date + pd.Timedelta(days=int(round(actual_gap / rel_slope)))
        fitted_x = (leader_intercept - player_intercept) / rel_slope
        fitted_eta = pd.Timestamp.fromordinal(int(round(fitted_x)))
        self.assertEqual(anchored_eta, same_date_eta)
        self.assertGreater(anchored_eta, fitted_eta)

        trace, reason = build_xp_catchup_projection_trace(player, leader, "Player", "Leader")

        self.assertIsNotNone(trace, reason)
        assert trace is not None
        self.assertEqual(
            float(trace.y[0]),
            player_last_actual,
            msg="catch-up line must start at the player's last actual Total XP",
        )
        self.assertEqual(pd.Timestamp(trace.x[0]), player_last_date)
        legend_date = _legend_date(trace.name)
        self.assertEqual(
            legend_date,
            anchored_eta,
            msg=(
                f"legend date should be the anchored ray crossing {anchored_eta.date().isoformat()}, "
                f"not the fitted-line crossing {fitted_eta.date().isoformat()}"
            ),
        )
        self.assertGreater(legend_date, fitted_eta)

    def test_leader_and_player_extensions_start_at_last_actual_xp(self):
        player, leader = _off_fit_projection_frames()
        end_date = pd.Timestamp(player["Date"].iloc[-1]) + pd.Timedelta(days=5)

        leader_trace, leader_reason = build_selected_leader_trend_trace(
            leader,
            "Leader",
            end_date=end_date,
        )
        player_trace, player_reason = build_player_trend_projection_trace(
            player,
            "Player",
            end_date=end_date,
        )

        self._assert_extension_anchored_to_last_actual(leader_trace, leader_reason, leader, end_date)
        self._assert_extension_anchored_to_last_actual(player_trace, player_reason, player, end_date)

    def _assert_extension_anchored_to_last_actual(self, trace, reason, series: pd.DataFrame, end_date: pd.Timestamp):
        slope, _intercept = _ols_slope_intercept(series)
        last_date = pd.Timestamp(series["Date"].iloc[-1])
        last_actual = float(series["Total XP"].iloc[-1])
        expected_end_y = last_actual + slope * (float(end_date.toordinal()) - float(last_date.toordinal()))

        self.assertIsNotNone(trace, reason)
        assert trace is not None
        self.assertEqual(
            float(trace.y[0]),
            last_actual,
            msg="trend extension must start at the last actual Total XP",
        )
        self.assertEqual(pd.Timestamp(trace.x[0]), last_date)
        end_ys = [float(y) for x, y in zip(trace.x, trace.y) if pd.Timestamp(x) == pd.Timestamp(end_date)]
        self.assertEqual(len(end_ys), 1, msg=list(trace.x))
        self.assertAlmostEqual(end_ys[0], expected_end_y, delta=1e-6)


if __name__ == "__main__":
    unittest.main()
