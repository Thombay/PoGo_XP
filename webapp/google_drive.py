from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]
from googleapiclient.discovery import build  # type: ignore[import-untyped]
from googleapiclient.http import MediaInMemoryUpload  # type: ignore[import-untyped]

from shared.paths import (
    google_drive_credentials_path,
    google_drive_exports_config_path,
    google_drive_token_path,
    private_dir,
)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
DEFAULT_ROOT_FOLDER_NAME = "PoGo"
DEFAULT_EXPORT_FILE_NAME = "dashboard.html"
DEFAULT_SHARE_MODE = "anyone_with_link"
DEFAULT_EXPORT_MODE = "dark"
DEFAULT_WINDOW_DAYS = 7
MIME_FOLDER = "application/vnd.google-apps.folder"
MIME_HTML = "text/html"


def load_google_drive_credentials(
    credentials_path: Path | None = None,
    token_path: Path | None = None,
    interactive: bool = True,
) -> Credentials:
    creds_path = credentials_path or google_drive_credentials_path()
    tok_path = token_path or google_drive_token_path()
    private_dir().mkdir(parents=True, exist_ok=True)

    creds: Credentials | None = None
    if tok_path.exists():
        creds = Credentials.from_authorized_user_file(str(tok_path), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    if not creds or not creds.valid:
        if not interactive:
            raise FileNotFoundError(
                f"Google Drive token is missing or invalid: {tok_path}. "
                "Run `python tools/google_drive_connect.py` once."
            )
        if not creds_path.exists():
            raise FileNotFoundError(
                f"Missing Google OAuth credentials: {creds_path}\n"
                "Create an OAuth client in Google Cloud, download the JSON, and save it there."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
        creds = flow.run_local_server(port=0)
        tok_path.write_text(creds.to_json(), encoding="utf-8")

    return creds


def build_drive_service(credentials: Credentials | None = None):
    creds = credentials or load_google_drive_credentials(interactive=False)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def default_google_drive_exports_config(
    dashboards: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    dashboard_groups = dashboards or {
        "Dashboard Global": ["All", "Family", "Work", "Papiermuehlgasse", "Bekannte"],
        "Dashboard Personal": ["OwnAccounts", "Ich"],
        "Medal Dashboard": ["OwnAccounts", "Ich"],
    }
    exports: list[dict[str, Any]] = []
    for dashboard, groups in dashboard_groups.items():
        for group in groups:
            exports.append(
                {
                    "dashboard": dashboard,
                    "group": group,
                    "folder_id": "",
                    "file_name": DEFAULT_EXPORT_FILE_NAME,
                    "file_id": "",
                    "web_view_link": "",
                    "enabled": True,
                }
            )
    return {
        "root_folder_name": DEFAULT_ROOT_FOLDER_NAME,
        "root_folder_id": "",
        "share_mode": DEFAULT_SHARE_MODE,
        "export_mode": DEFAULT_EXPORT_MODE,
        "window_days": DEFAULT_WINDOW_DAYS,
        "exports": exports,
    }


def load_google_drive_exports_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or google_drive_exports_config_path()
    if not config_path.exists():
        return default_google_drive_exports_config()
    raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        return default_google_drive_exports_config()
    base = default_google_drive_exports_config()
    base.update({k: raw.get(k, base[k]) for k in base.keys() if k != "exports"})
    exports = raw.get("exports", base["exports"])
    if isinstance(exports, list):
        base["exports"] = exports
    return base


def save_google_drive_exports_config(config: dict[str, Any], path: Path | None = None) -> Path:
    config_path = path or google_drive_exports_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return config_path


def _escape_drive_query_value(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def find_child_by_name(
    service: Any,
    name: str,
    parent_id: str | None = None,
    mime_type: str | None = None,
) -> dict[str, Any] | None:
    clauses = [f"name = '{_escape_drive_query_value(name)}'", "trashed = false"]
    if parent_id:
        clauses.append(f"'{_escape_drive_query_value(parent_id)}' in parents")
    else:
        clauses.append("'root' in parents")
    if mime_type:
        clauses.append(f"mimeType = '{_escape_drive_query_value(mime_type)}'")
    query = " and ".join(clauses)
    response = (
        service.files()
        .list(
            q=query,
            spaces="drive",
            fields="files(id, name, mimeType, webViewLink)",
            pageSize=10,
        )
        .execute()
    )
    files = response.get("files", [])
    return files[0] if files else None


def create_folder(service: Any, name: str, parent_id: str | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {"name": name, "mimeType": MIME_FOLDER}
    if parent_id:
        metadata["parents"] = [parent_id]
    return (
        service.files()
        .create(body=metadata, fields="id, name, mimeType, webViewLink")
        .execute()
    )


def ensure_folder(service: Any, name: str, parent_id: str | None = None) -> dict[str, Any]:
    existing = find_child_by_name(service, name, parent_id=parent_id, mime_type=MIME_FOLDER)
    if existing:
        return existing
    return create_folder(service, name, parent_id=parent_id)


def set_file_sharing(service: Any, file_id: str, share_mode: str = DEFAULT_SHARE_MODE) -> None:
    mode = str(share_mode or DEFAULT_SHARE_MODE).strip().lower()
    if mode in {"anyone_with_link", "anyone", "public"}:
        try:
            service.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
                fields="id",
            ).execute()
        except Exception as exc:
            # Permission may already exist for previously shared files.
            message = str(exc).lower()
            if "already exists" not in message and "duplicate" not in message:
                raise
    # restricted: leave Drive default permissions alone


def upload_or_update_file(
    service: Any,
    *,
    parent_folder_id: str,
    file_name: str,
    content: bytes,
    mime_type: str = MIME_HTML,
    file_id: str | None = None,
    share_mode: str = DEFAULT_SHARE_MODE,
) -> dict[str, Any]:
    media = MediaInMemoryUpload(content, mimetype=mime_type, resumable=False)
    existing_id = str(file_id or "").strip()
    if existing_id:
        updated = (
            service.files()
            .update(
                fileId=existing_id,
                media_body=media,
                fields="id, name, webViewLink, parents",
            )
            .execute()
        )
        set_file_sharing(service, existing_id, share_mode=share_mode)
        return updated

    created = (
        service.files()
        .create(
            body={"name": file_name, "parents": [parent_folder_id]},
            media_body=media,
            fields="id, name, webViewLink, parents",
        )
        .execute()
    )
    created_id = str(created.get("id", "")).strip()
    if created_id:
        set_file_sharing(service, created_id, share_mode=share_mode)
    return created


def setup_google_drive_folder_structure(
    service: Any,
    config: dict[str, Any] | None = None,
    dashboards: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    cfg = dict(config or default_google_drive_exports_config(dashboards=dashboards))
    root_name = str(cfg.get("root_folder_name") or DEFAULT_ROOT_FOLDER_NAME).strip() or DEFAULT_ROOT_FOLDER_NAME
    root = ensure_folder(service, root_name, parent_id=None)
    cfg["root_folder_id"] = str(root.get("id", ""))

    exports = list(cfg.get("exports") or [])
    if not exports and dashboards:
        exports = default_google_drive_exports_config(dashboards=dashboards)["exports"]

    dashboard_folder_ids: dict[str, str] = {}
    for row in exports:
        dashboard = str(row.get("dashboard", "")).strip()
        group = str(row.get("group", "")).strip()
        if not dashboard or not group:
            continue
        if dashboard not in dashboard_folder_ids:
            dash_folder = ensure_folder(service, dashboard, parent_id=cfg["root_folder_id"])
            dashboard_folder_ids[dashboard] = str(dash_folder.get("id", ""))
        group_folder = ensure_folder(service, group, parent_id=dashboard_folder_ids[dashboard])
        row["folder_id"] = str(group_folder.get("id", ""))
        row.setdefault("file_name", DEFAULT_EXPORT_FILE_NAME)
        row.setdefault("file_id", "")
        row.setdefault("web_view_link", "")
        row.setdefault("enabled", True)

    cfg["exports"] = exports
    return cfg


def enabled_export_targets(config: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for row in list(config.get("exports") or []):
        if not isinstance(row, dict):
            continue
        if row.get("enabled", True) is False:
            continue
        dashboard = str(row.get("dashboard", "")).strip()
        group = str(row.get("group", "")).strip()
        folder_id = str(row.get("folder_id", "")).strip()
        if not dashboard or not group or not folder_id:
            continue
        rows.append(row)
    return rows


def publish_html_exports(
    service: Any,
    config: dict[str, Any],
    build_html: Callable[[str, str, str, int], str],
    config_path: Path | None = None,
) -> dict[str, Any]:
    """
    Rebuild and upload configured HTML exports.

    build_html(dashboard, group, export_mode, window_days) -> html string
    """
    share_mode = str(config.get("share_mode") or DEFAULT_SHARE_MODE)
    export_mode = str(config.get("export_mode") or DEFAULT_EXPORT_MODE)
    window_days = int(config.get("window_days") or DEFAULT_WINDOW_DAYS)
    results: list[dict[str, Any]] = []
    updated_config = dict(config)
    exports = list(updated_config.get("exports") or [])

    for idx, row in enumerate(exports):
        if not isinstance(row, dict) or row.get("enabled", True) is False:
            continue
        dashboard = str(row.get("dashboard", "")).strip()
        group = str(row.get("group", "")).strip()
        folder_id = str(row.get("folder_id", "")).strip()
        file_name = str(row.get("file_name") or DEFAULT_EXPORT_FILE_NAME).strip() or DEFAULT_EXPORT_FILE_NAME
        if not dashboard or not group or not folder_id:
            results.append(
                {
                    "dashboard": dashboard,
                    "group": group,
                    "ok": False,
                    "error": "Missing dashboard/group/folder_id in Google Drive export config.",
                }
            )
            continue
        try:
            html = build_html(dashboard, group, export_mode, window_days)
            uploaded = upload_or_update_file(
                service,
                parent_folder_id=folder_id,
                file_name=file_name,
                content=html.encode("utf-8"),
                mime_type=MIME_HTML,
                file_id=str(row.get("file_id") or "").strip() or None,
                share_mode=share_mode,
            )
            file_id = str(uploaded.get("id") or "").strip()
            link = str(uploaded.get("webViewLink") or "").strip()
            if not link and file_id:
                link = f"https://drive.google.com/file/d/{file_id}/view"
            exports[idx] = {
                **row,
                "file_id": file_id,
                "web_view_link": link,
                "file_name": file_name,
            }
            results.append(
                {
                    "dashboard": dashboard,
                    "group": group,
                    "ok": True,
                    "file_id": file_id,
                    "web_view_link": link,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "dashboard": dashboard,
                    "group": group,
                    "ok": False,
                    "error": str(exc),
                }
            )

    updated_config["exports"] = exports
    save_google_drive_exports_config(updated_config, path=config_path)
    ok_count = sum(1 for item in results if item.get("ok"))
    return {
        "ok": ok_count > 0 and all(item.get("ok") for item in results),
        "uploaded": ok_count,
        "total": len(results),
        "results": results,
        "config": updated_config,
    }


def format_publish_summary(publish_result: dict[str, Any]) -> str:
    lines: list[str] = []
    uploaded = int(publish_result.get("uploaded") or 0)
    total = int(publish_result.get("total") or 0)
    lines.append(f"Google Drive exports updated: {uploaded}/{total}")
    for item in list(publish_result.get("results") or []):
        dashboard = item.get("dashboard", "?")
        group = item.get("group", "?")
        if item.get("ok"):
            link = item.get("web_view_link") or item.get("file_id") or "(no link)"
            lines.append(f"- {dashboard} / {group}: {link}")
        else:
            lines.append(f"- {dashboard} / {group}: failed ({item.get('error', 'unknown error')})")
    return "\n".join(lines)
