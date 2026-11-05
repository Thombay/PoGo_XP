from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared.paths import pokemon_evolutions_path
from tools.update_pokemon_catalog import (
    build_seed_catalog,
    extract_evolution_edges,
    pogoapi_released_dex_numbers,
    update_catalog,
    update_pokemon_evolutions,
)
from webapp.data_files import POKEMON_EVOLUTION_COLUMNS, load_pokemon_evolutions


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


def _edge_rows(frame) -> list[tuple[int, int, str, str, str]]:
    return [
        (
            int(row.source_dex_number),
            int(row.target_dex_number),
            str(row.method),
            str(row.source_form),
            str(row.notes),
        )
        for row in frame.itertuples(index=False)
    ]


class ExtractEvolutionEdgesTest(unittest.TestCase):
    def test_fixture_keeps_candy_and_galarian_edges_only(self) -> None:
        payload = [
            {
                "templateId": "V0001_POKEMON_BULBASAUR",
                "data": {
                    "pokemonSettings": {
                        "pokemonId": "BULBASAUR",
                        "evolutionBranch": [
                            {"evolution": "IVYSAUR", "candyCost": 25, "form": "IVYSAUR_NORMAL"},
                            {"evolution": "BULBASAUR", "candyCost": 25},
                        ],
                    }
                },
            },
            {
                "templateId": "V0002_POKEMON_IVYSAUR",
                "data": {"pokemonSettings": {"pokemonId": "IVYSAUR"}},
            },
            {
                "templateId": "V0052_POKEMON_MEOWTH_GALARIAN",
                "data": {
                    "pokemonSettings": {
                        "pokemonId": "MEOWTH",
                        "form": "MEOWTH_GALARIAN",
                        "evolutionBranch": [
                            {
                                "evolution": "PERRSERKER",
                                "candyCost": 50,
                                "form": "PERRSERKER_NORMAL",
                            },
                        ],
                    }
                },
            },
            {
                "templateId": "V0863_POKEMON_PERRSERKER",
                "data": {"pokemonSettings": {"pokemonId": "PERRSERKER"}},
            },
            {
                "templateId": "V0003_POKEMON_VENUSAUR",
                "data": {
                    "pokemonSettings": {
                        "pokemonId": "VENUSAUR",
                        "evolutionBranch": [
                            {
                                "temporaryEvolution": "TEMP_EVOLUTION_MEGA",
                                "temporaryEvolutionEnergyCost": 200,
                            }
                        ],
                    }
                },
            },
        ]
        edges = extract_evolution_edges(payload)
        self.assertEqual(list(edges.columns), POKEMON_EVOLUTION_COLUMNS)
        self.assertEqual(
            _edge_rows(edges),
            [
                (1, 2, "candy", "", ""),
                (52, 863, "candy", "Galarian", ""),
            ],
        )

    def test_methods_forms_and_duplicate_method_preference(self) -> None:
        payload = [
            {
                "templateId": "V0044_POKEMON_GLOOM",
                "data": {
                    "pokemonSettings": {
                        "pokemonId": "GLOOM",
                        "evolutionBranch": [
                            {
                                "evolution": "VILEPLUME",
                                "evolutionItemRequirement": "ITEM_SUN_STONE",
                            }
                        ],
                    }
                },
            },
            {
                "templateId": "V0044_POKEMON_GLOOM",
                "data": {
                    "pokemonSettings": {
                        "pokemonId": "GLOOM",
                        "evolutionBranch": [
                            {"evolution": "VILEPLUME", "candyCost": 25},
                        ],
                    }
                },
            },
            {
                "templateId": "V0045_POKEMON_VILEPLUME",
                "data": {"pokemonSettings": {"pokemonId": "VILEPLUME"}},
            },
            {
                "templateId": "V0550_POKEMON_BASCULIN",
                "data": {
                    "pokemonSettings": {
                        "pokemonId": "BASCULIN",
                        "form": "BASCULIN_RED_STRIPED",
                        "evolutionBranch": [
                            {
                                "evolution": "BASCULEGION",
                                "form": "BASCULIN_WHITE_STRIPED",
                                "kmBuddyDistanceRequirement": 20,
                            }
                        ],
                    }
                },
            },
            {
                "templateId": "V0902_POKEMON_BASCULEGION",
                "data": {"pokemonSettings": {"pokemonId": "BASCULEGION"}},
            },
        ]
        edges = extract_evolution_edges(payload)
        self.assertEqual(
            _edge_rows(edges),
            [
                (44, 45, "Sun Stone", "", ""),
                (550, 902, "buddy 20 km", "White Striped", ""),
            ],
        )

    def test_species_dex_prefers_normal_form_then_lowest_dex(self) -> None:
        payload = [
            {
                "templateId": "V0007_POKEMON_SQUIRTLE",
                "data": {
                    "pokemonSettings": {
                        "pokemonId": "SQUIRTLE",
                        "evolutionBranch": [
                            {"evolution": "EEVEE", "candyCost": 25},
                            {"evolution": "ODDISH", "candyCost": 25},
                        ],
                    }
                },
            },
            {
                "templateId": "V0001_POKEMON_EEVEE",
                "data": {
                    "pokemonSettings": {
                        "pokemonId": "EEVEE",
                        "form": "EEVEE_COSTUME",
                    }
                },
            },
            {
                "templateId": "V0133_POKEMON_EEVEE",
                "data": {"pokemonSettings": {"pokemonId": "EEVEE"}},
            },
            {
                "templateId": "V0200_POKEMON_ODDISH",
                "data": {
                    "pokemonSettings": {
                        "pokemonId": "ODDISH",
                        "form": "ODDISH_A",
                    }
                },
            },
            {
                "templateId": "V0100_POKEMON_ODDISH",
                "data": {
                    "pokemonSettings": {
                        "pokemonId": "ODDISH",
                        "form": "ODDISH_B",
                    }
                },
            },
        ]
        edges = extract_evolution_edges(payload)
        self.assertEqual(
            _edge_rows(edges),
            [
                (7, 100, "candy", "", ""),
                (7, 133, "candy", "", ""),
            ],
        )

    def test_item_templates_and_template_wrappers(self) -> None:
        templates = [
            {
                "templateId": "V0001_POKEMON_BULBASAUR",
                "data": {
                    "pokemonSettings": {
                        "pokemonId": "BULBASAUR",
                        "evolutionBranch": [{"evolution": "IVYSAUR", "candyCost": 25}],
                    }
                },
            },
            {
                "templateId": "V0002_POKEMON_IVYSAUR",
                "data": {"pokemonSettings": {"pokemonId": "IVYSAUR"}},
            },
        ]
        expected = [(1, 2, "candy", "", "")]
        for payload in ({"template": templates}, {"itemTemplates": templates}):
            with self.subTest(payload=next(iter(payload))):
                self.assertEqual(_edge_rows(extract_evolution_edges(payload)), expected)


