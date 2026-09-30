from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

LEVEL_REQUIREMENT_COLUMNS = ["requirement_id", "target_level", "label", "goal", "sort_order"]
LEVEL_PROGRESS_COLUMNS = ["date", "account", "requirement_id", "value"]
XP_REQUIREMENT_ID = "xp"


@dataclass(frozen=True)
class RequirementRow:
    requirement_id: str
    target_level: int
    label: str
    status: str  # "locked" | "active" | "reached"
    goal: int
    value: int | None
    remaining: int | None
    pace_per_day: float | None
    eta: pd.Timestamp | None
    note: str
    done: bool
    sort_order: int


@dataclass(frozen=True)
class LevelSet:
    target_level: int
    status: str
    unlock_level: int
    rows: tuple[RequirementRow, ...]
    finish_date: pd.Timestamp | None
    finish_days: int | None
    binding_label: str | None
    finish_note: str


def _empty_requirements() -> pd.DataFrame:
    return pd.DataFrame(columns=LEVEL_REQUIREMENT_COLUMNS)


def _empty_progress() -> pd.DataFrame:
    return pd.DataFrame(columns=LEVEL_PROGRESS_COLUMNS)


def _clean_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None or value is pd.NA:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _read_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except (OSError, UnicodeError, pd.errors.EmptyDataError, pd.errors.ParserError, ValueError):
        return None


