from __future__ import annotations

import unittest
from datetime import date

from webapp.profile_recording import (
    combine_screenshot_and_recording_parses,
    fill_xp_inputs_from_screenshots_and_recordings,
    merge_profile_visits,
    select_settled_frame_indexes,
)
from webapp.profile_screenshot import ProfileScreenshotParse


THOMZAY_OCR = """
Thomzay
62
LEVEL
3,743,983 / 4,050,000
TOTAL ACTIVITY
Battles Won
905
Distance Walked
1,006.1
Pokemon Caught
26,833
"""


class MergeProfileVisitsTest(unittest.TestCase):
    def test_header_and_nameless_activity_become_one_parse(self):
        result = merge_profile_visits(
            [
                ProfileScreenshotParse(
                    account="Thomzay",
                    level=62,
                    xp_bar=3_743_983,
                    xp_to_next=4_050_000,
                    source_name="header.jpg",
                ),
                ProfileScreenshotParse(
                    account=None,
                    battles_won=905,
                    distance_walked=1006.1,
                    pokemon_caught=26_833,
                    source_name="activity.jpg",
                ),
            ]
        )
        self.assertEqual([parsed.account for parsed in result.parses], ["Thomzay"])
        parsed = result.parses[0]
        self.assertEqual(parsed.level, 62)
        self.assertEqual(parsed.xp_bar, 3_743_983)
        self.assertEqual(parsed.xp_to_next, 4_050_000)
        self.assertEqual(parsed.battles_won, 905)
        self.assertEqual(parsed.distance_walked, 1006.1)
        self.assertEqual(parsed.pokemon_caught, 26_833)
        self.assertEqual(parsed.source_name, "header.jpg (2 frames)")
        self.assertEqual(result.multi_frame, ["Thomzay"])

    def test_second_header_does_not_leak_activity_backward(self):
        result = merge_profile_visits(
            [
                ProfileScreenshotParse(
                    account="Thomzay",
                    level=62,
                    xp_bar=100,
                    xp_to_next=4_050_000,
                    battles_won=1,
                ),
                ProfileScreenshotParse(distance_walked=10.5, pokemon_caught=4),
                ProfileScreenshotParse(
                    account="Trada17",
                    level=70,
                    xp_bar=200,
                    xp_to_next=9_000_000,
                ),
                ProfileScreenshotParse(battles_won=9, distance_walked=2.5, pokemon_caught=50),
            ]
        )
        self.assertEqual([parsed.account for parsed in result.parses], ["Thomzay", "Trada17"])
        thomzay, trada = result.parses
        self.assertEqual(thomzay.level, 62)
        self.assertEqual(thomzay.xp_bar, 100)
        self.assertEqual(thomzay.battles_won, 1)
        self.assertEqual(thomzay.distance_walked, 10.5)
        self.assertEqual(thomzay.pokemon_caught, 4)
        self.assertEqual(trada.level, 70)
        self.assertEqual(trada.xp_bar, 200)
        self.assertEqual(trada.xp_to_next, 9_000_000)
        self.assertEqual(trada.battles_won, 9)
        self.assertEqual(trada.distance_walked, 2.5)
        self.assertEqual(trada.pokemon_caught, 50)

    def test_activity_frame_for_another_trainer_does_not_switch(self):
        result = merge_profile_visits(
            [
                ProfileScreenshotParse(
                    account="Thomzay",
                    level=62,
                    xp_bar=100,
                    xp_to_next=4_050_000,
                    source_name="header.jpg",
                ),
                ProfileScreenshotParse(
                    account="Trada17",
                    battles_won=5,
                    distance_walked=1.5,
                    pokemon_caught=9,
                    source_name="activity.jpg",
                ),
            ]
        )
        self.assertEqual(len(result.parses), 1)
        parsed = result.parses[0]
        self.assertEqual(parsed.account, "Thomzay")
        self.assertEqual(parsed.level, 62)
        self.assertEqual(parsed.xp_bar, 100)
        self.assertEqual(parsed.battles_won, 5)
        self.assertEqual(parsed.distance_walked, 1.5)
        self.assertEqual(parsed.pokemon_caught, 9)
        self.assertEqual(result.multi_frame, ["Thomzay"])
        self.assertNotIn("Trada17", [parsed.account for parsed in result.parses])

    def test_keeps_last_xp_pair_matching_level_table(self):
        result = merge_profile_visits(
            [
                ProfileScreenshotParse(
                    account="Gloria",
                    level=53,
                    xp_bar=1_000_000,
                    xp_to_next=1_860_000,
                    battles_won=10,
                    source_name="match.jpg",
                ),
                ProfileScreenshotParse(
                    xp_bar=1_838_385,
                    xp_to_next=1_200_000,
                    pokemon_caught=20,
                    source_name="bad.jpg",
                ),
            ],
            xp_to_next_by_level={53: 1_860_000},
        )
        parsed = result.parses[0]
        self.assertEqual(parsed.level, 53)
        self.assertEqual(parsed.xp_bar, 1_000_000)
        self.assertEqual(parsed.xp_to_next, 1_860_000)
        self.assertEqual(parsed.battles_won, 10)
        self.assertEqual(parsed.pokemon_caught, 20)
        self.assertTrue(any("does not match" in warning for warning in result.warnings))

    def test_keeps_the_later_matching_xp_pair(self):
        result = merge_profile_visits(
            [
                ProfileScreenshotParse(account="Gloria", level=53, xp_bar=100_000, xp_to_next=1_860_000),
                ProfileScreenshotParse(xp_bar=200_000, xp_to_next=1_860_000),
            ],
            xp_to_next_by_level={53: 1_860_000},
        )
        self.assertEqual(result.parses[0].xp_bar, 200_000)
        self.assertEqual(result.parses[0].xp_to_next, 1_860_000)
        self.assertEqual(result.warnings, [])

    def test_blanks_xp_when_no_pair_matches_level_table(self):
        result = merge_profile_visits(
            [
                ProfileScreenshotParse(account="Gloria", level=53, xp_bar=1, xp_to_next=111, battles_won=4),
                ProfileScreenshotParse(xp_bar=2, xp_to_next=222, pokemon_caught=8),
            ],
            xp_to_next_by_level={53: 1_860_000},
        )
        parsed = result.parses[0]
        self.assertEqual(parsed.level, 53)
        self.assertIsNone(parsed.xp_bar)
        self.assertIsNone(parsed.xp_to_next)
        self.assertEqual(parsed.battles_won, 4)
        self.assertEqual(parsed.pokemon_caught, 8)
        self.assertTrue(any("left blank" in warning for warning in result.warnings))

    def test_level_80_without_xp_pair_has_no_conflict_warning(self):
        result = merge_profile_visits(
            [
                ProfileScreenshotParse(
                    account="AnSaCruiser",
                    level=80,
                    battles_won=10,
                    distance_walked=1.5,
                    pokemon_caught=3,
                )
            ],
            xp_to_next_by_level={80: 0, 79: 16_000_000},
        )
        parsed = result.parses[0]
        self.assertEqual(parsed.level, 80)
        self.assertIsNone(parsed.xp_bar)
        self.assertIsNone(parsed.xp_to_next)
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.multi_frame, [])

    def test_ignores_activity_before_the_first_header(self):
        result = merge_profile_visits(
            [
                ProfileScreenshotParse(account="Trada17", battles_won=5, pokemon_caught=9),
                ProfileScreenshotParse(account="Thomzay", level=62, xp_bar=10, xp_to_next=20, distance_walked=3.0),
            ]
        )
        self.assertEqual([parsed.account for parsed in result.parses], ["Thomzay"])
        self.assertIsNone(result.parses[0].battles_won)
        self.assertIsNone(result.parses[0].pokemon_caught)
        self.assertEqual(result.parses[0].distance_walked, 3.0)
        self.assertEqual(result.warnings, ["Activity before a trainer header was ignored."])

    def test_same_trainer_later_merges_into_one_parse(self):
        result = merge_profile_visits(
            [
                ProfileScreenshotParse(
                    account="Thomzay",
                    level=62,
                    xp_bar=1,
                    xp_to_next=2,
                    battles_won=1,
                    source_name="a.jpg",
                ),
                ProfileScreenshotParse(account="Trada17", level=70, xp_bar=3, xp_to_next=4, source_name="b.jpg"),
                ProfileScreenshotParse(account="Thomzay", level=63, pokemon_caught=9, source_name="c.jpg"),
            ]
        )
        self.assertEqual([parsed.account for parsed in result.parses], ["Thomzay", "Trada17"])
        self.assertEqual(result.parses[0].level, 63)
        self.assertEqual(result.parses[0].pokemon_caught, 9)
        self.assertEqual(result.parses[0].battles_won, 1)
        self.assertEqual(result.parses[0].xp_bar, 1)
        self.assertEqual(result.parses[0].source_name, "a.jpg (2 frames)")
        self.assertEqual(result.parses[1].pokemon_caught, None)
        self.assertEqual(result.multi_frame, ["Thomzay"])

    def test_copies_warnings_from_contributing_frames(self):
        result = merge_profile_visits(
            [
                ProfileScreenshotParse(
                    account="Thomzay",
                    level=62,
                    xp_bar=1,
                    xp_to_next=2,
                    warnings=["header blur"],
                ),
                ProfileScreenshotParse(battles_won=5, warnings=["activity blur"]),
            ]
        )
        self.assertEqual(result.parses[0].warnings, ["header blur", "activity blur"])

    def test_without_level_table_keeps_the_last_xp_pair(self):
        parses = [
            ProfileScreenshotParse(account="Gloria", level=53, xp_bar=1, xp_to_next=1_860_000),
            ProfileScreenshotParse(xp_bar=2, xp_to_next=1_200_000),
        ]
        without_table = merge_profile_visits(parses)
        self.assertEqual(without_table.parses[0].xp_bar, 2)
        self.assertEqual(without_table.parses[0].xp_to_next, 1_200_000)
        self.assertEqual(without_table.warnings, [])
        missing_level = merge_profile_visits(parses, xp_to_next_by_level={50: 1_000_000})
        self.assertEqual(missing_level.parses[0].xp_bar, 2)
        self.assertEqual(missing_level.parses[0].xp_to_next, 1_200_000)
        self.assertEqual(missing_level.warnings, [])


