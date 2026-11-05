from __future__ import annotations

import unittest

import pandas as pd

from shared.data_intervals import carry_forward_value_rows


class DataIntervalsTest(unittest.TestCase):
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
