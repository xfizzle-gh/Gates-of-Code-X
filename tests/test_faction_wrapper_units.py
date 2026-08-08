from __future__ import annotations

import unittest
from pathlib import Path

from gates_of_codex.codex.catalog import CodeXCatalogScanner
from gates_of_codex.faction_wiring_manifest import load_faction_manifest


class FactionWrapperUnitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repository_root = Path(__file__).resolve().parents[1]
        cls.catalog = CodeXCatalogScanner().scan_stack([cls.repository_root])

    def test_every_virtual_manifest_unit_has_a_native_catalog_definition(self) -> None:
        manifest = load_faction_manifest()
        expected = {
            unit["name"]
            for component in manifest["components"].values()
            for selector in component["selectors"]
            if selector["kind"] == "virtual"
            for unit in selector["units"]
        }
        self.assertEqual(
            expected,
            {
                "goc_ildu_rifle(ukr)",
                "goc_ildu_at(ukr)",
                "goc_ildu_javelin(ukr)",
                "goc_ildu_recon(ukr)",
                "goc_ildu_engineer(ukr)",
                "goc_ildu_manpads(ukr)",
                "goc_sparta_rifle(rusa)",
                "goc_sparta_recon(rusa)",
                "goc_vostok_rifle(rusa)",
                "goc_vostok_mortar(rusa)",
                "goc_vostok_spg9(rusa)",
                "goc_serb_rifle(rusa)",
                "goc_serb_at(rusa)",
                "goc_serb_recon(rusa)",
            },
        )
        for unit_name in sorted(expected):
            with self.subTest(unit_name=unit_name):
                definition = self.catalog.units.get(unit_name)
                self.assertIsNotNone(definition)
                assert definition is not None
                self.assertTrue(definition.materializable)
                self.assertTrue(definition.members)
                self.assertTrue(
                    any("units_goc_national_wrappers.set" in source for source in definition.source_files)
                )

    def test_wrapper_tactical_sides_remain_engine_supported(self) -> None:
        wrapper_units = [
            unit
            for unit in self.catalog.units.values()
            if unit.name.startswith("goc_")
        ]
        self.assertEqual(len(wrapper_units), 14)
        self.assertEqual(
            {unit.side for unit in wrapper_units},
            {"ukr", "rusa"},
        )
        self.assertTrue(
            all(unit.side in {"nato", "ukr", "rusa", "prc"} for unit in wrapper_units)
        )

    def test_wrapper_composition_matches_manifest_authority(self) -> None:
        manifest = load_faction_manifest()
        expected = {
            unit["name"]: {key: int(value) for key, value in unit["members"].items()}
            for component in manifest["components"].values()
            for selector in component["selectors"]
            if selector["kind"] == "virtual"
            for unit in selector["units"]
        }
        for unit_name, members in sorted(expected.items()):
            with self.subTest(unit_name=unit_name):
                definition = self.catalog.units[unit_name]
                self.assertEqual(definition.members, members)


if __name__ == "__main__":
    unittest.main()
