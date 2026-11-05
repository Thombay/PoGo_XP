from __future__ import annotations

import ast
import sys
import unittest
from datetime import date
from pathlib import Path

from webapp.medal_recording import (
    apply_medal_recording_fills,
    fill_medal_inputs_from_recording,
    merge_medal_reads,
    parse_medal_frame_text,
)


_MEDALS = [
    ("jogger", "Jogger"),
    ("collector", "Collector"),
    ("rising_star", "Rising Star"),
    ("rising_star_duo", "Rising Star Duo"),
]
_MEDAL_DATE = date(2026, 11, 3)
_ACCOUNT = "Thomzay"
_KNOWN_ACCOUNTS = ["Thomzay", "Trada17", "SwanHill666"]
_JPEG = b"\xff\xd8\xff\xd9"


def _value_key(medal_id: str) -> str:
    return f"medal_value_input_{_MEDAL_DATE.isoformat()}_{_ACCOUNT}_{medal_id}"


class ParseMedalFrameTextTest(unittest.TestCase):
    def test_name_and_count_on_separate_texts_do_not_merge(self):
        name_only = parse_medal_frame_text("Jogger", _MEDALS)
        count_only = parse_medal_frame_text("12345", _MEDALS)
        self.assertNotIn("jogger", name_only)
        self.assertNotIn("jogger", count_only)
        self.assertEqual(name_only, {})
        self.assertEqual(count_only, {})
        self.assertEqual(merge_medal_reads([name_only, count_only]), {})
        self.assertNotIn("jogger", merge_medal_reads([name_only, count_only]))

    def test_rising_star_duo_keeps_its_count_away_from_rising_star(self):
        parsed = parse_medal_frame_text("Rising Star Duo\n50\nRising Star\n10", _MEDALS)
        self.assertEqual(parsed["rising_star_duo"], 50)
        self.assertEqual(parsed["rising_star"], 10)
        self.assertEqual(set(parsed), {"rising_star", "rising_star_duo"})

    def test_rising_star_duo_alone_does_not_set_rising_star(self):
        parsed = parse_medal_frame_text("Rising Star Duo\n50", _MEDALS)
        self.assertEqual(parsed, {"rising_star_duo": 50.0})
        self.assertNotIn("rising_star", parsed)
        lowered = parse_medal_frame_text("rising star duo\n50", _MEDALS)
        self.assertEqual(lowered, {"rising_star_duo": 50.0})

    def test_comma_numbers_round_trip_without_commas(self):
        parsed = parse_medal_frame_text("Jogger\n12,345\nCollector\n1,006.5", _MEDALS)
        self.assertEqual(parsed["jogger"], 12345)
        self.assertEqual(parsed["collector"], 1006.5)
        session: dict[str, object] = {}
        apply_medal_recording_fills(
            parsed,
            medal_date=_MEDAL_DATE,
            account=_ACCOUNT,
            medals=_MEDALS,
            session_state=session,
            last_known={},
        )
        self.assertEqual(session[_value_key("jogger")], "12345")
        self.assertEqual(session[_value_key("collector")], "1006.5")

    def test_display_names_match_case_insensitively(self):
        self.assertEqual(parse_medal_frame_text("jOgGeR\n8", _MEDALS), {"jogger": 8.0})

    def test_total_xp_and_platinum_medals_are_ignored(self):
        medals = _MEDALS + [("total_xp", "Total XP"), ("platinum_medals", "Platinum Medals")]
        parsed = parse_medal_frame_text("Total XP\n900\nJogger\n12\nPlatinum Medals\n3", medals)
        self.assertEqual(parsed, {"jogger": 12.0})

    def test_equal_distance_prefers_the_number_after_the_name(self):
        self.assertEqual(parse_medal_frame_text("10 Jogger 12", _MEDALS), {"jogger": 12.0})

    def test_closer_medal_takes_the_shared_number(self):
        parsed = parse_medal_frame_text("Jogger" + (" " * 8) + "10 Collector", _MEDALS)
        self.assertEqual(parsed, {"collector": 10.0})

    def test_number_past_another_medal_name_is_not_used(self):
        parsed = parse_medal_frame_text("Jogger\nCollector\n10\n20", _MEDALS)
        self.assertEqual(parsed, {"collector": 10.0})
        self.assertNotIn("jogger", parsed)

    def test_one_number_is_not_given_to_two_medals(self):
        self.assertEqual(parse_medal_frame_text("Jogger 10 Collector", _MEDALS), {"jogger": 10.0})


