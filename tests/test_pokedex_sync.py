from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd  # type: ignore[import-untyped]

from shared.paths import config_dir, output_dir, private_dir
from webapp.data_files import POKEDEX_SPECIES_ENTRY_COLUMNS
from webapp.google_drive import SCOPES
from webapp.pokedex import ATLAS_ENTRY_KINDS
from webapp.pokedex_sync import (
    ACCOUNTS_SYNC_NAME,
    POKEDEX_ACCOUNTS_COLUMNS,
    POKEDEX_ATLAS_REFERENCE_COLUMNS,
    POKEDEX_SYNC_SCOPES,
    REFERENCE_SYNC_NAME,
    SPECIES_SYNC_NAME,
    build_pokedex_atlas_reference,
    default_pokedex_sync_config,
    ensure_pokedex_sync_folder,
    load_pokedex_sync_credentials,
    pokedex_accounts_csv_bytes,
    pokedex_sync_account_names,
    pokedex_sync_config_path,
    pokedex_sync_state_path,
    pokedex_sync_token_path,
    pokedex_sync_status_line,
    publish_local_species_save,
    read_species_pending,
    run_configured_sync,
    set_species_pending,
    sync_pokedex,
)


def _media_bytes(media: object) -> bytes:
    fd = getattr(media, "_fd", None)
    if fd is None:
        raise AssertionError("expected an in-memory upload body")
    fd.seek(0)
    data = fd.read()
    if isinstance(data, str):
        return data.encode("utf-8")
    return bytes(data)


def _executed(payload: object) -> MagicMock:
    call = MagicMock()
    call.execute.return_value = payload
    return call


class _Drive:
    def __init__(self, *, modified_time: str = "2020-01-01T00:00:00.000Z", remote_bytes: bytes = b"") -> None:
        self.service = MagicMock()
        self.uploaded: dict[str, bytes] = {}
        self.modified_time = modified_time
        self.remote_bytes = remote_bytes
        self.fail_species_upload = False
        self.species_file_id = "species-file"
        self.names_by_id = {self.species_file_id: SPECIES_SYNC_NAME}
        files = self.service.files.return_value
        files.create.side_effect = self._create
        files.update.side_effect = self._update
        files.get.side_effect = self._get
        files.get_media.side_effect = self._get_media

    def _create(self, **kwargs: object) -> MagicMock:
        body = kwargs["body"]
        assert isinstance(body, dict)
        name = str(body["name"])
        if self.fail_species_upload and name == SPECIES_SYNC_NAME:
            raise RuntimeError("species upload failed")
        self.uploaded[name] = _media_bytes(kwargs["media_body"])
        return _executed({"id": f"created-{name}", "name": name})

    def _update(self, **kwargs: object) -> MagicMock:
        file_id = str(kwargs["fileId"])
        name = self.names_by_id.get(file_id, file_id)
        if self.fail_species_upload and (file_id == self.species_file_id or name == SPECIES_SYNC_NAME):
            raise RuntimeError("species upload failed")
        self.uploaded[name] = _media_bytes(kwargs["media_body"])
        return _executed({"id": file_id, "name": name})

    def _get(self, **kwargs: object) -> MagicMock:
        return _executed({"id": kwargs.get("fileId", ""), "modifiedTime": self.modified_time})

    def _get_media(self, **kwargs: object) -> MagicMock:
        return _executed(self.remote_bytes)


def _set_mtime(path: Path, when: datetime) -> None:
    stamp = when.timestamp()
    os.utime(path, (stamp, stamp))


