from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.paths import google_drive_credentials_path, pokedex_sync_config_path, pokedex_sync_token_path
from webapp.pokedex_sync import (
    POKEDEX_SYNC_FOLDER_NAME,
    build_pokedex_sync_service,
    default_pokedex_sync_config,
    ensure_pokedex_sync_folder,
    load_pokedex_sync_config,
    load_pokedex_sync_credentials,
    save_pokedex_sync_config,
)


def main() -> int:
    try:
        creds = load_pokedex_sync_credentials(
            credentials_path=google_drive_credentials_path(),
            token_path=pokedex_sync_token_path(),
            interactive=True,
        )
        service = build_pokedex_sync_service(creds)
        about = service.about().get(fields="user,storageQuota").execute()
        config_path = pokedex_sync_config_path()
        config = load_pokedex_sync_config(config_path)
        if config is None:
            config = default_pokedex_sync_config()
        if not str(config.get("folder_id") or "").strip():
            config = ensure_pokedex_sync_folder(service, config)
            folder_id = str(config.get("folder_id") or "").strip()
            if not folder_id:
                raise RuntimeError(f"Google Drive did not return a folder id for {POKEDEX_SYNC_FOLDER_NAME}.")
            save_pokedex_sync_config(config, config_path)
        else:
            folder_id = str(config.get("folder_id") or "").strip()
    except Exception as exc:
        print(f"Pokédex sync connection failed: {exc}", file=sys.stderr)
        return 1

    user = about.get("user", {})
    email = user.get("emailAddress", "unknown")
    quota = about.get("storageQuota", {})
    used = quota.get("usage", "unknown")
    limit = quota.get("limit", "unknown")
    print(f"Pokédex sync connected: {email}")
    print(f"Credentials expected at: {google_drive_credentials_path()}")
    print(f"Sync token saved: {pokedex_sync_token_path()}")
    print(f"Sync folder: {POKEDEX_SYNC_FOLDER_NAME} ({folder_id})")
    print(f"Config: {pokedex_sync_config_path()}")
    print(f"Storage usage: {used} / {limit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
