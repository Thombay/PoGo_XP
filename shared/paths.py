from __future__ import annotations

import os
from pathlib import Path


def repo_root(start: Path | None = None) -> Path:
    here = (start or Path(__file__)).resolve()
    for p in [here] + list(here.parents):
        if (p / ".git").exists():
            return p
    return Path(__file__).resolve().parents[1]


def inputs_dir() -> Path:
    env = os.getenv("POGO_INPUT_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return repo_root() / "inputs"


def output_dir() -> Path:
    env = os.getenv("POGO_OUTPUT_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return repo_root() / "output"


def config_dir() -> Path:
    return inputs_dir() / "config"


def data_dir() -> Path:
    return inputs_dir() / "data"


def reference_dir() -> Path:
    return inputs_dir() / "reference"


def total_xp_curve_path() -> Path:
    return reference_dir() / "total_xp_curve.csv"


def xp_history_path() -> Path:
    return data_dir() / "xp_history.csv"


def player_groups_path() -> Path:
    return config_dir() / "player_groups.csv"


def xp_snapshots_path() -> Path:
    # Reserved for canonical per-account XP snapshots used by medal-tracker.
    return data_dir() / "xp_snapshots.csv"


def medals_config_path() -> Path:
    return config_dir() / "medal_goals.csv"


def medal_snapshots_path() -> Path:
    return data_dir() / "medal_snapshots.csv"


def medal_report_path() -> Path:
    return output_dir() / "medal-tracker" / "medal_report.csv"


def medal_explanations_path() -> Path:
    return config_dir() / "medal_explanations.csv"


def additional_activity_path() -> Path:
    return data_dir() / "additional_activity.csv"