def _write_config(path: Path, folder_id: str, species_id: str = "") -> None:
    payload = {
        "folder_id": folder_id,
        "files": {
            SPECIES_SYNC_NAME: species_id,
            REFERENCE_SYNC_NAME: "",
            ACCOUNTS_SYNC_NAME: "",
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class PokedexSyncTest(unittest.TestCase):
    def _sync(
        self,
        drive: _Drive,
        root: Path,
        *,
        species_bytes: bytes,
        folder_id: str | None,
        species_id: str = "species-file",
        pending: bool | None = None,
        mtime: datetime | None = None,
    ) -> dict[str, object]:
        species = root / "pokedex_species_entries.csv"
        species.write_bytes(species_bytes)
        if mtime is not None:
            _set_mtime(species, mtime)
        config = root / "pokedex_sync.json"
        state = root / "pokedex_sync_state.json"
        if folder_id is None:
            if config.exists():
                config.unlink()
        else:
            _write_config(config, folder_id, species_id=species_id)
        if pending is not None:
            set_species_pending(pending, state)
        return sync_pokedex(
            drive.service,
            config_path=config,
            state_path=state,
            species_path=species,
            catalog_path=root / "catalog.csv",
            availability_path=root / "availability.csv",
            accounts_source_path=root / "data_input_accounts.csv",
        )

    def test_sync_paths_use_config_private_and_output(self) -> None:
        self.assertEqual(pokedex_sync_config_path(), config_dir() / "pokedex_sync.json")
        self.assertEqual(pokedex_sync_token_path(), private_dir() / "pokedex_sync_token.json")
        self.assertEqual(pokedex_sync_state_path(), output_dir() / "pokedex_sync_state.json")

    def test_missing_config_skips_without_touching_species(self) -> None:
        local = "keep-local".encode("utf-8")
        drive = _Drive(remote_bytes=b"remote-should-not-land")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self._sync(drive, root, species_bytes=local, folder_id=None)
            species = root / "pokedex_species_entries.csv"

            self.assertTrue(result["skipped"])
            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["reason"], "missing_config")
            self.assertEqual(result["species_action"], "untouched")
            self.assertEqual(species.read_bytes(), local)
            self.assertFalse((root / "pokedex_sync.json").exists())
            self.assertFalse((root / "pokedex_sync_state.json").exists())

        drive.service.files.assert_not_called()
        drive.service.permissions.assert_not_called()

    def test_blank_folder_id_skips_without_touching_species(self) -> None:
        local = "keep-local-blank".encode("utf-8")
        drive = _Drive(remote_bytes=b"remote-should-not-land")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "pokedex_sync.json"
            result = self._sync(drive, root, species_bytes=local, folder_id="   ", species_id="species-file")

            self.assertTrue(result["skipped"])
            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["reason"], "blank_folder_id")
            self.assertEqual(result["species_action"], "untouched")
            self.assertEqual((root / "pokedex_species_entries.csv").read_bytes(), local)
            self.assertEqual(json.loads(config.read_text(encoding="utf-8"))["folder_id"], "   ")
            self.assertFalse((root / "pokedex_sync_state.json").exists())

        drive.service.files.assert_not_called()
        drive.service.permissions.assert_not_called()

    def test_pending_upload_failure_keeps_local_species_and_flag(self) -> None:
        local = (
            "date,account,entry_type,dex_number,form,registered,can_evolve_now,notes\n"
            "2026-06-11,Cerius,pokemon,6,Alolan,true,false,keep\n"
        ).encode("utf-8-sig")
        drive = _Drive(modified_time="2099-01-01T00:00:00.000Z", remote_bytes=b"REMOTE-SHOULD-NOT-WIN")
        drive.fail_species_upload = True
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self._sync(
                drive,
                root,
                species_bytes=local,
                folder_id="folder-1",
                pending=True,
            )
            state = root / "pokedex_sync_state.json"

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["species_action"], "upload_failed")
            self.assertTrue(result["species_pending"])
            self.assertTrue(read_species_pending(state))
            self.assertEqual(json.loads(state.read_text(encoding="utf-8")), {"species_pending": True})
            self.assertEqual((root / "pokedex_species_entries.csv").read_bytes(), local)
            self.assertNotIn(SPECIES_SYNC_NAME, drive.uploaded)

        drive.service.files.return_value.get_media.assert_not_called()

    def test_pending_upload_success_clears_flag_without_download(self) -> None:
        local = (
            "date,account,entry_type,dex_number,form,registered,can_evolve_now,notes\n"
            "2026-06-11,Cerius,pokemon,6,Alolan,true,false,uploaded\n"
        ).encode("utf-8-sig")
        drive = _Drive(modified_time="2099-01-01T00:00:00.000Z", remote_bytes=b"REMOTE-SHOULD-NOT-WIN")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self._sync(
                drive,
                root,
                species_bytes=local,
                folder_id="folder-1",
                pending=True,
            )
            saved = json.loads((root / "pokedex_sync.json").read_text(encoding="utf-8"))

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "synced")
            self.assertEqual(result["species_action"], "uploaded")
            self.assertFalse(result["species_pending"])
            self.assertEqual(
                json.loads((root / "pokedex_sync_state.json").read_text(encoding="utf-8")),
                {"species_pending": False},
            )
            self.assertEqual((root / "pokedex_species_entries.csv").read_bytes(), local)
            self.assertEqual(drive.uploaded[SPECIES_SYNC_NAME], local)
            self.assertEqual(saved["files"][SPECIES_SYNC_NAME], "species-file")
            self.assertEqual(saved["files"][REFERENCE_SYNC_NAME], f"created-{REFERENCE_SYNC_NAME}")
            self.assertEqual(saved["files"][ACCOUNTS_SYNC_NAME], f"created-{ACCOUNTS_SYNC_NAME}")

        drive.service.files.return_value.get_media.assert_not_called()
        drive.service.permissions.return_value.create.assert_not_called()

    def test_newer_remote_replaces_local_species_bytes(self) -> None:
        self.assertEqual(
            list(POKEDEX_SPECIES_ENTRY_COLUMNS),
            ["date", "account", "entry_type", "dex_number", "form", "registered", "can_evolve_now", "notes"],
        )
        local = b"local-older-species"
        remote = (
            "date,account,entry_type,dex_number,form,registered,can_evolve_now,notes\r\n"
            "2026-06-11,Cerius,pokemon,6,Party Hat,true,false,café\r\n"
        ).encode("utf-8-sig")
        self.assertTrue(remote.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"form", remote)
        drive = _Drive(modified_time="2026-10-22T12:00:00.000Z", remote_bytes=remote)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self._sync(
                drive,
                root,
                species_bytes=local,
                folder_id="folder-1",
                pending=False,
                mtime=datetime(2020, 1, 1, tzinfo=timezone.utc),
            )

            self.assertEqual(result["species_action"], "downloaded")
            self.assertFalse(result["species_pending"])
            self.assertEqual((root / "pokedex_species_entries.csv").read_bytes(), remote)
            self.assertNotIn(SPECIES_SYNC_NAME, drive.uploaded)

    def test_older_remote_keeps_newer_local_species(self) -> None:
        local = (
            "date,account,entry_type,dex_number,form,registered,can_evolve_now,notes\n"
            "2026-08-01,Thombay,shiny,25,Party Hat,true,false,local-wins\n"
        ).encode("utf-8-sig")
        drive = _Drive(modified_time="2020-01-01T00:00:00.000Z", remote_bytes=b"REMOTE-SHOULD-NOT-WIN")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self._sync(
                drive,
                root,
                species_bytes=local,
                folder_id="folder-1",
                pending=False,
                mtime=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )

            self.assertEqual(result["species_action"], "unchanged")
            self.assertEqual((root / "pokedex_species_entries.csv").read_bytes(), local)

        drive.service.files.return_value.get_media.assert_not_called()

    def test_reference_builder_emits_one_row_per_kind(self) -> None:
        catalog = pd.DataFrame(
            [
                {
                    "dex_number": 1,
                    "name": "Bulbasaur",
                    "german_name": "Bisasam",
                    "region": "kanto",
                    "available_in_pogo": "yes",
                    "location_restriction": "Route 1",
                    "last_event": "Community Day",
                },
                {
                    "dex_number": 83,
                    "name": "Farfetch'd",
                    "german_name": "Porenta",
                    "region": "kanto",
                    "available_in_pogo": "yes",
                    "location_restriction": "",
                    "last_event": "",
                },
                {
                    "dex_number": 50,
                    "name": "Diglett",
                    "german_name": "Digda",
                    "region": "overall",
                    "available_in_pogo": "yes",
                    "location_restriction": "",
                    "last_event": "",
                },
                {
                    "dex_number": 1025,
                    "name": "Pecharunt",
                    "german_name": "Infamomo",
                    "region": "paldea",
                    "available_in_pogo": "no",
                    "location_restriction": "",
                    "last_event": "",
                },
            ]
        )
        availability = pd.DataFrame(
            [
                {"entry_type": "shiny", "dex_number": 1, "form": "", "available": False},
                {"entry_type": "shiny", "dex_number": 1025, "form": "A", "available": True},
                {"entry_type": "shadow", "dex_number": 1, "form": "Galarian", "available": True},
                {"entry_type": "shadow", "dex_number": 1, "form": "Alolan", "available": True},
                {"entry_type": "shadow", "dex_number": 83, "form": "", "available": True},
            ]
        )

        frame = build_pokedex_atlas_reference(catalog, availability)

        self.assertEqual(list(frame.columns), POKEDEX_ATLAS_REFERENCE_COLUMNS)
        self.assertNotIn(50, set(frame["dex_number"].tolist()))
        self.assertEqual(set(frame["available"].tolist()), {"true", "false"})
        kind_ids = [kind for kind, _label in ATLAS_ENTRY_KINDS]
        bulbasaur = frame[frame["dex_number"] == 1]
        self.assertEqual(bulbasaur["entry_type"].tolist(), [*kind_ids[:-2], "shadow", "shadow", kind_ids[-1]])
        self.assertEqual(
            bulbasaur["entry_type_label"].tolist(),
            ["Pokemon", "Shiny", "100%", "Lucky", "XXL", "XXS", "Shadow", "Shadow", "Purified"],
        )
        by_kind = {str(row.entry_type): row for row in bulbasaur.itertuples(index=False) if row.entry_type != "shadow"}
        self.assertEqual(by_kind["pokemon"].available, "true")
        self.assertEqual(by_kind["pokemon"].form, "")
        self.assertEqual(by_kind["pokemon"].region_label, "Kanto")
        self.assertEqual(by_kind["pokemon"].german_name, "Bisasam")
        self.assertEqual(by_kind["pokemon"].location_restriction, "Route 1")
        self.assertEqual(by_kind["pokemon"].last_event, "Community Day")
        self.assertEqual(by_kind["shiny"].available, "false")
        self.assertEqual(by_kind["shiny"].form, "")
        shadow = bulbasaur[bulbasaur["entry_type"] == "shadow"]
        self.assertEqual(shadow["form"].tolist(), ["Alolan", "Galarian"])
        self.assertEqual(shadow["available"].tolist(), ["true", "true"])

        farfetchd = frame[frame["dex_number"] == 83].set_index("entry_type")
        self.assertEqual(list(farfetchd.index), kind_ids)
        self.assertEqual(farfetchd.loc["pokemon", "available"], "true")
        self.assertEqual(farfetchd.loc["pokemon", "location_restriction"], "East Asia")
        self.assertEqual(farfetchd.loc["pokemon", "region_label"], "Kanto")
        self.assertEqual(farfetchd.loc["shiny", "available"], "false")
        self.assertEqual(farfetchd.loc["shadow", "form"], "")
        self.assertEqual(farfetchd.loc["shadow", "available"], "true")

        pecharunt = frame[frame["dex_number"] == 1025]
        self.assertEqual(pecharunt["entry_type"].tolist(), kind_ids)
        self.assertEqual(set(pecharunt["available"].tolist()), {"false"})
        self.assertEqual(set(pecharunt["form"].tolist()), {""})
        self.assertEqual(pecharunt.iloc[0]["region_label"], "Paldea")
        self.assertEqual(pecharunt.iloc[0]["name"], "Pecharunt")

    def test_account_file_lists_enabled_pokedex_accounts_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "missing.csv"
            self.assertEqual(pokedex_sync_account_names(missing), [])

            long_form = root / "long.csv"
            pd.DataFrame(
                [
                    {"input_type": "pokedex", "account": "Cerius", "enabled": "yes", "notes": ""},
                    {"input_type": "xp", "account": "Babsi", "enabled": "yes", "notes": ""},
                    {"input_type": "pokedex", "account": "Thombay", "enabled": "no", "notes": ""},
                    {"input_type": "pokedex", "account": "Thomzay", "enabled": "true", "notes": ""},
                    {"input_type": "medal", "account": "Azog", "enabled": "yes", "notes": ""},
                ]
            ).to_csv(long_form, index=False, encoding="utf-8-sig")
            names = pokedex_sync_account_names(long_form)
            self.assertEqual(names, ["Cerius", "Thomzay"])
            raw = pokedex_accounts_csv_bytes(names)
            self.assertEqual(list(POKEDEX_ACCOUNTS_COLUMNS), ["account"])
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            self.assertEqual(raw.decode("utf-8-sig").splitlines(), ["account", "Cerius", "Thomzay"])

            account_centric = root / "centric.csv"
            pd.DataFrame(
                [
                    {"account": "Thombay", "input_types": "xp;medal;pokedex", "notes": ""},
                    {"account": "Cerius", "input_types": "xp", "notes": ""},
                    {"account": "Thomzay", "input_types": "pokedex;xp", "notes": ""},
                ]
            ).to_csv(account_centric, index=False, encoding="utf-8-sig")
            self.assertEqual(pokedex_sync_account_names(account_centric), ["Thombay", "Thomzay"])

    def test_sync_does_not_share_files_publicly(self) -> None:
        local = b"local-species"
        drive = _Drive(modified_time="2020-01-01T00:00:00.000Z", remote_bytes=b"REMOTE-SHOULD-NOT-WIN")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pd.DataFrame(
                [
                    {
                        "dex_number": 1,
                        "name": "Bulbasaur",
                        "german_name": "Bisasam",
                        "region": "kanto",
                        "type_1": "grass",
                        "type_2": "poison",
                        "available_in_pogo": "yes",
                        "location_restriction": "",
                        "last_event": "",
                        "last_event_date": "",
                        "extra_info": "",
                    }
                ]
            ).to_csv(root / "catalog.csv", index=False, encoding="utf-8-sig")
            pd.DataFrame(
                [
                    {"account": "Cerius", "input_types": "pokedex", "notes": ""},
                    {"account": "Babsi", "input_types": "xp", "notes": ""},
                    {"account": "Thomzay", "input_types": "xp;pokedex", "notes": ""},
                ]
            ).to_csv(root / "data_input_accounts.csv", index=False, encoding="utf-8-sig")
            result = self._sync(drive, root, species_bytes=local, folder_id="folder-1", pending=False)

            self.assertEqual(result["species_action"], "unchanged")
            self.assertEqual((root / "pokedex_species_entries.csv").read_bytes(), local)
            self.assertNotIn(SPECIES_SYNC_NAME, drive.uploaded)
            reference = drive.uploaded[REFERENCE_SYNC_NAME].decode("utf-8-sig").splitlines()
            self.assertEqual(reference[0], ",".join(POKEDEX_ATLAS_REFERENCE_COLUMNS))
            self.assertIn("Bulbasaur", "\n".join(reference))
            self.assertIn("Kanto", "\n".join(reference))
            self.assertEqual(
                drive.uploaded[ACCOUNTS_SYNC_NAME].decode("utf-8-sig").splitlines(),
                ["account", "Cerius", "Thomzay"],
            )

        drive.service.permissions.assert_not_called()
        drive.service.permissions.return_value.create.assert_not_called()

    def test_sync_credentials_use_full_drive_scope(self) -> None:
        self.assertEqual(POKEDEX_SYNC_SCOPES, ["https://www.googleapis.com/auth/drive"])
        self.assertEqual(SCOPES, ["https://www.googleapis.com/auth/drive.file"])
        with tempfile.TemporaryDirectory() as tmp:
            token = Path(tmp) / "pokedex_sync_token.json"
            credentials = Path(tmp) / "google_drive_credentials.json"
            token.write_text("{}", encoding="utf-8")
            valid = MagicMock()
            valid.expired = False
            valid.valid = True
            with patch("webapp.pokedex_sync.Credentials") as mock_creds:
                mock_creds.from_authorized_user_file.return_value = valid
                loaded = load_pokedex_sync_credentials(
                    credentials_path=credentials,
                    token_path=token,
                    interactive=False,
                )
            self.assertIs(loaded, valid)
            mock_creds.from_authorized_user_file.assert_called_once_with(str(token), POKEDEX_SYNC_SCOPES)

    def test_ensure_folder_creates_private_folder_when_id_blank(self) -> None:
        service = MagicMock()
        service.files.return_value.list.return_value.execute.return_value = {"files": []}
        service.files.return_value.create.return_value.execute.return_value = {
            "id": "folder-sync",
            "name": "PoGo Sync",
        }

        updated = ensure_pokedex_sync_folder(service, default_pokedex_sync_config())

        self.assertEqual(updated["folder_id"], "folder-sync")
        body = service.files.return_value.create.call_args.kwargs["body"]
        self.assertEqual(body["name"], "PoGo Sync")
        self.assertEqual(body["mimeType"], "application/vnd.google-apps.folder")
        service.permissions.return_value.create.assert_not_called()

        existing = default_pokedex_sync_config()
        existing["folder_id"] = "already"
        untouched = MagicMock()
        self.assertEqual(ensure_pokedex_sync_folder(untouched, existing)["folder_id"], "already")
        untouched.files.assert_not_called()

    def test_connect_module_imports_without_network(self) -> None:
        import tools.pokedex_sync_connect as connect

        self.assertTrue(callable(connect.main))

    def test_run_configured_sync_skips_when_token_is_missing(self) -> None:
        with (
            patch("webapp.pokedex_sync.build_pokedex_sync_service", side_effect=FileNotFoundError("missing token")),
            patch("webapp.pokedex_sync.sync_pokedex") as sync,
        ):
            result = run_configured_sync()

        sync.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "missing_token")
        self.assertEqual(result["errors"], [])
        self.assertEqual(pokedex_sync_status_line(result), "Pokedex sync: skipped (missing_token)")
        self.assertEqual(
            pokedex_sync_status_line({"status": "synced", "species_action": "uploaded"}),
            "Pokedex sync: synced (species uploaded)",
        )

    def test_run_configured_sync_returns_error_without_raising(self) -> None:
        with patch("webapp.pokedex_sync.build_pokedex_sync_service", side_effect=RuntimeError("drive down")):
            result = run_configured_sync()

        self.assertFalse(result["ok"])
        self.assertFalse(result["skipped"])
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["errors"], ["drive down"])
        self.assertEqual(pokedex_sync_status_line(result), "Pokedex sync: error (drive down)")

    def test_publish_local_species_save_keeps_pending_when_species_upload_fails(self) -> None:
        local = (
            "date,account,entry_type,dex_number,form,registered,can_evolve_now,notes\n"
            "2026-06-11,Cerius,pokemon,6,Alolan,true,false,keep\n"
        ).encode("utf-8-sig")
        drive = _Drive(modified_time="2099-01-01T00:00:00.000Z", remote_bytes=b"REMOTE-SHOULD-NOT-WIN")
        drive.fail_species_upload = True
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            species = root / "pokedex_species_entries.csv"
            species.write_bytes(local)
            config = root / "pokedex_sync.json"
            state = root / "pokedex_sync_state.json"
            _write_config(config, "folder-1", species_id="species-file")
            pending_before_sync: list[bool] = []

            def build_service() -> MagicMock:
                pending_before_sync.append(read_species_pending(state))
                return drive.service

            with (
                patch("webapp.pokedex_sync.build_pokedex_sync_service", side_effect=build_service),
                patch("webapp.pokedex_sync.pokedex_sync_config_path", return_value=config),
                patch("webapp.pokedex_sync.pokedex_sync_state_path", return_value=state),
                patch("webapp.pokedex_sync.pokedex_species_entries_path", return_value=species),
                patch("webapp.pokedex_sync.pokemon_catalog_path", return_value=root / "catalog.csv"),
                patch("webapp.pokedex_sync.pokedex_category_availability_path", return_value=root / "availability.csv"),
                patch("webapp.pokedex_sync.data_input_accounts_path", return_value=root / "accounts.csv"),
            ):
                result = publish_local_species_save()

            self.assertEqual(pending_before_sync, [True])
            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["species_action"], "upload_failed")
            self.assertTrue(result["species_pending"])
            self.assertTrue(read_species_pending(state))
            self.assertEqual(json.loads(state.read_text(encoding="utf-8")), {"species_pending": True})
            self.assertEqual(species.read_bytes(), local)
            self.assertNotIn(SPECIES_SYNC_NAME, drive.uploaded)


if __name__ == "__main__":
    unittest.main()
