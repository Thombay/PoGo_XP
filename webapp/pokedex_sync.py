from __future__ import annotations

import csv
import io
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]
from googleapiclient.discovery import build  # type: ignore[import-untyped]

from shared.paths import (
    data_input_accounts_path,
    google_drive_credentials_path,
    manual_pokemon_availability_path,
    pokedex_category_availability_path,
    pokedex_species_entries_path,
    pokedex_sync_config_path,
    pokedex_sync_state_path,
    pokedex_sync_token_path,
    pokemon_catalog_path,
    private_dir,
)
from webapp.data_files import (
    load_data_input_accounts,
    load_pokedex_category_availability,
    load_pokemon_catalog_with_availability,
)
from webapp.google_drive import ensure_folder, find_child_by_name, upload_or_update_file
from webapp.pokedex import (
    ATLAS_ENTRY_KINDS,
    _atlas_targets_by_kind,
    _available_form_map,
    _prepare_atlas_catalog,
    location_restriction_for_dex,
)

POKEDEX_SYNC_SCOPES = ["https://www.googleapis.com/auth/drive"]
POKEDEX_SYNC_FOLDER_NAME = "PoGo Sync"
PRIVATE_SHARE_MODE = "restricted"
MIME_CSV = "text/csv"

SPECIES_SYNC_NAME = "pokedex_species_entries.csv"
REFERENCE_SYNC_NAME = "pokedex_atlas_reference.csv"
ACCOUNTS_SYNC_NAME = "pokedex_accounts.csv"
POKEDEX_SYNC_FILE_NAMES = (
    SPECIES_SYNC_NAME,
    REFERENCE_SYNC_NAME,
    ACCOUNTS_SYNC_NAME,
)

POKEDEX_ATLAS_REFERENCE_COLUMNS = [
    "dex_number",
    "name",
    "german_name",
    "region",
    "region_label",
    "form",
    "entry_type",
    "entry_type_label",
    "available",
    "location_restriction",
    "last_event",
]
POKEDEX_ACCOUNTS_COLUMNS = ["account"]

POKEDEX_REGION_LABELS = {
    "overall": "Overall",
    "kanto": "Kanto",
    "johto": "Johto",
    "hoenn": "Hoenn",
    "sinnoh": "Sinnoh",
    "unova": "Unova",
    "kalos": "Kalos",
    "alola": "Alola",
    "galar": "Galar",
    "hisui": "Hisui",
    "paldea": "Paldea",
    "unidentified": "Unidentified",
}


def default_pokedex_sync_config() -> dict[str, Any]:
    return {
        "folder_id": "",
        "files": {name: "" for name in POKEDEX_SYNC_FILE_NAMES},
    }


def normalize_pokedex_sync_config(raw: dict[str, Any]) -> dict[str, Any]:
    folder_id = str(raw.get("folder_id") or "").strip()
    files_raw = raw.get("files")
    files = {name: "" for name in POKEDEX_SYNC_FILE_NAMES}
    if isinstance(files_raw, dict):
        for name in POKEDEX_SYNC_FILE_NAMES:
            files[name] = str(files_raw.get(name) or "").strip()
    return {"folder_id": folder_id, "files": files}


def load_pokedex_sync_config(path: Path | None = None) -> dict[str, Any] | None:
    config_path = path or pokedex_sync_config_path()
    if not config_path.exists():
        return None
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    return normalize_pokedex_sync_config(raw)


def save_pokedex_sync_config(config: dict[str, Any], path: Path | None = None) -> Path:
    config_path = path or pokedex_sync_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = normalize_pokedex_sync_config(config)
    config_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return config_path


def read_species_pending(path: Path | None = None) -> bool:
    state_path = path or pokedex_sync_state_path()
    if not state_path.exists():
        return False
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(raw, dict):
        return False
    value = raw.get("species_pending", False)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def set_species_pending(pending: bool, path: Path | None = None) -> Path:
    state_path = path or pokedex_sync_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"species_pending": bool(pending)}
    state_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return state_path


def _text_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([""] * len(frame), index=frame.index, dtype="object")
    return frame[column].fillna("").astype(str).str.strip()


def _location_restrictions(catalog: pd.DataFrame) -> pd.Series:
    if "location_restriction" not in catalog.columns:
        return catalog["dex_number"].map(location_restriction_for_dex)
    current = _text_series(catalog, "location_restriction")
    blank = current == ""
    filled = current.copy()
    filled.loc[blank] = catalog.loc[blank, "dex_number"].map(location_restriction_for_dex)
    return filled


