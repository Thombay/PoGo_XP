from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.paths import google_drive_credentials_path, google_drive_token_path
from webapp.google_drive import build_drive_service, load_google_drive_credentials


def main() -> int:
    try:
        creds = load_google_drive_credentials(
            credentials_path=google_drive_credentials_path(),
            token_path=google_drive_token_path(),
            interactive=True,
        )
        about = (
            build_drive_service(creds)
            .about()
            .get(fields="user,storageQuota")
            .execute()
        )
    except Exception as exc:
        print(f"Google Drive connection failed: {exc}", file=sys.stderr)
        return 1

    user = about.get("user", {})
    email = user.get("emailAddress", "unknown")
    quota = about.get("storageQuota", {})
    used = quota.get("usage", "unknown")
    limit = quota.get("limit", "unknown")
    print(f"Google Drive connected: {email}")
    print(f"Credentials expected at: {google_drive_credentials_path()}")
    print(f"Token saved: {google_drive_token_path()}")
    print(f"Storage usage: {used} / {limit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
