from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.expanded_nations import (
    ExpandedNationsError,
    RESEARCH_RELATIVE,
    ROSTER_RELATIVE,
    UNITS_RELATIVE,
    activate_actor_projection,
    deactivate_actor_projection,
    verify_actor_projection,
)
from gates_of_codex.goh_source import scan_source_entries


class ExpandedNationsProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.layers = [self.root / name for name in ("vanilla", "west81", "codex", "ai", "gates")]
        for layer in self.layers:
            (layer / "resource").mkdir(parents=True)
        self.gates = self.layers[-1]
        self._source(2, "units_nato.set",
            '{"fra_rifle(nato)" ("squad_with1types_conquest" side(nato) c1(fr_rifle:5))}\n'
            '{"deu_rifle(nato)" ("squad_with1types_conquest" side(nato) c1(deu_rifle:5))}\n')
        self._source(2, "units_ukr.set",
            '{"amx10rc" ("vehicle" side(ukr) crew(fr_crew:3) vehicle(amx10rc))}\n')
        self._source(3, "units_rusa.set",
            '("squad_with1types_conquest" side(rusa) name(serb_line) c1(Serb_rifleman:5))\n')
        wrapper = self.gates / "resource/set/multiplayer/units/conquest/units_goc_national_wrappers.set"
        wrapper.parent.mkdir(parents=True)
        wrapper.write_text(
            '("squad_with1types_conquest" side(ukr) period(2022s) '
            'min_stage(1) max_stage(99) name(goc_ildu_rifle) '
            'c1(nato_rifleman:5))\n',
            encoding="utf-8",
        )
        # Virtual cost projection requires resolvable breeds + priced rows.
        for side in ("nato", "ukr", "rusa"):
            breed = self.layers[2] / f"resource/set/breed/mp/{side}/2022s/fixture.set"
            breed.parent.mkdir(parents=True, exist_ok=True)
            breed.write_text('{breed {skin "fixture"}}\n', encoding="utf-8")
            inf = self.layers[2] / f"resource/set/multiplayer/units/conquest/inf_{side}.set"
            inf.parent.mkdir(parents=True, exist_ok=True)
            row = (
                f'{{"mp/{side}/2022s/fixture" ("{side}_basic" side({side})) ' 
                f'{{cost 10.0}}}}\n'
            )
            existing = inf.read_text(encoding="utf-8") if inf.is_file() else ""
            if f"mp/{side}/2022s/fixture" not in existing:
                inf.write_text(existing + row, encoding="utf-8")
        self.payload = _payload()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _source(self, priority: int, name: str, text: str) -> None:
        path = self.layers[priority] / "resource/set/multiplayer/units/conquest" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_actor_projection_isolated_and_side_remapped(self) -> None:
        result = activate_actor_projection(self.payload, self.layers, "fra")
        self.assertEqual((result.actor_id, result.tactical_side, result.unit_count), ("fra", "nato", 2))
        units = (self.gates / UNITS_RELATIVE).read_text(encoding="utf-8")
        self.assertIn("fra_rifle", units)
        self.assertIn("amx10rc", units)
        self.assertNotIn("deu_rifle", units)
        self.assertNotIn("side(ukr)", units)
        self.assertEqual(units.count("side(nato)"), 2)
        roster = (self.gates / ROSTER_RELATIVE).read_text(encoding="utf-8")
        self.assertIn('(include "conquest/goc_active_actor_units.set")', roster)
        self.assertNotIn('(include "conquest/units_nato.set")', roster)
        research = (self.gates / RESEARCH_RELATIVE["nato"]).read_text(encoding="utf-8")
        self.assertIn('{"fra_rifle(nato)"', research)
        self.assertNotIn("deu_rifle", research)
        verify_actor_projection(self.gates)

    def test_switch_is_transactional_and_core_removes_projection(self) -> None:
        first = activate_actor_projection(self.payload, self.layers, "fra")
        paths = (ROSTER_RELATIVE, UNITS_RELATIVE, RESEARCH_RELATIVE["nato"])
        before = {(self.gates / path).read_bytes() for path in paths}
        second = activate_actor_projection(self.payload, self.layers, "fra")
        after = {(self.gates / path).read_bytes() for path in paths}
        self.assertEqual(first.projection_signature, second.projection_signature)
        self.assertEqual(before, after)
        activate_actor_projection(self.payload, self.layers, "srb")
        self.assertFalse((self.gates / RESEARCH_RELATIVE["nato"]).exists())
        self.assertTrue((self.gates / RESEARCH_RELATIVE["rusa"]).is_file())
        self.assertTrue(deactivate_actor_projection(self.gates))
        self.assertFalse((self.gates / ROSTER_RELATIVE).exists())

    def test_fail_closed_boundaries(self) -> None:
        with self.assertRaisesRegex(ExpandedNationsError, "not independently playable"):
            activate_actor_projection(self.payload, self.layers, "ukr_ildu")
        actor = next(row for row in self.payload["actors"] if row["actor_id"] == "fra")
        actor["research_nodes"][-1]["unlock_units"] = ["foreign_unit(nato)"]
        with self.assertRaisesRegex(ExpandedNationsError, "research/unit projection mismatch"):
            activate_actor_projection(self.payload, self.layers, "fra")

    def test_unmanaged_or_modified_files_are_never_destroyed(self) -> None:
        path = self.gates / ROSTER_RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("unmanaged\n", encoding="utf-8")
        with self.assertRaisesRegex(ExpandedNationsError, "refuses to overwrite unmanaged"):
            activate_actor_projection(self.payload, self.layers, "fra")
        path.unlink()
        activate_actor_projection(self.payload, self.layers, "fra")
        units = self.gates / UNITS_RELATIVE
        units.write_text(units.read_text(encoding="utf-8") + "; changed\n", encoding="utf-8")
        with self.assertRaisesRegex(ExpandedNationsError, "was modified"):
            deactivate_actor_projection(self.gates)

    def test_later_source_priority_and_virtual_wrapper(self) -> None:
        self._source(3, "units_nato.set",
            '{"fra_rifle(nato)" ("squad_with1types_conquest" side(nato) c1(fr_elite:7))}\n')
        actor = next(row for row in self.payload["actors"] if row["actor_id"] == "fra")
        unit = next(row for row in actor["units"] if row["unit_name"] == "fra_rifle(nato)")
        unit["source_files"].append("3:ai/set/multiplayer/units/conquest/units_nato.set")
        unit["source_priority"] = 3
        activate_actor_projection(self.payload, self.layers, "fra")
        self.assertIn("fr_elite:7", (self.gates / UNITS_RELATIVE).read_text(encoding="utf-8"))
        activate_actor_projection(self.payload, self.layers, "ukr")
        manifest = verify_actor_projection(self.gates)
        self.assertEqual(manifest["unit_count"], 1)
        self.assertEqual(manifest["units"][0]["unit_name"], "goc_ildu_rifle(ukr)")
        scan = scan_source_entries((self.gates / UNITS_RELATIVE).read_text(encoding="utf-8"), "generated")
        self.assertEqual(scan.entries[0].form, "macro")
        self.assertEqual(scan.entries[0].name, "goc_ildu_rifle")


