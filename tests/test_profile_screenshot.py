from __future__ import annotations

import unittest
from datetime import date

from webapp.profile_screenshot import (
    XpScreenshotFillReport,
    apply_xp_screenshot_fills,
    parse_profile_ocr_text,
    screenshot_fill_outcome,
)


THOMZAY_OCR = """
Thomzay
& Dragonite
LEVEL
62
3,743,983 / 4,050,000
SEND GIFT
LOCAL TRADE
REMOTE TRADE
BATTLE
TOTAL ACTIVITY
Battles Won
905
Distance Walked
1,006.1
Pokémon Caught
26,833
"""


class ParseProfileOcrTextTest(unittest.TestCase):
    def test_extracts_account_level_xp_and_activity(self):
        parsed = parse_profile_ocr_text(
            THOMZAY_OCR,
            known_accounts=["Trada17", "SwanHill666", "Thomzay"],
        )
        self.assertEqual(parsed.account, "Thomzay")
        self.assertEqual(parsed.level, 62)
        self.assertEqual(parsed.xp_bar, 3_743_983)
        self.assertEqual(parsed.xp_to_next, 4_050_000)
        self.assertEqual(parsed.battles_won, 905.0)
        self.assertEqual(parsed.distance_walked, 1006.1)
        self.assertEqual(parsed.pokemon_caught, 26_833.0)

    def test_extracts_friend_profile_with_large_xp_and_thousands_commas(self):
        text = """
        Trada17
        & Diancie
        75
        LEVEL
        125,966,825 / 12,000,000
        TOTAL ACTIVITY
        Battles Won 3,673
        Distance Walked 3,669.5
        Pokemon Caught 134,284
        """
        parsed = parse_profile_ocr_text(
            text,
            known_accounts=["Thomzay", "Trada17", "SwanHill666"],
        )
        self.assertEqual(parsed.account, "Trada17")
        self.assertEqual(parsed.level, 75)
        self.assertEqual(parsed.xp_bar, 125_966_825)
        self.assertEqual(parsed.battles_won, 3673.0)
        self.assertEqual(parsed.distance_walked, 3669.5)
        self.assertEqual(parsed.pokemon_caught, 134_284.0)

    def test_leaves_account_empty_when_trainer_is_unknown(self):
        parsed = parse_profile_ocr_text(
            "SomeoneElse\nLEVEL\n10\n1,000 / 2,500\nBattles Won 1\nDistance Walked 2.0\nPokemon Caught 3",
            known_accounts=["Thomzay", "Trada17"],
        )
        self.assertIsNone(parsed.account)

    def test_does_not_treat_xp_thousands_digit_as_level(self):
        text = """
        Thomzay
        62
        LEVEL
        3,743,983/4,050,000
        TOTALACTIVITY
        Battles Won 905
        Distance Walked 1,006.1
        Pokemon Caught 26,833
        """
        parsed = parse_profile_ocr_text(text, known_accounts=["Thomzay"])
        self.assertEqual(parsed.level, 62)
        self.assertEqual(parsed.xp_bar, 3_743_983)

    def test_reads_fairphone_ocr_with_xp_between_level_and_label(self):
        text = """
        13TurboDoudl12
        &Zekrom100%
        67
        6,073,942 / 6,250,000
        LEVEL
        TOTALACTIVITY
        3,500
        BattlesWon
        6,623.2
        Distance Walke
        Pokémon Caught
        63,719
        """
        parsed = parse_profile_ocr_text(text, known_accounts=["13TurboDoudl12", "Thomzay"])
        self.assertEqual(parsed.account, "13TurboDoudl12")
        self.assertEqual(parsed.level, 67)
        self.assertEqual(parsed.xp_bar, 6_073_942)
        self.assertEqual(parsed.battles_won, 3500.0)
        self.assertEqual(parsed.distance_walked, 6623.2)
        self.assertEqual(parsed.pokemon_caught, 63_719.0)

    def test_fuzzy_matches_ocr_trainer_name(self):
        parsed = parse_profile_ocr_text(
            "PhiiDhill\n75\n35,328,094/12,000,000\nLEVEL\nTOTALACTIVITY\n7,056\nBattlesWon\n4,353.6\nDistance Walked\nPokémon Caughi\n96,613",
            known_accounts=["PhilDhill", "PhilDlow", "Thomzay"],
        )
        self.assertEqual(parsed.account, "PhilDhill")
        self.assertEqual(parsed.level, 75)
        self.assertEqual(parsed.battles_won, 7056.0)
        self.assertEqual(parsed.distance_walked, 4353.6)
        self.assertEqual(parsed.pokemon_caught, 96_613.0)

    def test_matches_account_name_with_trailing_ocr_digits(self):
        parsed = parse_profile_ocr_text(
            "Babsi5760\n66\n3,286,046 / 5,750,000\nLEVEL\nTOTALACTIVITY\n1,604\nBattlesWon\nDistance Walkea\n4,754.4\nPokemonCaught\n23,792",
            known_accounts=["Babsi", "Thomzay"],
        )
        self.assertEqual(parsed.account, "Babsi")
        self.assertEqual(parsed.level, 66)
        self.assertEqual(parsed.battles_won, 1604.0)
        self.assertEqual(parsed.distance_walked, 4754.4)
        self.assertEqual(parsed.pokemon_caught, 23_792.0)

    def test_maps_trainer_alias_cmanthehero_to_simon(self):
        text = """
        cmanthehero
        &Mew2
        71
        145,848,563 / 8,750,000
        LEVEL
        TOTALACTIVITY
        5,848
        BattlesWon
        Distance Walked
        17,693.9
        121,276
        Pokemon Caught
        """
        parsed = parse_profile_ocr_text(
            text,
            known_accounts=["Simon", "Thomzay", "PhilDhill"],
        )
        self.assertEqual(parsed.account, "Simon")
        self.assertEqual(parsed.level, 71)
        self.assertEqual(parsed.battles_won, 5848.0)
        self.assertEqual(parsed.distance_walked, 17693.9)
        self.assertEqual(parsed.pokemon_caught, 121_276.0)

    def test_reads_level_80_xp_when_denominator_is_zero(self):
        text = """
        AnSaCruiser
        80
        LEVEL
        431,512,558 / 0
        TOTAL ACTIVITY
        Battles Won 9,205
        Distance Walked 9,484.0
        Pokemon Caught 94,840
        """
        parsed = parse_profile_ocr_text(text, known_accounts=["AnSaCruiser", "Thomzay"])
        self.assertEqual(parsed.account, "AnSaCruiser")
        self.assertEqual(parsed.level, 80)
        self.assertEqual(parsed.xp_bar, 431_512_558)
        self.assertEqual(parsed.xp_to_next, 0)
        self.assertEqual(parsed.battles_won, 9205.0)
        self.assertEqual(parsed.distance_walked, 9484.0)
        self.assertEqual(parsed.pokemon_caught, 94_840.0)

    def test_reads_level_80_profile_without_an_xp_line(self):
        text = """
        AnSaCruiser
        80
        LEVEL
        TOTAL ACTIVITY
        Battles Won
        16,021
        Distance Walked
        10,489.0
        Pokemon Caught
        323,896
        """
        parsed = parse_profile_ocr_text(text, known_accounts=["AnSaCruiser", "Tastef"])
        self.assertEqual(parsed.level, 80)
        self.assertIsNone(parsed.xp_bar)
        self.assertEqual(parsed.battles_won, 16021.0)
        self.assertEqual(parsed.distance_walked, 10489.0)
        self.assertEqual(parsed.pokemon_caught, 323_896.0)

    def test_reads_xp_when_ocr_drops_the_slash(self):
        text = """
        PhilDhill
        75
        38,453,27712,000,000
        LEVEL
        TOTALACTIVITY
        7,062
        Battles Won
        DistanceWalke
        4,386.7
        Pokémon Caught
        97,807
        """
        parsed = parse_profile_ocr_text(text, known_accounts=["PhilDhill", "PhilDlow"])
        self.assertEqual(parsed.account, "PhilDhill")
        self.assertEqual(parsed.level, 75)
        self.assertEqual(parsed.xp_bar, 38_453_277)
        self.assertEqual(parsed.xp_to_next, 12_000_000)
        self.assertEqual(parsed.battles_won, 7062.0)
        self.assertEqual(parsed.distance_walked, 4386.7)
        self.assertEqual(parsed.pokemon_caught, 97_807.0)

    def test_does_not_swap_whole_number_distance_with_battles(self):
        text = """
        86Berni
        78
        84,048,480 / 15,000,000
        LEVEL
        TOTALACTIVITY
        6,631
        BattlesWon
        14,901.0
        DistanceWalked
        366,706
        Pokemon Caught
        """
        parsed = parse_profile_ocr_text(text, known_accounts=["86Berni"])
        self.assertEqual(parsed.battles_won, 6631.0)
        self.assertEqual(parsed.distance_walked, 14901.0)
        self.assertEqual(parsed.pokemon_caught, 366_706.0)

    def test_ignores_caught_count_with_the_leading_digits_covered(self):
        text = """
        Ins3rtN4m3Her3
        44
        750,549/800,000
        LEVEL
        TOTALACTIVITY
        199
        BattlesWon
        34.3
        DistanceWalked
        Pokemon Caught
        ,953
        """
        parsed = parse_profile_ocr_text(text, known_accounts=["Ins3rtN4m3Her3"])
        self.assertEqual(parsed.level, 44)
        self.assertEqual(parsed.xp_bar, 750_549)
        self.assertEqual(parsed.battles_won, 199.0)
        self.assertEqual(parsed.distance_walked, 34.3)
        self.assertIsNone(parsed.pokemon_caught)

    def test_reads_level_80_xp_when_profile_has_no_denominator(self):
        text = """
        AnSaCruiser
        LEVEL
        80
        431,512,558
        TOTAL ACTIVITY
        Battles Won 9,205
        Distance Walked 9,484.0
        Pokemon Caught 94,840
        """
        parsed = parse_profile_ocr_text(text, known_accounts=["AnSaCruiser"])
        self.assertEqual(parsed.level, 80)
        self.assertEqual(parsed.xp_bar, 431_512_558)
        self.assertEqual(parsed.xp_to_next, 0)


