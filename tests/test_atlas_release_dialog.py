from __future__ import annotations

import unittest

import pandas as pd

from webapp.category_release import blank_kind_release_edit, mega_release_edits
from webapp.views.pokedex_dashboard import (
    AtlasKindRelease,
    _atlas_caught_default,
    _atlas_kind_release_state,
    _atlas_mega_released_checked,
    _atlas_species_not_in_go,
    _release_edits_change_manual,
)


def _availability_row(**overrides: object) -> pd.DataFrame:
    row = {
        "entry_type": "shiny",
        "dex_number": 1,
        "form": "",
        "available": False,
        "notes": "",
        "release_source": "seed",
        "release_detail": "",
        "seed_available": False,
    }
    row.update(overrides)
    return pd.DataFrame([row])


class AtlasReleaseDialogHelperTest(unittest.TestCase):
    def test_missing_release_row_is_editable_and_unreleased(self) -> None:
        state = _atlas_kind_release_state(pd.DataFrame(), 25, "shadow")
        self.assertEqual(state, AtlasKindRelease(False, True, False, ""))

    def test_evolution_release_is_locked_to_the_ancestor(self) -> None:
        frame = _availability_row(
            entry_type="shadow",
            dex_number=2,
            available=False,
            release_source="evolution",
            release_detail="Bulbasaur",
        )
        state = _atlas_kind_release_state(frame, 2, "shadow")
        self.assertEqual(state, AtlasKindRelease(True, False, False, "Bulbasaur"))

    def test_seed_row_uses_available_and_seed_flags(self) -> None:
        frame = _availability_row(available=True, seed_available=True, release_source="seed")
        state = _atlas_kind_release_state(frame, 1, "shiny")
        self.assertEqual(state, AtlasKindRelease(True, True, True, ""))

    def test_blank_form_does_not_match_another_form(self) -> None:
        frame = _availability_row(form="Alolan", available=True, seed_available=True)
        state = _atlas_kind_release_state(frame, 1, "shiny")
        self.assertEqual(state, AtlasKindRelease(False, True, False, ""))

    def test_caught_default_prefers_registered_then_caught(self) -> None:
        registered = pd.Series({"registered_shiny": False, "caught_shiny": True})
        self.assertFalse(_atlas_caught_default(registered, "shiny"))
        caught = pd.Series({"registered_shiny": pd.NA, "caught_gmax": True})
        self.assertTrue(_atlas_caught_default(caught, "gmax"))
        blank = pd.Series({"registered_shadow": pd.NA})
        self.assertFalse(_atlas_caught_default(blank, "shadow"))

    def test_mega_released_from_card_forms_or_available_row(self) -> None:
        with_forms = pd.Series({"mega_forms": '["X"]'})
        self.assertTrue(_atlas_mega_released_checked(with_forms, pd.DataFrame(), 6))
        available = _availability_row(entry_type="mega", dex_number=6, form="Y", available=True)
        without_forms = pd.Series({"mega_forms": "[]"})
        self.assertTrue(_atlas_mega_released_checked(without_forms, available, 6))
        hidden = _availability_row(entry_type="mega", dex_number=6, form="Y", available=False)
        self.assertFalse(_atlas_mega_released_checked(without_forms, hidden, 6))
        self.assertFalse(_atlas_mega_released_checked(without_forms, available, 3))

    def test_species_not_in_go_uses_status_or_catalog_flag(self) -> None:
        self.assertTrue(
            _atlas_species_not_in_go(pd.Series({"status": "unavailable", "available_in_pogo": "yes"}))
        )
        self.assertTrue(_atlas_species_not_in_go(pd.Series({"status": "missing", "available_in_pogo": "no"})))
        self.assertFalse(_atlas_species_not_in_go(pd.Series({"status": "missing", "available_in_pogo": "yes"})))

    def test_delete_of_missing_override_is_not_a_change(self) -> None:
        edit = blank_kind_release_edit("shiny", 25, form="", want_released=True, seed_available=True)
        self.assertIsNone(edit["available"])
        self.assertFalse(_release_edits_change_manual([edit], pd.DataFrame()))
        self.assertFalse(_release_edits_change_manual([], pd.DataFrame()))

    def test_delete_of_existing_override_is_a_change(self) -> None:
        edit = blank_kind_release_edit("shiny", 1, form="", want_released=False, seed_available=False)
        manual = pd.DataFrame(
            [{"entry_type": "shiny", "dex_number": 1, "form": "", "available": True, "notes": "keep"}]
        )
        self.assertTrue(_release_edits_change_manual([edit], manual))

    def test_same_override_value_is_not_a_change(self) -> None:
        edit = blank_kind_release_edit("shiny", 1, form="", want_released=True, seed_available=False)
        manual = pd.DataFrame(
            [{"entry_type": "Shiny", "dex_number": 1, "form": "", "available": True, "notes": "keep"}]
        )
        self.assertFalse(_release_edits_change_manual([edit], manual))
        turned_off = blank_kind_release_edit("shiny", 1, form="", want_released=False, seed_available=True)
        self.assertTrue(_release_edits_change_manual([turned_off], manual))

    def test_form_keys_match_case_insensitively(self) -> None:
        manual = pd.DataFrame(
            [{"entry_type": "mega", "dex_number": 6, "form": "Normal", "available": False, "notes": ""}]
        )
        edit = {"entry_type": "mega", "dex_number": 6, "form": "normal", "available": False, "notes": ""}
        self.assertFalse(_release_edits_change_manual([edit], manual))

    def test_unidentified_edit_counts_as_a_change(self) -> None:
        self.assertTrue(_release_edits_change_manual([{"available": None}], pd.DataFrame()))

    def test_mega_edits_ignore_an_already_released_seed_form(self) -> None:
        effective = _availability_row(
            entry_type="mega",
            dex_number=6,
            form="X",
            available=True,
            seed_available=True,
            release_source="seed",
        )
        self.assertFalse(_release_edits_change_manual(mega_release_edits(6, True, effective), pd.DataFrame()))
        self.assertTrue(_release_edits_change_manual(mega_release_edits(6, False, effective), pd.DataFrame()))
        self.assertTrue(_release_edits_change_manual(mega_release_edits(6, True, pd.DataFrame()), pd.DataFrame()))


if __name__ == "__main__":
    unittest.main()
