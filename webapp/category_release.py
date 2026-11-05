from __future__ import annotations

import csv
from collections import deque
from pathlib import Path

import pandas as pd

from webapp.data_files import (
    load_pokedex_category_availability,
    load_pokemon_evolutions,
    parse_bool_text,
)

MANUAL_CATEGORY_COLUMNS = ["entry_type", "dex_number", "form", "available", "notes"]
EFFECTIVE_CATEGORY_COLUMNS = [
    "entry_type",
    "dex_number",
    "form",
    "available",
    "notes",
    "release_source",
    "release_detail",
    "seed_available",
]
_DIRECT_SHADOW_SOURCES = {"seed", "override"}


def _text(value: object) -> str:
    if value is None or isinstance(value, str):
        return "" if value is None else value.strip()
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return parse_bool_text(value)
    if value is None:
        return False
    try:
        if bool(pd.isna(value)):
            return False
    except (TypeError, ValueError):
        return parse_bool_text(value)
    return parse_bool_text(value)


def _is_bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return True
    value_type = type(value)
    return value_type.__module__ == "numpy" and value_type.__name__ in {"bool", "bool_"}


def _positive_dex(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    number = pd.to_numeric(value, errors="coerce")
    try:
        if bool(pd.isna(number)):
            return None
    except (TypeError, ValueError):
        return None
    numeric = float(number)
    if numeric <= 0 or not numeric.is_integer():
        return None
    return int(numeric)


def _empty_manual() -> pd.DataFrame:
    return pd.DataFrame(columns=MANUAL_CATEGORY_COLUMNS)


def _empty_effective() -> pd.DataFrame:
    return pd.DataFrame(columns=EFFECTIVE_CATEGORY_COLUMNS)


def _dex_set(values: set[int] | None) -> set[int] | None:
    if values is None:
        return None
    cleaned: set[int] = set()
    for value in values:
        dex = _positive_dex(value)
        if dex is not None:
            cleaned.add(dex)
    return cleaned


def _name_map(names: dict[int, str] | None) -> dict[int, str]:
    if not names:
        return {}
    cleaned: dict[int, str] = {}
    for key, value in names.items():
        dex = _positive_dex(key)
        text = _text(value)
        if dex is None or not text:
            continue
        cleaned[dex] = text
    return cleaned


def _ancestor_label(dex: int, names: dict[int, str]) -> str:
    return names.get(dex) or f"#{dex:04d}"


def _release_edit(
    entry_type: str,
    dex: int,
    form: str,
    available: bool | None,
    notes: str = "",
) -> dict[str, object]:
    return {
        "entry_type": entry_type,
        "dex_number": dex,
        "form": form,
        "available": available,
        "notes": notes,
    }


def load_manual_category_availability(path: Path) -> pd.DataFrame:
    if not path.exists() or not path.is_file():
        return _empty_manual()
    try:
        frame = pd.read_csv(path, encoding="utf-8-sig")
    except (OSError, UnicodeError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return _empty_manual()
    if frame.empty or not {"entry_type", "dex_number"}.issubset(frame.columns):
        return _empty_manual()

    has_form = "form" in frame.columns
    has_notes = "notes" in frame.columns
    has_available = "available" in frame.columns
    stored: dict[tuple[str, int, str], dict[str, object]] = {}
    for record in frame.to_dict(orient="records"):
        entry_type = _text(record.get("entry_type")).lower()
        dex = _positive_dex(record.get("dex_number"))
        if not entry_type or dex is None:
            continue
        form = _text(record.get("form")) if has_form else ""
        available = _as_bool(record.get("available")) if has_available else False
        notes = _text(record.get("notes")) if has_notes else ""
        stored[(entry_type, dex, form.casefold())] = {
            "entry_type": entry_type,
            "dex_number": dex,
            "form": form,
            "available": available,
            "notes": notes,
        }
    return _manual_frame(list(stored.values()))


def _manual_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=MANUAL_CATEGORY_COLUMNS)
    if frame.empty:
        return _empty_manual()
    frame["entry_type"] = frame["entry_type"].astype(str)
    frame["dex_number"] = frame["dex_number"].astype(int)
    frame["form"] = frame["form"].fillna("").astype(str)
    frame["available"] = frame["available"].astype(bool)
    frame["notes"] = frame["notes"].fillna("").astype(str)
    return frame.sort_values(["entry_type", "dex_number", "form"]).reset_index(drop=True)


def save_manual_category_availability(path: Path, edits: list[dict[str, object]]) -> int:
    existing = load_manual_category_availability(path)
    stored: dict[tuple[str, int, str], tuple[str, bool, str]] = {}
    for record in existing.to_dict(orient="records"):
        entry_type = _text(record.get("entry_type")).lower()
        dex = _positive_dex(record.get("dex_number"))
        if not entry_type or dex is None:
            continue
        form = _text(record.get("form"))
        stored[(entry_type, dex, form.casefold())] = (
            form,
            _as_bool(record.get("available")),
            _text(record.get("notes")),
        )

    for edit in edits:
        entry_type = _text(edit.get("entry_type")).lower()
        dex = _positive_dex(edit.get("dex_number"))
        if not entry_type or dex is None or "available" not in edit:
            continue
        choice = edit.get("available")
        form = _text(edit.get("form")) if "form" in edit else ""
        key = (entry_type, dex, form.casefold())
        if choice is None:
            stored.pop(key, None)
            continue
        if not _is_bool_value(choice):
            continue
        if "notes" in edit:
            notes = _text(edit.get("notes"))
        elif key in stored:
            notes = stored[key][2]
        else:
            notes = ""
        stored[key] = (form, bool(choice), notes)

    rows = [
        {
            "entry_type": entry_type,
            "dex_number": dex,
            "form": form,
            "available": "true" if available else "false",
            "notes": notes,
        }
        for (entry_type, dex, _form_key), (form, available, notes) in stored.items()
    ]
    out = pd.DataFrame(rows, columns=MANUAL_CATEGORY_COLUMNS)
    if not out.empty:
        out = out.sort_values(["entry_type", "dex_number", "form"]).reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
    return int(len(out))


def blank_kind_release_edit(
    entry_type: str,
    dex: int,
    *,
    form: str = "",
    want_released: bool,
    seed_available: bool,
) -> dict[str, object]:
    if want_released == seed_available:
        return _release_edit(entry_type, dex, form, None)
    return _release_edit(entry_type, dex, form, bool(want_released))


def mega_release_edits(dex: int, want_released: bool, effective: pd.DataFrame) -> list[dict[str, object]]:
    dex_number = _positive_dex(dex)
    if dex_number is None:
        return []
    rows = _mega_rows(effective, dex_number)
    if not want_released:
        if not rows:
            return []
        edits: list[dict[str, object]] = []
        for row in rows:
            if row["release_source"] == "evolution":
                continue
            if row["seed_available"]:
                edits.append(_release_edit("mega", dex_number, str(row["form"]), False))
            elif row["release_source"] == "override":
                edits.append(_release_edit("mega", dex_number, str(row["form"]), None))
        return edits
    if any(bool(row["available"]) for row in rows):
        return [
            _release_edit("mega", dex_number, str(row["form"]), None)
            for row in rows
            if row["release_source"] == "override" and not row["available"]
        ]
    return [_release_edit("mega", dex_number, "Normal", True)]


def _mega_rows(effective: pd.DataFrame, dex: int) -> list[dict[str, object]]:
    if effective is None or effective.empty or "entry_type" not in effective.columns:
        return []
    has_form = "form" in effective.columns
    has_available = "available" in effective.columns
    has_seed = "seed_available" in effective.columns
    has_source = "release_source" in effective.columns
    rows: list[dict[str, object]] = []
    for record in effective.to_dict(orient="records"):
        if _text(record.get("entry_type")).lower() != "mega":
            continue
        row_dex = _positive_dex(record.get("dex_number"))
        if row_dex != dex:
            continue
        form = _text(record.get("form")) if has_form else ""
        available = _as_bool(record.get("available")) if has_available else False
        source = _text(record.get("release_source")).lower() if has_source else ""
        if has_seed:
            seed_available = _as_bool(record.get("seed_available"))
        else:
            seed_available = source == "seed" and available
        rows.append(
            {
                "form": form,
                "available": available,
                "seed_available": seed_available,
                "release_source": source,
            }
        )
    return rows


def effective_category_availability(
    availability: pd.DataFrame | None,
    overrides: pd.DataFrame | None = None,
    evolutions: pd.DataFrame | None = None,
    in_go: set[int] | None = None,
    names: dict[int, str] | None = None,
) -> pd.DataFrame:
    rows = _normalize_effective_rows(availability)
    rows = _apply_overrides(rows, _normalize_override_rows(overrides))
    rows = _with_shadow_evolutions(rows, evolutions, in_go, names)
    rows = _with_purified(rows)
    return _finish(rows)


def load_effective_category_availability(
    availability_path: Path,
    override_path: Path,
    evolutions_path: Path,
    *,
    in_go: set[int] | None = None,
    names: dict[int, str] | None = None,
    valid_entry_types: set[str] | None = None,
) -> pd.DataFrame:
    return effective_category_availability(
        load_pokedex_category_availability(availability_path, valid_entry_types=valid_entry_types),
        load_manual_category_availability(override_path),
        load_pokemon_evolutions(evolutions_path),
        in_go=in_go,
        names=names,
    )


def _normalize_effective_rows(frame: pd.DataFrame | None) -> list[dict[str, object]]:
    if frame is None or frame.empty:
        return []
    has_form = "form" in frame.columns
    has_notes = "notes" in frame.columns
    has_source = "release_source" in frame.columns
    has_detail = "release_detail" in frame.columns
    has_seed = "seed_available" in frame.columns
    stored: dict[tuple[str, int, str], dict[str, object]] = {}
    for record in frame.to_dict(orient="records"):
        entry_type = _text(record.get("entry_type")).lower()
        dex = _positive_dex(record.get("dex_number"))
        if not entry_type or dex is None:
            continue
        form = _text(record.get("form")) if has_form else ""
        available = _as_bool(record.get("available"))
        notes = _text(record.get("notes")) if has_notes else ""
        if has_source:
            source = _text(record.get("release_source")).lower() or "seed"
        else:
            source = "seed"
        detail = _text(record.get("release_detail")) if has_detail else ""
        if has_seed:
            seed_available = _as_bool(record.get("seed_available"))
        elif has_source:
            seed_available = source == "seed" and available
        else:
            seed_available = available
        stored[(entry_type, dex, form.casefold())] = {
            "entry_type": entry_type,
            "dex_number": dex,
            "form": form,
            "available": available,
            "notes": notes,
            "release_source": source,
            "release_detail": detail,
            "seed_available": seed_available,
        }
    return list(stored.values())


def _normalize_override_rows(frame: pd.DataFrame | None) -> list[dict[str, object]]:
    if frame is None or frame.empty or "available" not in frame.columns:
        return []
    if not {"entry_type", "dex_number"}.issubset(frame.columns):
        return []
    has_form = "form" in frame.columns
    has_notes = "notes" in frame.columns
    stored: dict[tuple[str, int, str], dict[str, object]] = {}
    for record in frame.to_dict(orient="records"):
        entry_type = _text(record.get("entry_type")).lower()
        dex = _positive_dex(record.get("dex_number"))
        if not entry_type or dex is None:
            continue
        form = _text(record.get("form")) if has_form else ""
        stored[(entry_type, dex, form.casefold())] = {
            "entry_type": entry_type,
            "dex_number": dex,
            "form": form,
            "available": _as_bool(record.get("available")),
            "notes": _text(record.get("notes")) if has_notes else "",
        }
    return list(stored.values())


def _apply_overrides(
    rows: list[dict[str, object]],
    overrides: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not overrides:
        return rows
    stored: dict[tuple[str, int, str], dict[str, object]] = {
        (str(row["entry_type"]), int(row["dex_number"]), str(row["form"]).casefold()): row for row in rows
    }
    for override in overrides:
        key = (str(override["entry_type"]), int(override["dex_number"]), str(override["form"]).casefold())
        notes = str(override["notes"])
        existing = stored.get(key)
        if existing is None:
            stored[key] = {
                "entry_type": override["entry_type"],
                "dex_number": override["dex_number"],
                "form": override["form"],
                "available": bool(override["available"]),
                "notes": notes,
                "release_source": "override",
                "release_detail": "",
                "seed_available": False,
            }
            continue
        existing["available"] = bool(override["available"])
        existing["release_source"] = "override"
        existing["release_detail"] = ""
        if notes:
            existing["notes"] = notes
    return list(stored.values())


def _evolution_children(evolutions: pd.DataFrame | None, in_go: set[int] | None) -> dict[int, set[int]]:
    children: dict[int, set[int]] = {}
    if evolutions is None or evolutions.empty:
        return children
    if not {"source_dex_number", "target_dex_number"}.issubset(evolutions.columns):
        return children
    allowed = _dex_set(in_go)
    for record in evolutions.to_dict(orient="records"):
        source = _positive_dex(record.get("source_dex_number"))
        target = _positive_dex(record.get("target_dex_number"))
        if source is None or target is None or source == target:
            continue
        if allowed is not None and (source not in allowed or target not in allowed):
            continue
        children.setdefault(source, set()).add(target)
    return children


def _nearest_shadow_ancestors(direct: set[int], children: dict[int, set[int]]) -> dict[int, int]:
    best: dict[int, tuple[int, int]] = {}
    queue: deque[tuple[int, int, int]] = deque((ancestor, 0, ancestor) for ancestor in sorted(direct))
    while queue:
        current, hops, ancestor = queue.popleft()
        if current not in direct and best.get(current) != (hops, ancestor):
            continue
        for target in children.get(current, ()):
            if target in direct:
                continue
            candidate = (hops + 1, ancestor)
            known = best.get(target)
            if known is not None and candidate >= known:
                continue
            best[target] = candidate
            queue.append((target, candidate[0], candidate[1]))
    return {dex: ancestor for dex, (_hops, ancestor) in best.items()}


def _with_shadow_evolutions(
    rows: list[dict[str, object]],
    evolutions: pd.DataFrame | None,
    in_go: set[int] | None,
    names: dict[int, str] | None,
) -> list[dict[str, object]]:
    if not any(row["entry_type"] == "shadow" for row in rows):
        return rows
    direct = {
        int(row["dex_number"])
        for row in rows
        if row["entry_type"] == "shadow" and row["available"] and row["release_source"] in _DIRECT_SHADOW_SOURCES
    }
    kept = [row for row in rows if not (row["entry_type"] == "shadow" and row["release_source"] == "evolution")]
    ancestors = _nearest_shadow_ancestors(direct, _evolution_children(evolutions, in_go))
    labels = _name_map(names)
    filtered: list[dict[str, object]] = []
    for row in kept:
        dex = int(row["dex_number"])
        if row["entry_type"] == "shadow" and dex in ancestors:
            source = str(row["release_source"])
            if row["available"] and source in _DIRECT_SHADOW_SOURCES:
                filtered.append(row)
                continue
            if source == "override" and not row["available"]:
                continue
            if row["form"] == "":
                continue
        filtered.append(row)
    occupied = {
        int(row["dex_number"])
        for row in filtered
        if row["entry_type"] == "shadow" and row["form"] == ""
    }
    for dex in sorted(ancestors):
        if dex in occupied:
            continue
        ancestor = ancestors[dex]
        filtered.append(
            {
                "entry_type": "shadow",
                "dex_number": dex,
                "form": "",
                "available": True,
                "notes": "",
                "release_source": "evolution",
                "release_detail": _ancestor_label(ancestor, labels),
                "seed_available": False,
            }
        )
    return filtered


def _with_purified(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    shadow_rows = [row for row in rows if row["entry_type"] == "shadow"]
    if not shadow_rows:
        return rows
    released = sorted({int(row["dex_number"]) for row in shadow_rows if row["available"]})
    kept = [row for row in rows if row["entry_type"] != "purified"]
    for dex in released:
        kept.append(
            {
                "entry_type": "purified",
                "dex_number": dex,
                "form": "",
                "available": True,
                "notes": "",
                "release_source": "seed",
                "release_detail": "",
                "seed_available": False,
            }
        )
    return kept


def _finish(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=EFFECTIVE_CATEGORY_COLUMNS)
    if frame.empty:
        return _empty_effective()
    frame["entry_type"] = frame["entry_type"].astype(str)
    frame["dex_number"] = frame["dex_number"].astype(int)
    frame["form"] = frame["form"].fillna("").astype(str)
    frame["available"] = frame["available"].astype(bool)
    frame["notes"] = frame["notes"].fillna("").astype(str)
    frame["release_source"] = frame["release_source"].fillna("").astype(str)
    frame["release_detail"] = frame["release_detail"].fillna("").astype(str)
    frame["seed_available"] = frame["seed_available"].astype(bool)
    frame["_form_key"] = frame["form"].str.casefold()
    frame = frame.drop_duplicates(subset=["entry_type", "dex_number", "_form_key"], keep="last")
    frame = frame.drop(columns=["_form_key"])
    return frame.sort_values(["entry_type", "dex_number", "form"]).reset_index(drop=True)