class ApplyXpScreenshotFillsTest(unittest.TestCase):
    def test_writes_widget_keys_without_saving(self):
        parsed = parse_profile_ocr_text(
            THOMZAY_OCR,
            known_accounts=["Thomzay"],
        )
        session_state: dict[str, object] = {}
        report = apply_xp_screenshot_fills(
            [parsed],
            xp_date=date(2026, 9, 7),
            selected_accounts=["Thomzay", "Trada17"],
            session_state=session_state,
        )
        self.assertEqual(report.filled, ["Thomzay"])
        self.assertEqual(session_state["xp_level_input_2026-09-07_Thomzay"], 62)
        self.assertEqual(session_state["xp_bar_input_2026-09-07_Thomzay"], "3743983")
        self.assertEqual(session_state["xp_battles_input_2026-09-07_Thomzay"], "905")
        self.assertEqual(session_state["xp_distance_input_2026-09-07_Thomzay"], "1006.1")
        self.assertEqual(session_state["xp_caught_input_2026-09-07_Thomzay"], "26833")
        self.assertNotIn("saved", report.__dict__)

    def test_skips_accounts_not_in_selected_list(self):
        parsed = parse_profile_ocr_text(THOMZAY_OCR, known_accounts=["Thomzay"])
        session_state: dict[str, object] = {}
        report = apply_xp_screenshot_fills(
            [parsed],
            xp_date=date(2026, 9, 7),
            selected_accounts=["Trada17"],
            session_state=session_state,
        )
        self.assertEqual(report.filled, [])
        self.assertEqual(report.skipped_unselected, ["Thomzay"])
        self.assertEqual(session_state, {})

    def test_marks_unchanged_screenshot_as_inactive(self):
        parsed = parse_profile_ocr_text(THOMZAY_OCR, known_accounts=["Thomzay"])
        session_state: dict[str, object] = {"xp_inactive_2026-09-07_Thomzay": False}
        report = apply_xp_screenshot_fills(
            [parsed],
            xp_date=date(2026, 9, 7),
            selected_accounts=["Thomzay"],
            session_state=session_state,
            last_known={
                "Thomzay": {
                    "level": 62,
                    "xp_bar": 3_743_983,
                    "battles_won": 905.0,
                    "distance_walked": 1006.1,
                    "pokemon_caught": 26_833.0,
                }
            },
        )
        self.assertTrue(session_state["xp_inactive_2026-09-07_Thomzay"])
        self.assertEqual(report.deactivated, ["Thomzay"])
        self.assertEqual(report.activated, [])

    def test_marks_changed_screenshot_as_active(self):
        parsed = parse_profile_ocr_text(THOMZAY_OCR, known_accounts=["Thomzay"])
        session_state: dict[str, object] = {"xp_inactive_2026-09-07_Thomzay": True}
        report = apply_xp_screenshot_fills(
            [parsed],
            xp_date=date(2026, 9, 7),
            selected_accounts=["Thomzay"],
            session_state=session_state,
            last_known={
                "Thomzay": {
                    "level": 61,
                    "xp_bar": 2_000_000,
                    "battles_won": 800.0,
                    "distance_walked": 900.0,
                    "pokemon_caught": 20_000.0,
                }
            },
        )
        self.assertFalse(session_state["xp_inactive_2026-09-07_Thomzay"])
        self.assertEqual(report.activated, ["Thomzay"])
        self.assertEqual(report.deactivated, [])
        self.assertEqual(session_state["xp_level_input_2026-09-07_Thomzay"], 62)

    def test_level_80_without_xp_line_keeps_previous_xp_bar(self):
        parsed = parse_profile_ocr_text(
            """
            AnSaCruiser
            80
            LEVEL
            TOTAL ACTIVITY
            Battles Won
            16,021
            Distance Walked
            10,489.0
            Pokemon Caught
            323,896
            """,
            known_accounts=["AnSaCruiser"],
        )
        session_state: dict[str, object] = {"xp_bar_input_2026-09-28_AnSaCruiser": "431512558"}
        report = apply_xp_screenshot_fills(
            [parsed],
            xp_date=date(2026, 9, 28),
            selected_accounts=["AnSaCruiser"],
            session_state=session_state,
            last_known={
                "AnSaCruiser": {
                    "level": 80,
                    "xp_bar": 431_512_558,
                    "battles_won": 9_000,
                    "distance_walked": 9_000.0,
                    "pokemon_caught": 300_000,
                }
            },
        )
        self.assertEqual(report.filled, ["AnSaCruiser"])
        self.assertEqual(report.kept_xp, ["AnSaCruiser"])
        self.assertEqual(report.warnings, [])
        self.assertEqual(session_state["xp_bar_input_2026-09-28_AnSaCruiser"], "431512558")
        self.assertEqual(session_state["xp_battles_input_2026-09-28_AnSaCruiser"], "16021")
        self.assertFalse(session_state["xp_inactive_2026-09-28_AnSaCruiser"])


