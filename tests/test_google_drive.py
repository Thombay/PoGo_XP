from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from webapp.google_drive import (
    DEFAULT_EXPORT_FILE_NAME,
    default_google_drive_exports_config,
    enabled_export_targets,
    format_publish_summary,
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


if __name__ == "__main__":
    unittest.main()
