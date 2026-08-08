from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gates_of_codex.expanded_nations import (
    ExpandedNationsError, OPPONENT_UNITS_RELATIVE, RESEARCH_RELATIVE,
    ROSTER_RELATIVE, UNITS_RELATIVE, activate_actor_projection,
    deactivate_actor_projection, verify_actor_projection,
)
from gates_of_codex.expanded_nations_models import (
    BROAD_ROSTER_INCLUDES, MANIFEST_RELATIVE, pretty_json, sha256_bytes,
)
from gates_of_codex.goh_source import scan_source_entries
import gates_of_codex.expanded_nations_transaction as transaction


class ExpandedNationsAuditRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.layers = [self.root / name for name in ("vanilla", "west81", "codex", "ai", "gates")]
        for layer in self.layers:
            (layer / "resource").mkdir(parents=True)
        self.gates = self.layers[-1]
        self._write_core_rosters()
        self.payload = _payload()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_core_rosters(self) -> None:
        rows = {
            "conquest/units_ukr.set": '{"core_ukr(ukr)" ("squad_with1types_conquest" side(ukr) c1(ukr_rifle:5))}\n',
            "conquest/units_rusa.set": (
                '{"core_rusa(rusa)" ("squad_with1types_conquest" side(rusa) c1(rus_rifle:5))}\n'
                '("squad_with1types_conquest" side(rusa) name(serb_line) c1(Serb_rifleman:5))\n'
            ),
            "conquest/units_nato.set": (
                '{"core_nato(nato)" ("squad_with1types_conquest" side(nato) c1(nato_rifle:5))}\n'
                '{"fra_rifle(nato)" ("squad_with1types_conquest" side(nato) c1(fr_rifle:5))}\n'
                '{"alias" ("squad_with1types_conquest" side(nato) c1(fr_alias:5))}\n'
                '{"alias(ukr)" ("squad_with1types_conquest" side(ukr) c1(ukr_alias:5))}\n'
            ),
            "conquest/units_sov_era1960.set": '{"core_sov(rusa)" ("squad_with1types_conquest" side(rusa) c1(sov_rifle:5))}\n',
            "conquest/units_csa_era1960.set": '{"core_csa(rusa)" ("squad_with1types_conquest" side(rusa) c1(csa_rifle:5))}\n',
            "conquest/units_frg_era1960.set": '{"core_frg(nato)" ("squad_with1types_conquest" side(nato) c1(frg_rifle:5))}\n',
            "conquest/units_prc_era1960.set": '{"core_prc(prc)" ("squad_with1types_conquest" side(prc) c1(prc_rifle:5))}\n',
        }
        self.assertEqual(set(rows), set(BROAD_ROSTER_INCLUDES))
        for include, text in rows.items():
            path = self.layers[2] / "resource/set/multiplayer/units" / include
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def test_selected_side_is_replaced_but_opponents_remain(self) -> None:
        activate_actor_projection(self.payload, self.layers, "srb")
        roster = (self.gates / ROSTER_RELATIVE).read_text(encoding="utf-8")
        self.assertIn('(include "conquest/goc_opponent_units.set")', roster)
        self.assertIn('(include "conquest/goc_active_actor_units.set")', roster)
        for include in BROAD_ROSTER_INCLUDES:
            self.assertNotIn(f'(include "{include}")', roster)
        actor_scan = scan_source_entries((self.gates / UNITS_RELATIVE).read_text(encoding="utf-8"), "actor")
        self.assertEqual([entry.name for entry in actor_scan.entries], ["serb_line"])
        opponent_scan = scan_source_entries(
            (self.gates / OPPONENT_UNITS_RELATIVE).read_text(encoding="utf-8"), "opponents"
        )
        sides = [call.value for entry in opponent_scan.entries for call in entry.calls if call.family == "side"]
        self.assertNotIn("rusa", sides)
        self.assertTrue({"nato", "ukr", "prc"}.issubset(set(sides)))
        verify_actor_projection(self.gates)

    def test_cross_side_switch_refuses_unmanaged_destination(self) -> None:
        activate_actor_projection(self.payload, self.layers, "fra")
        unmanaged = self.gates / RESEARCH_RELATIVE["rusa"]
        unmanaged.parent.mkdir(parents=True, exist_ok=True)
        unmanaged.write_text("unmanaged-rusa-research\n", encoding="utf-8")
        with self.assertRaisesRegex(ExpandedNationsError, "unmanaged destination"):
            activate_actor_projection(self.payload, self.layers, "srb")
        self.assertEqual(unmanaged.read_text(encoding="utf-8"), "unmanaged-rusa-research\n")
        self.assertEqual(verify_actor_projection(self.gates)["actor_id"], "fra")

    def test_alias_is_canonicalized_for_purchase_and_research(self) -> None:
        activate_actor_projection(self.payload, self.layers, "fra")
        scan = scan_source_entries((self.gates / UNITS_RELATIVE).read_text(encoding="utf-8"), "actor")
        self.assertEqual([entry.name for entry in scan.entries], ["alias(nato)", "fra_rifle(nato)"])
        units = (self.gates / UNITS_RELATIVE).read_text(encoding="utf-8")
        self.assertIn("; source_entry=alias", units)
        research = (self.gates / RESEARCH_RELATIVE["nato"]).read_text(encoding="utf-8")
        self.assertIn('{"alias(nato)" requires', research)
        self.assertNotIn('{"alias" requires', research)
        verify_actor_projection(self.gates)

    def _assert_switch_failure_rolls_back(self, patcher) -> None:
        activate_actor_projection(self.payload, self.layers, "fra")
        with patcher:
            with self.assertRaises(PermissionError):
                activate_actor_projection(self.payload, self.layers, "srb")
        self.assertEqual(verify_actor_projection(self.gates)["actor_id"], "fra")

    def test_output_stale_and_manifest_failures_roll_back(self) -> None:
        real_replace, real_unlink = transaction.replace_path, transaction.unlink_path
        failed = False

        def fail_actor(source: Path, target: Path) -> None:
            nonlocal failed
            if target == self.gates / UNITS_RELATIVE and not failed:
                failed = True
                raise PermissionError("forced output replacement failure")
            real_replace(source, target)

        self._assert_switch_failure_rolls_back(
            mock.patch.object(transaction, "replace_path", side_effect=fail_actor)
        )
        deactivate_actor_projection(self.gates)
        failed = False
        stale = self.gates / RESEARCH_RELATIVE["nato"]

        def fail_stale(path: Path) -> None:
            nonlocal failed
            if path == stale and not failed:
                failed = True
                raise PermissionError("forced stale deletion failure")
            real_unlink(path)

        self._assert_switch_failure_rolls_back(
            mock.patch.object(transaction, "unlink_path", side_effect=fail_stale)
        )
        deactivate_actor_projection(self.gates)
        failed = False
        manifest = self.gates / MANIFEST_RELATIVE

        def fail_manifest(source: Path, target: Path) -> None:
            nonlocal failed
            if target == manifest and source.name.endswith(".goc-stage") and not failed:
                failed = True
                raise PermissionError("forced manifest replacement failure")
            real_replace(source, target)

        self._assert_switch_failure_rolls_back(
            mock.patch.object(transaction, "replace_path", side_effect=fail_manifest)
        )

    def test_post_install_verification_failure_rolls_back(self) -> None:
        activate_actor_projection(self.payload, self.layers, "fra")
        with mock.patch(
            "gates_of_codex.expanded_nations.verify_actor_projection",
            side_effect=ExpandedNationsError("forced post-install verification failure"),
        ):
            with self.assertRaisesRegex(ExpandedNationsError, "forced post-install"):
                activate_actor_projection(self.payload, self.layers, "srb")
        self.assertEqual(verify_actor_projection(self.gates)["actor_id"], "fra")

    def test_deactivation_failure_restores_active_projection(self) -> None:
        activate_actor_projection(self.payload, self.layers, "fra")
        real_unlink = transaction.unlink_path
        failed = False
        actor_file = self.gates / UNITS_RELATIVE

        def flaky(path: Path) -> None:
            nonlocal failed
            if path == actor_file and not failed:
                failed = True
                raise PermissionError("forced deactivation failure")
            real_unlink(path)

        with mock.patch.object(transaction, "unlink_path", side_effect=flaky):
            with self.assertRaises(PermissionError):
                deactivate_actor_projection(self.gates)
        self.assertEqual(verify_actor_projection(self.gates)["actor_id"], "fra")

    def test_research_semantics_are_checked_beyond_hashes(self) -> None:
        activate_actor_projection(self.payload, self.layers, "fra")
        research_path = self.gates / RESEARCH_RELATIVE["nato"]
        text = research_path.read_text(encoding="utf-8").replace(
            '{"alias(nato)" requires', '{"foreign(nato)" requires', 1
        )
        research_path.write_text(text, encoding="utf-8")
        manifest_path = self.gates / MANIFEST_RELATIVE
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        relative, data = RESEARCH_RELATIVE["nato"].as_posix(), research_path.read_bytes()
        for row in manifest["files"]:
            if row["relative_path"] == relative:
                row["sha256"], row["byte_count"] = sha256_bytes(data), len(data)
        manifest_path.write_text(pretty_json(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ExpandedNationsError, "engine ID disagrees"):
            verify_actor_projection(self.gates)


def _unit(actor: str, name: str, side: str, source: str, priority: int) -> dict:
    return {
        "unit_name": name, "actor_id": actor, "component_id": f"{actor}_component",
        "source_side": side, "tactical_side": side, "period": "2022s",
        "category": "infantry", "members": {"fixture": 5}, "vehicles": [], "actions": [],
        "materializable": True, "source_files": [source], "source_layer": "fixture",
        "source_priority": priority, "virtual": False, "tier": 1, "research_cost": 1,
    }


def _actor(actor: str, side: str, units: list[dict]) -> dict:
    root = f"actor:{actor}:root"
    nodes = [{
        "key": root, "actor_id": actor, "node_type": "root", "display_name": root,
        "cost": 0, "prerequisites": [], "unlock_units": [], "source_node": "",
        "source_file": "", "component_id": "",
    }]
    previous = root
    for index, unit in enumerate(units):
        key = f"actor:{actor}:unit:{index}"
        nodes.append({
            "key": key, "actor_id": actor, "node_type": "unit",
            "display_name": unit["unit_name"], "cost": 1,
            "prerequisites": [previous], "unlock_units": [unit["unit_name"]],
            "source_node": unit["unit_name"], "source_file": unit["source_files"][0],
            "component_id": unit["component_id"],
        })
        previous = key
    return {
        "actor_id": actor, "display_name": actor.upper(), "actor_type": "sovereign",
        "coalition_id": "blue" if side in {"nato", "ukr"} else "red",
        "host_actor_id": None, "tactical_side": side, "playable": True,
        "roster_class": "full_national", "components": [f"{actor}_component"],
        "unit_count": len(units), "modern_unit_count": len(units), "legacy_unit_count": 0,
        "virtual_unit_count": 0, "category_counts": {"infantry": len(units)},
        "required_categories": ["infantry"], "missing_categories": [], "units": units,
        "research_node_count": len(nodes), "research_nodes": nodes, "notes": [],
    }


def _payload() -> dict:
    actors = [
        _actor("fra", "nato", [
            _unit("fra", "fra_rifle(nato)", "nato", "2:codex/set/multiplayer/units/conquest/units_nato.set", 2),
            _unit("fra", "alias(nato)", "nato", "2:codex/set/multiplayer/units/conquest/units_nato.set", 2),
        ]),
        _actor("srb", "rusa", [
            _unit("srb", "serb_line", "rusa", "2:codex/set/multiplayer/units/conquest/units_rusa.set", 2),
        ]),
    ]
    payload = {
        "schema": "gates-of-codex.resolved-factions", "schema_version": 1,
        "manifest_schema_version": 1, "stack_signature": "fixture-stack",
        "manifest_sha256": "fixture-manifest", "source_policy": {}, "source_layers": [],
        "actor_count": len(actors), "actors": actors, "problems": [],
        "error_count": 0, "warning_count": 0,
    }
    payload["wiring_signature"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


if __name__ == "__main__":
    unittest.main()
