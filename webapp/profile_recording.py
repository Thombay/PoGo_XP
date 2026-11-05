from __future__ import annotations

import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import MutableMapping

from webapp.profile_screenshot import (
    ProfileScreenshotParse,
    XpScreenshotFillReport,
    apply_xp_screenshot_fills,
    fill_xp_inputs_from_screenshots,
    parse_profile_screenshot,
)

_PRESENT_FIELDS = ("level", "battles_won", "distance_walked", "pokemon_caught")


def select_settled_frame_indexes(
    frames: Sequence[object],
    *,
    settle_mad: float = 12.0,
    duplicate_mad: float = 2.0,
) -> list[int]:
    settled: list[int] = []
    for index in range(1, len(frames)):
        if _mean_absolute_difference(frames[index], frames[index - 1]) <= settle_mad:
            settled.append(index)
    kept: list[int] = []
    for index in settled:
        if not kept or _mean_absolute_difference(frames[index], frames[kept[-1]]) > duplicate_mad:
            kept.append(index)
    return kept


def extract_settled_frames(video_bytes: bytes, *, max_frames: int = 400) -> tuple[list[bytes], list[str]]:
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise RuntimeError(
            "Recording frame extraction needs imageio-ffmpeg. "
            "Install it with: pip install -r requirements-localhost.txt"
        ) from exc

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    warnings: list[str] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        directory = Path(temp_dir)
        (directory / "recording.mp4").write_bytes(video_bytes)
        command = [
            ffmpeg,
            "-y",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "recording.mp4",
            "-vf",
            "fps=2",
            "-q:v",
            "3",
            "frame_%05d.jpg",
        ]
        run_kwargs: dict[str, object] = {}
        if sys.platform == "win32":
            run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(
            command,
            cwd=temp_dir,
            capture_output=True,
            check=False,
            **run_kwargs,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"ffmpeg failed ({result.returncode}): {stderr}")
        encoded: list[bytes] = []
        arrays: list[object] = []
        for frame_path in sorted(directory.glob("frame_*.jpg")):
            encoded.append(frame_path.read_bytes())
            arrays.append(_load_frame_array(frame_path))
        indexes = select_settled_frame_indexes(arrays)
        if len(indexes) > max_frames:
            indexes = indexes[:max_frames]
            warnings.append(f"Recording was truncated to {max_frames} settled frames.")
        kept = [encoded[index] for index in indexes]
    return kept, warnings


@dataclass
class VisitMergeResult:
    parses: list[ProfileScreenshotParse]
    warnings: list[str]
    multi_frame: list[str]


def merge_profile_visits(
    parses: list[ProfileScreenshotParse],
    *,
    xp_to_next_by_level: Mapping[int, int] | None = None,
) -> VisitMergeResult:
    order: list[str] = []
    frames_by_account: dict[str, list[ProfileScreenshotParse]] = {}
    current: str | None = None
    warnings: list[str] = []
    ignored_leading = False
    for parsed in parses:
        if _is_header(parsed):
            current = _account_name(parsed)
            if current not in frames_by_account:
                frames_by_account[current] = []
                order.append(current)
            frames_by_account[current].append(parsed)
            continue
        if current is None:
            if not ignored_leading:
                warnings.append("Activity before a trainer header was ignored.")
                ignored_leading = True
            continue
        frames_by_account[current].append(parsed)

    merged: list[ProfileScreenshotParse] = []
    multi_frame: list[str] = []
    for account in order:
        visit_frames = frames_by_account[account]
        merged_parse, xp_warnings = _merge_visit_frames(account, visit_frames, xp_to_next_by_level)
        merged.append(merged_parse)
        warnings.extend(xp_warnings)
        if len(visit_frames) > 1:
            multi_frame.append(account)
    return VisitMergeResult(parses=merged, warnings=warnings, multi_frame=multi_frame)


