from __future__ import annotations

import subprocess
import unittest
from unittest.mock import MagicMock, patch

import run_server


class RunServerTest(unittest.TestCase):
    @patch("run_server.free_dashboard_port", return_value=0)
    @patch("run_server.subprocess.Popen")
    @patch("run_server.subprocess.run")
    def test_starts_streamlit_after_successful_connect(self, mock_run, mock_popen, mock_free):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        proc = MagicMock()
        proc.wait.return_value = 0
        mock_popen.return_value = proc

        self.assertEqual(run_server.main(), 0)

        mock_run.assert_called_once()
        connect_cmd = mock_run.call_args.args[0]
        self.assertTrue(connect_cmd[-1].replace("\\", "/").endswith("tools/google_drive_connect.py"))
        mock_popen.assert_called_once()
        streamlit_cmd = mock_popen.call_args.args[0]
        self.assertIn("streamlit", streamlit_cmd)
        self.assertEqual(mock_free.call_args.args[0], 8502)

    @patch("run_server.free_dashboard_port", return_value=0)
    @patch("run_server.subprocess.Popen")
    @patch("run_server.subprocess.run")
    def test_skips_streamlit_when_connect_fails(self, mock_run, mock_popen, mock_free):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1)

        self.assertEqual(run_server.main(), 1)
        mock_popen.assert_not_called()
        mock_free.assert_not_called()

    @patch("run_server.free_dashboard_port", return_value=1)
    @patch("run_server.subprocess.Popen")
    @patch("run_server.subprocess.run")
    def test_skips_streamlit_when_port_stays_busy(self, mock_run, mock_popen, _mock_free):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        self.assertEqual(run_server.main(), 1)
        mock_popen.assert_not_called()

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
