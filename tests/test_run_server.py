from __future__ import annotations

import subprocess
import unittest
from unittest.mock import MagicMock, patch

import run_server

_SKIPPED_SYNC = {
    "ok": True,
    "skipped": True,
    "status": "skipped",
    "reason": "missing_token",
    "species_action": "untouched",
    "errors": [],
}


class RunServerTest(unittest.TestCase):
    @patch("run_server.run_configured_sync", return_value=_SKIPPED_SYNC)
    @patch("run_server.free_dashboard_port", return_value=0)
    @patch("run_server.subprocess.Popen")
    @patch("run_server.subprocess.run")
    def test_starts_streamlit_after_successful_connect(self, mock_run, mock_popen, mock_free, mock_sync):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        proc = MagicMock()
        proc.wait.return_value = 0
        mock_popen.return_value = proc

        self.assertEqual(run_server.main(), 0)

        self.assertEqual(mock_run.call_count, 2)
        connect_cmd = mock_run.call_args_list[0].args[0]
        catalog_cmd = mock_run.call_args_list[1].args[0]
        self.assertTrue(connect_cmd[-1].replace("\\", "/").endswith("tools/google_drive_connect.py"))
        self.assertTrue(catalog_cmd[-1].replace("\\", "/").endswith("tools/update_pokemon_catalog.py"))
        mock_popen.assert_called_once()
        streamlit_cmd = mock_popen.call_args.args[0]
        self.assertIn("streamlit", streamlit_cmd)
        self.assertEqual(mock_free.call_args.args[0], 8502)
        mock_sync.assert_called_once_with()

    @patch("run_server.run_configured_sync", return_value=_SKIPPED_SYNC)
    @patch("run_server.free_dashboard_port", return_value=0)
    @patch("run_server.subprocess.Popen")
    @patch("run_server.subprocess.run")
    def test_starts_streamlit_when_catalog_refresh_fails(self, mock_run, mock_popen, mock_free, mock_sync):
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=0),
            subprocess.CompletedProcess(args=[], returncode=1),
        ]
        proc = MagicMock()
        proc.wait.return_value = 0
        mock_popen.return_value = proc

        self.assertEqual(run_server.main(), 0)

        self.assertEqual(mock_run.call_count, 2)
        connect_cmd = mock_run.call_args_list[0].args[0]
        catalog_cmd = mock_run.call_args_list[1].args[0]
        self.assertTrue(connect_cmd[-1].replace("\\", "/").endswith("tools/google_drive_connect.py"))
        self.assertTrue(catalog_cmd[-1].replace("\\", "/").endswith("tools/update_pokemon_catalog.py"))
        mock_popen.assert_called_once()
        self.assertIn("streamlit", mock_popen.call_args.args[0])
        self.assertEqual(mock_free.call_args.args[0], 8502)
        mock_sync.assert_called_once_with()

    @patch("run_server.run_configured_sync", return_value=_SKIPPED_SYNC)
    @patch("run_server.free_dashboard_port", return_value=0)
    @patch("run_server.subprocess.Popen")
    @patch("run_server.subprocess.run")
    def test_skips_streamlit_when_catalog_refresh_is_cancelled(self, mock_run, mock_popen, _mock_free, mock_sync):
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=0),
            KeyboardInterrupt(),
        ]

        self.assertEqual(run_server.main(), 130)
        mock_popen.assert_not_called()
        self.assertEqual(mock_run.call_count, 2)
        catalog_cmd = mock_run.call_args_list[1].args[0]
        self.assertTrue(catalog_cmd[-1].replace("\\", "/").endswith("tools/update_pokemon_catalog.py"))
        mock_sync.assert_not_called()

    @patch("run_server.run_configured_sync", return_value=_SKIPPED_SYNC)
    @patch("run_server.free_dashboard_port", return_value=0)
    @patch("run_server.subprocess.Popen")
    @patch("run_server.subprocess.run")
    def test_skips_streamlit_when_connect_fails(self, mock_run, mock_popen, mock_free, mock_sync):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1)

        self.assertEqual(run_server.main(), 1)
        mock_popen.assert_not_called()
        mock_free.assert_not_called()
        mock_run.assert_called_once()
        connect_cmd = mock_run.call_args.args[0]
        self.assertTrue(connect_cmd[-1].replace("\\", "/").endswith("tools/google_drive_connect.py"))
        mock_sync.assert_not_called()

    @patch("run_server.run_configured_sync", return_value=_SKIPPED_SYNC)
    @patch("run_server.free_dashboard_port", return_value=1)
    @patch("run_server.subprocess.Popen")
    @patch("run_server.subprocess.run")
    def test_skips_streamlit_when_port_stays_busy(self, mock_run, mock_popen, _mock_free, mock_sync):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        self.assertEqual(run_server.main(), 1)
        mock_popen.assert_not_called()
        mock_run.assert_called_once()
        connect_cmd = mock_run.call_args.args[0]
        self.assertTrue(connect_cmd[-1].replace("\\", "/").endswith("tools/google_drive_connect.py"))
        mock_sync.assert_not_called()

    @patch("run_server.run_configured_sync", side_effect=RuntimeError("drive down"))
    @patch("run_server.free_dashboard_port", return_value=0)
    @patch("run_server.subprocess.Popen")
    @patch("run_server.subprocess.run")
    def test_starts_streamlit_when_pokedex_sync_raises(self, mock_run, mock_popen, _mock_free, _mock_sync):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        proc = MagicMock()
        proc.wait.return_value = 0
        mock_popen.return_value = proc

        self.assertEqual(run_server.main(), 0)

        mock_popen.assert_called_once()
        self.assertEqual(mock_run.call_count, 2)
        connect_cmd = mock_run.call_args_list[0].args[0]
        catalog_cmd = mock_run.call_args_list[1].args[0]
        self.assertTrue(connect_cmd[-1].replace("\\", "/").endswith("tools/google_drive_connect.py"))
        self.assertTrue(catalog_cmd[-1].replace("\\", "/").endswith("tools/update_pokemon_catalog.py"))

    def test_netstat_parser_keeps_listen_rows_only(self):
        output = """
  TCP    127.0.0.1:8502         0.0.0.0:0              LISTENING       22032
  TCP    127.0.0.1:8502         127.0.0.1:51301        ESTABLISHED     22032
  TCP    127.0.0.1:8502         127.0.0.1:51301        HERGESTELLT     14564
  TCP    [::1]:8502             [::]:0                 ABHÖREN         99
  TCP    127.0.0.1:8503         0.0.0.0:0              LISTENING       7
"""
        self.assertEqual(run_server.listening_pids_from_netstat(output, 8502), {22032, 99})

    def test_recognizes_this_apps_streamlit_command(self):
        root = run_server.Path(r"C:\Users\thomashumitsch\Git_Projects\PoGo_XP")
        ours = (
            r"C:\Python312\python.exe -m streamlit run "
            r"C:\Users\thomashumitsch\Git_Projects\PoGo_XP\webapp\app.py "
            r"--server.address=127.0.0.1 --server.port=8502"
        )
        other = r"C:\Python312\python.exe -m streamlit run D:\other\webapp\app.py"
        self.assertTrue(run_server.is_our_streamlit(ours, root))
        self.assertFalse(run_server.is_our_streamlit(other, root))

    @patch("run_server._wait_until_gone", return_value=True)
    @patch("run_server._stop_process")
    @patch("run_server._command_line")
    @patch("run_server._listening_pids")
    def test_frees_only_previous_dashboard(self, mock_pids, mock_cmd, mock_stop, _mock_wait):
        root = run_server.Path(r"C:\repo")
        mock_pids.return_value = {10, 20}
        mock_cmd.side_effect = lambda pid: {
            10: r"C:\Python312\python.exe -m streamlit run C:\repo\webapp\app.py",
            20: r"C:\other\server.exe",
        }[pid]

        self.assertEqual(run_server.free_dashboard_port(8502, root), 1)
        mock_stop.assert_called_once_with(10)
