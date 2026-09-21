from __future__ import annotations

import csv
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import MutableMapping

from shared.paths import screenshot_account_aliases_path

SCREENSHOT_ACCOUNT_ALIASES = {
    "cmanthehero": "Simon",
}


@dataclass
class ProfileScreenshotParse:
    account: str | None = None
    level: int | None = None
    xp_bar: int | None = None
    xp_to_next: int | None = None
    battles_won: float | None = None
    distance_walked: float | None = None
    pokemon_caught: float | None = None
    warnings: list[str] = field(default_factory=list)
    source_name: str = ""


@dataclass
class XpScreenshotFillReport:
    filled: list[str] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    skipped_unselected: list[str] = field(default_factory=list)
    incomplete: list[str] = field(default_factory=list)
    activated: list[str] = field(default_factory=list)
    deactivated: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def xp_screenshot_widget_keys(xp_date: date, account: str) -> dict[str, str]:
    iso = xp_date.isoformat()
    return {
        "level": f"xp_level_input_{iso}_{account}",
        "xp_bar": f"xp_bar_input_{iso}_{account}",
        "battles_won": f"xp_battles_input_{iso}_{account}",
        "distance_walked": f"xp_distance_input_{iso}_{account}",
        "pokemon_caught": f"xp_caught_input_{iso}_{account}",
        "inactive": f"xp_inactive_{iso}_{account}",
    }


def apply_xp_screenshot_fills(
    parses: list[ProfileScreenshotParse],
    *,
    xp_date: date,
    selected_accounts: list[str],
    session_state: MutableMapping[str, object],
    last_known: Mapping[str, Mapping[str, object]] | None = None,
) -> XpScreenshotFillReport:
    selected = [str(name).strip() for name in selected_accounts if str(name).strip()]
    selected_set = set(selected)
    known_by_account = last_known or {}
    report = XpScreenshotFillReport()
    for parsed in parses:
        account = str(parsed.account or "").strip()
        source = parsed.source_name or account or "screenshot"
        if not account:
            report.unmatched.append(source)
            report.warnings.append(f"{source}: trainer name is not a known XP account.")
            continue
        if account not in selected_set:
            report.skipped_unselected.append(account)
            report.warnings.append(f"{account}: not in the current missing-account list.")
            continue
        missing_fields = [
            name
            for name, value in (
                ("level", parsed.level),
                ("xp_bar", parsed.xp_bar),
                ("battles_won", parsed.battles_won),
                ("distance_walked", parsed.distance_walked),
                ("pokemon_caught", parsed.pokemon_caught),
            )
            if value is None
        ]
        if missing_fields:
            report.incomplete.append(account)
            report.warnings.append(f"{account}: could not read {', '.join(missing_fields)}.")
        keys = xp_screenshot_widget_keys(xp_date, account)
        if parsed.level is not None:
            session_state[keys["level"]] = int(parsed.level)
        if parsed.xp_bar is not None:
            session_state[keys["xp_bar"]] = str(int(parsed.xp_bar))
        if parsed.battles_won is not None:
            session_state[keys["battles_won"]] = str(int(round(float(parsed.battles_won))))
        if parsed.distance_walked is not None:
            session_state[keys["distance_walked"]] = f"{float(parsed.distance_walked):.1f}"
        if parsed.pokemon_caught is not None:
            session_state[keys["pokemon_caught"]] = str(int(round(float(parsed.pokemon_caught))))
        inactive = _inactive_from_screenshot(parsed, known_by_account.get(account))
        if inactive is not None:
            session_state[keys["inactive"]] = bool(inactive)
            if inactive:
                report.deactivated.append(account)
            else:
                report.activated.append(account)
        if parsed.warnings:
            report.warnings.extend(parsed.warnings)
        report.filled.append(account)
    return report


def _inactive_from_screenshot(
    parsed: ProfileScreenshotParse,
    last_known: Mapping[str, object] | None,
) -> bool | None:
    fields = (
        ("level", parsed.level, 0),
        ("xp_bar", parsed.xp_bar, 0),
        ("battles_won", parsed.battles_won, 0),
        ("distance_walked", parsed.distance_walked, 1),
        ("pokemon_caught", parsed.pokemon_caught, 0),
    )
    if any(value is None for _name, value, _decimals in fields):
        return None
    known = last_known or {}
    for name, value, decimals in fields:
        current = round(float(value), decimals)
        previous = round(float(known.get(name, 0) or 0), decimals)
        if current != previous:
            return False
    return True


def fill_xp_inputs_from_screenshots(
    files: list[tuple[str, bytes]],
    *,
    xp_date: date,
    selected_accounts: list[str],
    known_accounts: list[str],
    session_state: MutableMapping[str, object],
    ocr_fn: Callable[[bytes], str] | None = None,
    last_known: Mapping[str, Mapping[str, object]] | None = None,
) -> XpScreenshotFillReport:
    parses: list[ProfileScreenshotParse] = []
    ocr_warnings: list[str] = []
    for source_name, image_bytes in files:
        name = str(source_name or "screenshot").strip() or "screenshot"
        try:
            parses.append(
                parse_profile_screenshot(
                    image_bytes,
                    known_accounts=known_accounts,
                    source_name=name,
                    ocr_fn=ocr_fn,
                )
            )
        except Exception as exc:
            ocr_warnings.append(f"{name}: {exc}")
    report = apply_xp_screenshot_fills(
        parses,
        xp_date=xp_date,
        selected_accounts=selected_accounts,
        session_state=session_state,
        last_known=last_known,
    )
    report.warnings = ocr_warnings + report.warnings
    return report