def combine_screenshot_and_recording_parses(
    screenshot_parses: list[ProfileScreenshotParse],
    recording_parses: list[ProfileScreenshotParse],
) -> list[ProfileScreenshotParse]:
    folded: list[ProfileScreenshotParse] = []
    index_by_account: dict[str, int] = {}
    for parsed in screenshot_parses:
        account = _account_name(parsed)
        if not account:
            folded.append(_clone_parse(parsed))
            continue
        if account in index_by_account:
            folded[index_by_account[account]] = _clone_parse(parsed)
        else:
            index_by_account[account] = len(folded)
            folded.append(_clone_parse(parsed))
    for parsed in recording_parses:
        account = _account_name(parsed)
        if not account or account not in index_by_account:
            clone = _clone_parse(parsed)
            if account:
                index_by_account[account] = len(folded)
            folded.append(clone)
            continue
        _overlay_present_fields(folded[index_by_account[account]], parsed)
    return folded


def fill_xp_inputs_from_screenshots_and_recordings(
    screenshots: list[tuple[str, bytes]],
    recordings: list[tuple[str, bytes]],
    *,
    xp_date: date,
    selected_accounts: list[str],
    known_accounts: list[str],
    session_state: MutableMapping[str, object],
    ocr_fn: Callable[[bytes], str] | None = None,
    last_known: Mapping[str, Mapping[str, object]] | None = None,
    xp_to_next_by_level: Mapping[int, int] | None = None,
    frame_extractor: Callable[[bytes], tuple[list[bytes], list[str]]] | None = None,
) -> XpScreenshotFillReport:
    if not recordings:
        return fill_xp_inputs_from_screenshots(
            screenshots,
            xp_date=xp_date,
            selected_accounts=selected_accounts,
            known_accounts=known_accounts,
            session_state=session_state,
            ocr_fn=ocr_fn,
            last_known=last_known,
            xp_to_next_by_level=xp_to_next_by_level,
        )

    extractor = frame_extractor or extract_settled_frames
    screenshot_parses: list[ProfileScreenshotParse] = []
    extractor_warnings: list[str] = []
    ocr_warnings: list[str] = []
    merge_warnings: list[str] = []
    recording_parses: list[ProfileScreenshotParse] = []
    multi_frame: list[str] = []

    for source_name, image_bytes in screenshots:
        name = str(source_name or "screenshot").strip() or "screenshot"
        try:
            screenshot_parses.append(
                parse_profile_screenshot(
                    image_bytes,
                    known_accounts=known_accounts,
                    source_name=name,
                    ocr_fn=ocr_fn,
                )
            )
        except Exception as exc:
            ocr_warnings.append(f"{name}: {exc}")

    for source_name, video_bytes in recordings:
        name = str(source_name or "recording").strip() or "recording"
        try:
            frames, frame_warnings = extractor(video_bytes)
        except Exception as exc:
            extractor_warnings.append(f"{name}: {exc}")
            continue
        extractor_warnings.extend(f"{name}: {warning}" for warning in frame_warnings)
        if not frames:
            extractor_warnings.append(f"{name}: no settled frames to read.")
        frame_parses: list[ProfileScreenshotParse] = []
        for index, frame_bytes in enumerate(frames, start=1):
            frame_name = f"{name} frame {index}"
            try:
                frame_parses.append(
                    parse_profile_screenshot(
                        frame_bytes,
                        known_accounts=known_accounts,
                        source_name=frame_name,
                        ocr_fn=ocr_fn,
                    )
                )
            except Exception as exc:
                ocr_warnings.append(f"{frame_name}: {exc}")
        merged = merge_profile_visits(frame_parses, xp_to_next_by_level=xp_to_next_by_level)
        recording_parses.extend(merged.parses)
        merge_warnings.extend(f"{name}: {warning}" for warning in merged.warnings)
        for account in merged.multi_frame:
            if account not in multi_frame:
                multi_frame.append(account)

    combined = combine_screenshot_and_recording_parses(screenshot_parses, recording_parses)
    report = apply_xp_screenshot_fills(
        combined,
        xp_date=xp_date,
        selected_accounts=selected_accounts,
        session_state=session_state,
        last_known=last_known,
        xp_to_next_by_level=xp_to_next_by_level,
    )
    report.warnings = extractor_warnings + ocr_warnings + merge_warnings + report.warnings
    report.multi_frame = multi_frame
    return report