class MergeMedalReadsTest(unittest.TestCase):
    def test_last_successful_subset_wins(self):
        merged = merge_medal_reads(
            [
                {"jogger": 10},
                {"collector": 20, "jogger": 11},
            ]
        )
        self.assertEqual(merged, {"jogger": 11.0, "collector": 20.0})

    def test_later_omission_does_not_erase_a_medal(self):
        merged = merge_medal_reads(
            [
                {"jogger": 10, "collector": 4},
                {"collector": 20},
            ]
        )
        self.assertEqual(merged, {"jogger": 10.0, "collector": 20.0})

    def test_empty_reads_stay_empty(self):
        self.assertEqual(merge_medal_reads([]), {})


class ApplyMedalRecordingFillsTest(unittest.TestCase):
    def test_value_below_last_known_is_not_written(self):
        jogger_key = _value_key("jogger")
        collector_key = _value_key("collector")
        session: dict[str, object] = {jogger_key: "80", "unrelated": "keep"}
        report = apply_medal_recording_fills(
            {"jogger": 79, "collector": 1.5},
            medal_date=_MEDAL_DATE,
            account=_ACCOUNT,
            medals=_MEDALS,
            session_state=session,
            last_known={"jogger": 80, "collector": 2.5},
        )
        self.assertEqual(session[jogger_key], "80")
        self.assertNotIn(collector_key, session)
        self.assertEqual(session["unrelated"], "keep")
        self.assertEqual(report.rejected_below_last, ["Jogger", "Collector"])
        self.assertEqual(report.filled, [])
        self.assertEqual(report.not_seen, ["Rising Star", "Rising Star Duo"])
        self.assertEqual(
            report.warnings,
            [
                "Jogger: 79 is below the last saved 80, so it was left unchanged.",
                "Collector: 1.5 is below the last saved 2.5, so it was left unchanged.",
            ],
        )

    def test_unseen_medals_stay_absent_and_seen_medals_are_written(self):
        session: dict[str, object] = {"unrelated": "keep"}
        report = apply_medal_recording_fills(
            {"collector": 20.5, "jogger": 12345},
            medal_date=_MEDAL_DATE,
            account=_ACCOUNT,
            medals=_MEDALS,
            session_state=session,
            last_known={"jogger": 100, "collector": 20.5},
        )
        self.assertEqual(session[_value_key("jogger")], "12345")
        self.assertEqual(session[_value_key("collector")], "20.5")
        self.assertNotIn(_value_key("rising_star"), session)
        self.assertNotIn(_value_key("rising_star_duo"), session)
        self.assertEqual(session["unrelated"], "keep")
        self.assertEqual(report.filled, ["Jogger", "Collector"])
        self.assertEqual(report.not_seen, ["Rising Star", "Rising Star Duo"])
        self.assertEqual(report.rejected_below_last, [])
        self.assertEqual(report.warnings, [])