def _coerce_requirements(df: pd.DataFrame) -> pd.DataFrame:
    if not set(LEVEL_REQUIREMENT_COLUMNS).issubset(df.columns):
        return _empty_requirements()
    out = df.loc[:, LEVEL_REQUIREMENT_COLUMNS].copy()
    out["requirement_id"] = out["requirement_id"].map(_clean_text)
    out["label"] = out["label"].map(_clean_text)
    for column in ("target_level", "goal", "sort_order"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out = out.dropna(subset=["requirement_id", "target_level", "goal", "sort_order"]).copy()
    out = out[out["requirement_id"] != ""].copy()
    if out.empty:
        return _empty_requirements()
    out["target_level"] = out["target_level"].map(int)
    out["goal"] = out["goal"].map(int)
    out["sort_order"] = out["sort_order"].map(int)
    out = out.sort_values(["target_level", "sort_order", "requirement_id"], kind="mergesort")
    return out.reset_index(drop=True)


def _coerce_progress(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy() if df is not None else _empty_progress()
    for column in LEVEL_PROGRESS_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    if frame.empty:
        return _empty_progress()
    out = frame.loc[:, LEVEL_PROGRESS_COLUMNS].copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["account"] = out["account"].map(_clean_text)
    out["requirement_id"] = out["requirement_id"].map(_clean_text)
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    out = out.dropna(subset=["date", "account", "requirement_id", "value"]).copy()
    out = out[(out["account"] != "") & (out["requirement_id"] != "")].copy()
    if out.empty:
        return _empty_progress()
    out["date"] = out["date"].dt.normalize()
    out["value"] = out["value"].map(int)
    return out.reset_index(drop=True)


def load_level_requirements(path: Path) -> pd.DataFrame:
    raw = _read_csv(path)
    if raw is None:
        return _empty_requirements()
    return _coerce_requirements(raw)


def load_level_requirement_progress(path: Path) -> pd.DataFrame:
    raw = _read_csv(path)
    if raw is None:
        return _empty_progress()
    progress = _coerce_progress(raw)
    if progress.empty:
        return _empty_progress()
    progress = progress.sort_values(["date", "account", "requirement_id"], kind="mergesort")
    return progress.reset_index(drop=True)


def _series_decrease_message(progress: pd.DataFrame) -> str | None:
    ordered = progress.sort_values(["account", "requirement_id", "date"], kind="mergesort")
    previous: dict[tuple[str, str], int] = {}
    for row in ordered.itertuples(index=False):
        key = (str(row.account), str(row.requirement_id))
        value = int(row.value)
        prior = previous.get(key)
        if prior is not None and value < prior:
            account, requirement_id = key
            return (
                f"Level requirement progress must be non-decreasing over time: "
                f"{account} {requirement_id} goes from {prior} to {value}."
            )
        previous[key] = value
    return None


def upsert_level_requirement_progress(path: Path, rows: list[dict]) -> int:
    if not rows:
        return 0
    incoming = _coerce_progress(pd.DataFrame(rows))
    incoming = incoming.drop_duplicates(subset=["date", "account", "requirement_id"], keep="last")
    if incoming.empty:
        return 0

    existing = load_level_requirement_progress(path)
    if existing.empty:
        combined = incoming.copy()
    else:
        combined = pd.concat([existing, incoming], ignore_index=True)
    combined = combined.drop_duplicates(subset=["date", "account", "requirement_id"], keep="last")
    decrease = _series_decrease_message(combined)
    if decrease is not None:
        raise ValueError(decrease)

    combined = combined.sort_values(["date", "account", "requirement_id"], kind="mergesort")
    combined = combined.reset_index(drop=True)
    out = combined.loc[:, LEVEL_PROGRESS_COLUMNS].copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out["value"] = out["value"].map(int)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, encoding="utf-8-sig")
    return int(len(incoming))


def set_status(current_level: int, target_level: int) -> str:
    if int(current_level) >= int(target_level):
        return "reached"
    if int(current_level) < int(target_level) - 1:
        return "locked"
    return "active"


def _curve_total(curve_totals: Mapping[int, int], level: int) -> int | None:
    try:
        return int(curve_totals[level])
    except (KeyError, TypeError, ValueError):
        return None


def _xp_goal(curve_totals: Mapping[int, int], target_level: int) -> int | None:
    start = _curve_total(curve_totals, target_level - 1)
    end = _curve_total(curve_totals, target_level)
    if start is None or end is None:
        return None
    return int(end - start)


def _daily_points(dates: pd.Series, values: pd.Series) -> list[tuple[pd.Timestamp, int]]:
    frame = pd.DataFrame({"date": pd.to_datetime(dates, errors="coerce"), "value": pd.to_numeric(values, errors="coerce")})
    frame = frame.dropna(subset=["date", "value"]).copy()
    if frame.empty:
        return []
    frame["date"] = frame["date"].dt.normalize()
    frame["_ord"] = frame.index
    frame = frame.sort_values(["date", "_ord"], kind="mergesort")
    frame = frame.groupby("date", sort=True).tail(1)
    return [(pd.Timestamp(day), int(value)) for day, value in zip(frame["date"], frame["value"])]


def _pace(
    observations: list[tuple[pd.Timestamp, int]],
    window_days: int,
    remaining: int,
) -> tuple[float | None, pd.Timestamp | None, str]:
    if remaining == 0:
        return None, None, ""

    collapsed: list[tuple[pd.Timestamp, int]] = []
    for day, value in sorted(observations, key=lambda item: pd.Timestamp(item[0])):
        normalized = pd.Timestamp(day).normalize()
        point = (normalized, int(value))
        if collapsed and collapsed[-1][0] == normalized:
            collapsed[-1] = point
        else:
            collapsed.append(point)

    if not collapsed:
        return None, None, "log again for a date"

    end_date, end_value = collapsed[-1]
    cutoff = end_date - pd.Timedelta(days=int(window_days))
    on_or_before_cutoff = [point for point in collapsed if point[0] <= cutoff]
    if on_or_before_cutoff:
        baseline_date, baseline_value = on_or_before_cutoff[-1]
    else:
        # A second log inside the window still sets a pace. Use the oldest earlier day.
        earlier = [point for point in collapsed if point[0] < end_date]
        if not earlier:
            return None, None, "log again for a date"
        baseline_date, baseline_value = earlier[0]

    days = int((end_date - baseline_date).days)
    if days <= 0:
        return None, None, "log again for a date"
    pace = (int(end_value) - int(baseline_value)) / days
    if pace <= 0:
        return None, None, "no date"
    eta = end_date + pd.Timedelta(days=int(remaining) / pace)
    return float(pace), pd.Timestamp(eta), ""


def _account_xp(xp_history: pd.DataFrame, account: str) -> pd.DataFrame:
    columns = ["Date", "Spieler", "Lvl", "Total XP"]
    if xp_history is None or xp_history.empty or not set(columns).issubset(xp_history.columns):
        return pd.DataFrame(columns=columns)
    history = xp_history.loc[:, columns].copy()
    history["Date"] = pd.to_datetime(history["Date"], errors="coerce")
    history["Spieler"] = history["Spieler"].map(_clean_text)
    history["Lvl"] = pd.to_numeric(history["Lvl"], errors="coerce")
    history["Total XP"] = pd.to_numeric(history["Total XP"], errors="coerce")
    history = history.dropna(subset=["Date", "Spieler", "Lvl", "Total XP"]).copy()
    history = history[history["Spieler"] == account].copy()
    if history.empty:
        return pd.DataFrame(columns=columns)
    history["Lvl"] = history["Lvl"].map(int)
    history["Total XP"] = history["Total XP"].map(int)
    return history.reset_index(drop=True)


def _latest_xp_row(history: pd.DataFrame) -> pd.Series:
    ordered = history.reset_index(drop=True)
    ordered["_ord"] = ordered.index
    ordered = ordered.sort_values(["Date", "_ord"], kind="mergesort")
    return ordered.iloc[-1]


def _task_points(progress: pd.DataFrame, account: str, requirement_id: str) -> list[tuple[pd.Timestamp, int]]:
    if progress.empty:
        return []
    rows = progress[
        (progress["account"] == account) & (progress["requirement_id"] == requirement_id)
    ]
    if rows.empty:
        return []
    return _daily_points(rows["date"], rows["value"])


def _done(status: str, value: int | None, goal: int) -> bool:
    return status == "reached" or (value is not None and value >= goal)


def _scored_task(
    *,
    requirement_id: str,
    target_level: int,
    label: str,
    status: str,
    goal: int,
    sort_order: int,
    observations: list[tuple[pd.Timestamp, int]],
    window_days: int,
) -> RequirementRow:
    logged = observations[-1][1] if observations else None
    if status == "locked":
        value = None
        remaining = None
        pace = None
        eta = None
        note = ""
    elif status == "reached":
        if logged is not None and logged >= goal:
            value = int(logged)
        else:
            value = int(goal)
        remaining = int(max(0, goal - value))
        pace = None
        eta = None
        note = ""
    else:
        value = int(logged) if logged is not None else 0
        remaining = int(max(0, goal - value))
        if remaining == 0:
            pace, eta, note = None, None, ""
        else:
            pace, eta, note = _pace(observations, window_days, remaining)
    return RequirementRow(
        requirement_id=requirement_id,
        target_level=int(target_level),
        label=label,
        status=status,
        goal=int(goal),
        value=None if value is None else int(value),
        remaining=None if remaining is None else int(remaining),
        pace_per_day=None if pace is None else float(pace),
        eta=None if eta is None else pd.Timestamp(eta),
        note=note,
        done=_done(status, None if value is None else int(value), int(goal)),
        sort_order=int(sort_order),
    )


def _xp_row(
    *,
    target_level: int,
    status: str,
    goal: int | None,
    current_total: int,
    curve_totals: Mapping[int, int],
    observations: list[tuple[pd.Timestamp, int]],
    window_days: int,
) -> RequirementRow:
    xp_goal = 0 if goal is None else int(goal)
    start = _curve_total(curve_totals, target_level - 1)
    if status == "locked" or goal is None or start is None:
        return RequirementRow(
            requirement_id=XP_REQUIREMENT_ID,
            target_level=int(target_level),
            label="XP",
            status=status,
            goal=xp_goal,
            value=None,
            remaining=None,
            pace_per_day=None,
            eta=None,
            note="",
            done=_done(status, None, xp_goal),
            sort_order=0,
        )
    if status == "reached":
        value = xp_goal
        remaining = 0
        pace, eta, note = None, None, ""
    else:
        value = int(current_total - start)
        remaining = int(max(0, xp_goal - value))
        if remaining == 0:
            pace, eta, note = None, None, ""
        else:
            pace, eta, note = _pace(observations, window_days, remaining)
    return RequirementRow(
        requirement_id=XP_REQUIREMENT_ID,
        target_level=int(target_level),
        label="XP",
        status=status,
        goal=xp_goal,
        value=int(value),
        remaining=int(remaining),
        pace_per_day=None if pace is None else float(pace),
        eta=None if eta is None else pd.Timestamp(eta),
        note=note,
        done=_done(status, int(value), xp_goal),
        sort_order=0,
    )


def _finish(
    status: str,
    rows: tuple[RequirementRow, ...],
    as_of: pd.Timestamp,
) -> tuple[pd.Timestamp | None, int | None, str | None, str]:
    if status != "active":
        return None, None, None, ""
    incomplete = [row for row in rows if not row.done]
    if not incomplete:
        return None, None, None, "Requirements complete"
    waiting = sorted(
        (row for row in incomplete if row.eta is None),
        key=lambda row: (row.sort_order, row.requirement_id),
    )
    if waiting:
        labels = ", ".join(row.label for row in waiting)
        return None, None, None, f"Level date waits on {labels}."
    binding = min(
        incomplete,
        key=lambda row: (-int(pd.Timestamp(row.eta).value), row.sort_order, row.requirement_id),
    )
    finish_date = pd.Timestamp(binding.eta)
    delta_days = (finish_date - as_of).total_seconds() / 86400.0
    return finish_date, int(round(delta_days)), binding.label, ""


def _resolve_as_of(as_of: pd.Timestamp | None, latest_date: pd.Timestamp) -> pd.Timestamp:
    if as_of is not None:
        parsed = pd.Timestamp(as_of)
        if not pd.isna(parsed):
            return parsed
    if not pd.isna(latest_date):
        return pd.Timestamp(latest_date).normalize()
    return pd.Timestamp.now().normalize()


def build_level_sets(
    *,
    requirements: pd.DataFrame,
    progress: pd.DataFrame,
    xp_history: pd.DataFrame,
    curve_totals: Mapping[int, int],
    account: str,
    window_days: int,
    as_of: pd.Timestamp | None = None,
) -> list[LevelSet]:
    account_name = _clean_text(account)
    history = _account_xp(xp_history, account_name)
    if history.empty:
        return []

    latest = _latest_xp_row(history)
    current_level = int(latest["Lvl"])
    current_total = int(latest["Total XP"])
    as_of_ts = _resolve_as_of(as_of, pd.Timestamp(latest["Date"]))
    xp_points = _daily_points(history["Date"], history["Total XP"])

    catalog = _coerce_requirements(requirements) if requirements is not None else _empty_requirements()
    if catalog.empty:
        return []
    logged = _coerce_progress(progress) if progress is not None else _empty_progress()

    grouped: dict[str, list[LevelSet]] = {"reached": [], "active": [], "locked": []}
    targets = sorted({int(level) for level in catalog["target_level"].tolist()})
    for target_level in targets:
        status = set_status(current_level, target_level)
        level_reqs = catalog[catalog["target_level"] == target_level]
        rows = [
            _xp_row(
                target_level=target_level,
                status=status,
                goal=_xp_goal(curve_totals, target_level),
                current_total=current_total,
                curve_totals=curve_totals,
                observations=xp_points,
                window_days=window_days,
            )
        ]
        for requirement in level_reqs.itertuples(index=False):
            requirement_id = str(requirement.requirement_id)
            rows.append(
                _scored_task(
                    requirement_id=requirement_id,
                    target_level=target_level,
                    label=str(requirement.label),
                    status=status,
                    goal=int(requirement.goal),
                    sort_order=int(requirement.sort_order),
                    observations=_task_points(logged, account_name, requirement_id),
                    window_days=window_days,
                )
            )
        row_tuple = tuple(rows)
        finish_date, finish_days, binding_label, finish_note = _finish(status, row_tuple, as_of_ts)
        grouped[status].append(
            LevelSet(
                target_level=int(target_level),
                status=status,
                unlock_level=int(target_level - 1),
                rows=row_tuple,
                finish_date=finish_date,
                finish_days=finish_days,
                binding_label=binding_label,
                finish_note=finish_note,
            )
        )
    return grouped["reached"] + grouped["active"] + grouped["locked"]
