from __future__ import annotations

import unittest

from webapp.data_files import accounts_for_selected_group


class GroupSelectionTest(unittest.TestCase):
    def test_all_group_uses_configured_members_when_present(self):
        groups = {"All": ["A", "B"], "Team": ["B"]}
        all_accounts = ["A", "B", "C"]

        selected = accounts_for_selected_group("All", groups, all_accounts)

        self.assertEqual(selected, ["A", "B"])

    def test_all_group_falls_back_to_all_accounts_when_not_configured(self):
        groups = {"Team": ["B"]}
        all_accounts = ["A", "B", "C"]

        selected = accounts_for_selected_group("All", groups, all_accounts)

        self.assertEqual(selected, ["A", "B", "C"])

    def test_group_selection_filters_out_accounts_missing_from_data(self):
        groups = {"Team": ["A", "Ghost", "B"]}
        all_accounts = ["B", "A"]

        selected = accounts_for_selected_group("Team", groups, all_accounts)

        self.assertEqual(selected, ["A", "B"])


if __name__ == "__main__":
    unittest.main()
