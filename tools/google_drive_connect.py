from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]
from googleapiclient.discovery import build  # type: ignore[import-untyped]


PRIVATE_DIR = REPO_ROOT / "inputs" / "private"
CREDENTIALS_PATH = PRIVATE_DIR / "google_drive_credentials.json"
TOKEN_PATH = PRIVATE_DIR / "google_drive_token.json"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def load_credentials() -> Credentials:
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    if not creds or not creds.valid:
        if not CREDENTIALS_PATH.exists():
            raise FileNotFoundError(
                f"Missing Google OAuth credentials: {CREDENTIALS_PATH}\n"
                "Create an OAuth client in Google Cloud, download the JSON, and save it there."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
        creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return creds


def main() -> int:
    try:
        creds = load_credentials()
        about = (
            build("drive", "v3", credentials=creds)
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
    print(f"Token saved: {TOKEN_PATH}")
    print(f"Storage usage: {used} / {limit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