def _mean_absolute_difference(left: object, right: object) -> float:
    import numpy as np

    before = np.asarray(left)
    after = np.asarray(right)
    if before.shape != after.shape or before.size == 0:
        return float("inf")
    delta = np.abs(before.astype(np.float64) - after.astype(np.float64))
    return float(np.mean(delta))


def _load_frame_array(frame_path: Path) -> object:
    import numpy as np
    from PIL import Image

    with Image.open(frame_path) as image:
        return np.array(image.convert("RGB"))


def _account_name(parsed: ProfileScreenshotParse) -> str:
    return str(parsed.account or "").strip()


def _is_header(parsed: ProfileScreenshotParse) -> bool:
    return bool(_account_name(parsed)) and (parsed.level is not None or parsed.xp_bar is not None)


def _last_not_none(frames: list[ProfileScreenshotParse], name: str) -> object:
    value = None
    for frame in frames:
        current = getattr(frame, name)
        if current is not None:
            value = current
    return value


def _merge_visit_frames(
    account: str,
    frames: list[ProfileScreenshotParse],
    xp_to_next_by_level: Mapping[int, int] | None,
) -> tuple[ProfileScreenshotParse, list[str]]:
    level = _last_not_none(frames, "level")
    pairs = [(frame.xp_bar, frame.xp_to_next) for frame in frames if frame.xp_bar is not None]
    xp_bar, xp_to_next, xp_warnings = _choose_xp_pair(account, level, pairs, xp_to_next_by_level)
    source_name = frames[0].source_name
    if len(frames) > 1:
        source_name = f"{source_name} ({len(frames)} frames)"
    warnings: list[str] = []
    for frame in frames:
        warnings.extend(frame.warnings)
    parsed = ProfileScreenshotParse(
        account=account,
        level=level if isinstance(level, int) else None,
        xp_bar=xp_bar,
        xp_to_next=xp_to_next,
        battles_won=_as_optional_float(_last_not_none(frames, "battles_won")),
        distance_walked=_as_optional_float(_last_not_none(frames, "distance_walked")),
        pokemon_caught=_as_optional_float(_last_not_none(frames, "pokemon_caught")),
        warnings=warnings,
        source_name=source_name,
    )
    return parsed, xp_warnings


def _as_optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _choose_xp_pair(
    account: str,
    level: object,
    pairs: list[tuple[int, int | None]],
    xp_to_next_by_level: Mapping[int, int] | None,
) -> tuple[int | None, int | None, list[str]]:
    if not pairs:
        return None, None, []
    if xp_to_next_by_level is None or not isinstance(level, int) or int(level) not in xp_to_next_by_level:
        xp_bar, xp_to_next = pairs[-1]
        return xp_bar, xp_to_next, []
    expected = int(xp_to_next_by_level[int(level)])
    matching = [pair for pair in pairs if pair[1] is not None and int(pair[1]) == expected]
    if not matching:
        return None, None, [
            (
                f"{account}: XP bar does not match level {int(level)} "
                f"(expected / {expected:,}), so XP was left blank."
            )
        ]
    warnings: list[str] = []
    if len(matching) != len(pairs):
        warnings.append(
            (
                f"{account}: dropped an XP pair that does not match level {int(level)} "
                f"(expected / {expected:,})."
            )
        )
    xp_bar, xp_to_next = matching[-1]
    return xp_bar, xp_to_next, warnings


def _clone_parse(parsed: ProfileScreenshotParse) -> ProfileScreenshotParse:
    return replace(parsed, warnings=list(parsed.warnings))


def _overlay_present_fields(base: ProfileScreenshotParse, incoming: ProfileScreenshotParse) -> None:
    for name in _PRESENT_FIELDS:
        value = getattr(incoming, name)
        if value is not None:
            setattr(base, name, value)
    if incoming.xp_bar is not None:
        base.xp_bar = incoming.xp_bar
        base.xp_to_next = incoming.xp_to_next
    if incoming.warnings:
        base.warnings.extend(list(incoming.warnings))
