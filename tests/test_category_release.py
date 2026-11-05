from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd  # type: ignore[import-untyped]

from shared.paths import manual_category_availability_path
from webapp.category_release import (
    EFFECTIVE_CATEGORY_COLUMNS,
    MANUAL_CATEGORY_COLUMNS,
    blank_kind_release_edit,
    effective_category_availability,
    load_effective_category_availability,
    load_manual_category_availability,
    mega_release_edits,
    save_manual_category_availability,
)


def _row(frame: pd.DataFrame, entry_type: str, dex: int, form: str = "") -> pd.Series:
    matched = frame[
        (frame["entry_type"] == entry_type)
        & (frame["dex_number"].astype(int) == dex)
        & (frame["form"].astype(str) == form)
    ]
    if len(matched) != 1:
        raise AssertionError(f"expected one {entry_type} #{dex} form {form!r}, found {len(matched)}")
    return matched.iloc[0]


class CategoryReleaseTest(unittest.TestCase):
    def test_manual_category_availability_path(self) -> None:
        path = manual_category_availability_path()
        self.assertEqual(path.name, "manual_category_availability.csv")
        self.assertEqual(path.parent.name, "reference")

    def test_missing_override_file_loads_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = load_manual_category_availability(root / "missing.csv")
            empty = root / "empty.csv"
            empty.write_text("", encoding="utf-8")
            blank = load_manual_category_availability(empty)
            folder = root / "folder"
            folder.mkdir()
            unreadable = load_manual_category_availability(folder)
            garbled = root / "garbled.csv"
            garbled.write_bytes(b"\xff\xfe\x00\x81")
            broken = load_manual_category_availability(garbled)
            formed = root / "formed.csv"
            formed.write_text(
                "entry_type,dex_number,form,available,notes\n"
                " Mega ,6,X,false, first \n"
                "mega,6,x,true,second\n"
                "mega,0,Y,true,drop\n"
                ",7,Z,true,drop\n",
                encoding="utf-8-sig",
            )
            deduped = load_manual_category_availability(formed)

        for frame in (missing, blank, unreadable, broken):
            self.assertTrue(frame.empty)
            self.assertEqual(list(frame.columns), MANUAL_CATEGORY_COLUMNS)
        self.assertEqual(len(deduped), 1)
        kept = deduped.iloc[0]
        self.assertEqual(kept["entry_type"], "mega")
        self.assertEqual(int(kept["dex_number"]), 6)
        self.assertEqual(kept["form"], "x")
        self.assertTrue(bool(kept["available"]))
        self.assertEqual(kept["notes"], "second")

    def test_save_upserts_deletes_and_roundtrips_bools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "manual_category_availability.csv"
            written = save_manual_category_availability(
                path,
                [
                    {"entry_type": "shiny", "dex_number": 1, "available": True, "notes": "one"},
                    {"entry_type": "mega", "dex_number": 6, "form": "X", "available": False, "notes": "ex"},
                    {"entry_type": " ", "dex_number": 9, "available": True, "notes": "skip"},
                    {"entry_type": "shiny", "dex_number": 0, "available": True, "notes": "skip"},
                    {"entry_type": "shiny", "dex_number": 4, "available": True, "notes": "gone"},
                ],
            )
            self.assertEqual(written, 3)
            self.assertTrue(path.is_file())
            text = path.read_text(encoding="utf-8-sig")
            self.assertIn("true", text)
            self.assertIn("false", text)
            self.assertNotIn("True", text)
            self.assertNotIn("False", text)

            kept_notes = save_manual_category_availability(
                path,
                [{"entry_type": "mega", "dex_number": 6, "form": "x", "available": True}],
            )
            self.assertEqual(kept_notes, 3)
            after_upsert = load_manual_category_availability(path)
            mega = _row(after_upsert, "mega", 6, "x")
            self.assertIs(bool(mega["available"]), True)
            self.assertEqual(mega["notes"], "ex")
            shiny = _row(after_upsert, "shiny", 1)
            self.assertTrue(bool(shiny["available"]))

            numpy_true = pd.DataFrame({"available": [True]}).iloc[0]["available"]
            self.assertNotIsInstance(numpy_true, bool)
            save_manual_category_availability(
                path,
                [{"entry_type": "gmax", "dex_number": 3, "available": numpy_true, "notes": "from frame"}],
            )
            deleted = save_manual_category_availability(
                path,
                [{"entry_type": "Shiny", "dex_number": 4, "available": None}],
            )
            loaded = load_manual_category_availability(path)

        self.assertEqual(deleted, 3)
        self.assertEqual(sorted(int(dex) for dex in loaded["dex_number"]), [1, 3, 6])
        self.assertIs(bool(_row(loaded, "gmax", 3)["available"]), True)
        self.assertEqual(_row(loaded, "gmax", 3)["notes"], "from frame")
        self.assertIs(bool(_row(loaded, "mega", 6, "x")["available"]), True)
        self.assertIs(bool(_row(loaded, "shiny", 1)["available"]), True)
        self.assertNotIn(4, set(loaded["dex_number"].astype(int)))

    def test_blank_kind_release_edit_matches_seed_or_writes_override(self) -> None:
        matched = blank_kind_release_edit("shadow", 77, want_released=True, seed_available=True)
        also_matched = blank_kind_release_edit("shiny", 1, want_released=False, seed_available=False)
        turn_off = blank_kind_release_edit("shadow", 77, want_released=False, seed_available=True)
        turn_on = blank_kind_release_edit("shiny", 4, form="Alolan", want_released=True, seed_available=False)

        self.assertIsNone(matched["available"])
        self.assertEqual(matched["entry_type"], "shadow")
        self.assertEqual(matched["dex_number"], 77)
        self.assertEqual(matched["form"], "")
        self.assertIsNone(also_matched["available"])
        self.assertFalse(bool(turn_off["available"]))
        self.assertEqual(turn_off["notes"], "")
        self.assertTrue(bool(turn_on["available"]))
        self.assertEqual(turn_on["form"], "Alolan")
        self.assertEqual(turn_on["notes"], "")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manual.csv"
            save_manual_category_availability(
                path,
                [{"entry_type": "shadow", "dex_number": 77, "available": False, "notes": "held"}],
            )
            save_manual_category_availability(path, [matched])
            self.assertTrue(load_manual_category_availability(path).empty)
            save_manual_category_availability(path, [turn_on])
            loaded = load_manual_category_availability(path)

        row = _row(loaded, "shiny", 4, "Alolan")
        self.assertTrue(bool(row["available"]))
        self.assertEqual(row["notes"], "")

    def test_no_shadow_rows_leave_purified_unchanged(self) -> None:
        availability = pd.DataFrame(
            [
                {"entry_type": "purified", "dex_number": 1, "available": True, "notes": "kept"},
            ]
        )
        evolutions = pd.DataFrame(
            [
                {"source_dex_number": 1, "target_dex_number": 2, "source_form": ""},
            ]
        )
        result = effective_category_availability(
            availability,
            evolutions=evolutions,
            in_go={1, 2},
            names={1: "Bulbasaur"},
        )

        self.assertEqual(list(result.columns), EFFECTIVE_CATEGORY_COLUMNS)
        self.assertFalse((result["entry_type"] == "shadow").any())
        purified = _row(result, "purified", 1)
        self.assertEqual(purified["form"], "")
        self.assertTrue(bool(purified["available"]))
        self.assertEqual(purified["notes"], "kept")
        self.assertEqual(purified["release_source"], "seed")
        self.assertEqual(purified["release_detail"], "")
        self.assertTrue(bool(purified["seed_available"]))
        self.assertTrue(effective_category_availability(None).empty)

    def test_shadow_evolution_adds_descendant_and_purified(self) -> None:
        availability = pd.DataFrame(
            [
                {"entry_type": "shadow", "dex_number": 77, "form": "", "available": True, "notes": ""},
            ]
        )
        evolutions = pd.DataFrame(
            [
                {"source_dex_number": 76, "target_dex_number": 77},
                {"source_dex_number": 77, "target_dex_number": 78},
            ]
        )
        result = effective_category_availability(
            availability,
            evolutions=evolutions,
            in_go={76, 77, 78},
            names={77: "Ponyta"},
        )

        self.assertEqual(list(result.columns), EFFECTIVE_CATEGORY_COLUMNS)
        ponyta = _row(result, "shadow", 77)
        rapidash = _row(result, "shadow", 78)
        self.assertTrue(bool(ponyta["available"]))
        self.assertEqual(ponyta["release_source"], "seed")
        self.assertTrue(bool(ponyta["seed_available"]))
        self.assertEqual(ponyta["release_detail"], "")
        self.assertTrue(bool(rapidash["available"]))
        self.assertEqual(rapidash["release_source"], "evolution")
        self.assertEqual(rapidash["release_detail"], "Ponyta")
        self.assertFalse(bool(rapidash["seed_available"]))
        self.assertEqual(rapidash["form"], "")
        self.assertEqual(rapidash["notes"], "")
        self.assertFalse((result["entry_type"].eq("shadow") & result["dex_number"].eq(76)).any())
        for dex in (77, 78):
            purified = _row(result, "purified", dex)
            self.assertTrue(bool(purified["available"]))
            self.assertEqual(purified["release_source"], "seed")
            self.assertFalse(bool(purified["seed_available"]))
            self.assertEqual(purified["form"], "")
        self.assertEqual(sorted(result.loc[result["entry_type"] == "purified", "dex_number"].astype(int)), [77, 78])
        ordered = result.sort_values(["entry_type", "dex_number", "form"]).reset_index(drop=True)
        pd.testing.assert_frame_equal(result, ordered)

        again = effective_category_availability(
            result,
            overrides=None,
            evolutions=evolutions,
            in_go={76, 77, 78},
            names={77: "Ponyta"},
        )
        pd.testing.assert_frame_equal(again, result)
        again_rapidash = again[(again["entry_type"] == "shadow") & (again["dex_number"] == 78)]
        self.assertEqual(len(again_rapidash), 1)
        self.assertEqual(again_rapidash.iloc[0]["release_source"], "evolution")

    def test_existing_release_source_is_kept_when_seed_column_is_absent(self) -> None:
        availability = pd.DataFrame(
            [
                {
                    "entry_type": "shiny",
                    "dex_number": 1,
                    "form": "",
                    "available": True,
                    "notes": "keep",
                    "release_source": "evolution",
                    "release_detail": "Bulbasaur",
                }
            ]
        )
        result = effective_category_availability(availability)
        row = _row(result, "shiny", 1)
        self.assertEqual(row["release_source"], "evolution")
        self.assertEqual(row["release_detail"], "Bulbasaur")
        self.assertFalse(bool(row["seed_available"]))
        self.assertEqual(row["notes"], "keep")

    def test_shadow_evolution_overwrites_override_false(self) -> None:
        availability = pd.DataFrame(
            [
                {"entry_type": "shadow", "dex_number": 77, "available": True, "notes": ""},
            ]
        )
        overrides = pd.DataFrame(
            [
                {"entry_type": "shadow", "dex_number": 78, "form": "", "available": False, "notes": "hold"},
            ]
        )
        evolutions = pd.DataFrame(
            [
                {"source_dex_number": 77, "target_dex_number": 78},
            ]
        )
        result = effective_category_availability(
            availability,
            overrides,
            evolutions,
            in_go={77, 78},
            names={77: "Ponyta"},
        )

        rapidash = _row(result, "shadow", 78)
        self.assertTrue(bool(rapidash["available"]))
        self.assertEqual(rapidash["release_source"], "evolution")
        self.assertEqual(rapidash["release_detail"], "Ponyta")
        self.assertFalse(bool(rapidash["seed_available"]))

    def test_shadow_override_true_without_seed(self) -> None:
        overrides = pd.DataFrame(
            [
                {"entry_type": "shadow", "dex_number": 77, "form": "", "available": True, "notes": ""},
            ]
        )
        result = effective_category_availability(None, overrides)

        row = _row(result, "shadow", 77)
        self.assertEqual(row["release_source"], "override")
        self.assertFalse(bool(row["seed_available"]))
        self.assertTrue(bool(row["available"]))
        self.assertEqual(row["release_detail"], "")
        purified = _row(result, "purified", 77)
        self.assertTrue(bool(purified["available"]))
        self.assertFalse(bool(purified["seed_available"]))

    def test_shadow_override_false_keeps_seed_available_and_skips_purified(self) -> None:
        availability = pd.DataFrame(
            [
                {"entry_type": "shadow", "dex_number": 76, "available": True, "notes": "from seed"},
                {"entry_type": "purified", "dex_number": 76, "available": True, "notes": "old purified"},
            ]
        )
        overrides = pd.DataFrame(
            [
                {"entry_type": "shadow", "dex_number": 76, "form": "", "available": False, "notes": ""},
            ]
        )
        result = effective_category_availability(availability, overrides)

        row = _row(result, "shadow", 76)
        self.assertFalse(bool(row["available"]))
        self.assertEqual(row["release_source"], "override")
        self.assertTrue(bool(row["seed_available"]))
        self.assertEqual(row["notes"], "from seed")
        self.assertTrue(result[result["entry_type"] == "purified"].empty)
        self.assertNotIn(76, set(result.loc[result["entry_type"] == "purified", "dex_number"].astype(int)))

    def test_mega_release_edits(self) -> None:
        empty = pd.DataFrame(columns=EFFECTIVE_CATEGORY_COLUMNS)
        added = mega_release_edits(6, True, empty)
        self.assertEqual(
            added,
            [
                {
                    "entry_type": "mega",
                    "dex_number": 6,
                    "form": "Normal",
                    "available": True,
                    "notes": "",
                }
            ],
        )
        self.assertEqual(mega_release_edits(6, False, empty), [])

        seed_true = pd.DataFrame(
            [
                {
                    "entry_type": "mega",
                    "dex_number": 6,
                    "form": "X",
                    "available": True,
                    "notes": "",
                    "release_source": "seed",
                    "release_detail": "",
                    "seed_available": True,
                }
            ]
        )
        turned_off = mega_release_edits(6, False, seed_true)
        self.assertEqual(turned_off[0]["form"], "X")
        self.assertFalse(bool(turned_off[0]["available"]))
        self.assertEqual(turned_off[0]["notes"], "")

        override_true = pd.DataFrame(
            [
                {
                    "entry_type": "mega",
                    "dex_number": 6,
                    "form": "Normal",
                    "available": True,
                    "notes": "temp",
                    "release_source": "override",
                    "release_detail": "",
                    "seed_available": False,
                }
            ]
        )
        dropped = mega_release_edits(6, False, override_true)
        self.assertEqual(dropped[0]["form"], "Normal")
        self.assertIsNone(dropped[0]["available"])

    def test_nearest_shadow_ancestor_prefers_fewer_hops_then_lower_dex(self) -> None:
        availability = pd.DataFrame(
            [
                {"entry_type": "shadow", "dex_number": 10, "available": True},
                {"entry_type": "shadow", "dex_number": 20, "available": True},
            ]
        )
        evolutions = pd.DataFrame(
            [
                {"source_dex_number": 10, "target_dex_number": 30},
                {"source_dex_number": 20, "target_dex_number": 30},
                {"source_dex_number": 10, "target_dex_number": 11},
                {"source_dex_number": 11, "target_dex_number": 12},
                {"source_dex_number": 20, "target_dex_number": 12},
                {"source_dex_number": 11, "target_dex_number": 13},
            ]
        )
        result = effective_category_availability(
            availability,
            evolutions=evolutions,
            in_go={10, 11, 12, 13, 20, 30},
            names={10: "Ten", 20: "Twenty"},
        )

        self.assertEqual(_row(result, "shadow", 30)["release_detail"], "Ten")
        self.assertEqual(_row(result, "shadow", 12)["release_detail"], "Twenty")
        self.assertEqual(_row(result, "shadow", 13)["release_detail"], "Ten")
        self.assertEqual(_row(result, "shadow", 11)["release_source"], "evolution")

    def test_in_go_blocks_evolution_edges(self) -> None:
        availability = pd.DataFrame(
            [
                {"entry_type": "shadow", "dex_number": 77, "available": True},
            ]
        )
        evolutions = pd.DataFrame(
            [
                {"source_dex_number": 77, "target_dex_number": 78},
            ]
        )
        result = effective_category_availability(
            availability,
            evolutions=evolutions,
            in_go={77},
            names={77: "Ponyta"},
        )

        self.assertFalse((result["entry_type"].eq("shadow") & result["dex_number"].eq(78)).any())
        self.assertEqual(list(result.loc[result["entry_type"] == "purified", "dex_number"].astype(int)), [77])

    def test_missing_ancestor_name_uses_four_digit_dex(self) -> None:
        availability = pd.DataFrame(
            [
                {"entry_type": "shadow", "dex_number": 77, "available": True},
            ]
        )
        evolutions = pd.DataFrame(
            [
                {"source_dex_number": 77, "target_dex_number": 78},
            ]
        )
        result = effective_category_availability(availability, evolutions=evolutions, in_go={77, 78})
        self.assertEqual(_row(result, "shadow", 78)["release_detail"], "#0077")

    def test_load_effective_category_availability_applies_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            availability = root / "pokedex_category_availability.csv"
            availability.write_text(
                "entry_type,dex_number,form,available,notes\n"
                "shadow,25,,true,\n"
                "shiny,1,,true,shine\n",
                encoding="utf-8-sig",
            )
            evolutions = root / "pokemon_evolutions.csv"
            evolutions.write_text(
                "source_dex_number,target_dex_number,method,source_form,notes\n"
                "25,26,evolve,,\n",
                encoding="utf-8-sig",
            )
            result = load_effective_category_availability(
                availability,
                root / "missing_overrides.csv",
                evolutions,
                in_go={25, 26},
                names={25: "Pikachu"},
                valid_entry_types={"shadow"},
            )

        self.assertFalse((result["entry_type"] == "shiny").any())
        raichu = _row(result, "shadow", 26)
        self.assertEqual(raichu["release_source"], "evolution")
        self.assertEqual(raichu["release_detail"], "Pikachu")
        self.assertFalse(bool(raichu["seed_available"]))
        self.assertTrue(bool(_row(result, "shadow", 25)["seed_available"]))


if __name__ == "__main__":
    unittest.main()
