from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from shared.paths import level_requirement_progress_path, level_requirements_path
from webapp.level_requirements import (
    LEVEL_PROGRESS_COLUMNS,
    LEVEL_REQUIREMENT_COLUMNS,
    REQUIREMENT_LEVELS,
    XP_REQUIREMENT_ID,
    LevelSet,
    RequirementRow,
    active_progress_timeline,
    build_level_sets,
    other_account_names,
    progression_start_date,
    is_platinum_requirement,
    load_level_requirement_progress,
    load_level_requirements,
    set_status,
    upsert_level_requirement_progress,
)

SIMPLE_CURVE = {77: 0, 78: 1_000, 79: 3_000, 80: 6_000}
REAL_CURVE = {77: 158_353_000, 78: 172_353_000, 79: 187_353_000, 80: 203_353_000}


def _requirements(rows: list[tuple[object, ...]]) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=LEVEL_REQUIREMENT_COLUMNS)


def _progress(rows: list[tuple[object, ...]]) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=LEVEL_PROGRESS_COLUMNS)


def _xp(rows: list[tuple[object, ...]]) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=["Date", "Spieler", "Lvl", "XP Bar", "Total XP"])


def _platinum(rows: list[tuple[object, ...]]) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=["date", "account", "value", "medal_id"])


def _catalog() -> pd.DataFrame:
    return _requirements(
        [
            ("platinum_medals_78", 78, "Earn platinum medals", 45, 1),
            ("buddy_hearts_78", 78, "Earn hearts with your buddy", 400, 2),
            ("explore_km_78", 78, "Explore km", 400, 3),
            ("field_research_78", 78, "Complete Field Research tasks", 500, 4),
            ("rocket_leaders_79", 79, "Defeat a Team GO Rocket Leader", 30, 2),
            ("raids_won_80", 80, "Win raids", 80, 4),
        ]
    )


def _build(
    requirements: pd.DataFrame,
    progress: pd.DataFrame,
    xp: pd.DataFrame,
    curve: dict[int, int],
    *,
    account: str = "Thombay",
    window_days: int = 7,
    as_of: pd.Timestamp | None = None,
    levels: list[int] | None = None,
    platinum: pd.DataFrame | None = None,
) -> list[LevelSet]:
    return build_level_sets(
        requirements=requirements,
        progress=progress,
        xp_history=xp,
        curve_totals=curve,
        account=account,
        window_days=window_days,
        as_of=as_of,
        levels=levels,
        platinum=platinum,
    )


def _level(sets: list[LevelSet], target_level: int) -> LevelSet:
    return next(item for item in sets if item.target_level == target_level)


def _row(level_set: LevelSet, requirement_id: str) -> RequirementRow:
    return next(item for item in level_set.rows if item.requirement_id == requirement_id)