def parse_profile_screenshot(
    image_bytes: bytes,
    *,
    known_accounts: list[str] | None = None,
    source_name: str = "",
    ocr_fn: Callable[[bytes], str] | None = None,
) -> ProfileScreenshotParse:
    reader = ocr_fn or ocr_image_bytes
    text = reader(image_bytes)
    return parse_profile_ocr_text(
        text,
        known_accounts=known_accounts,
        source_name=source_name,
    )


_OCR_ENGINE = None


def ocr_image_bytes(image_bytes: bytes) -> str:
    image = _load_rgb_image(image_bytes)
    engine = _get_ocr_engine()
    result, _elapse = engine(image)
    if not result:
        return ""
    rows: list[tuple[float, float, str]] = []
    for item in result:
        if not item or len(item) < 2:
            continue
        box, text = item[0], str(item[1]).strip()
        if not text:
            continue
        ys = [float(point[1]) for point in box]
        xs = [float(point[0]) for point in box]
        rows.append((min(ys), min(xs), text))
    rows.sort()
    return "\n".join(text for _y, _x, text in rows)


def _load_rgb_image(image_bytes: bytes):
    from io import BytesIO

    import numpy as np
    from PIL import Image

    image = Image.open(BytesIO(image_bytes))
    if image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")
    return np.array(image)


def _get_ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is not None:
        return _OCR_ENGINE
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise RuntimeError(
            "Screenshot OCR needs rapidocr-onnxruntime. "
            "Install it with: pip install -r requirements-localhost.txt"
        ) from exc
    _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def load_screenshot_account_aliases(path: Path | None = None) -> dict[str, str]:
    mapping = {key.lower(): value for key, value in SCREENSHOT_ACCOUNT_ALIASES.items()}
    target = path or screenshot_account_aliases_path()
    if not target.is_file():
        return mapping
    with target.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            alias = str(row.get("alias") or "").strip()
            account = str(row.get("account") or "").strip()
            if alias and account:
                mapping[alias.lower()] = account
    return mapping


def parse_profile_ocr_text(
    text: str,
    *,
    known_accounts: list[str] | None = None,
    account_aliases: Mapping[str, str] | None = None,
    source_name: str = "",
) -> ProfileScreenshotParse:
    raw = str(text or "")
    parsed = ProfileScreenshotParse(source_name=source_name)
    parsed.account = _match_known_account(
        raw,
        known_accounts or [],
        aliases=account_aliases if account_aliases is not None else load_screenshot_account_aliases(),
    )
    parsed.level = _parse_level(raw)
    parsed.xp_bar, parsed.xp_to_next = _parse_xp_pair(raw)
    activity = _parse_activity_metrics(raw)
    parsed.battles_won = activity["battles_won"]
    parsed.distance_walked = activity["distance_walked"]
    parsed.pokemon_caught = activity["pokemon_caught"]
    return parsed


def _match_known_account(
    text: str,
    known_accounts: list[str],
    aliases: Mapping[str, str] | None = None,
) -> str | None:
    known_set = {str(name).strip() for name in known_accounts if str(name).strip()}
    if not known_set:
        return None
    candidates: dict[str, str] = {name: name for name in known_set}
    for alias, canonical in (aliases or {}).items():
        alias_name = str(alias).strip()
        account = str(canonical).strip()
        if alias_name and account in known_set:
            candidates[alias_name] = account
    ranked = sorted(candidates, key=len, reverse=True)
    for search_name in ranked:
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(search_name)}(?![A-Za-z])", text, flags=re.IGNORECASE):
            return candidates[search_name]
    return _fuzzy_match_account(text, sorted(known_set, key=len, reverse=True))


def _fuzzy_match_account(text: str, known_accounts: list[str]) -> str | None:
    from difflib import SequenceMatcher

    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_]{3,}", text.split("TOTAL")[0] if "TOTAL" in text.upper() else text[:400])
    best_name = None
    best_ratio = 0.0
    for account in known_accounts:
        if len(account) < 5:
            continue
        for token in tokens:
            if abs(len(token) - len(account)) > 2:
                continue
            ratio = SequenceMatcher(None, token.lower(), account.lower()).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_name = account
    if best_name is not None and best_ratio >= 0.82:
        return best_name
    return None


def _parse_level(text: str) -> int | None:
    stripped = re.sub(
        r"[0-9][0-9,\. ]{2,}/\s*[0-9][0-9,\. ]{2,}",
        " ",
        text,
    )
    standalone = r"(?<![\d,])(\d{1,2})(?![\d,])"
    matches = list(re.finditer(rf"{standalone}\s+\blevel\b", stripped, flags=re.IGNORECASE))
    if matches:
        value = int(matches[-1].group(1))
        if 1 <= value <= 80:
            return value
    match = re.search(rf"\blevel\b\s+{standalone}", stripped, flags=re.IGNORECASE)
    if match:
        value = int(match.group(1))
        if 1 <= value <= 80:
            return value
    return None


