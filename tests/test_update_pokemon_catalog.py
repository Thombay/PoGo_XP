from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.update_pokemon_catalog import (
    build_seed_catalog,
    pogoapi_released_dex_numbers,
    update_catalog,
)


class PogoapiReleasedDexNumbersTest(unittest.TestCase):
    def test_empty_or_missing_released_list_raises(self) -> None:
        for released in (set(), None):
            with self.subTest(released=released):
                with self.assertRaises(RuntimeError) as caught:
                    pogoapi_released_dex_numbers(released)
                message = str(caught.exception)
                self.assertIn("PoGO API released_pokemon list was empty", message)
                self.assertIn("refusing to refresh availability from the game master", message)

    def test_non_empty_released_list_returns_ints(self) -> None:
        self.assertEqual(pogoapi_released_dex_numbers({1, 746}), {1, 746})


class BuildSeedCatalogTest(unittest.TestCase):
    def test_empty_released_list_raises_without_download(self) -> None:
        with patch(
            "tools.update_pokemon_catalog._read_url_text",
            side_effect=AssertionError("must not download"),
        ):
            with self.assertRaises(RuntimeError):
                build_seed_catalog(released_dex_numbers=set())


class UpdateCatalogTest(unittest.TestCase):
    def test_empty_released_list_does_not_write_catalog(self) -> None:
        original = "dex_number,name,available_in_pogo\n1,Bulbasaur,yes\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            catalog_path = Path(tmpdir) / "pokemon_catalog.csv"
            availability_path = Path(tmpdir) / "category_availability.csv"
            catalog_path.write_text(original, encoding="utf-8")
            with (
                patch(
                    "tools.update_pokemon_catalog.load_pogoapi_seed_data",
                    return_value={"released": set()},
                ),
                patch(
                    "tools.update_pokemon_catalog._read_url_text",
                    side_effect=AssertionError("must not download"),
                ),
            ):
                with self.assertRaises(RuntimeError):
                    update_catalog(catalog_path, availability_path=availability_path)
            self.assertEqual(catalog_path.read_text(encoding="utf-8"), original)
            self.assertFalse(availability_path.exists())


if __name__ == "__main__":
    unittest.main()
