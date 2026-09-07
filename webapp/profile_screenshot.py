from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import MutableMapping


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


def parse_profile_ocr_text(
    text: str,
    *,
    known_accounts: list[str] | None = None,
    source_name: str = "",
) -> ProfileScreenshotParse:
    raw = str(text or "")
    parsed = ProfileScreenshotParse(source_name=source_name)
    parsed.account = _match_known_account(raw, known_accounts or [])
    parsed.level = _parse_level(raw)
    parsed.xp_bar, parsed.xp_to_next = _parse_xp_pair(raw)
    parsed.battles_won = _parse_labeled_number(raw, r"battles\s*won")
    parsed.distance_walked = _parse_labeled_number(raw, r"distance\s*walked")
    parsed.pokemon_caught = _parse_labeled_number(raw, r"pok[eé]mon\s*caught")
    return parsed


def _match_known_account(text: str, known_accounts: list[str]) -> str | None:
    if not known_accounts:
        return None
    lower = text.lower()
    ranked = sorted(known_accounts, key=lambda name: len(str(name).strip()), reverse=True)
    for name in ranked:
        account = str(name).strip()
        if not account:
            continue
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(account)}(?![A-Za-z0-9])", text, flags=re.IGNORECASE):
            return account
        if account.lower() in lower:
            return account
    return None


def _parse_level(text: str) -> int | None:
    standalone = r"(?<![\d,])(\d{1,2})(?![\d,])"
    match = re.search(rf"\blevel\b\s+{standalone}", text, flags=re.IGNORECASE)
    if match:
        value = int(match.group(1))
        if 1 <= value <= 80:
            return value
    match = re.search(rf"{standalone}\s+\blevel\b", text, flags=re.IGNORECASE)
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


def _parse_labeled_number(text: str, label_pattern: str) -> float | None:
    match = re.search(
        rf"{label_pattern}\s*[^\d]{{0,40}}([0-9][0-9,\.]*)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    return _parse_float_us(match.group(1))


def _parse_int_us(raw: str) -> int | None:
    value = _parse_float_us(raw)
    if value is None:
        return None
    return int(round(value))


def _parse_float_us(raw: str) -> float | None:
    s = str(raw).strip().replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
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
