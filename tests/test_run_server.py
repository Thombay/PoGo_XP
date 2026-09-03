from __future__ import annotations

import subprocess
import unittest
from unittest.mock import MagicMock, patch

import run_server


class RunServerTest(unittest.TestCase):
    @patch("run_server.subprocess.Popen")
    @patch("run_server.subprocess.run")
    def test_starts_streamlit_after_successful_connect(self, mock_run, mock_popen):
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

    @patch("run_server.subprocess.Popen")
    @patch("run_server.subprocess.run")
    def test_skips_streamlit_when_connect_fails(self, mock_run, mock_popen):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1)

        self.assertEqual(run_server.main(), 1)
        mock_popen.assert_not_called()
