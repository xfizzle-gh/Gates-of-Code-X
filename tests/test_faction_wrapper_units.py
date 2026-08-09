from __future__ import annotations

import unittest
from pathlib import Path

from gates_of_codex.codex.catalog import CodeXCatalogScanner
from gates_of_codex.expanded_nations_actor_sources import effective_purchase_id
from gates_of_codex.faction_wiring_manifest import load_faction_manifest
from gates_of_codex.goh_source import scan_source_entries


class FactionWrapperUnitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repository_root = Path(__file__).resolve().parents[1]
        cls.catalog = CodeXCatalogScanner().scan_stack([cls.repository_root])
        cls.wrapper_path = (
            cls.repository_root
            / "resource/set/multiplayer/units/conquest/units_goc_national_wrappers.set"
        )
        scan = scan_source_entries(
            cls.wrapper_path.read_text(encoding="utf-8"),
            str(cls.wrapper_path),
        )
        if scan.diagnostics:
            raise AssertionError(f"Wrapper source has parser diagnostics: {scan.diagnostics}")

        cls.native_entries = {}
        for entry in scan.entries:
            sides = [
                call.value.lower()
                for call in entry.calls
                if call.family == "side"
            ]
            if len(sides) != 1:
                raise AssertionError(
                    f"Wrapper {entry.name!r} must declare exactly one tactical side"
                )
            effective_id = effective_purchase_id(entry, sides[0])
            if effective_id in cls.native_entries:
                raise AssertionError(
                    f"Duplicate native wrapper effective ID: {effective_id}"
                )
            cls.native_entries[effective_id] = entry

        cls.native_catalog = {}
        for definition in cls.catalog.units.values():
            if not any(
                "units_goc_national_wrappers.set" in source
                for source in definition.source_files
            ):
                continue
            effective_id = f"{definition.name}({definition.side})"
            if effective_id in cls.native_catalog:
                raise AssertionError(
                    f"Duplicate catalog wrapper effective ID: {effective_id}"
                )
            cls.native_catalog[effective_id] = definition

    @staticmethod
    def _manifest_virtual_units() -> dict[str, dict]:
        manifest = load_faction_manifest()
        return {
            unit["name"]: unit
            for component in manifest["components"].values()
            for selector in component["selectors"]
            if selector["kind"] == "virtual"
            for unit in selector["units"]
        }

    def test_every_virtual_manifest_unit_has_a_native_catalog_definition(self) -> None:
        expected = set(self._manifest_virtual_units())
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
        self.assertEqual(expected, set(self.native_entries))
        self.assertEqual(expected, set(self.native_catalog))

        for unit_name in sorted(expected):
            with self.subTest(unit_name=unit_name):
                entry = self.native_entries[unit_name]
                definition = self.native_catalog[unit_name]
                self.assertEqual("macro", entry.form)
                self.assertTrue(entry.macro_kind.lower().startswith("squad_with"))
                self.assertTrue(definition.materializable)
                self.assertTrue(definition.members)
                self.assertTrue(
                    any(
                        "units_goc_national_wrappers.set" in source
                        for source in definition.source_files
                    )
                )

    def test_wrapper_tactical_sides_remain_engine_supported(self) -> None:
        wrapper_units = list(self.native_catalog.values())
        self.assertEqual(len(wrapper_units), 14)
        self.assertEqual(
            {unit.side for unit in wrapper_units},
            {"ukr", "rusa"},
        )
        self.assertTrue(
            all(
                unit.side in {"nato", "ukr", "rusa", "prc"}
                for unit in wrapper_units
            )
        )

    def test_wrapper_composition_matches_manifest_authority(self) -> None:
        expected = self._manifest_virtual_units()
        for unit_name, unit in sorted(expected.items()):
            with self.subTest(unit_name=unit_name):
                definition = self.native_catalog[unit_name]
                members = {
                    key: int(value)
                    for key, value in unit["members"].items()
                }
                self.assertEqual(definition.members, members)


if __name__ == "__main__":
    unittest.main()