class ScreenshotFillOutcomeTest(unittest.TestCase):
    def test_finished_when_every_account_is_filled_without_warnings(self):
        kind, message = screenshot_fill_outcome(XpScreenshotFillReport(filled=["Thomzay"]))
        self.assertEqual(kind, "finished")
        self.assertIn("Finished", message)
        self.assertIn("Thomzay", message)

    def test_failed_when_nothing_is_filled(self):
        kind, message = screenshot_fill_outcome(
            XpScreenshotFillReport(warnings=["shot.png: trainer name is not a known XP account."])
        )
        self.assertEqual(kind, "failed")
        self.assertIn("Failed", message)
        self.assertIn("shot.png", message)

    def test_other_when_fill_is_partial(self):
        kind, message = screenshot_fill_outcome(
            XpScreenshotFillReport(
                filled=["AnSaCruiser"],
                incomplete=["AnSaCruiser"],
                warnings=["AnSaCruiser: could not read xp_bar."],
            )
        )
        self.assertEqual(kind, "other")
        self.assertIn("Other", message)
        self.assertIn("xp_bar", message)


class ParseProfileScreenshotTest(unittest.TestCase):
    def test_reads_image_bytes_through_ocr_function(self):
        from webapp.profile_screenshot import parse_profile_screenshot

        parsed = parse_profile_screenshot(
            b"fake-image",
            known_accounts=["Thomzay"],
            source_name="thomzay.png",
            ocr_fn=lambda _image: THOMZAY_OCR,
        )
        self.assertEqual(parsed.account, "Thomzay")
        self.assertEqual(parsed.level, 62)
        self.assertEqual(parsed.source_name, "thomzay.png")