class LoadPokemonEvolutionsTest(unittest.TestCase):
    def test_parses_ints_drops_invalid_rows_and_blanks_missing_text(self) -> None:
        content = "\n".join(
            [
                "source_dex_number,target_dex_number,method,source_form",
                "1,2, candy , Galarian ",
                ",3,candy,X",
                "abc,4,candy,X",
                "0,5,candy,X",
                "-2,6,candy,X",
                "7,7,candy,X",
                "8,9.5,candy,X",
                "10,11,,",
                "12,13,buddy 1 km,Alolan",
                "12,13, Sun Stone , Alolan ",
                "",
            ]
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            path = directory / "pokemon_evolutions.csv"
            path.write_text(content, encoding="utf-8")
            loaded = load_pokemon_evolutions(path)
            missing = load_pokemon_evolutions(directory / "missing.csv")
            unusable = directory / "unusable.csv"
            unusable.write_text("name,value\nBulbasaur,1\n", encoding="utf-8")
            rejected = load_pokemon_evolutions(unusable)

        self.assertEqual(list(loaded.columns), POKEMON_EVOLUTION_COLUMNS)
        self.assertEqual(
            _edge_rows(loaded),
            [
                (1, 2, "candy", "Galarian", ""),
                (10, 11, "", "", ""),
                (12, 13, "Sun Stone", "Alolan", ""),
            ],
        )
        self.assertTrue(missing.empty)
        self.assertEqual(list(missing.columns), POKEMON_EVOLUTION_COLUMNS)
        self.assertTrue(rejected.empty)
        self.assertEqual(list(rejected.columns), POKEMON_EVOLUTION_COLUMNS)


class PokemonEvolutionsReferenceTest(unittest.TestCase):
    def test_reference_csv_includes_bulbasaur_evolution(self) -> None:
        frame = load_pokemon_evolutions(pokemon_evolutions_path())
        matched = frame[(frame["source_dex_number"] == 1) & (frame["target_dex_number"] == 2)]
        self.assertGreater(len(matched), 0)


class UpdatePokemonEvolutionsTest(unittest.TestCase):
    def test_none_payload_does_not_replace_existing_file(self) -> None:
        original = (
            "source_dex_number,target_dex_number,method,source_form,notes\n"
            "9,10,candy,Galarian,keep\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "pokemon_evolutions.csv"
            path.write_text(original, encoding="utf-8")
            with patch(
                "tools.update_pokemon_catalog._load_game_master_payload",
                return_value=None,
            ) as load_payload:
                loaded = update_pokemon_evolutions(path, payload=None)
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            load_payload.assert_called_once()
        self.assertEqual(_edge_rows(loaded), [(9, 10, "candy", "Galarian", "keep")])

    def test_empty_extract_does_not_replace_existing_file(self) -> None:
        original = (
            "source_dex_number,target_dex_number,method,source_form,notes\n"
            "9,10,candy,,\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "pokemon_evolutions.csv"
            path.write_text(original, encoding="utf-8")
            loaded = update_pokemon_evolutions(path, payload=[])
            self.assertEqual(path.read_text(encoding="utf-8"), original)
        self.assertEqual(_edge_rows(loaded), [(9, 10, "candy", "", "")])

    def test_writes_extracted_edges(self) -> None:
        payload = [
            {
                "templateId": "V0001_POKEMON_BULBASAUR",
                "data": {
                    "pokemonSettings": {
                        "pokemonId": "BULBASAUR",
                        "evolutionBranch": [{"evolution": "IVYSAUR", "candyCost": 25}],
                    }
                },
            },
            {
                "templateId": "V0002_POKEMON_IVYSAUR",
                "data": {"pokemonSettings": {"pokemonId": "IVYSAUR"}},
            },
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nested" / "pokemon_evolutions.csv"
            written = update_pokemon_evolutions(path, payload=payload)
            text = path.read_bytes()
        self.assertTrue(text.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"source_dex_number,target_dex_number,method,source_form,notes", text)
        self.assertIn(b"1,2,candy,,", text)
        self.assertEqual(_edge_rows(written), [(1, 2, "candy", "", "")])


if __name__ == "__main__":
    unittest.main()
