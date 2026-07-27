from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.paths import google_drive_exports_config_path, player_groups_path
from webapp.data_files import parse_groups
from webapp.google_drive import (
    build_drive_service,
    default_google_drive_exports_config,
    load_google_drive_credentials,
    load_google_drive_exports_config,
    save_google_drive_exports_config,
    setup_google_drive_folder_structure,
)


def _dashboard_groups_from_player_groups() -> dict[str, list[str]]:
    groups = parse_groups(player_groups_path())
    personal = {"ich", "ownaccounts"}
    global_groups = ["All"] + [name for name in groups.keys() if name and name != "All" and name.strip().lower() not in personal]
    personal_by_key = {name.strip().lower(): name for name in groups.keys() if name.strip().lower() in personal}
    personal_groups = [personal_by_key[key] for key in ["ownaccounts", "ich"] if key in personal_by_key]
    return {
        "Dashboard Global": global_groups,
        "Dashboard Personal": personal_groups,
        "Medal Dashboard": personal_groups,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create/find PoGo Google Drive export folders and save IDs.")
    parser.add_argument(
        "--config",
        type=Path,
        default=google_drive_exports_config_path(),
        help="Path to google_drive_exports.json",
    )
    parser.add_argument(
        "--reset-exports",
        action="store_true",
        help="Rebuild export rows from current player groups before creating folders.",
    )
    args = parser.parse_args()

    try:
        creds = load_google_drive_credentials(interactive=True)
        service = build_drive_service(creds)
        dashboards = _dashboard_groups_from_player_groups()
        if args.reset_exports or not args.config.exists():
            config = default_google_drive_exports_config(dashboards=dashboards)
        else:
            config = load_google_drive_exports_config(args.config)
        updated = setup_google_drive_folder_structure(service, config=config, dashboards=dashboards)
        save_path = save_google_drive_exports_config(updated, path=args.config)
    except Exception as exc:
        print(f"Google Drive folder setup failed: {exc}", file=sys.stderr)
        return 1

    print(f"Root folder: {updated.get('root_folder_name')} ({updated.get('root_folder_id')})")
    for row in updated.get("exports", []):
        print(
            f"- {row.get('dashboard')} / {row.get('group')}: folder_id={row.get('folder_id') or '(missing)'}"
        )
    print(f"Wrote config: {save_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