class FillXpInputsFromScreenshotsTest(unittest.TestCase):
    def test_fills_multiple_screenshots_through_ocr(self):
        from webapp.profile_screenshot import fill_xp_inputs_from_screenshots

        session_state: dict[str, object] = {}
        report = fill_xp_inputs_from_screenshots(
            [("thomzay.png", b"img-1"), ("unknown.png", b"img-2")],
            xp_date=date(2026, 9, 7),
            selected_accounts=["Thomzay", "Trada17"],
            known_accounts=["Thomzay", "Trada17"],
            session_state=session_state,
            ocr_fn=lambda image: THOMZAY_OCR if image == b"img-1" else "Noone\nLEVEL\n10\n100 / 200",
        )
        self.assertEqual(report.filled, ["Thomzay"])
        self.assertEqual(report.unmatched, ["unknown.png"])
        self.assertEqual(session_state["xp_level_input_2026-09-07_Thomzay"], 62)


class GeneratedImageOcrTest(unittest.TestCase):
    def test_reads_rendered_profile_text(self):
        from io import BytesIO

        from PIL import Image, ImageDraw, ImageFont

        from webapp.profile_screenshot import parse_profile_screenshot

        image = Image.new("RGB", (720, 900), (255, 248, 220))
        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.truetype("arial.ttf", 36)
        except OSError:
            font = ImageFont.load_default()
        lines = [
            "Thomzay",
            "62",
            "LEVEL",
            "3,743,983 / 4,050,000",
            "Battles Won 905",
            "Distance Walked 1,006.1",
            "Pokemon Caught 26,833",
        ]
        y = 40
        for line in lines:
            draw.text((40, y), line, fill=(20, 40, 80), font=font)
            y += 70
        buf = BytesIO()
        image.save(buf, format="PNG")
        parsed = parse_profile_screenshot(
            buf.getvalue(),
            known_accounts=["Thomzay"],
            source_name="generated.png",
        )
        self.assertEqual(parsed.account, "Thomzay")
        self.assertEqual(parsed.level, 62)
        self.assertEqual(parsed.xp_bar, 3_743_983)
        self.assertEqual(parsed.battles_won, 905.0)
        self.assertEqual(parsed.distance_walked, 1006.1)
        self.assertEqual(parsed.pokemon_caught, 26_833.0)


if __name__ == "__main__":
    unittest.main()
