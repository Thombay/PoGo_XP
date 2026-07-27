from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.paths import github_pages_site_dir, google_drive_exports_config_path
from webapp.google_drive import load_google_drive_exports_config
from webapp.github_pages import (
    format_github_pages_summary,
    load_github_pages_config,
    publish_html_to_github_pages,
)


def _load_app_helpers() -> ModuleType:
    """Load rebuild helpers from webapp.app without executing the Streamlit UI."""
    source = (REPO_ROOT / "webapp" / "app.py").read_text(encoding="utf-8")
    cut = source.split("st.set_page_config", 1)[0]
    mod = ModuleType("pogo_app_publish")
    mod.__file__ = str(REPO_ROOT / "webapp" / "app.py")
    exec(compile(cut, str(REPO_ROOT / "webapp" / "app.py"), "exec"), mod.__dict__)
    return mod


def main() -> int:
    parser = argparse.ArgumentParser(description="Build dashboard HTML and publish to the gh-pages branch.")
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Write the site locally only; do not commit/push gh-pages.",
    )
    args = parser.parse_args()

    try:
        app = _load_app_helpers()
        drive_config = load_google_drive_exports_config(google_drive_exports_config_path())
        pages_config = load_github_pages_config()
        targets = app.enabled_github_pages_targets(drive_config)
        if not targets:
            print("No enabled dashboard/group export targets found.", file=sys.stderr)
            return 1

        export_mode = str(drive_config.get("export_mode") or "dark")
        window_days = int(drive_config.get("window_days") or 7)
        build_html = app.build_export_html_callback(drive_config)

        result = publish_html_to_github_pages(
            targets=targets,
            build_html=build_html,
            export_mode=export_mode,
            window_days=window_days,
            site_dir=github_pages_site_dir(),
            pages_config=pages_config,
            push=not args.no_push,
            repo=REPO_ROOT,
        )
    except Exception as exc:
        print(f"GitHub Pages publish failed: {exc}", file=sys.stderr)
        return 1

    print(format_github_pages_summary(result))
    if result.get("skipped") or not result.get("ok"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