class SelectSettledFrameIndexesTest(unittest.TestCase):
    def test_black_white_white_keeps_only_the_hold(self):
        import numpy as np

        black = np.zeros((4, 4, 3), dtype=np.uint8)
        white = np.full((4, 4, 3), 255, dtype=np.uint8)
        self.assertEqual(select_settled_frame_indexes([black, white, white]), [2])
        self.assertEqual(select_settled_frame_indexes([black, white]), [])
        self.assertEqual(select_settled_frame_indexes([white, white, white]), [1])

    def test_keeps_each_hold_and_drops_the_transition(self):
        import numpy as np

        black = np.zeros((2, 2), dtype=np.uint8)
        white = np.full((2, 2), 255, dtype=np.uint8)
        self.assertEqual(select_settled_frame_indexes([black, black, white, white]), [1, 3])


class CombineScreenshotAndRecordingParsesTest(unittest.TestCase):
    def test_recording_fills_caught_and_keeps_screenshot_level_and_xp(self):
        screenshot = ProfileScreenshotParse(
            account="Thomzay",
            level=62,
            xp_bar=3_743_983,
            xp_to_next=4_050_000,
            pokemon_caught=None,
        )
        recording = ProfileScreenshotParse(account="Thomzay", pokemon_caught=26_833)
        combined = combine_screenshot_and_recording_parses([screenshot], [recording])
        self.assertEqual(len(combined), 1)
        self.assertEqual(combined[0].pokemon_caught, 26_833)
        self.assertEqual(combined[0].level, 62)
        self.assertEqual(combined[0].xp_bar, 3_743_983)
        self.assertEqual(combined[0].xp_to_next, 4_050_000)
        self.assertIsNone(screenshot.pokemon_caught)

    def test_later_screenshot_replaces_earlier_including_missing_fields(self):
        unknown = ProfileScreenshotParse(source_name="unknown.png", level=10)
        first = ProfileScreenshotParse(
            account="Thomzay",
            level=62,
            xp_bar=10,
            xp_to_next=20,
            pokemon_caught=5,
        )
        second = ProfileScreenshotParse(account="Thomzay", level=63, xp_bar=None, xp_to_next=None, pokemon_caught=None)
        combined = combine_screenshot_and_recording_parses([unknown, first, second], [])
        self.assertEqual(len(combined), 2)
        self.assertIsNone(combined[0].account)
        self.assertEqual(combined[0].source_name, "unknown.png")
        self.assertEqual(combined[1].level, 63)
        self.assertIsNone(combined[1].xp_bar)
        self.assertIsNone(combined[1].xp_to_next)
        self.assertIsNone(combined[1].pokemon_caught)

    def test_recording_xp_denominator_of_zero_overlays_together(self):
        screenshot = ProfileScreenshotParse(
            account="AnSaCruiser",
            level=80,
            xp_bar=10,
            xp_to_next=99,
            pokemon_caught=1,
        )
        recording = ProfileScreenshotParse(account="AnSaCruiser", xp_bar=431_512_558, xp_to_next=0)
        combined = combine_screenshot_and_recording_parses([screenshot], [recording])
        self.assertEqual(combined[0].level, 80)
        self.assertEqual(combined[0].xp_bar, 431_512_558)
        self.assertEqual(combined[0].xp_to_next, 0)
        self.assertEqual(combined[0].pokemon_caught, 1)

    def test_appends_accounts_only_in_the_recording(self):
        screenshot = ProfileScreenshotParse(account="Thomzay", level=62, pokemon_caught=1)
        earlier = ProfileScreenshotParse(account="Trada17", level=70, pokemon_caught=4)
        later = ProfileScreenshotParse(account="Trada17", battles_won=8)
        combined = combine_screenshot_and_recording_parses([screenshot], [earlier, later])
        self.assertEqual([parsed.account for parsed in combined], ["Thomzay", "Trada17"])
        self.assertEqual(combined[0].level, 62)
        self.assertEqual(combined[0].pokemon_caught, 1)
        self.assertEqual(combined[1].level, 70)
        self.assertEqual(combined[1].pokemon_caught, 4)
        self.assertEqual(combined[1].battles_won, 8)

    def test_later_recording_overwrites_only_fields_it_shows(self):
        screenshot = ProfileScreenshotParse(
            account="Thomzay",
            level=62,
            xp_bar=1,
            xp_to_next=2,
            pokemon_caught=5,
            battles_won=1,
        )
        first = ProfileScreenshotParse(account="Thomzay", pokemon_caught=9, battles_won=2)
        second = ProfileScreenshotParse(account="Thomzay", pokemon_caught=12)
        combined = combine_screenshot_and_recording_parses([screenshot], [first, second])
        self.assertEqual(combined[0].pokemon_caught, 12)
        self.assertEqual(combined[0].battles_won, 2)
        self.assertEqual(combined[0].level, 62)
        self.assertEqual(combined[0].xp_bar, 1)
        self.assertEqual(combined[0].xp_to_next, 2)


