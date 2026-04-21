from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from webapp.data_files import load_medal_goals


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

    def test_load_medal_goals_accepts_legacy_file_without_explanation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "medal_goals.csv"
            pd.DataFrame(
                [{"medal_id": "jogger", "display_name": "Jogger", "goal_value": "10000"}]
            ).to_csv(path, index=False, encoding="utf-8-sig")

            goals = load_medal_goals(path)

        self.assertIn("explanation", goals.columns)
        self.assertEqual(goals.iloc[0]["explanation"], "")


if __name__ == "__main__":
    unittest.main()
