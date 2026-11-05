from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import MutableMapping

_IGNORED_MEDAL_IDS = {"total_xp", "platinum_medals"}
_NUMBER_RE = re.compile(r"(?<![\d.,])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\d.,])")


@dataclass
class MedalRecordingReport:
    filled: list[str] = field(default_factory=list)
    not_seen: list[str] = field(default_factory=list)
    rejected_below_last: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped_other_trainer: int = 0


def parse_medal_frame_text(text: str, medals: list[tuple[str, str]]) -> dict[str, float]:
    raw = "" if text is None else str(text)
    names = _medal_name_spans(raw, medals)
    numbers = _number_spans(raw)
    return _assign_medal_counts(names, numbers)


def merge_medal_reads(reads: list[dict[str, float]]) -> dict[str, float]:
    merged: dict[str, float] = {}
    for read in reads:
        for medal_id, value in read.items():
            merged[medal_id] = float(value)
    return merged


def apply_medal_recording_fills(
    values: Mapping[str, float],
    *,
    medal_date: date,
    account: str,
    medals: list[tuple[str, str]],
    session_state: MutableMapping[str, object],
    last_known: Mapping[str, float],
) -> MedalRecordingReport:
    filled: list[str] = []
    not_seen: list[str] = []
    rejected_below_last: list[str] = []
    warnings: list[str] = []
    for medal_id, display_name in _clean_medals(medals, skip_ignored=False):
        if medal_id not in values:
            not_seen.append(display_name)
            continue
        value = float(values[medal_id])
        last = float(last_known.get(medal_id, 0))
        if value < last:
            rejected_below_last.append(display_name)
            warnings.append(
                f"{display_name}: {value:g} is below the last saved {last:g}, so it was left unchanged."
            )
            continue
        session_state[_medal_value_key(medal_date, account, medal_id)] = _format_medal_value(value)
        filled.append(display_name)
    return MedalRecordingReport(
        filled=filled,
        not_seen=not_seen,
        rejected_below_last=rejected_below_last,
        warnings=warnings,
    )


def fill_medal_inputs_from_recording(
    video_files: list[tuple[str, bytes]],
    *,
    medal_date: date,
    account: str,
    known_accounts: list[str],
    medals: list[tuple[str, str]],
    session_state: MutableMapping[str, object],
    last_known: Mapping[str, float],
    ocr_fn: Callable[[bytes], str] | None = None,
    frame_extractor: Callable[[bytes], tuple[list[bytes], list[str]]] | None = None,
) -> MedalRecordingReport:
    if frame_extractor is None:
        from webapp.profile_recording import extract_settled_frames

        frame_extractor = extract_settled_frames
    if ocr_fn is None:
        from webapp.profile_screenshot import ocr_image_bytes

        ocr_fn = ocr_image_bytes

    extractor_warnings: list[str] = []
    reads: list[dict[str, float]] = []
    skipped_other_trainer = 0
    other_trainer_patterns = _other_trainer_patterns(account, known_accounts)
    for source_name, video_bytes in video_files:
        name = str(source_name or "recording").strip() or "recording"
        try:
            frames, frame_warnings = frame_extractor(video_bytes)
        except Exception as exc:
            extractor_warnings.append(f"{name}: {exc}")
            continue
        extractor_warnings.extend(frame_warnings)
        if not frames:
            extractor_warnings.append(f"{name}: no settled frames to read.")
        for frame_bytes in frames:
            try:
                text = ocr_fn(frame_bytes)
            except Exception as exc:
                extractor_warnings.append(f"{name}: {exc}")
                continue
            if _names_other_trainer(text, other_trainer_patterns):
                skipped_other_trainer += 1
                continue
            reads.append(parse_medal_frame_text(text, medals))

    report = apply_medal_recording_fills(
        merge_medal_reads(reads),
        medal_date=medal_date,
        account=account,
        medals=medals,
        session_state=session_state,
        last_known=last_known,
    )
    report.skipped_other_trainer = skipped_other_trainer
    report.warnings = extractor_warnings + _other_trainer_warning(skipped_other_trainer) + report.warnings
    return report


def _clean_medals(
    medals: Sequence[tuple[str, str]],
    *,
    skip_ignored: bool,
) -> list[tuple[str, str]]:
    cleaned: list[tuple[str, str]] = []
    for medal_id, display_name in medals:
        medal_key = str(medal_id).strip()
        label = str(display_name).strip()
        if not medal_key or not label:
            continue
        if skip_ignored and medal_key.casefold() in _IGNORED_MEDAL_IDS:
            continue
        cleaned.append((medal_key, label))
    return cleaned


