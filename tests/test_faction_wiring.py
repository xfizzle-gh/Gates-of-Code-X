from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.faction_wiring import (
    FactionWiringCompiler,
    FactionWiringError,
    load_faction_manifest,
    validate_faction_manifest,
)


class BundledManifestContractTest(unittest.TestCase):
    def test_bundled_manifest_has_every_approved_actor_and_supported_export_side(self) -> None:
        manifest = load_faction_manifest()
        validate_faction_manifest(manifest)
        actors = {actor["actor_id"]: actor for actor in manifest["actors"]}
        expected = {
            "usa", "gbr", "deu", "fra", "pol", "ita", "fin", "swe", "nld", "can",
            "nor", "dnk", "esp", "tur", "rus", "ukr", "prc", "dprk", "donbas", "blr", "srb",
            "ukr_ildu", "kpa_expeditionary", "wagner",
        }
        self.assertEqual(set(actors), expected)
        self.assertTrue(all(actor["tactical_side"] in {"nato", "ukr", "rusa", "prc"} for actor in actors.values()))
        self.assertTrue(all(actors[actor_id]["playable"] for actor_id in expected - {"ukr_ildu", "kpa_expeditionary", "wagner"}))
        self.assertFalse(actors["ukr_ildu"]["playable"])
        self.assertEqual(actors["ukr_ildu"]["host_actor_id"], "ukr")
        self.assertEqual(actors["kpa_expeditionary"]["host_actor_id"], "rus")
        self.assertEqual(actors["wagner"]["host_actor_id"], "rus")

    def test_manifest_rejects_unknown_fields(self) -> None:
        manifest = load_faction_manifest()
        manifest["unexpected"] = True
        with self.assertRaises(FactionWiringError):
            validate_faction_manifest(manifest)


class FactionWiringCompilerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.west = self.root / "West81"
        self.codex = self.root / "CodeX"
        self._write_fixture_stack()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_compiles_native_hybrid_legacy_and_virtual_content_deterministically(self) -> None:
        manifest = self._manifest()
        first = FactionWiringCompiler([self.west, self.codex], manifest=manifest).compile()
        second = FactionWiringCompiler([self.west, self.codex], manifest=manifest).compile()
        self.assertEqual(first, second)
        self.assertEqual(first["error_count"], 0)
        self.assertEqual(first["warning_count"], 0)

        actors = {actor["actor_id"]: actor for actor in first["actors"]}
        usa = actors["usa"]
        self.assertEqual({unit["unit_name"] for unit in usa["units"]}, {"test_rifle", "test_apc", "test_tank"})
        self.assertTrue(all(unit["tactical_side"] == "nato" for unit in usa["units"]))
        self.assertGreaterEqual(usa["research_node_count"], 4)

        proxy = actors["proxy"]
        legacy = next(unit for unit in proxy["units"] if unit["unit_name"] == "legacy_tank")
        self.assertEqual(legacy["source_side"], "sov")
        self.assertEqual(legacy["tactical_side"], "rusa")
        self.assertEqual(proxy["legacy_unit_count"], 1)

        volunteer = actors["volunteer"]
        virtual = next(unit for unit in volunteer["units"] if unit["virtual"])
        self.assertEqual(virtual["members"], {"vol_lead": 1, "vol_rifle": 4})
        self.assertEqual(virtual["tactical_side"], "ukr")
        self.assertTrue(any(node["unlock_units"] == [virtual["unit_name"]] for node in volunteer["research_nodes"]))

    def test_missing_required_unit_is_a_resolution_error(self) -> None:
        manifest = self._manifest()
        manifest["components"]["legacy"]["selectors"][0]["units"].append("does_not_exist")
        payload = FactionWiringCompiler([self.west, self.codex], manifest=manifest).compile()
        self.assertEqual(payload["error_count"], 1)
        self.assertIn("does_not_exist", payload["problems"][0]["message"])

    def test_source_unit_missing_breed_is_a_resolution_error(self) -> None:
        missing = self.codex / "resource/set/breed/mp/nato/2022s/test_rifleman.set"
        missing.unlink()
        payload = FactionWiringCompiler([self.west, self.codex], manifest=self._manifest()).compile()
        self.assertGreaterEqual(payload["error_count"], 1)
        self.assertTrue(any("missing nato breeds: test_rifleman" in item["message"] for item in payload["problems"]))

    def test_source_unit_invalid_breed_definition_is_a_resolution_error(self) -> None:
        self._write(
            self.codex / "resource/set/breed/mp/nato/2022s/test_rifleman.set",
            '{breed {inventory {item ""}}}\n',
        )
        payload = FactionWiringCompiler([self.west, self.codex], manifest=self._manifest()).compile()
        self.assertGreaterEqual(payload["error_count"], 1)
        self.assertTrue(any("empty inventory item" in item["message"] for item in payload["problems"]))

    def test_source_unit_missing_vehicle_is_a_resolution_error(self) -> None:
        self._write(
            self.codex / "resource/set/registry/unit.reg",
            '{"test_apc"}\n',
        )
        payload = FactionWiringCompiler([self.west, self.codex], manifest=self._manifest()).compile()
        self.assertGreaterEqual(payload["error_count"], 1)
        self.assertTrue(any("missing vehicle/entity IDs: test_tank" in item["message"] for item in payload["problems"]))

    def test_filtered_branch_reparents_prerequisites_without_cycles(self) -> None:
        manifest = self._manifest()
        manifest["components"]["native"]["selectors"][0]["exclude_regex"] = "test_apc"
        payload = FactionWiringCompiler([self.west, self.codex], manifest=manifest).compile()
        self.assertEqual(payload["error_count"], 0)
        usa = next(actor for actor in payload["actors"] if actor["actor_id"] == "usa")
        keys = {node["key"] for node in usa["research_nodes"]}
        for node in usa["research_nodes"]:
            self.assertTrue(set(node["prerequisites"]).issubset(keys))

    def _manifest(self) -> dict:
        return {
            "schema": "gates-of-codex.faction-wiring",
            "schema_version": 1,
            "source_policy": {
                "modern_authority": "Code:X",
                "legacy_authority": "West81",
                "overlay_authority": "Gates",
                "asset_policy": "reference only",
                "tactical_side_policy": "four sides",
                "legacy_policy": "explicit only",
            },
            "components": {
                "native": {
                    "description": "native branch",
                    "selectors": [{"kind": "research_branch", "source_side": "nato", "root": "test_root"}],
                },
                "legacy": {
                    "description": "legacy exact",
                    "selectors": [{"kind": "exact", "source_side": "sov", "units": ["legacy_tank"]}],
                },
                "virtual": {
                    "description": "virtual volunteers",
                    "selectors": [{
                        "kind": "virtual",
                        "units": [{
                            "name": "goc_volunteer(ukr)",
                            "source_side": "ukr",
                            "category": "infantry",
                            "members": {"vol_lead": 1, "vol_rifle": 4},
                            "tier": 1,
                            "cost": 2,
                        }],
                    }],
                },
            },
            "actors": [
                {
                    "actor_id": "usa", "display_name": "United States", "actor_type": "sovereign",
                    "coalition_id": "atlantic", "tactical_side": "nato", "playable": True,
                    "roster_class": "full_national", "components": ["native"],
                    "research": {"mode": "native"}, "required_categories": ["infantry", "tank"], "notes": [],
                },
                {
                    "actor_id": "proxy", "display_name": "Proxy", "actor_type": "sovereign",
                    "coalition_id": "east", "tactical_side": "rusa", "playable": True,
                    "roster_class": "proxy_hybrid", "components": ["legacy"],
                    "research": {"mode": "generated"}, "required_categories": ["tank"], "notes": [],
                },
                {
                    "actor_id": "volunteer", "display_name": "Volunteers", "actor_type": "volunteer",
                    "coalition_id": "ukraine", "tactical_side": "ukr", "playable": False,
                    "roster_class": "nonstate", "components": ["virtual"],
                    "research": {"mode": "generated"}, "required_categories": ["infantry"], "notes": [],
                    "host_actor_id": "usa",
                },
            ],
        }

    def _write_fixture_stack(self) -> None:
        codex_resource = self.codex / "resource"
        west_resource = self.west / "resource"
        self._write(
            codex_resource / "set/multiplayer/units/conquest/units_nato.set",
            '("squad" side(nato) period(2022s) name(test_rifle) c1(test_lead:1) c2(test_rifleman:4))\n'
            '{"test_apc" {vehicle "test_apc"}}\n'
            '{"test_tank" {vehicle "test_tank"}}\n',
        )
        self._write(
            codex_resource / "set/dynamic_campaign/unit_research_nato.set",
            '{ tech "test_root" requires "" costs 1 position 0 0}\n'
            '{"test_rifle" requires "test_root" costs 1 position 1 0}\n'
            '{"test_apc" requires "test_rifle" costs 2 position 2 0}\n'
            '{"test_tank" requires "test_apc" costs 4 position 3 0}\n',
        )
        self._write(
            codex_resource / "set/registry/unit.reg",
            '{"test_apc"}\n{"test_tank"}\n',
        )
        self._write(codex_resource / "set/breed/mp/nato/2022s/test_lead.set", '{breed}\n')
        self._write(codex_resource / "set/breed/mp/nato/2022s/test_rifleman.set", '{breed}\n')
        self._write(
            west_resource / "set/multiplayer/units/conquest/units_sov_era1960.set",
            '{"legacy_tank" {vehicle "legacy_tank"}}\n',
        )
        self._write(west_resource / "set/registry/unit.reg", '{"legacy_tank"}\n')
        self._write(codex_resource / "set/breed/mp/ukr/2022s/vol_lead.set", '{breed}\n')
        self._write(codex_resource / "set/breed/mp/ukr/2022s/vol_rifle.set", '{breed}\n')

    @staticmethod
    def _write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