def _parse_xp_pair(text: str) -> tuple[int | None, int | None]:
    match = re.search(
        r"([0-9][0-9,\.]{2,})\s*/\s*([0-9][0-9,\.]{2,})",
        text,
    )
    if not match:
        return None, None
    left = _parse_int_us(match.group(1))
    right = _parse_int_us(match.group(2))
    return left, right


_NUM_RE = r"[0-9][0-9,\.]*"
_BATTLES_RE = re.compile(r"battles\s*won", re.IGNORECASE)
_DISTANCE_RE = re.compile(r"distance\s*walk\w*", re.IGNORECASE)
_CAUGHT_RE = re.compile(r"pok[eéè]?\s*mon.{0,16}caugh\w*|caugh[ti]\w*", re.IGNORECASE | re.DOTALL)


def _parse_activity_metrics(text: str) -> dict[str, float | None]:
    section = text
    total = re.search(r"total\s*activity", text, flags=re.IGNORECASE)
    if total:
        section = text[total.end() :]
    section = re.sub(r"[0-9][0-9,\. ]{2,}/\s*[0-9][0-9,\. ]{2,}", " ", section)
    tokens = _activity_tokens(section)
    assigned: dict[str, float | None] = {
        "battles_won": None,
        "distance_walked": None,
        "pokemon_caught": None,
    }
    used: set[int] = set()
    label_indexes = {kind: [] for kind in assigned}
    for idx, token in enumerate(tokens):
        if token[0] == "label":
            label_indexes[str(token[1])].append(idx)

    def adjacent(idx: int) -> list[int]:
        found: list[int] = []
        for neighbor in (idx + 1, idx - 1):
            if 0 <= neighbor < len(tokens) and tokens[neighbor][0] == "num" and neighbor not in used:
                found.append(neighbor)
        return found

    def assign(kind: str, idx: int) -> None:
        if assigned[kind] is not None or idx in used:
            return
        assigned[kind] = float(tokens[idx][1])
        used.add(idx)

    for idx in label_indexes["distance_walked"]:
        decimals = [i for i in adjacent(idx) if _is_one_decimal(float(tokens[i][1]))]
        if decimals:
            assign("distance_walked", decimals[0])
    for idx in label_indexes["battles_won"]:
        ints = [i for i in adjacent(idx) if not _is_one_decimal(float(tokens[i][1]))]
        if ints:
            assign("battles_won", ints[0])
    for idx in label_indexes["pokemon_caught"]:
        ints = [i for i in adjacent(idx) if not _is_one_decimal(float(tokens[i][1]))]
        if ints:
            assign("pokemon_caught", ints[0])
    for idx in label_indexes["distance_walked"]:
        if assigned["distance_walked"] is None:
            nearby = adjacent(idx)
            if nearby:
                assign("distance_walked", nearby[0])
    unused_nums = [i for i, token in enumerate(tokens) if token[0] == "num" and i not in used]
    if assigned["distance_walked"] is None:
        for idx in unused_nums:
            if _is_one_decimal(float(tokens[idx][1])):
                assign("distance_walked", idx)
                break
    unused_nums = [i for i, token in enumerate(tokens) if token[0] == "num" and i not in used]
    for kind in ("battles_won", "pokemon_caught", "distance_walked"):
        if assigned[kind] is None and unused_nums:
            assign(kind, unused_nums.pop(0))
    return assigned


def _activity_tokens(section: str) -> list[tuple[str, object]]:
    matches: list[tuple[int, int, str, object]] = []
    for match in re.finditer(_NUM_RE, section):
        value = _parse_float_us(match.group(0))
        if value is None:
            continue
        matches.append((match.start(), match.end(), "num", value))
    for kind, pattern in (
        ("battles_won", _BATTLES_RE),
        ("distance_walked", _DISTANCE_RE),
        ("pokemon_caught", _CAUGHT_RE),
    ):
        for match in pattern.finditer(section):
            matches.append((match.start(), match.end(), "label", kind))
    matches.sort(key=lambda item: (item[0], item[1]))
    return [(kind, value) for _start, _end, kind, value in matches]


def _is_one_decimal(value: float) -> bool:
    return abs(value - round(value, 1)) < 1e-9 and abs(value - round(value)) > 0.05


def _parse_int_us(raw: str) -> int | None:
    value = _parse_float_us(raw)
    if value is None:
        return None
    return int(round(value))


def _parse_float_us(raw: str) -> float | None:
    s = str(raw).strip().replace(" ", "")
    if not s:
        return None
    if re.fullmatch(r"\d{1,3}\.\d{3}", s):
        s = s.replace(".", "")
    elif "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) > 1 and all(part.isdigit() for part in parts[1:]) and all(len(part) == 3 for part in parts[1:]):
            s = s.replace(",", "")
        elif s.count(",") == 1 and len(parts[1]) != 3:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None
