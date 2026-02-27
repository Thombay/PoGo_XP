from __future__ import annotations

import unittest

import pandas as pd

from webapp.metrics import compute_player_kpis_30d, compute_player_kpis_window, recent_gain_table_from_metrics, xp_at


def _df(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["Date", "Spieler", "Total XP"])


class MetricsTest(unittest.TestCase):
    def test_window_specific_columns_for_7d(self):
        rows = [
            ("2026-01-01", "A", 0),
            ("2026-01-08", "A", 700),
            ("2026-01-15", "A", 1400),
            ("2026-01-22", "A", 2100),
        ]
        xp_df = _df(rows)
        xp_df["Date"] = pd.to_datetime(xp_df["Date"], errors="coerce")
        metrics = compute_player_kpis_window(xp_df, window_days=7, baseline_min_windows=1)
        self.assertIn("xp_gain_7d", metrics.columns)
        self.assertIn("xp_per_day_7d", metrics.columns)
        self.assertIn("eligible_7d", metrics.columns)
        self.assertNotIn("xp_gain_30d", metrics.columns)
        self.assertTrue(bool(metrics.iloc[0]["eligible_7d"]))

        gain = recent_gain_table_from_metrics(metrics, window_days=7)
        self.assertFalse(gain.empty)
        self.assertEqual(str(gain.iloc[0]["Spieler"]), "A")

    def test_increasing_series_has_no_declines(self):
        rows: list[tuple[str, str, float]] = []
        base = pd.Timestamp("2026-01-01")
        for day in range(0, 121, 10):
            d = (base + pd.Timedelta(days=day)).date().isoformat()
            rows.append((d, "A", day * 100.0))
            rows.append((d, "B", day * 120.0))
        xp_df = _df(rows)
        xp_df["Date"] = pd.to_datetime(xp_df["Date"], errors="coerce")
        metrics = compute_player_kpis_30d(xp_df, window_days=30, baseline_min_windows=3)
        eligible = metrics[metrics["eligible_baseline_30d"] == True]  # noqa: E712
        self.assertFalse(eligible.empty)
        self.assertTrue((eligible["delta_vs_baseline_30d"] >= 0).all())

    def test_mixed_improvement_and_decline_detected(self):
        rows = [
            ("2026-01-01", "Decliner", 0),
            ("2026-01-11", "Decliner", 1000),
            ("2026-01-21", "Decliner", 2000),
            ("2026-01-31", "Decliner", 3000),
            ("2026-02-10", "Decliner", 4000),
            ("2026-02-20", "Decliner", 5000),
            ("2026-03-02", "Decliner", 5500),
            ("2026-03-12", "Decliner", 6000),
            ("2026-03-22", "Decliner", 6500),
            ("2026-01-01", "Improver", 0),
            ("2026-01-11", "Improver", 900),
            ("2026-01-21", "Improver", 1800),
            ("2026-01-31", "Improver", 2700),
            ("2026-02-10", "Improver", 3600),
            ("2026-02-20", "Improver", 4500),
            ("2026-03-02", "Improver", 6300),
            ("2026-03-12", "Improver", 8100),
            ("2026-03-22", "Improver", 9900),
        ]
        xp_df = _df(rows)
        xp_df["Date"] = pd.to_datetime(xp_df["Date"], errors="coerce")
        metrics = compute_player_kpis_30d(xp_df, window_days=30, baseline_min_windows=3)
        d = metrics.set_index("Spieler")
        self.assertLess(float(d.loc["Decliner", "delta_vs_baseline_30d"]), 0.0)
        self.assertGreater(float(d.loc["Improver", "delta_vs_baseline_30d"]), 0.0)

    def test_irregular_interpolation_and_step(self):
        p = pd.DataFrame(
            {
                "Date": pd.to_datetime(["2026-01-01", "2026-01-21"]),
                "Spieler": ["A", "A"],
                "Total XP": [0.0, 2000.0],
            }
        )
        mid = xp_at(p, pd.Timestamp("2026-01-11"))
        self.assertAlmostEqual(float(mid.value), 1000.0, places=6)
        self.assertEqual(mid.method, "interpolated")

        after = xp_at(p, pd.Timestamp("2026-01-25"))
        self.assertAlmostEqual(float(after.value), 2000.0, places=6)
        self.assertEqual(after.method, "step")

        before = xp_at(p, pd.Timestamp("2025-12-25"))
        self.assertIsNone(before.value)
        self.assertIsNone(before.method)

    def test_baseline_threshold(self):
        rows = [
            ("2026-01-01", "A", 0),
            ("2026-01-10", "A", 800),
            ("2026-01-20", "A", 1700),
            ("2026-01-30", "A", 2600),
            ("2026-02-10", "A", 3600),
            ("2026-02-20", "A", 4700),
        ]
        xp_df = _df(rows)
        xp_df["Date"] = pd.to_datetime(xp_df["Date"], errors="coerce")
        metrics = compute_player_kpis_30d(xp_df, window_days=30, baseline_min_windows=10)
        self.assertEqual(len(metrics), 1)
        row = metrics.iloc[0]
        self.assertTrue(bool(row["eligible_30d"]))
        self.assertFalse(bool(row["eligible_baseline_30d"]))


if __name__ == "__main__":
    unittest.main()