def _reference_forms(forms: Sequence[str], *, available: bool) -> list[str]:
    if not available:
        return [""]
    cleaned = [str(form).strip() for form in forms]
    named = [form for form in cleaned if form]
    if not named:
        return [""]
    return cleaned


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def build_pokedex_atlas_reference(
    catalog_df: pd.DataFrame,
    availability_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    columns = list(POKEDEX_ATLAS_REFERENCE_COLUMNS)
    catalog = _prepare_atlas_catalog(catalog_df, None)
    if catalog.empty or "dex_number" not in catalog.columns:
        return pd.DataFrame(columns=columns)
    region_text = _text_series(catalog, "region")
    catalog = catalog.loc[region_text.str.casefold() != "overall"].copy()
    if catalog.empty:
        return pd.DataFrame(columns=columns)
    catalog = catalog.sort_values("dex_number").reset_index(drop=True)

    kind_ids = [kind for kind, _label in ATLAS_ENTRY_KINDS]
    labels = {kind: label for kind, label in ATLAS_ENTRY_KINDS}
    targets = _atlas_targets_by_kind(catalog, availability_df, kind_ids)
    form_maps = {kind: _available_form_map(availability_df, kind) for kind in kind_ids}

    names = _text_series(catalog, "name")
    german_names = _text_series(catalog, "german_name")
    regions = _text_series(catalog, "region")
    region_labels = regions.map(lambda value: POKEDEX_REGION_LABELS.get(value.casefold(), value))
    locations = _location_restrictions(catalog)
    events = _text_series(catalog, "last_event")
    dex_numbers = catalog["dex_number"].astype(int)

    rows: list[dict[str, object]] = []
    for index in catalog.index:
        dex = int(dex_numbers.loc[index])
        for kind in kind_ids:
            available = dex in targets.get(kind, set())
            forms = _reference_forms(form_maps[kind].get(dex, []), available=available)
            for form in forms:
                rows.append(
                    {
                        "dex_number": dex,
                        "name": names.loc[index],
                        "german_name": german_names.loc[index],
                        "region": regions.loc[index],
                        "region_label": region_labels.loc[index],
                        "form": form,
                        "entry_type": kind,
                        "entry_type_label": labels[kind],
                        "available": _bool_text(available),
                        "location_restriction": locations.loc[index],
                        "last_event": events.loc[index],
                    }
                )
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)


def pokedex_atlas_reference_csv_bytes(
    catalog_df: pd.DataFrame,
    availability_df: pd.DataFrame | None = None,
) -> bytes:
    return _csv_frame_bytes(build_pokedex_atlas_reference(catalog_df, availability_df))


def pokedex_sync_account_names(path: Path | None = None) -> list[str]:
    source = path or data_input_accounts_path()
    config = load_data_input_accounts(source, valid_input_types={"pokedex"})
    if config.empty or not {"input_type", "account", "enabled"}.issubset(config.columns):
        return []
    scoped = config[config["input_type"].astype(str).str.strip().str.lower() == "pokedex"]
    names: list[str] = []
    seen: set[str] = set()
    for account, enabled in zip(scoped["account"].tolist(), scoped["enabled"].tolist(), strict=True):
        text = str(account).strip()
        if not text or text in seen or not bool(enabled):
            continue
        seen.add(text)
        names.append(text)
    return names


def build_pokedex_accounts_frame(accounts: Sequence[str]) -> pd.DataFrame:
    return pd.DataFrame({"account": [str(account) for account in accounts]}, columns=POKEDEX_ACCOUNTS_COLUMNS)


def pokedex_accounts_csv_bytes(accounts: Sequence[str]) -> bytes:
    return _csv_frame_bytes(build_pokedex_accounts_frame(accounts))


def _csv_frame_bytes(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.to_csv(
        buffer,
        index=False,
        encoding="utf-8-sig",
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\n",
    )
    return buffer.getvalue()


def load_pokedex_sync_credentials(
    credentials_path: Path | None = None,
    token_path: Path | None = None,
    interactive: bool = True,
) -> Credentials:
    creds_path = credentials_path or google_drive_credentials_path()
    tok_path = token_path or pokedex_sync_token_path()
    private_dir().mkdir(parents=True, exist_ok=True)

    creds: Credentials | None = None
    if tok_path.exists():
        creds = Credentials.from_authorized_user_file(str(tok_path), POKEDEX_SYNC_SCOPES)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            tok_path.write_text(creds.to_json(), encoding="utf-8")
        except RefreshError:
            tok_path.unlink(missing_ok=True)
            creds = None

    if not creds or not creds.valid:
        if not interactive:
            raise FileNotFoundError(
                f"Pokédex sync token is missing or invalid: {tok_path}. "
                "Run `python tools/pokedex_sync_connect.py` once."
            )
        if not creds_path.exists():
            raise FileNotFoundError(
                f"Missing Google OAuth credentials: {creds_path}\n"
                "Create an OAuth client in Google Cloud, download the JSON, and save it there."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), POKEDEX_SYNC_SCOPES)
        creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
        tok_path.write_text(creds.to_json(), encoding="utf-8")

    return creds