class ExpandedNationsStaticContractTests(unittest.TestCase):
    def test_cli_wrapper_and_ignored_runtime_paths(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertIn(
            'gates-of-codex-expanded = "gates_of_codex.expanded_nations_cli:main"',
            (root / "pyproject.toml").read_text(encoding="utf-8"),
        )
        ignore = (root / ".gitignore").read_text(encoding="utf-8")
        for relative in (
            "/resource/set/multiplayer/units/roster_conquest.set",
            "/resource/set/multiplayer/units/conquest/goc_active_actor_units.set",
            "/resource/set/dynamic_campaign/unit_research_nato.set",
            "/resource/set/dynamic_campaign/unit_research_ukr.set",
            "/resource/set/dynamic_campaign/unit_research_rusa.set",
            "/resource/set/dynamic_campaign/unit_research_prc.set",
        ):
            self.assertIn(relative, ignore)
        script = (root / "tools/activate_expanded_nation.ps1").read_text(encoding="utf-8")
        for token in ("GOH_VANILLA_ROOT", "WEST81_ROOT", "CODEX_ROOT", "CODEX_AI_OVERHAUL_ROOT", "GATES_CODEX_ROOT"):
            self.assertIn(token, script)
        self.assertIn("expanded_nations_cli core", script)
        self.assertIn("expanded_nations_cli launch", script)
        self.assertNotIn("C:\\Users\\", script)


def _unit(actor: str, name: str, side: str, source: str, priority: int, *, source_side: str | None = None, virtual: bool = False) -> dict:
    return {
        "unit_name": name, "actor_id": actor, "component_id": f"{actor}_component",
        "source_side": source_side or side, "tactical_side": side, "period": "2022s",
        "category": "infantry", "members": {"fixture": 5}, "vehicles": [], "actions": [],
        "materializable": True, "source_files": [source], "source_layer": "fixture",
        "source_priority": priority, "virtual": virtual, "tier": 1, "research_cost": 1,
    }


def _actor(actor: str, side: str, units: list[dict], *, playable: bool = True, host: str | None = None) -> dict:
    root = f"actor:{actor}:root"
    nodes = [{"key": root, "actor_id": actor, "node_type": "root", "display_name": root,
              "cost": 0, "prerequisites": [], "unlock_units": [], "source_node": "",
              "source_file": "", "component_id": ""}]
    previous = root
    for index, unit in enumerate(units):
        key = f"actor:{actor}:unit:{index}"
        nodes.append({"key": key, "actor_id": actor, "node_type": "unit",
                      "display_name": unit["unit_name"], "cost": 1,
                      "prerequisites": [previous], "unlock_units": [unit["unit_name"]],
                      "source_node": unit["unit_name"], "source_file": unit["source_files"][0],
                      "component_id": unit["component_id"]})
        previous = key
    return {
        "actor_id": actor, "display_name": actor.upper(), "actor_type": "sovereign" if playable else "volunteer",
        "coalition_id": "blue" if side in {"nato", "ukr"} else "red", "host_actor_id": host,
        "tactical_side": side, "playable": playable, "roster_class": "full_national" if playable else "nonstate",
        "components": [f"{actor}_component"], "unit_count": len(units), "modern_unit_count": len(units),
        "legacy_unit_count": 0, "virtual_unit_count": sum(bool(unit["virtual"]) for unit in units),
        "category_counts": {"infantry": len(units)}, "required_categories": ["infantry"], "missing_categories": [],
        "units": units, "research_node_count": len(nodes), "research_nodes": nodes, "notes": [],
    }


def _payload() -> dict:
    actors = [
        _actor("fra", "nato", [
            _unit("fra", "fra_rifle(nato)", "nato", "2:codex/set/multiplayer/units/conquest/units_nato.set", 2),
            _unit("fra", "amx10rc", "nato", "2:codex/set/multiplayer/units/conquest/units_ukr.set", 2, source_side="ukr"),
        ]),
        _actor("deu", "nato", [_unit("deu", "deu_rifle(nato)", "nato", "2:codex/set/multiplayer/units/conquest/units_nato.set", 2)]),
        _actor("srb", "rusa", [_unit("srb", "serb_line", "rusa", "3:ai/set/multiplayer/units/conquest/units_rusa.set", 3)]),
        _actor("ukr", "ukr", [_unit("ukr", "goc_ildu_rifle(ukr)", "ukr", "Gates:faction_wiring_manifest", 5, virtual=True)]),
        _actor("ukr_ildu", "ukr", [_unit("ukr_ildu", "goc_ildu_rifle(ukr)", "ukr", "Gates:faction_wiring_manifest", 5, virtual=True)], playable=False, host="ukr"),
    ]
    payload = {
        "schema": "gates-of-codex.resolved-factions", "schema_version": 1,
        "manifest_schema_version": 1, "stack_signature": "fixture-stack",
        "manifest_sha256": "fixture-manifest", "source_policy": {}, "source_layers": [],
        "actor_count": len(actors), "actors": actors, "problems": [], "error_count": 0, "warning_count": 0,
    }
    payload["wiring_signature"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


if __name__ == "__main__":
    unittest.main()
