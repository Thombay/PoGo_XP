---
name: Level Requirements Tracker
overview: Add a local Streamlit page that shows level 78-80 requirements, logs task progress, and estimates when the active level finishes from the slowest remaining requirement.
todos:
  - id: requirement-config
    content: Add the level 78-80 requirement catalog and seed today's Thombay task progress.
    status: completed
  - id: progress-math
    content: Add unlock, remaining, pace, and finish-date calculations, with XP read from xp_history.
    status: completed
  - id: tracker-page
    content: Add a Level Requirements page with progress, pace, and the binding finish date.
    status: completed
  - id: tests
    content: Test unlock rules, remaining counts, and finish date as the latest requirement ETA.
    status: completed
isProject: false
---

# Level Requirements Tracker

## What this answers

Thombay is level 77. The in-game page titled 78 is the requirement set for reaching level 78. Level 79 tasks unlock at level 78. Level 80 tasks unlock at level 79.

The page should show, for the active set:

- progress and remaining for XP and each task
- pace and a finish date once two readings exist
- one level finish date, which is the latest of those dates
- the name of the requirement that sets that date

Locked sets stay visible as a checklist. Their counters stay at zero until the unlock level is reached, matching the game screens.

## Today, 2026-09-28

Active set: reach level 78. Saved XP is the 2026-09-28 row in `inputs/data/xp_history.csv` (level 77, bar 6,616,112). The screenshot taken later the same day shows 6,622,087. The page uses the saved XP row. Update that row in Data Input when the screenshot number should be the source.

| Requirement | Progress | Remaining | Pace we can use today |
| --- | ---: | ---: | --- |
| XP to level 78 | 6,622,087 / 14,000,000 | 7,377,913 | From XP history |
| Earn 45 platinum medals | done | 0 | Done |
| Buddy hearts | 85 / 400 | 315 | None until the next log |
| Explore | 67 / 400 km | 333 | None until the next log |
| Field research | 65 / 500 | 435 | None until the next log |

XP pace from total XP (`level start + XP bar` via `inputs/reference/total_xp_curve.csv`):

| Window | Pace | XP-only ETA |
| --- | ---: | --- |
| Since 2026-09-21 (7 days) | 193,009 XP/day | 38 days, 2026-11-05 |
| Since 2026-08-24 (35 days) | 269,114 XP/day | 27 days, 2026-10-25 |
| Since 2026-06-30 (90 days) | 251,804 XP/day | 29 days, 2026-10-27 |

Those dates are only the XP requirement. Level 78 finishes on the later of the XP date and the three open tasks. Hearts, kilometres, and field research have a single reading, so the page shows their remaining counts and waits for the next log before printing a date.

Level 79, unlocked at level 78:

- 15,000,000 XP
- 47 platinum medals
- Defeat a Team GO Rocket Leader 30 times
- Hatch 100 eggs
- Obtain 50 lucky Pokémon in trades

Level 80, unlocked at level 79:

- 16,000,000 XP
- 50 platinum medals
- Win 80 trainer battles in the GO Battle League
- Make 999 excellent throws
- Win 80 raids

Each task awards 800 XP in game. That amount does not change the forecast.

## Rules

- A requirement set for reaching level N is active when the account's latest level is N - 1.
- The set is locked while the latest level is below N - 1.
- The set is reached when latest level is N or higher.
- Latest level and the XP bar come from `xp_history.csv`. XP is not typed again on this page.
- Task counters come only from logs on this page. Medal snapshots and `battles_won` are separate observations and are not copied in.
- On the first log after a set unlocks, enter the numbers the game shows. Some counters may already be partly filled or complete.
- A level finish date is the latest ETA among requirements that are still short.
- A requirement with value >= goal is done and drops out of that date.
- XP can pass the bar requirement while tasks are still open. Past that point XP shows done for the current level. Later XP still lands in `xp_history` and counts toward the next bar after level-up.
- Pace uses the same 7-day and 30-day choices as the dashboards. With one task point, show remaining and "log again for a date". With a flat or falling pace, show remaining and no date.
- ETA for one requirement is `remaining / daily pace` from the newest point and the newest earlier point inside the window.
- Task values for an account cannot decrease.

## Data

`inputs/reference/level_requirements.csv`

```text
requirement_id,target_level,label,goal,sort_order
platinum_medals_78,78,Earn platinum medals,45,1
buddy_hearts_78,78,Earn hearts with your buddy,400,2
explore_km_78,78,Explore km,400,3
field_research_78,78,Complete Field Research tasks,500,4
platinum_medals_79,79,Earn platinum medals,47,1
rocket_leaders_79,79,Defeat a Team GO Rocket Leader,30,2
eggs_hatched_79,79,Hatch eggs,100,3
lucky_trades_79,79,Obtain Lucky Pokémon in trades,50,4
platinum_medals_80,80,Earn platinum medals,50,1
gbl_wins_80,80,Win Trainer Battles in the GO Battle League,80,2
excellent_throws_80,80,Make Excellent Throws,999,3
raids_won_80,80,Win raids,80,4
```

XP stays on the curve file. Unlock level is `target_level - 1`.

`inputs/data/level_requirement_progress.csv`

```text
date,account,requirement_id,value
2026-09-28,Thombay,platinum_medals_78,45
2026-09-28,Thombay,buddy_hearts_78,85
2026-09-28,Thombay,explore_km_78,67
2026-09-28,Thombay,field_research_78,65
```

## Page

Add **Level Requirements** to the Streamlit page radio in `webapp/app.py`. Keep the math in a new `webapp/level_requirements.py` so `app.py` only loads data and renders.

Account picker defaults to Thombay (`Ich`). Any account with XP history can be selected.

Active level:

- one summary line: finish date, days left, and the requirement that sets the date
- window toggle: 7 days and 30 days
- one row per requirement: label, `value / goal`, remaining, pace per day, ETA
- XP row reads `xp_history`
- task rows read the progress file
- a small form: date plus one number per active task, saved into the progress file

Locked levels:

- listed under the active level
- label, goal, and "Unlocks at level N"
- no progress bar and no ETA

Reached levels, once they exist, show as complete and stay above the active set.

## Tests

In `tests/test_level_requirements.py`:

- level 77 activates the level 78 set and locks 79 and 80
- level 78 activates 79 and marks 78 reached
- remaining is `goal - value`, floored at 0
- finish date equals the latest incomplete ETA
- a done task is excluded from that date
- a single progress point produces no task ETA
- a lower new value is rejected

## Out of scope

- GitHub Pages or Drive export of this page
- Requirements below level 78
- Predicting locked counters from medals, distance, eggs, or `battles_won`
- Counting the 800 XP task rewards in the XP forecast