def _medal_name_spans(text: str, medals: Sequence[tuple[str, str]]) -> list[tuple[int, int, str]]:
    ordered = [
        (index, medal_id, display_name)
        for index, (medal_id, display_name) in enumerate(_clean_medals(medals, skip_ignored=True))
    ]
    ordered.sort(key=lambda item: (-len(item[2]), item[0]))
    occupied: list[tuple[int, int, str]] = []
    for _index, medal_id, display_name in ordered:
        pattern = re.compile(rf"\b{re.escape(display_name)}\b", re.IGNORECASE)
        for match in pattern.finditer(text):
            start, end = match.span()
            if _overlaps(start, end, occupied):
                continue
            occupied.append((start, end, medal_id))
    occupied.sort(key=lambda item: item[0])
    return occupied


def _overlaps(start: int, end: int, spans: Sequence[tuple[int, int, str]]) -> bool:
    return any(start < span_end and end > span_start for span_start, span_end, _medal_id in spans)


def _number_spans(text: str) -> list[tuple[int, int, float]]:
    spans: list[tuple[int, int, float]] = []
    for match in _NUMBER_RE.finditer(text):
        spans.append((match.start(), match.end(), float(match.group(0).replace(",", ""))))
    return spans


def _assign_medal_counts(
    names: Sequence[tuple[int, int, str]],
    numbers: Sequence[tuple[int, int, float]],
) -> dict[str, float]:
    candidates: list[tuple[int, int, int, int, int, int, str, float]] = []
    for name_index, (name_start, name_end, medal_id) in enumerate(names):
        for number_index, (number_start, number_end, value) in enumerate(numbers):
            located = _locate_number(name_start, name_end, number_start, number_end)
            if located is None:
                continue
            distance, after_penalty, gap_start, gap_end = located
            if _gap_contains_other_name(gap_start, gap_end, names, name_index):
                continue
            candidates.append(
                (distance, after_penalty, name_start, number_start, name_index, number_index, medal_id, value)
            )
    candidates.sort()
    used_names: set[int] = set()
    used_numbers: set[int] = set()
    chosen: dict[str, tuple[int, float]] = {}
    for _distance, _after_penalty, name_start, _number_start, name_index, number_index, medal_id, value in candidates:
        if name_index in used_names or number_index in used_numbers:
            continue
        used_names.add(name_index)
        used_numbers.add(number_index)
        previous = chosen.get(medal_id)
        if previous is None or name_start >= previous[0]:
            chosen[medal_id] = (name_start, value)
    return {medal_id: value for medal_id, (_name_start, value) in chosen.items()}


def _locate_number(
    name_start: int,
    name_end: int,
    number_start: int,
    number_end: int,
) -> tuple[int, int, int, int] | None:
    if number_start >= name_end:
        return (number_start - name_end, 0, name_end, number_start)
    if number_end <= name_start:
        return (name_start - number_end, 1, number_end, name_start)
    return None


def _gap_contains_other_name(
    gap_start: int,
    gap_end: int,
    names: Sequence[tuple[int, int, str]],
    skip_index: int,
) -> bool:
    for index, (name_start, name_end, _medal_id) in enumerate(names):
        if index == skip_index:
            continue
        if name_start < gap_end and name_end > gap_start:
            return True
    return False


def _format_medal_value(value: float) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return str(number).replace(",", "")


def _medal_value_key(medal_date: date, account: str, medal_id: str) -> str:
    return f"medal_value_input_{medal_date.isoformat()}_{account}_{medal_id}"


def _other_trainer_patterns(account: str, known_accounts: Sequence[str]) -> list[re.Pattern[str]]:
    selected = str(account).strip().casefold()
    patterns: list[re.Pattern[str]] = []
    seen: set[str] = set()
    for raw_name in known_accounts:
        name = str(raw_name).strip()
        folded = name.casefold()
        if not name or folded == selected or folded in seen:
            continue
        seen.add(folded)
        patterns.append(re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE))
    return patterns


def _names_other_trainer(text: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    raw = "" if text is None else str(text)
    return any(pattern.search(raw) for pattern in patterns)


def _other_trainer_warning(skipped: int) -> list[str]:
    if skipped <= 0:
        return []
    if skipped == 1:
        return ["Skipped 1 frame that named another trainer."]
    return [f"Skipped {skipped} frames that named another trainer."]
