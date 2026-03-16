from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from webapp.app import (
    UI_PREF_DASHBOARD_WINDOW_DAYS,
    load_saved_dashboard_window_days,
    load_ui_preferences,
    normalize_dashboard_window_days,
    save_dashboard_window_days,
)


class UiPreferencesTest(unittest.TestCase):
    def test_normalize_dashboard_window_days_restricts_to_supported_values(self):
        self.assertEqual(normalize_dashboard_window_days("7d", fallback=30), 7)
        self.assertEqual(normalize_dashboard_window_days("30", fallback=7), 30)
        self.assertEqual(normalize_dashboard_window_days("14d", fallback=30), 30)

    def test_dashboard_window_days_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ui_preferences.json"
            self.assertEqual(load_saved_dashboard_window_days(30, path=path), 30)

            save_dashboard_window_days(7, path=path)

            prefs = load_ui_preferences(path)
            self.assertEqual(prefs.get(UI_PREF_DASHBOARD_WINDOW_DAYS), 7)
            self.assertEqual(load_saved_dashboard_window_days(30, path=path), 7)


if __name__ == "__main__":
    unittest.main()
