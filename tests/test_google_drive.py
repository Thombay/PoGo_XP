from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from google.auth.exceptions import RefreshError

from webapp.google_drive import (
    DEFAULT_EXPORT_FILE_NAME,
    dashboard_matches_export_kind,
    default_google_drive_exports_config,
    enabled_export_targets,
    format_publish_summary,
    load_google_drive_credentials,
    load_google_drive_exports_config,
    publish_html_exports,
    save_google_drive_exports_config,
    setup_google_drive_folder_structure,
    upload_or_update_file,
)


class GoogleDriveHelpersTest(unittest.TestCase):
    def test_default_config_includes_dashboard_group_exports(self):
        config = default_google_drive_exports_config(
            dashboards={
                "Dashboard Global": ["All", "Family"],
                "Dashboard Personal": ["OwnAccounts"],
            }
        )

        self.assertEqual(config["root_folder_name"], "PoGo")
        self.assertEqual(config["share_mode"], "anyone_with_link")
        self.assertEqual(len(config["exports"]), 3)
        self.assertEqual(config["exports"][0]["file_name"], DEFAULT_EXPORT_FILE_NAME)
        self.assertEqual(config["exports"][1]["group"], "Family")

    def test_default_config_includes_medal_dashboard(self):
        config = default_google_drive_exports_config()
        medal_rows = [row for row in config["exports"] if row["dashboard"] == "Medal Dashboard"]
        self.assertEqual([row["group"] for row in medal_rows], ["OwnAccounts", "Ich"])

    def test_config_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "google_drive_exports.json"
            config = default_google_drive_exports_config(
                dashboards={"Dashboard Global": ["All"]}
            )
            config["root_folder_id"] = "root-1"
            config["exports"][0]["folder_id"] = "folder-1"
            save_google_drive_exports_config(config, path=path)

            loaded = load_google_drive_exports_config(path)

        self.assertEqual(loaded["root_folder_id"], "root-1")
        self.assertEqual(loaded["exports"][0]["folder_id"], "folder-1")
        self.assertEqual(enabled_export_targets(loaded)[0]["group"], "All")

    def test_enabled_export_targets_requires_folder_id(self):
        config = default_google_drive_exports_config(dashboards={"Dashboard Global": ["All", "Family"]})
        config["exports"][0]["folder_id"] = "folder-all"
        config["exports"][1]["enabled"] = False

        targets = enabled_export_targets(config)

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["group"], "All")

    def test_export_kind_separates_medal_and_xp_dashboards(self):
        self.assertTrue(dashboard_matches_export_kind("Medal Dashboard", "medal"))
        self.assertFalse(dashboard_matches_export_kind("Dashboard Global", "medal"))
        self.assertFalse(dashboard_matches_export_kind("Medal Dashboard", "xp"))
        self.assertTrue(dashboard_matches_export_kind("Dashboard Personal", "xp"))
        self.assertTrue(dashboard_matches_export_kind("Medal Dashboard", "all"))

        config = default_google_drive_exports_config()
        for row in config["exports"]:
            row["folder_id"] = f"folder-{row['dashboard']}-{row['group']}"

        medal_targets = enabled_export_targets(config, kind="medal")
        xp_targets = enabled_export_targets(config, kind="xp")

        self.assertEqual({row["dashboard"] for row in medal_targets}, {"Medal Dashboard"})
        self.assertEqual(
            {row["dashboard"] for row in xp_targets},
            {"Dashboard Global", "Dashboard Personal"},
        )

    def test_setup_google_drive_folder_structure_reuses_existing_folders(self):
        service = MagicMock()
        existing_root = {"id": "root-id", "name": "PoGo"}
        existing_dashboard = {"id": "dash-id", "name": "Dashboard Global"}
        existing_group = {"id": "group-id", "name": "All"}

        def list_side_effect(**kwargs):
            query = kwargs.get("q", "")
            if "name = 'PoGo'" in query:
                return MagicMock(execute=MagicMock(return_value={"files": [existing_root]}))
            if "name = 'Dashboard Global'" in query:
                return MagicMock(execute=MagicMock(return_value={"files": [existing_dashboard]}))
            if "name = 'All'" in query:
                return MagicMock(execute=MagicMock(return_value={"files": [existing_group]}))
            return MagicMock(execute=MagicMock(return_value={"files": []}))

        service.files.return_value.list.side_effect = list_side_effect

        config = default_google_drive_exports_config(dashboards={"Dashboard Global": ["All"]})
        updated = setup_google_drive_folder_structure(service, config=config)

        self.assertEqual(updated["root_folder_id"], "root-id")
        self.assertEqual(updated["exports"][0]["folder_id"], "group-id")
        service.files.return_value.create.assert_not_called()

    def test_upload_or_update_file_updates_existing_by_id(self):
        service = MagicMock()
        service.files.return_value.update.return_value.execute.return_value = {
            "id": "file-123",
            "name": "dashboard.html",
            "webViewLink": "https://drive.google.com/file/d/file-123/view",
        }

        result = upload_or_update_file(
            service,
            parent_folder_id="folder-1",
            file_name="dashboard.html",
            content=b"<html>updated</html>",
            file_id="file-123",
            share_mode="restricted",
        )

        self.assertEqual(result["id"], "file-123")
        service.files.return_value.update.assert_called_once()
        service.files.return_value.create.assert_not_called()
        service.permissions.return_value.create.assert_not_called()

    def test_upload_or_update_file_creates_and_shares_public_link(self):
        service = MagicMock()
        service.files.return_value.create.return_value.execute.return_value = {
            "id": "file-new",
            "name": "dashboard.html",
            "webViewLink": "https://drive.google.com/file/d/file-new/view",
        }

        result = upload_or_update_file(
            service,
            parent_folder_id="folder-1",
            file_name="dashboard.html",
            content=b"<html>new</html>",
            file_id=None,
            share_mode="anyone_with_link",
        )

        self.assertEqual(result["id"], "file-new")
        service.files.return_value.create.assert_called_once()
        service.permissions.return_value.create.assert_called_once()
        body = service.permissions.return_value.create.call_args.kwargs["body"]
        self.assertEqual(body, {"type": "anyone", "role": "reader"})

    def test_publish_html_exports_updates_file_ids_and_links(self):
        service = MagicMock()
        service.files.return_value.create.return_value.execute.return_value = {
            "id": "file-1",
            "name": "dashboard.html",
            "webViewLink": "https://drive.example/file-1",
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "google_drive_exports.json"
            config = default_google_drive_exports_config(dashboards={"Dashboard Global": ["All"]})
            config["exports"][0]["folder_id"] = "folder-1"

            def build_html(dashboard: str, group: str, export_mode: str, window_days: int) -> str:
                return f"<html>{dashboard}:{group}:{export_mode}:{window_days}</html>"

            result = publish_html_exports(service, config, build_html=build_html, config_path=path)
            saved = load_google_drive_exports_config(path)

        self.assertTrue(result["ok"])
        self.assertEqual(result["uploaded"], 1)
        self.assertEqual(saved["exports"][0]["file_id"], "file-1")
        self.assertEqual(saved["exports"][0]["web_view_link"], "https://drive.example/file-1")
        self.assertIn("Dashboard Global / All", format_publish_summary(result))

    def test_publish_html_exports_reports_progress_per_file(self):
        service = MagicMock()
        service.files.return_value.create.return_value.execute.return_value = {
            "id": "file-1",
            "name": "dashboard.html",
            "webViewLink": "https://drive.example/file-1",
        }
        seen: list[str] = []

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "google_drive_exports.json"
            config = default_google_drive_exports_config(dashboards={"Dashboard Global": ["All", "Family"]})
            config["exports"][0]["folder_id"] = "folder-all"
            config["exports"][1]["folder_id"] = "folder-family"
            publish_html_exports(
                service,
                config,
                build_html=lambda *_args: "<html>ok</html>",
                config_path=path,
                on_progress=seen.append,
            )

        self.assertEqual(
            seen,
            ["Google Drive: Dashboard Global / All", "Google Drive: Dashboard Global / Family"],
        )

    def test_publish_html_exports_kind_medal_skips_other_dashboards(self):
        service = MagicMock()
        service.files.return_value.create.return_value.execute.return_value = {
            "id": "medal-file",
            "name": "dashboard.html",
            "webViewLink": "https://drive.example/medal-file",
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "google_drive_exports.json"
            config = default_google_drive_exports_config(
                dashboards={
                    "Dashboard Global": ["All"],
                    "Medal Dashboard": ["Ich"],
                }
            )
            config["exports"][0]["folder_id"] = "folder-global"
            config["exports"][1]["folder_id"] = "folder-medal"

            built: list[tuple[str, str]] = []

            def build_html(dashboard: str, group: str, export_mode: str, window_days: int) -> str:
                built.append((dashboard, group))
                return f"<html>{dashboard}:{group}</html>"

            result = publish_html_exports(
                service,
                config,
                build_html=build_html,
                config_path=path,
                kind="medal",
            )
            saved = load_google_drive_exports_config(path)

        self.assertTrue(result["ok"])
        self.assertEqual(result["uploaded"], 1)
        self.assertEqual(built, [("Medal Dashboard", "Ich")])
        self.assertEqual(saved["exports"][0]["file_id"], "")
        self.assertEqual(saved["exports"][1]["file_id"], "medal-file")

    def test_publish_html_exports_keeps_existing_file_id_on_update(self):
        service = MagicMock()
        service.files.return_value.update.return_value.execute.return_value = {
            "id": "stable-file",
            "name": "dashboard.html",
            "webViewLink": "https://drive.example/stable-file",
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "google_drive_exports.json"
            config = default_google_drive_exports_config(dashboards={"Dashboard Global": ["Family"]})
            config["exports"][0]["folder_id"] = "folder-family"
            config["exports"][0]["file_id"] = "stable-file"
            config["exports"][0]["web_view_link"] = "https://drive.example/stable-file"

            result = publish_html_exports(
                service,
                config,
                build_html=lambda *_args: "<html>again</html>",
                config_path=path,
            )
            saved = load_google_drive_exports_config(path)

        self.assertTrue(result["ok"])
        self.assertEqual(saved["exports"][0]["file_id"], "stable-file")
        self.assertEqual(saved["exports"][0]["web_view_link"], "https://drive.example/stable-file")
        service.files.return_value.update.assert_called_once()
        service.files.return_value.create.assert_not_called()

    def test_publish_create_then_update_keeps_stable_link(self):
        """First publish creates; second publish updates same file_id so links stay stable."""
        service = MagicMock()
        stable_link = "https://drive.example/file/stable-abc"
        service.files.return_value.create.return_value.execute.return_value = {
            "id": "stable-abc",
            "name": "dashboard.html",
            "webViewLink": stable_link,
        }
        service.files.return_value.update.return_value.execute.return_value = {
            "id": "stable-abc",
            "name": "dashboard.html",
            "webViewLink": stable_link,
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "google_drive_exports.json"
            config = default_google_drive_exports_config(dashboards={"Dashboard Global": ["All"]})
            config["exports"][0]["folder_id"] = "folder-all"

            first = publish_html_exports(
                service,
                config,
                build_html=lambda *_args: "<html>v1</html>",
                config_path=path,
            )
            after_create = load_google_drive_exports_config(path)
            second = publish_html_exports(
                service,
                after_create,
                build_html=lambda *_args: "<html>v2</html>",
                config_path=path,
            )
            after_update = load_google_drive_exports_config(path)

        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertEqual(after_create["exports"][0]["file_id"], "stable-abc")
        self.assertEqual(after_update["exports"][0]["file_id"], "stable-abc")
        self.assertEqual(after_create["exports"][0]["web_view_link"], stable_link)
        self.assertEqual(after_update["exports"][0]["web_view_link"], stable_link)
        service.files.return_value.create.assert_called_once()
        service.files.return_value.update.assert_called_once()

    def test_load_credentials_refresh_error_noninteractive_asks_reconnect(self):
        with tempfile.TemporaryDirectory() as tmp:
            tok_path = Path(tmp) / "google_drive_token.json"
            creds_path = Path(tmp) / "google_drive_credentials.json"
            tok_path.write_text("{}", encoding="utf-8")
            stale = MagicMock()
            stale.expired = True
            stale.refresh_token = "stale-refresh"
            stale.valid = False
            stale.refresh.side_effect = RefreshError(
                "invalid_grant: Bad Request",
                {"error": "invalid_grant", "error_description": "Bad Request"},
            )

            with patch("webapp.google_drive.Credentials") as mock_creds_cls:
                mock_creds_cls.from_authorized_user_file.return_value = stale
                with self.assertRaises(FileNotFoundError) as ctx:
                    load_google_drive_credentials(
                        credentials_path=creds_path,
                        token_path=tok_path,
                        interactive=False,
                    )

            self.assertIn("google_drive_connect.py", str(ctx.exception))
            self.assertFalse(tok_path.exists())

    def test_load_credentials_refresh_error_interactive_reauths(self):
        with tempfile.TemporaryDirectory() as tmp:
            tok_path = Path(tmp) / "google_drive_token.json"
            creds_path = Path(tmp) / "google_drive_credentials.json"
            tok_path.write_text("{}", encoding="utf-8")
            creds_path.write_text("{}", encoding="utf-8")
            stale = MagicMock()
            stale.expired = True
            stale.refresh_token = "stale-refresh"
            stale.valid = False
            stale.refresh.side_effect = RefreshError(
                "invalid_grant: Bad Request",
                {"error": "invalid_grant", "error_description": "Bad Request"},
            )
            fresh = MagicMock()
            fresh.to_json.return_value = '{"token": "new"}'
            flow = MagicMock()
            flow.run_local_server.return_value = fresh

            with patch("webapp.google_drive.Credentials") as mock_creds_cls:
                mock_creds_cls.from_authorized_user_file.return_value = stale
                with patch("webapp.google_drive.InstalledAppFlow") as mock_flow_cls:
                    mock_flow_cls.from_client_secrets_file.return_value = flow
                    result = load_google_drive_credentials(
                        credentials_path=creds_path,
                        token_path=tok_path,
                        interactive=True,
                    )

            self.assertIs(result, fresh)
            flow.run_local_server.assert_called_once()
            kwargs = flow.run_local_server.call_args.kwargs
            self.assertEqual(kwargs.get("access_type"), "offline")
            self.assertEqual(kwargs.get("prompt"), "consent")
            self.assertEqual(tok_path.read_text(encoding="utf-8"), '{"token": "new"}')

    def test_load_credentials_successful_refresh_saves_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            tok_path = Path(tmp) / "google_drive_token.json"
            creds_path = Path(tmp) / "google_drive_credentials.json"
            tok_path.write_text("{}", encoding="utf-8")
            refreshed = MagicMock()
            refreshed.expired = True
            refreshed.refresh_token = "refresh"
            refreshed.valid = True
            refreshed.to_json.return_value = '{"token": "refreshed"}'

            with patch("webapp.google_drive.Credentials") as mock_creds_cls:
                mock_creds_cls.from_authorized_user_file.return_value = refreshed
                result = load_google_drive_credentials(
                    credentials_path=creds_path,
                    token_path=tok_path,
                    interactive=False,
                )

            self.assertIs(result, refreshed)
            refreshed.refresh.assert_called_once()
            self.assertEqual(tok_path.read_text(encoding="utf-8"), '{"token": "refreshed"}')


if __name__ == "__main__":
    unittest.main()