class LevelRequirementsTest(unittest.TestCase):
    def test_set_status_level_77_and_78(self):
        self.assertEqual(set_status(77, 78), "active")
        self.assertEqual(set_status(77, 79), "locked")
        self.assertEqual(set_status(77, 80), "locked")
        self.assertEqual(set_status(78, 78), "reached")
        self.assertEqual(set_status(78, 79), "active")
        self.assertEqual(set_status(78, 80), "locked")

    def test_build_level_sets_orders_reached_active_locked(self):
        requirements = _catalog()
        progress = _progress(
            [
                ("2026-09-28", "Thombay", "platinum_medals_78", 10),
                ("2026-09-28", "Thombay", "buddy_hearts_78", 10),
                ("2026-09-28", "Thombay", "explore_km_78", 500),
                ("2026-09-28", "Thombay", "raids_won_80", 9),
            ]
        )
        at_77 = _build(
            requirements,
            progress,
            _xp(
                [
                    ("2026-09-28", "Thombay", 70, 1, 111),
                    ("2026-09-01", "Thombay", 10, 1, 50),
                    ("2026-09-28", "Thombay", 77, 400, 400),
                    ("2026-08-01", "Thombay", 5, 1, 10),
                ]
            ),
            SIMPLE_CURVE,
        )
        self.assertEqual([item.target_level for item in at_77], [78, 79, 80])
        self.assertEqual([item.status for item in at_77], ["active", "locked", "locked"])
        active = at_77[0]
        self.assertEqual(active.unlock_level, 77)
        xp_row = _row(active, XP_REQUIREMENT_ID)
        self.assertEqual(xp_row.value, 400)
        self.assertEqual(xp_row.goal, 1_000)
        self.assertEqual(xp_row.remaining, 600)
        self.assertEqual([item.requirement_id for item in active.rows], [XP_REQUIREMENT_ID, "platinum_medals_78", "buddy_hearts_78", "explore_km_78", "field_research_78"])
        self.assertEqual(_row(active, "field_research_78").value, 0)
        self.assertIsNone(_row(at_77[2], "raids_won_80").value)
        self.assertIsNone(_row(at_77[2], "raids_won_80").remaining)
        self.assertFalse(_row(at_77[2], "raids_won_80").done)
        self.assertEqual(_row(at_77[2], XP_REQUIREMENT_ID).goal, 3_000)
        self.assertEqual(at_77[1].finish_note, "")
        self.assertIsNone(at_77[2].finish_date)
        self.assertIsNone(at_77[2].binding_label)

        at_78 = _build(
            requirements,
            progress,
            _xp([("2026-09-28", "Thombay", 78, 0, 1_000)]),
            SIMPLE_CURVE,
        )
        self.assertEqual([item.status for item in at_78], ["reached", "active", "locked"])
        self.assertEqual([item.target_level for item in at_78], [78, 79, 80])
        reached = at_78[0]
        self.assertEqual(reached.finish_note, "")
        self.assertIsNone(reached.finish_date)
        self.assertIsNone(reached.binding_label)
        self.assertEqual(reached.unlock_level, 77)
        self.assertEqual(_row(reached, "platinum_medals_78").value, 45)
        self.assertTrue(_row(reached, "platinum_medals_78").done)
        self.assertEqual(_row(reached, "buddy_hearts_78").value, 400)
        self.assertEqual(_row(reached, "buddy_hearts_78").remaining, 0)
        self.assertEqual(_row(reached, "explore_km_78").value, 500)
        self.assertEqual(_row(reached, "explore_km_78").remaining, 0)
        self.assertTrue(_row(reached, XP_REQUIREMENT_ID).done)
        self.assertEqual(_row(reached, XP_REQUIREMENT_ID).value, 1_000)
        self.assertEqual(_row(at_78[1], "rocket_leaders_79").value, 0)
        self.assertEqual(_row(at_78[1], "rocket_leaders_79").status, "active")
        self.assertEqual(at_78[1].unlock_level, 78)

    def test_remaining_floored_at_zero_when_value_exceeds_goal(self):
        sets = _build(
            _requirements([("platinum_medals_78", 78, "Earn platinum medals", 45, 1)]),
            _progress([("2026-09-28", "Thombay", "platinum_medals_78", 1)]),
            _xp([("2026-09-28", "Thombay", 77, 0, 0)]),
            SIMPLE_CURVE,
            platinum=_platinum([("2026-09-28", "Thombay", 50, "platinum_medals")]),
        )
        row = _row(sets[0], "platinum_medals_78")
        self.assertEqual(row.value, 50)
        self.assertEqual(row.remaining, 0)
        self.assertTrue(row.done)
        self.assertIsNone(row.pace_per_day)
        self.assertIsNone(row.eta)
        self.assertEqual(row.note, "")
        self.assertIs(type(row.remaining), int)

    def test_finish_date_is_latest_incomplete_eta(self):
        requirements = _requirements(
            [
                ("fast_task", 78, "Fast task", 100, 1),
                ("slow_task", 78, "Slow task", 100, 2),
                ("done_task", 78, "Done task", 10, 3),
            ]
        )
        progress = _progress(
            [
                ("2026-01-01", "Thombay", "fast_task", 0),
                ("2026-01-11", "Thombay", "fast_task", 50),
                ("2026-01-01", "Thombay", "slow_task", 0),
                ("2026-01-11", "Thombay", "slow_task", 10),
                ("2026-01-11", "Thombay", "done_task", 10),
            ]
        )
        sets = _build(
            requirements,
            progress,
            _xp([("2026-01-11", "Thombay", 77, 1_000, 1_000)]),
            SIMPLE_CURVE,
            as_of=pd.Timestamp("2026-01-11"),
        )
        level_set = sets[0]
        self.assertEqual(_row(level_set, "fast_task").eta, pd.Timestamp("2026-01-21"))
        self.assertEqual(_row(level_set, "slow_task").eta, pd.Timestamp("2026-04-11"))
        self.assertEqual(level_set.finish_date, pd.Timestamp("2026-04-11"))
        self.assertEqual(level_set.binding_label, "Slow task")
        self.assertEqual(level_set.finish_note, "")
        self.assertEqual(level_set.finish_days, 90)

    def test_done_task_is_excluded_from_finish_date(self):
        requirements = _requirements(
            [
                ("open_task", 78, "Open task", 100, 1),
                ("done_task", 78, "Done task", 10, 2),
            ]
        )
        progress = _progress(
            [
                ("2026-01-01", "Thombay", "open_task", 0),
                ("2026-01-11", "Thombay", "open_task", 50),
                ("2026-01-11", "Thombay", "done_task", 10),
            ]
        )
        sets = _build(
            requirements,
            progress,
            _xp([("2026-01-11", "Thombay", 77, 1_000, 1_000)]),
            SIMPLE_CURVE,
            as_of=pd.Timestamp("2026-01-11"),
        )
        level_set = sets[0]
        done = _row(level_set, "done_task")
        self.assertTrue(done.done)
        self.assertIsNone(done.eta)
        self.assertEqual(level_set.finish_date, pd.Timestamp("2026-01-21"))
        self.assertEqual(level_set.binding_label, "Open task")
        self.assertEqual(level_set.finish_note, "")

    def test_single_progress_point_has_no_eta(self):
        sets = _build(
            _requirements([("buddy_hearts_78", 78, "Earn hearts with your buddy", 100, 2)]),
            _progress([("2026-09-28", "Thombay", "buddy_hearts_78", 10)]),
            _xp([("2026-09-28", "Thombay", 77, 1_000, 1_000)]),
            SIMPLE_CURVE,
        )
        row = _row(sets[0], "buddy_hearts_78")
        self.assertEqual(row.value, 10)
        self.assertEqual(row.remaining, 90)
        self.assertIsNone(row.eta)
        self.assertIsNone(row.pace_per_day)
        self.assertEqual(row.note, "log again for a date")
        self.assertIsNone(sets[0].finish_date)
        self.assertEqual(sets[0].finish_note, "Level date waits on Earn hearts with your buddy.")

    def test_upsert_rejects_decrease_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "level_requirement_progress.csv"
            written = upsert_level_requirement_progress(
                path,
                [
                    {"date": "2026-09-01", "account": "Thombay", "requirement_id": "buddy_hearts_78", "value": 10},
                    {"date": "2026-09-10", "account": "Thombay", "requirement_id": "buddy_hearts_78", "value": 20},
                    {"date": "2026-09-10", "account": "Thombay", "requirement_id": "platinum_medals_78", "value": 1},
                ],
            )
            self.assertEqual(written, 3)
            before = path.read_bytes()
            self.assertEqual(before[:3], b"\xef\xbb\xbf")

            with self.assertRaises(ValueError) as lowered:
                upsert_level_requirement_progress(
                    path,
                    [{"date": "2026-09-12", "account": "Thombay", "requirement_id": "buddy_hearts_78", "value": 9}],
                )
            self.assertIn("non-decreasing", str(lowered.exception))
            self.assertEqual(path.read_bytes(), before)

            with self.assertRaises(ValueError) as backdated:
                upsert_level_requirement_progress(
                    path,
                    [{"date": "2026-09-05", "account": "Thombay", "requirement_id": "buddy_hearts_78", "value": 25}],
                )
            self.assertIn("non-decreasing", str(backdated.exception))
            self.assertEqual(path.read_bytes(), before)

            replaced = upsert_level_requirement_progress(
                path,
                [{"date": "2026-09-10", "account": " Thombay ", "requirement_id": "buddy_hearts_78", "value": 15}],
            )
            self.assertEqual(replaced, 1)
            loaded = load_level_requirement_progress(path)
            buddy = loaded[loaded["requirement_id"] == "buddy_hearts_78"]["value"].tolist()
            self.assertEqual([int(value) for value in buddy], [10, 15])

            fresh = Path(tmp) / "fresh.csv"
            with self.assertRaises(ValueError) as batch:
                upsert_level_requirement_progress(
                    fresh,
                    [
                        {"date": "2026-09-01", "account": "Thombay", "requirement_id": "buddy_hearts_78", "value": 10},
                        {"date": "2026-09-02", "account": "Thombay", "requirement_id": "buddy_hearts_78", "value": 5},
                    ],
                )
            self.assertIn("non-decreasing", str(batch.exception))
            self.assertFalse(fresh.exists())

            untouched = Path(tmp) / "empty.csv"
            self.assertEqual(
                upsert_level_requirement_progress(
                    untouched,
                    [{"date": "not-a-date", "account": "Thombay", "requirement_id": "buddy_hearts_78", "value": 1}],
                ),
                0,
            )
            self.assertFalse(untouched.exists())

            duplicate_path = Path(tmp) / "duplicates.csv"
            count = upsert_level_requirement_progress(
                duplicate_path,
                [
                    {"date": "2026-09-01", "account": "Thombay", "requirement_id": "buddy_hearts_78", "value": 1},
                    {"date": "2026-09-01", "account": "Thombay", "requirement_id": "buddy_hearts_78", "value": 4},
                ],
            )
            self.assertEqual(count, 1)
            saved = load_level_requirement_progress(duplicate_path)
            self.assertEqual(int(saved.iloc[0]["value"]), 4)
            self.assertIn("2026-09-01,Thombay,buddy_hearts_78,4", duplicate_path.read_text(encoding="utf-8-sig"))

    def test_known_seven_day_xp_pace_and_waiting_tasks(self):
        requirements = _requirements(
            [
                ("platinum_medals_78", 78, "Earn platinum medals", 45, 1),
                ("buddy_hearts_78", 78, "Earn hearts with your buddy", 400, 2),
                ("explore_km_78", 78, "Explore km", 400, 3),
                ("field_research_78", 78, "Complete Field Research tasks", 500, 4),
            ]
        )
        progress = _progress(
            [
                ("2026-09-28", "Thombay", "platinum_medals_78", 1),
                ("2026-09-28", "Thombay", "buddy_hearts_78", 85),
                ("2026-09-28", "Thombay", "explore_km_78", 67),
                ("2026-09-28", "Thombay", "field_research_78", 65),
                ("2026-09-01", "Cerius", "buddy_hearts_78", 0),
                ("2026-09-28", "Cerius", "buddy_hearts_78", 300),
            ]
        )
        xp = _xp(
            [
                ("2026-09-21", "Thombay", 77, 5_265_047, 163_618_047),
                ("2026-09-28", "Thombay", 77, 6_616_112, 164_969_112),
                ("2026-09-21", "Cerius", 40, 0, 0),
                ("2026-09-28", "Cerius", 40, 0, 10_000_000),
            ]
        )
        platinum = _platinum([("2026-09-28", "Thombay", 45, "platinum_medals")])
        sets = _build(requirements, progress, xp, REAL_CURVE, window_days=7, platinum=platinum)
        self.assertEqual(len(sets), 1)
        level_set = sets[0]
        self.assertEqual(level_set.status, "active")
        self.assertEqual(level_set.unlock_level, 77)
        xp_row = _row(level_set, XP_REQUIREMENT_ID)
        self.assertEqual(xp_row.label, "XP")
        self.assertEqual(xp_row.sort_order, 0)
        self.assertEqual(xp_row.goal, 14_000_000)
        self.assertEqual(xp_row.value, 6_616_112)
        self.assertEqual(xp_row.remaining, 7_383_888)
        self.assertAlmostEqual(xp_row.pace_per_day, 1_351_065 / 7, places=6)
        self.assertIsNotNone(xp_row.eta)
        assert xp_row.eta is not None
        self.assertEqual(xp_row.eta.normalize(), pd.Timestamp("2026-11-05"))
        self.assertNotEqual(xp_row.eta, xp_row.eta.normalize())
        self.assertEqual(xp_row.note, "")
        self.assertFalse(xp_row.done)
        self.assertIs(type(xp_row.value), int)
        self.assertIs(type(xp_row.goal), int)
        self.assertIs(type(xp_row.remaining), int)
        self.assertIs(type(xp_row.pace_per_day), float)

        buddy = _row(level_set, "buddy_hearts_78")
        self.assertEqual(buddy.value, 85)
        self.assertEqual(buddy.remaining, 315)
        self.assertIsNone(buddy.eta)
        self.assertEqual(buddy.note, "log again for a date")
        self.assertTrue(_row(level_set, "platinum_medals_78").done)
        self.assertEqual(_row(level_set, "platinum_medals_78").remaining, 0)
        self.assertIsNone(level_set.finish_date)
        self.assertIsNone(level_set.finish_days)
        self.assertIsNone(level_set.binding_label)
        self.assertEqual(
            level_set.finish_note,
            "Level date waits on Earn hearts with your buddy, Explore km, Complete Field Research tasks.",
        )

        completed = _progress(
            [
                ("2026-09-28", "Thombay", "platinum_medals_78", 1),
                ("2026-09-28", "Thombay", "buddy_hearts_78", 400),
                ("2026-09-28", "Thombay", "explore_km_78", 400),
                ("2026-09-28", "Thombay", "field_research_78", 500),
            ]
        )
        finished = _build(
            requirements,
            completed,
            xp,
            REAL_CURVE,
            window_days=7,
            as_of=pd.Timestamp("2026-09-28"),
            platinum=platinum,
        )[0]
        self.assertEqual(finished.finish_date, _row(finished, XP_REQUIREMENT_ID).eta)
        self.assertEqual(finished.finish_date.normalize(), pd.Timestamp("2026-11-05"))
        self.assertEqual(finished.binding_label, "XP")
        self.assertEqual(finished.finish_note, "")
        self.assertEqual(finished.finish_days, 38)

    def test_pace_baseline_is_newest_on_or_before_cutoff(self):
        sets = _build(
            _requirements([("explore_km_78", 78, "Explore km", 100, 1)]),
            _progress(
                [
                    ("2026-01-01", "Thombay", "explore_km_78", 0),
                    ("2026-01-04", "Thombay", "explore_km_78", 10),
                    ("2026-01-11", "Thombay", "explore_km_78", 80),
                ]
            ),
            _xp([("2026-01-11", "Thombay", 77, 1_000, 1_000)]),
            SIMPLE_CURVE,
        )
        row = _row(sets[0], "explore_km_78")
        self.assertEqual(row.pace_per_day, 10.0)
        self.assertEqual(row.eta, pd.Timestamp("2026-01-13"))

    def test_second_log_inside_window_still_has_pace(self):
        sets = _build(
            _requirements([("explore_km_78", 78, "Explore km", 30, 1)]),
            _progress(
                [
                    ("2026-09-26", "Thombay", "explore_km_78", 0),
                    ("2026-09-28", "Thombay", "explore_km_78", 10),
                ]
            ),
            _xp([("2026-09-28", "Thombay", 77, 1_000, 1_000)]),
            SIMPLE_CURVE,
        )
        row = _row(sets[0], "explore_km_78")
        self.assertEqual(row.pace_per_day, 5.0)
        self.assertEqual(row.eta, pd.Timestamp("2026-10-02"))
        self.assertEqual(row.note, "")

    def test_flat_pace_has_no_date(self):
        sets = _build(
            _requirements([("explore_km_78", 78, "Explore km", 30, 1)]),
            _progress(
                [
                    ("2026-09-21", "Thombay", "explore_km_78", 10),
                    ("2026-09-28", "Thombay", "explore_km_78", 10),
                ]
            ),
            _xp([("2026-09-28", "Thombay", 77, 1_000, 1_000)]),
            SIMPLE_CURVE,
        )
        row = _row(sets[0], "explore_km_78")
        self.assertEqual(row.remaining, 20)
        self.assertIsNone(row.pace_per_day)
        self.assertIsNone(row.eta)
        self.assertEqual(row.note, "no date")

    def test_equal_etas_use_smallest_sort_order(self):
        sets = _build(
            _requirements(
                [
                    ("later_label", 78, "Later label", 100, 2),
                    ("earlier_label", 78, "Earlier label", 100, 1),
                ]
            ),
            _progress(
                [
                    ("2026-01-01", "Thombay", "later_label", 0),
                    ("2026-01-11", "Thombay", "later_label", 50),
                    ("2026-01-01", "Thombay", "earlier_label", 0),
                    ("2026-01-11", "Thombay", "earlier_label", 50),
                ]
            ),
            _xp([("2026-01-11", "Thombay", 77, 1_000, 1_000)]),
            SIMPLE_CURVE,
        )
        level_set = sets[0]
        self.assertEqual(_row(level_set, "earlier_label").eta, _row(level_set, "later_label").eta)
        self.assertEqual(level_set.binding_label, "Earlier label")
        self.assertEqual([item.requirement_id for item in level_set.rows], [XP_REQUIREMENT_ID, "earlier_label", "later_label"])

    def test_finish_days_rounds_and_defaults_to_latest_xp_date(self):
        requirements = _requirements([("explore_km_78", 78, "Explore km", 104, 1)])
        progress = _progress(
            [
                ("2026-01-01", "Thombay", "explore_km_78", 0),
                ("2026-01-11", "Thombay", "explore_km_78", 100),
            ]
        )
        xp = _xp([("2026-01-11", "Thombay", 77, 1_000, 1_000)])
        short = _build(requirements, progress, xp, SIMPLE_CURVE, as_of=pd.Timestamp("2026-01-11"))
        self.assertEqual(short[0].finish_days, 0)

        longer = _build(
            _requirements([("explore_km_78", 78, "Explore km", 106, 1)]),
            progress,
            xp,
            SIMPLE_CURVE,
            as_of=pd.Timestamp("2026-01-11"),
        )
        self.assertEqual(longer[0].finish_days, 1)

        dated = _build(
            _requirements([("buddy_hearts_78", 78, "Earn hearts with your buddy", 10, 1)]),
            _progress([("2026-01-01", "Thombay", "buddy_hearts_78", 10)]),
            _xp(
                [
                    ("2025-12-22", "Thombay", 77, 0, 0),
                    ("2026-01-01", "Thombay", 77, 50, 50),
                ]
            ),
            {77: 0, 78: 100},
        )
        self.assertEqual(dated[0].finish_date, pd.Timestamp("2026-01-11"))
        self.assertEqual(dated[0].finish_days, 10)
        self.assertEqual(dated[0].binding_label, "XP")

    def test_requirements_complete_when_nothing_is_open(self):
        sets = _build(
            _requirements([("platinum_medals_78", 78, "Earn platinum medals", 45, 1)]),
            _progress([("2026-09-28", "Thombay", "platinum_medals_78", 1)]),
            _xp([("2026-09-28", "Thombay", 77, 1_000, 1_000)]),
            SIMPLE_CURVE,
            platinum=_platinum([("2026-09-28", "Thombay", 45, "platinum_medals")]),
        )
        self.assertIsNone(sets[0].finish_date)
        self.assertIsNone(sets[0].finish_days)
        self.assertIsNone(sets[0].binding_label)
        self.assertEqual(sets[0].finish_note, "Requirements complete")

    def test_account_without_xp_returns_no_sets(self):
        sets = _build(
            _catalog(),
            _progress([]),
            _xp([("2026-09-28", "Cerius", 77, 1, 1)]),
            SIMPLE_CURVE,
            account="Thombay",
        )
        self.assertEqual(sets, [])

    def test_loader_drops_bad_rows_and_sorts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirements_path = root / "level_requirements.csv"
            requirements_path.write_text(
                "requirement_id,target_level,label,goal,sort_order\n"
                "b_task,79,Second,2,1\n"
                "a_task,78,First,1,2\n"
                "bad,nope,Skipped,1,1\n",
                encoding="utf-8",
            )
            loaded = load_level_requirements(requirements_path)
            self.assertEqual(loaded["requirement_id"].tolist(), ["a_task", "b_task"])
            self.assertEqual(int(loaded.iloc[0]["goal"]), 1)

            missing = load_level_requirements(root / "missing.csv")
            self.assertEqual(list(missing.columns), LEVEL_REQUIREMENT_COLUMNS)
            self.assertTrue(missing.empty)

            invalid = load_level_requirement_progress(requirements_path)
            self.assertEqual(list(invalid.columns), LEVEL_PROGRESS_COLUMNS)
            self.assertTrue(invalid.empty)

            progress_path = root / "progress.csv"
            progress_path.write_text(
                "date,account,requirement_id,value\n"
                "2026-09-02, Thombay ,buddy_hearts_78,12\n"
                "not-a-date,Thombay,buddy_hearts_78,99\n"
                "2026-09-01,Thombay,buddy_hearts_78,4\n",
                encoding="utf-8",
            )
            progress = load_level_requirement_progress(progress_path)
            self.assertEqual(progress["account"].tolist(), ["Thombay", "Thombay"])
            self.assertEqual([int(value) for value in progress["value"]], [4, 12])
            self.assertEqual(progress.iloc[0]["date"], pd.Timestamp("2026-09-01"))

    def test_seed_files_load_requirements_and_thombay_progress(self):
        requirements = load_level_requirements(level_requirements_path())
        progress = load_level_requirement_progress(level_requirement_progress_path())

        self.assertEqual(len(requirements), 40)
        self.assertEqual(list(requirements.columns), LEVEL_REQUIREMENT_COLUMNS)
        self.assertEqual(requirements.iloc[0]["requirement_id"], "platinum_medals_71")
        self.assertEqual(requirements.iloc[-1]["requirement_id"], "raids_won_80")
        medals_78 = requirements[requirements["requirement_id"] == "platinum_medals_78"].iloc[0]
        self.assertEqual(int(medals_78["goal"]), 45)
        lucky = requirements[requirements["requirement_id"] == "lucky_trades_79"].iloc[0]
        self.assertEqual(lucky["label"], "Obtain Lucky Pokémon in trades")

        day = progress[progress["date"].dt.normalize().eq(pd.Timestamp("2026-09-28"))]
        thombay = day[day["account"] == "Thombay"]
        self.assertEqual(len(thombay), 4)
        values = {str(req): int(val) for req, val in zip(thombay["requirement_id"], thombay["value"])}
        self.assertEqual(
            values,
            {
                "platinum_medals_78": 45,
                "buddy_hearts_78": 85,
                "explore_km_78": 67,
                "field_research_78": 65,
            },
        )

    def test_platinum_series_is_shared_and_ignores_progress(self):
        self.assertTrue(is_platinum_requirement("platinum_medals_71"))
        self.assertTrue(is_platinum_requirement("platinum_medals_72"))
        self.assertFalse(is_platinum_requirement("normal_task"))
        self.assertFalse(is_platinum_requirement(XP_REQUIREMENT_ID))

        requirements = _requirements(
            [
                ("platinum_medals_71", 71, "Earn platinum medals", 15, 1),
                ("normal_task", 71, "Normal task", 100, 2),
                ("platinum_medals_72", 72, "Earn platinum medals", 20, 1),
            ]
        )
        progress = _progress(
            [
                ("2026-09-28", "Thombay", "platinum_medals_71", 1),
                ("2026-09-28", "Thombay", "normal_task", 5),
                ("2026-09-28", "Thombay", "platinum_medals_72", 99),
            ]
        )
        platinum = _platinum(
            [
                ("2026-09-28", "Thombay", 18, "platinum_medals"),
                ("2026-09-29", "Thombay", 999, "raids_won"),
                ("2026-09-29", "Cerius", 40, "platinum_medals"),
            ]
        )
        sets = _build(
            requirements,
            progress,
            _xp([("2026-09-28", "Thombay", 70, 0, 0)]),
            {70: 0, 71: 1_000, 72: 3_000},
            levels=[71, 72],
            platinum=platinum,
        )
        self.assertEqual([item.target_level for item in sets], [71, 72])
        self.assertEqual([item.status for item in sets], ["active", "locked"])

        active = _row(_level(sets, 71), "platinum_medals_71")
        self.assertEqual(active.value, 18)
        self.assertEqual(active.remaining, 0)
        self.assertTrue(active.done)
        self.assertEqual(_row(_level(sets, 71), "normal_task").value, 5)

        locked = _row(_level(sets, 72), "platinum_medals_72")
        self.assertEqual(locked.value, 18)
        self.assertEqual(locked.remaining, 2)
        self.assertFalse(locked.done)
        self.assertIsNone(locked.eta)
        self.assertIsNone(locked.pace_per_day)
        self.assertEqual(locked.note, "")

    def test_requested_levels_include_xp_only_level(self):
        sets = _build(
            _requirements([("level_71_task", 71, "Level 71 task", 10, 1)]),
            _progress([]),
            _xp([("2026-09-28", "Thombay", 69, 400, 400)]),
            {69: 0, 70: 1_000, 71: 3_000},
            levels=[70, 71],
        )
        self.assertEqual([item.status for item in sets], ["active", "locked"])
        self.assertEqual([item.target_level for item in sets], [70, 71])

        level_70 = _level(sets, 70)
        self.assertEqual([row.requirement_id for row in level_70.rows], [XP_REQUIREMENT_ID])
        xp_row = _row(level_70, XP_REQUIREMENT_ID)
        self.assertEqual(xp_row.goal, 1_000)
        self.assertEqual(xp_row.value, 400)
        self.assertEqual(_level(sets, 71).unlock_level, 70)
        self.assertIn("level_71_task", [row.requirement_id for row in _level(sets, 71).rows])

    def test_level_far_below_requested_level_is_locked(self):
        sets = _build(
            _requirements([("raids_won_80", 80, "Win raids", 80, 4)]),
            _progress([]),
            _xp([("2026-09-28", "Thombay", 65, 0, 100)]),
            {69: 0, 70: 1_000},
            levels=[70],
        )
        self.assertEqual([item.target_level for item in sets], [70])
        self.assertEqual([item.status for item in sets], ["locked"])

    def test_active_progress_timeline_caps_percents(self):
        requirements = _requirements(
            [
                ("platinum_medals_78", 78, "Earn platinum medals", 45, 1),
                ("field_task", 78, "Field task", 100, 2),
                ("zero_task", 78, "Zero task", 100, 3),
            ]
        )
        progress = _progress(
            [
                ("2026-09-01", "Thombay", "platinum_medals_78", 9),
                ("2026-09-28", "Thombay", "field_task", 50),
                ("2026-09-28", "Thombay", "zero_task", 0),
            ]
        )
        xp = _xp([("2026-09-28", "Thombay", 77, 100, 50_000)])
        platinum = _platinum([("2026-09-28", "Thombay", 90, "platinum_medals")])
        level_set = _build(requirements, progress, xp, SIMPLE_CURVE, platinum=platinum)[0]
        self.assertEqual(level_set.target_level, 78)
        self.assertEqual(level_set.status, "active")

        timeline = active_progress_timeline(
            level_set,
            xp_history=xp,
            progress=progress,
            curve_totals=SIMPLE_CURVE,
            account="Thombay",
            platinum=platinum,
        )
        self.assertEqual(list(timeline.columns), ["date", "requirement_id", "label", "percent"])
        self.assertTrue(pd.api.types.is_float_dtype(timeline["percent"]))
        self.assertTrue(timeline["percent"].map(lambda value: 0.0 <= float(value) <= 100.0).all())

        def rows_on(requirement_id: str, day: str) -> pd.DataFrame:
            matched = timeline[timeline["requirement_id"].astype(str) == requirement_id]
            return matched[pd.to_datetime(matched["date"]).dt.normalize().eq(pd.Timestamp(day))]

        def percent_on(requirement_id: str, day: str) -> float:
            matched = rows_on(requirement_id, day)
            self.assertGreaterEqual(len(matched), 1)
            percents = {round(float(value), 6) for value in matched["percent"]}
            self.assertEqual(percents, {round(float(matched.iloc[0]["percent"]), 6)})
            return float(matched.iloc[0]["percent"])

        self.assertAlmostEqual(percent_on(XP_REQUIREMENT_ID, "2026-09-28"), 100.0)
        self.assertEqual(rows_on(XP_REQUIREMENT_ID, "2026-09-28")["label"].astype(str).unique().tolist(), ["XP"])
        self.assertAlmostEqual(percent_on("field_task", "2026-09-28"), 50.0)
        self.assertEqual(rows_on("field_task", "2026-09-28")["label"].astype(str).unique().tolist(), ["Field task"])
        self.assertAlmostEqual(percent_on("zero_task", "2026-09-28"), 0.0)
        self.assertAlmostEqual(percent_on("platinum_medals_78", "2026-09-28"), 100.0)
        self.assertEqual(
            rows_on("platinum_medals_78", "2026-09-28")["label"].astype(str).unique().tolist(),
            ["Earn platinum medals"],
        )

        platinum_rows = timeline[timeline["requirement_id"].astype(str) == "platinum_medals_78"]
        for value in platinum_rows["percent"]:
            self.assertNotAlmostEqual(float(value), 20.0)
        stray = rows_on("platinum_medals_78", "2026-09-01")
        self.assertTrue(stray.empty)

    def _level_79_set(
        self,
        xp: pd.DataFrame,
        progress: pd.DataFrame,
        platinum: pd.DataFrame | None = None,
    ) -> tuple[LevelSet, pd.DataFrame]:
        requirements = _requirements(
            [
                ("platinum_medals_79", 79, "Earn platinum medals", 45, 1),
                ("rocket_leaders_79", 79, "Defeat a Team GO Rocket Leader", 30, 2),
            ]
        )
        level_set = _build(requirements, progress, xp, SIMPLE_CURVE, platinum=platinum)[0]
        timeline = active_progress_timeline(
            level_set,
            xp_history=xp,
            progress=progress,
            curve_totals=SIMPLE_CURVE,
            account="Thombay",
            platinum=platinum,
        )
        return level_set, timeline

    def test_progression_starts_when_the_level_number_changes(self):
        xp = _xp(
            [
                ("2026-11-03", "Thombay", 77, 0, 5_000),
                ("2026-11-24", "Thombay", 78, 0, 1_200),
            ]
        )
        progress = _progress([("2026-11-03", "Thombay", "rocket_leaders_79", 4)])
        level_set, timeline = self._level_79_set(xp, progress)
        self.assertEqual(level_set.target_level, 79)
        self.assertEqual(level_set.unlock_level, 78)
        early_xp = timeline[
            (timeline["requirement_id"] == XP_REQUIREMENT_ID)
            & (pd.to_datetime(timeline["date"]) == pd.Timestamp("2026-11-03"))
        ]
        self.assertFalse(early_xp.empty)
        self.assertGreater(float(early_xp["percent"].iloc[0]), 0)

        start = progression_start_date(
            level_set,
            xp_history=xp,
            timeline=timeline,
            account="Thombay",
        )
        self.assertEqual(start, pd.Timestamp("2026-11-24"))

    def test_progression_starts_when_every_requirement_is_complete_without_a_level_change(self):
        xp = _xp(
            [
                ("2026-11-01", "Thombay", 78, 0, 5_000),
                ("2026-11-26", "Thombay", 78, 0, 5_100),
            ]
        )
        progress = _progress(
            [
                ("2026-11-10", "Thombay", "rocket_leaders_79", 10),
                ("2026-11-26", "Thombay", "rocket_leaders_79", 30),
            ]
        )
        platinum = _platinum([("2026-11-20", "Thombay", 50, "platinum_medals")])
        level_set, timeline = self._level_79_set(xp, progress, platinum)
        start = progression_start_date(
            level_set,
            xp_history=xp,
            timeline=timeline,
            account="Thombay",
        )
        self.assertEqual(start, pd.Timestamp("2026-11-26"))

    def test_progression_has_no_start_before_level_change_or_completion(self):
        xp = _xp([("2026-11-01", "Thombay", 78, 0, 5_000)])
        progress = _progress([("2026-11-10", "Thombay", "rocket_leaders_79", 10)])
        platinum = _platinum([("2026-11-01", "Thombay", 50, "platinum_medals")])
        level_set, timeline = self._level_79_set(xp, progress, platinum)
        start = progression_start_date(
            level_set,
            xp_history=xp,
            timeline=timeline,
            account="Thombay",
        )
        self.assertIsNone(start)

    def test_other_account_names_excludes_personal_and_sorts(self):
        result = other_account_names(
            ["Thombay", "Babsi", "Cerius", " Azog ", "", "Babsi"],
            ["Thombay", "Cerius", "Thomzay"],
        )
        self.assertEqual(result, ["Azog", "Babsi"])

    def test_requirement_levels_cover_2_through_80(self):
        self.assertEqual(REQUIREMENT_LEVELS, list(range(2, 81)))

    def test_level_65_activates_xp_only_level_66_inside_full_range(self):
        sets = _build(
            _requirements([]),
            _progress([]),
            _xp([("2026-09-28", "Thombay", 65, 0, 100)]),
            SIMPLE_CURVE,
            levels=list(REQUIREMENT_LEVELS),
        )
        level_66 = _level(sets, 66)
        self.assertEqual(level_66.status, "active")
        self.assertEqual(level_66.unlock_level, 65)
        self.assertEqual([row.requirement_id for row in level_66.rows], [XP_REQUIREMENT_ID])
        self.assertEqual(_level(sets, 65).status, "reached")
        self.assertEqual(_level(sets, 67).status, "locked")
        self.assertEqual(_level(sets, 2).status, "reached")


if __name__ == "__main__":
    unittest.main()