def build_pokedex_sync_service(credentials: Credentials | None = None):
    creds = credentials or load_pokedex_sync_credentials(interactive=False)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def ensure_pokedex_sync_folder(service: Any, config: dict[str, Any] | None = None) -> dict[str, Any]:
    updated = normalize_pokedex_sync_config(config or default_pokedex_sync_config())
    if updated["folder_id"]:
        return updated
    folder = ensure_folder(service, POKEDEX_SYNC_FOLDER_NAME, parent_id=None)
    if isinstance(folder, dict):
        updated["folder_id"] = str(folder.get("id") or "").strip()
    return updated


def _parse_drive_time(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _local_mtime_utc(path: Path) -> datetime | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _lookup_child_id(service: Any, folder_id: str, file_name: str) -> str:
    found = find_child_by_name(service, file_name, parent_id=folder_id)
    if not isinstance(found, dict):
        return ""
    return str(found.get("id") or "").strip()


def _drive_modified_time(service: Any, file_id: str) -> datetime | None:
    meta = service.files().get(fileId=file_id, fields="modifiedTime").execute()
    if not isinstance(meta, dict):
        return None
    return _parse_drive_time(meta.get("modifiedTime"))


def _download_bytes(service: Any, file_id: str) -> bytes:
    payload = service.files().get_media(fileId=file_id).execute()
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, bytearray):
        return bytes(payload)
    raise TypeError("Drive file download did not return bytes.")


def _replace_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.sync-tmp")
    temporary.write_bytes(content)
    try:
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _upload_private_csv(
    service: Any,
    *,
    folder_id: str,
    file_name: str,
    content: bytes,
    file_id: str,
) -> dict[str, Any]:
    uploaded = upload_or_update_file(
        service,
        parent_folder_id=folder_id,
        file_name=file_name,
        content=content,
        mime_type=MIME_CSV,
        file_id=file_id or None,
        share_mode=PRIVATE_SHARE_MODE,
    )
    if not isinstance(uploaded, dict):
        raise TypeError(f"Drive upload for {file_name} did not return a file record.")
    return uploaded


def _remember_file_id(file_ids: dict[str, str], file_name: str, uploaded: dict[str, Any]) -> None:
    new_id = str(uploaded.get("id") or "").strip()
    if new_id:
        file_ids[file_name] = new_id


def _download_species_if_remote_newer(
    service: Any,
    *,
    folder_id: str,
    species_path: Path,
    file_ids: dict[str, str],
) -> bool:
    file_id = str(file_ids.get(SPECIES_SYNC_NAME) or "").strip()
    if not file_id:
        file_id = _lookup_child_id(service, folder_id, SPECIES_SYNC_NAME)
        if file_id:
            file_ids[SPECIES_SYNC_NAME] = file_id
    if not file_id:
        return False
    remote_time = _drive_modified_time(service, file_id)
    if remote_time is None:
        return False
    local_time = _local_mtime_utc(species_path)
    if local_time is not None and remote_time <= local_time:
        return False
    _replace_bytes(species_path, _download_bytes(service, file_id))
    return True


def _skipped_result(reason: str, state_path: Path) -> dict[str, Any]:
    return {
        "ok": True,
        "skipped": True,
        "status": "skipped",
        "reason": reason,
        "species_action": "untouched",
        "species_pending": read_species_pending(state_path),
        "file_ids": {},
        "errors": [],
    }


def _sync_error_result(exc: Exception) -> dict[str, Any]:
    message = " ".join(str(exc).split()) or exc.__class__.__name__
    return {
        "ok": False,
        "skipped": False,
        "status": "error",
        "reason": "",
        "species_action": "untouched",
        "species_pending": read_species_pending(),
        "file_ids": {},
        "errors": [message],
    }


def pokedex_sync_status_line(result: dict[str, Any]) -> str:
    status = str(result.get("status") or "error")
    if status == "skipped":
        detail = str(result.get("reason") or "skipped")
    elif status == "error":
        errors = result.get("errors")
        if isinstance(errors, list) and errors:
            detail = " ".join(str(errors[0]).split()) or "error"
        else:
            detail = "error"
    else:
        action = str(result.get("species_action") or "unchanged").replace("_", " ")
        detail = f"species {action}"
    return f"Pokedex sync: {status} ({detail})"


