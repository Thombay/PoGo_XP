from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from webapp.github_pages import (
    export_pages_url,
    export_relative_dir,
    format_github_pages_summary,
    publish_html_to_github_pages,
    slugify_path_segment,
    write_export_site,
)


class GithubPagesHelpersTest(unittest.TestCase):
    def test_slugify_and_url_paths(self):
        self.assertEqual(slugify_path_segment("Dashboard Global"), "Dashboard-Global")
        self.assertEqual(slugify_path_segment("Papiermuehlgasse"), "Papiermuehlgasse")
        self.assertEqual(
            export_relative_dir("Dashboard Global", "Family").as_posix(),
            "Dashboard-Global/Family",
        )
        self.assertEqual(
            export_pages_url("https://thombay.github.io/PoGo_XP", "Dashboard Global", "Family"),
            "https://thombay.github.io/PoGo_XP/Dashboard-Global/Family/",
        )

    def test_write_export_site_creates_index_and_nojekyll(self):
        with tempfile.TemporaryDirectory() as tmp:
            site_dir = Path(tmp) / "site"
            written = write_export_site(
                site_dir,
                pages=[
                    {
                        "dashboard": "Dashboard Global",
                        "group": "All",
                        "html": "<html>all</html>",
                    }
                ],
            )

            self.assertTrue((site_dir / ".nojekyll").exists())
            self.assertEqual(
                (site_dir / "Dashboard-Global" / "All" / "index.html").read_text(encoding="utf-8"),
                "<html>all</html>",
            )
            self.assertEqual(written[0]["url_path"], "Dashboard-Global/All/")

    def test_publish_html_to_github_pages_without_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            site_dir = Path(tmp) / "site"
            result = publish_html_to_github_pages(
                targets=[{"dashboard": "Dashboard Personal", "group": "Ich", "enabled": True}],
                build_html=lambda dashboard, group, mode, days: f"<html>{dashboard}:{group}:{mode}:{days}</html>",
                export_mode="dark",
                window_days=7,
                site_dir=site_dir,
                push=False,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["uploaded"], 1)
        self.assertIn("Dashboard-Personal/Ich/", result["results"][0]["web_view_link"])
        self.assertIn("GitHub Pages exports updated: 1/1", format_github_pages_summary(result))

    def test_publish_respects_disabled_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            site_dir = Path(tmp) / "site"
            with patch("webapp.github_pages.load_github_pages_config") as mocked:
                from webapp.github_pages import GithubPagesConfig

                mocked.return_value = GithubPagesConfig(enabled=False)
                result = publish_html_to_github_pages(
                    targets=[{"dashboard": "Dashboard Global", "group": "All"}],
                    build_html=lambda *_args: "<html></html>",
                    export_mode="dark",
                    window_days=7,
                    site_dir=site_dir,
                    pages_config=None,
                    push=False,
                )

        self.assertTrue(result.get("skipped"))
        self.assertFalse(result.get("ok"))


if __name__ == "__main__":
    unittest.main()