class FillMedalInputsFromRecordingTest(unittest.TestCase):
    def test_import_does_not_load_recording_or_ocr_modules(self):
        source = Path(__file__).resolve().parents[1] / "webapp" / "medal_recording.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        modules: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
        self.assertFalse(any(name.startswith("webapp.profile_") for name in modules))

    def test_sequential_frames_merge_for_the_selected_account(self):
        texts = ["thomzay\nJogger\n10", "Collector\n20\nJogger\n11"]
        seen_frames: list[bytes] = []
        seen_videos: list[bytes] = []

        def ocr_fn(frame: bytes) -> str:
            seen_frames.append(frame)
            return texts.pop(0)

        def frame_extractor(video_bytes: bytes) -> tuple[list[bytes], list[str]]:
            seen_videos.append(video_bytes)
            return [b"\xff\xd8" + video_bytes], ["kept one settled frame"]

        session: dict[str, object] = {}
        loaded_before = "webapp.profile_recording" in sys.modules or "webapp.profile_screenshot" in sys.modules
        report = fill_medal_inputs_from_recording(
            [("a.mp4", b"video-a"), ("b.mp4", b"video-b")],
            medal_date=_MEDAL_DATE,
            account=_ACCOUNT,
            known_accounts=_KNOWN_ACCOUNTS,
            medals=_MEDALS,
            session_state=session,
            last_known={"jogger": 1},
            ocr_fn=ocr_fn,
            frame_extractor=frame_extractor,
        )
        self.assertEqual(seen_videos, [b"video-a", b"video-b"])
        self.assertEqual(seen_frames, [b"\xff\xd8video-a", b"\xff\xd8video-b"])
        self.assertEqual(texts, [])
        self.assertEqual(session[_value_key("jogger")], "11")
        self.assertEqual(session[_value_key("collector")], "20")
        self.assertEqual(report.filled, ["Jogger", "Collector"])
        self.assertEqual(report.not_seen, ["Rising Star", "Rising Star Duo"])
        self.assertEqual(report.skipped_other_trainer, 0)
        self.assertEqual(report.rejected_below_last, [])
        self.assertEqual(report.warnings, ["kept one settled frame", "kept one settled frame"])
        loaded_after = "webapp.profile_recording" in sys.modules or "webapp.profile_screenshot" in sys.modules
        self.assertEqual(loaded_after, loaded_before)

    def test_other_trainer_frame_is_skipped_and_does_not_apply(self):
        texts = [
            "thomzay\nJogger\n10\nCollector\n4",
            "TRADA17\nCollector\n99",
            "xxTRADA17\nJogger\n11",
        ]

        def ocr_fn(_frame: bytes) -> str:
            return texts.pop(0)

        def frame_extractor(_video_bytes: bytes) -> tuple[list[bytes], list[str]]:
            return [_JPEG], ["kept one settled frame"]

        session: dict[str, object] = {}
        report = fill_medal_inputs_from_recording(
            [("a.mp4", b"video-a"), ("b.mp4", b"video-b"), ("c.mp4", b"video-c")],
            medal_date=_MEDAL_DATE,
            account=_ACCOUNT,
            known_accounts=_KNOWN_ACCOUNTS,
            medals=_MEDALS,
            session_state=session,
            last_known={},
            ocr_fn=ocr_fn,
            frame_extractor=frame_extractor,
        )
        self.assertEqual(texts, [])
        self.assertEqual(session[_value_key("jogger")], "11")
        self.assertEqual(session[_value_key("collector")], "4")
        self.assertNotIn(_value_key("rising_star"), session)
        self.assertEqual(report.filled, ["Jogger", "Collector"])
        self.assertEqual(report.not_seen, ["Rising Star", "Rising Star Duo"])
        self.assertEqual(report.skipped_other_trainer, 1)
        self.assertEqual(report.rejected_below_last, [])
        self.assertEqual(
            report.warnings,
            [
                "kept one settled frame",
                "kept one settled frame",
                "kept one settled frame",
                "Skipped 1 frame that named another trainer.",
            ],
        )

    def test_extractor_failure_is_a_warning(self):
        def frame_extractor(_video_bytes: bytes) -> tuple[list[bytes], list[str]]:
            raise RuntimeError("ffmpeg failed")

        report = fill_medal_inputs_from_recording(
            [("bad.mp4", b"video")],
            medal_date=_MEDAL_DATE,
            account=_ACCOUNT,
            known_accounts=_KNOWN_ACCOUNTS,
            medals=_MEDALS,
            session_state={},
            last_known={},
            ocr_fn=lambda _frame: "",
            frame_extractor=frame_extractor,
        )
        self.assertEqual(report.filled, [])
        self.assertEqual(report.warnings, ["bad.mp4: ffmpeg failed"])

    def test_recording_with_no_settled_frames_warns(self):
        def frame_extractor(_video_bytes: bytes) -> tuple[list[bytes], list[str]]:
            return [], []

        report = fill_medal_inputs_from_recording(
            [("empty.mp4", b"video")],
            medal_date=_MEDAL_DATE,
            account=_ACCOUNT,
            known_accounts=_KNOWN_ACCOUNTS,
            medals=_MEDALS,
            session_state={},
            last_known={},
            ocr_fn=lambda _frame: "",
            frame_extractor=frame_extractor,
        )
        self.assertEqual(report.filled, [])
        self.assertEqual(report.warnings, ["empty.mp4: no settled frames to read."])


if __name__ == "__main__":
    unittest.main()