def sync_pokedex(
    service: Any,
    *,
    config_path: Path | None = None,
    state_path: Path | None = None,
    species_path: Path | None = None,
    catalog_path: Path | None = None,
    availability_path: Path | None = None,
    accounts_source_path: Path | None = None,
) -> dict[str, Any]:
    """Sync Pokédex files with Drive.

    A missing config or blank folder_id skips without raising. Species bytes
    upload only while the pending flag is set. A failed species upload leaves
    that flag set and does not download over the local file. Reference and
    account files are rebuilt and uploaded whenever sync runs.
    """
    config_file = config_path or pokedex_sync_config_path()
    state_file = state_path or pokedex_sync_state_path()
    species_file = species_path or pokedex_species_entries_path()
    catalog_file = catalog_path or pokemon_catalog_path()
    availability_file = availability_path or pokedex_category_availability_path()
    accounts_file = accounts_source_path or data_input_accounts_path()

    config = load_pokedex_sync_config(config_file)
    if config is None:
        return _skipped_result("missing_config", state_file)
    if not str(config.get("folder_id") or "").strip():
        return _skipped_result("blank_folder_id", state_file)

    errors: list[str] = []
    species_action = "unchanged"
    file_ids = {name: str(config["files"].get(name) or "").strip() for name in POKEDEX_SYNC_FILE_NAMES}
    folder_id = str(config["folder_id"]).strip()

    if read_species_pending(state_file):
        try:
            if not species_file.exists():
                raise FileNotFoundError(f"Missing species file: {species_file}")
            uploaded = _upload_private_csv(
                service,
                folder_id=folder_id,
                file_name=SPECIES_SYNC_NAME,
                content=species_file.read_bytes(),
                file_id=file_ids.get(SPECIES_SYNC_NAME, ""),
            )
            _remember_file_id(file_ids, SPECIES_SYNC_NAME, uploaded)
            set_species_pending(False, state_file)
            species_action = "uploaded"
        except Exception as exc:
            errors.append(f"{SPECIES_SYNC_NAME}: {exc}")
            species_action = "upload_failed"
    else:
        try:
            if _download_species_if_remote_newer(
                service,
                folder_id=folder_id,
                species_path=species_file,
                file_ids=file_ids,
            ):
                species_action = "downloaded"
        except Exception as exc:
            errors.append(f"{SPECIES_SYNC_NAME}: {exc}")

    try:
        reference_bytes = pokedex_atlas_reference_csv_bytes(
            load_pokemon_catalog_with_availability(catalog_file, manual_pokemon_availability_path()),
            load_pokedex_category_availability(availability_file),
        )
        uploaded = _upload_private_csv(
            service,
            folder_id=folder_id,
            file_name=REFERENCE_SYNC_NAME,
            content=reference_bytes,
            file_id=file_ids.get(REFERENCE_SYNC_NAME, ""),
        )
        _remember_file_id(file_ids, REFERENCE_SYNC_NAME, uploaded)
    except Exception as exc:
        errors.append(f"{REFERENCE_SYNC_NAME}: {exc}")

    try:
        account_bytes = pokedex_accounts_csv_bytes(pokedex_sync_account_names(accounts_file))
        uploaded = _upload_private_csv(
            service,
            folder_id=folder_id,
            file_name=ACCOUNTS_SYNC_NAME,
            content=account_bytes,
            file_id=file_ids.get(ACCOUNTS_SYNC_NAME, ""),
        )
        _remember_file_id(file_ids, ACCOUNTS_SYNC_NAME, uploaded)
    except Exception as exc:
        errors.append(f"{ACCOUNTS_SYNC_NAME}: {exc}")

    config["folder_id"] = folder_id
    config["files"] = file_ids
    save_pokedex_sync_config(config, config_file)
    return {
        "ok": not errors,
        "skipped": False,
        "status": "synced" if not errors else "partial",
        "reason": "",
        "species_action": species_action,
        "species_pending": read_species_pending(state_file),
        "file_ids": file_ids,
        "errors": errors,
    }


def run_configured_sync() -> dict[str, Any]:
    try:
        service = build_pokedex_sync_service()
        return sync_pokedex(service)
    except FileNotFoundError:
        return _skipped_result("missing_token", pokedex_sync_state_path())
    except Exception as exc:
        return _sync_error_result(exc)


def publish_local_species_save() -> dict[str, Any]:
    set_species_pending(True)
    return run_configured_sync()
