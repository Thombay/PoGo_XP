from __future__ import annotations

import runpy
from pathlib import Path


def run_script(path: Path):
    runpy.run_path(str(path), run_name="__main__")


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    run_script(root / "pogo-xp" / "pogo_totalXP.py")
    # Medal snapshot append from XLSX is intentionally separate for now.
    run_script(root / "medal-tracker" / "tools" / "generate_report.py")
