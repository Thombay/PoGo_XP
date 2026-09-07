from __future__ import annotations

import unittest
from datetime import date

from webapp.profile_screenshot import apply_xp_screenshot_fills, parse_profile_ocr_text


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