class FillXpInputsFromScreenshotsAndRecordingsTest(unittest.TestCase):
    def test_empty_recordings_delegate_to_screenshot_filling(self):
        def ocr(image: bytes) -> str:
            if image == b"known":
                return THOMZAY_OCR
            return "Noone\nLEVEL\n10\n1,000 / 2,500"

        def extractor(_video: bytes) -> tuple[list[bytes], list[str]]:
            raise AssertionError("extractor should not run")

        session: dict[str, object] = {}
        report = fill_xp_inputs_from_screenshots_and_recordings(
            [("thomzay.png", b"known"), ("unknown.png", b"other")],
            [],
            xp_date=date(2026, 9, 7),
            selected_accounts=["Thomzay"],
            known_accounts=["Thomzay"],
            session_state=session,
            ocr_fn=ocr,
            frame_extractor=extractor,
        )
        self.assertEqual(report.filled, ["Thomzay"])
        self.assertEqual(report.unmatched, ["unknown.png"])
        self.assertEqual(session["xp_level_input_2026-09-07_Thomzay"], 62)
        self.assertEqual(session["xp_bar_input_2026-09-07_Thomzay"], "3743983")
        self.assertEqual(report.multi_frame, [])

    def test_new_recording_does_not_continue_the_previous_trainer(self):
        def ocr(image: bytes) -> str:
            if image == b"header":
                return THOMZAY_OCR
            if image == b"activity":
                return """
                TOTAL ACTIVITY
                Battles Won
                10
                Distance Walked
                2.0
                Pokemon Caught
                99
                """
            raise AssertionError(image)

        def extractor(video: bytes) -> tuple[list[bytes], list[str]]:
            if video == b"one":
                return [b"header"], []
            if video == b"two":
                return [b"activity"], ["Recording was truncated to 400 settled frames."]
            raise AssertionError(video)

        session: dict[str, object] = {}
        report = fill_xp_inputs_from_screenshots_and_recordings(
            [],
            [("one.mp4", b"one"), ("two.mp4", b"two")],
            xp_date=date(2026, 9, 7),
            selected_accounts=["Thomzay"],
            known_accounts=["Thomzay"],
            session_state=session,
            ocr_fn=ocr,
            xp_to_next_by_level={62: 4_050_000},
            frame_extractor=extractor,
        )
        self.assertEqual(session["xp_caught_input_2026-09-07_Thomzay"], "26833")
        self.assertEqual(session["xp_battles_input_2026-09-07_Thomzay"], "905")
        self.assertEqual(session["xp_level_input_2026-09-07_Thomzay"], 62)
        self.assertEqual(report.multi_frame, [])
        self.assertTrue(any("before a trainer header was ignored" in warning for warning in report.warnings))
        self.assertTrue(
            any("Recording was truncated to 400 settled frames." in warning for warning in report.warnings)
        )
        self.assertLess(
            report.warnings.index(next(warning for warning in report.warnings if "truncated" in warning)),
            report.warnings.index(next(warning for warning in report.warnings if "header was ignored" in warning)),
        )

    def test_recording_overlays_screenshot_fields_it_actually_shows(self):
        def ocr(image: bytes) -> str:
            if image == b"shot":
                return """
                Thomzay
                62
                LEVEL
                1,000 / 4,050,000
                TOTAL ACTIVITY
                Battles Won
                1
                Distance Walked
                2.0
                Pokemon Caught
                3
                """
            if image == b"header":
                return """
                Thomzay
                62
                LEVEL
                """
            if image == b"activity":
                return """
                TOTAL ACTIVITY
                Battles Won
                905
                Distance Walked
                1,006.1
                Pokemon Caught
                26,833
                """
            raise AssertionError(image)

        session: dict[str, object] = {}
        report = fill_xp_inputs_from_screenshots_and_recordings(
            [("thomzay.png", b"shot")],
            [("visit.mp4", b"video")],
            xp_date=date(2026, 9, 7),
            selected_accounts=["Thomzay"],
            known_accounts=["Thomzay"],
            session_state=session,
            ocr_fn=ocr,
            xp_to_next_by_level={62: 4_050_000},
            frame_extractor=lambda _video: ([b"header", b"activity"], []),
        )
        self.assertEqual(report.filled, ["Thomzay"])
        self.assertEqual(report.multi_frame, ["Thomzay"])
        self.assertEqual(session["xp_level_input_2026-09-07_Thomzay"], 62)
        self.assertEqual(session["xp_bar_input_2026-09-07_Thomzay"], "1000")
        self.assertEqual(session["xp_caught_input_2026-09-07_Thomzay"], "26833")
        self.assertEqual(session["xp_battles_input_2026-09-07_Thomzay"], "905")

    def test_merge_warning_is_prepended_when_xp_pair_does_not_match(self):
        def ocr(_image: bytes) -> str:
            return """
            Gloria
            53
            LEVEL
            1,838,385 / 1,200,000
            TOTAL ACTIVITY
            Battles Won
            1,384
            Distance Walked
            4,711.7
            Pokemon Caught
            13,956
            """

        session: dict[str, object] = {}
        report = fill_xp_inputs_from_screenshots_and_recordings(
            [],
            [("gloria.mp4", b"video")],
            xp_date=date(2026, 10, 8),
            selected_accounts=["Gloria"],
            known_accounts=["Gloria"],
            session_state=session,
            ocr_fn=ocr,
            xp_to_next_by_level={53: 1_860_000},
            frame_extractor=lambda _video: ([b"bad"], []),
        )
        self.assertEqual(session["xp_level_input_2026-10-08_Gloria"], 53)
        self.assertEqual(session["xp_bar_input_2026-10-08_Gloria"], "")
        self.assertEqual(session["xp_caught_input_2026-10-08_Gloria"], "13956")
        self.assertTrue(any("does not match" in warning for warning in report.warnings))
        self.assertLess(
            next(index for index, warning in enumerate(report.warnings) if "does not match" in warning),
            next(index for index, warning in enumerate(report.warnings) if "could not be read" in warning),
        )


if __name__ == "__main__":
    unittest.main()
