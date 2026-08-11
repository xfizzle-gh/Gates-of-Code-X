from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.expanded_nations import (
    RESEARCH_RELATIVE,
    ROSTER_RELATIVE,
    UNITS_RELATIVE,
    activate_actor_projection,
    deactivate_actor_projection,
    verify_actor_projection,
)
from gates_of_codex.expanded_nations_models import (
    ACTIVATION_MODE_CODEX_PASSTHROUGH,
    OPPONENT_UNITS_RELATIVE,
)


class ExpandedNationsPrcPassthroughTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.layers = [
            self.root / name for name in ("vanilla", "west81", "codex", "ai", "gates")
        ]
        for layer in self.layers:
            (layer / "resource").mkdir(parents=True)
        self.gates = self.layers[-1]
        self._source(
            2,
            "units_nato.set",
            '{"fra_rifle(nato)" ("squad_with1types_conquest" side(nato) c1(fr_rifle:5))}\n',
        )
        self._source(
            2,
            "units_prc_era1960.set",
            (
                '{"aft-10"\n'
                '\t("vehicle" period(2022s) min_stage(4) max_stage(99) '
                "side(prc) crew(pla_crew:4) cw(4) cp(18))\n"
                "\t{cost 1250}\n"
                "}\n"
                '{"squad_pla112_rifle"\n'
                '\t("mp_infantry_8" side(prc) period(2022s) '
                "c1(pla_rifleman:8))\n"
                "}\n"
            ),
        )
        for side in ("nato", "prc"):
            breed = self.layers[2] / f"resource/set/breed/mp/{side}/2022s/fixture.set"
            breed.parent.mkdir(parents=True, exist_ok=True)
            breed.write_text('{breed {skin "fixture"}}\n', encoding="utf-8")
            inf = (
                self.layers[2]
                / f"resource/set/multiplayer/units/conquest/inf_{side}.set"
            )
            inf.parent.mkdir(parents=True, exist_ok=True)
            inf.write_text(
                f'{{"mp/{side}/2022s/fixture" ("{side}_basic" side({side})) '
                f"{{cost 10.0}}}}\n",
                encoding="utf-8",
            )
        self.payload = _payload()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _source(self, priority: int, name: str, text: str) -> None:
        path = (
            self.layers[priority]
            / "resource/set/multiplayer/units/conquest"
            / name
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_prc_passthrough_does_not_clone_macroized_purchases(self) -> None:
        result = activate_actor_projection(self.payload, self.layers, "prc")
        self.assertEqual(result.actor_id, "prc")
        self.assertEqual(result.tactical_side, "prc")
        self.assertEqual(result.unit_count, 2)
        self.assertEqual(result.files, ())
        self.assertFalse((self.gates / UNITS_RELATIVE).exists())
        self.assertFalse((self.gates / ROSTER_RELATIVE).exists())
        self.assertFalse((self.gates / OPPONENT_UNITS_RELATIVE).exists())
        self.assertFalse((self.gates / RESEARCH_RELATIVE["prc"]).exists())
        manifest = verify_actor_projection(self.gates)
        self.assertEqual(
            manifest["activation_mode"], ACTIVATION_MODE_CODEX_PASSTHROUGH
        )
        self.assertEqual(manifest["files"], [])
        self.assertEqual(manifest["units"], [])
        self.assertEqual(manifest["research_nodes"], [])
        self.assertEqual(manifest["opponent_entry_count"], 0)
        self.assertIn("do_not_clone_purchase_definitions", manifest["passthrough_policy"])

    def test_prc_passthrough_core_restore_and_switch_are_reversible(self) -> None:
        activate_actor_projection(self.payload, self.layers, "fra")
        self.assertTrue((self.gates / UNITS_RELATIVE).is_file())
        self.assertTrue((self.gates / RESEARCH_RELATIVE["nato"]).is_file())
        activate_actor_projection(self.payload, self.layers, "prc")
        self.assertFalse((self.gates / UNITS_RELATIVE).exists())
        self.assertFalse((self.gates / RESEARCH_RELATIVE["nato"]).exists())
        self.assertFalse((self.gates / RESEARCH_RELATIVE["prc"]).exists())
        activate_actor_projection(self.payload, self.layers, "fra")
        self.assertTrue((self.gates / UNITS_RELATIVE).is_file())
        units = (self.gates / UNITS_RELATIVE).read_text(encoding="utf-8")
        self.assertIn("fra_rifle", units)
        self.assertNotIn("aft-10", units)
        self.assertTrue(deactivate_actor_projection(self.gates))
        self.assertFalse((self.gates / ROSTER_RELATIVE).exists())
        self.assertFalse(
            (self.gates / "live/expanded_nations/active.json").exists()
        )


def _unit(
    actor: str,
    name: str,
    side: str,
    source: str,
    priority: int,
) -> dict:
    return {
        "unit_name": name,
        "actor_id": actor,
        "component_id": f"{actor}_component",
        "source_side": side,
        "tactical_side": side,
        "period": "2022s",
        "category": "infantry",
        "members": {"fixture": 5},
        "vehicles": [],
        "actions": [],
        "materializable": True,
        "source_files": [source],
        "source_layer": "fixture",
        "source_priority": priority,
        "virtual": False,
        "tier": 1,
        "research_cost": 1,
    }


def _actor(actor: str, side: str, units: list[dict]) -> dict:
    root = f"actor:{actor}:root"
    nodes = [
        {
            "key": root,
            "actor_id": actor,
            "node_type": "root",
            "display_name": root,
            "cost": 0,
            "prerequisites": [],
            "unlock_units": [],
            "source_node": "",
            "source_file": "",
            "component_id": "",
        }
    ]
    previous = root
    for index, unit in enumerate(units):
        key = f"actor:{actor}:unit:{index}"
        nodes.append(
            {
                "key": key,
                "actor_id": actor,
                "node_type": "unit",
                "display_name": unit["unit_name"],
                "cost": 1,
                "prerequisites": [previous],
                "unlock_units": [unit["unit_name"]],
                "source_node": unit["unit_name"],
                "source_file": unit["source_files"][0],
                "component_id": unit["component_id"],
            }
        )
        previous = key
    return {
        "actor_id": actor,
        "display_name": actor.upper(),
        "actor_type": "sovereign",
        "coalition_id": "blue" if side in {"nato", "ukr"} else "red",
        "host_actor_id": None,
        "tactical_side": side,
        "playable": True,
        "roster_class": "full_national",
        "components": [f"{actor}_component"],
        "unit_count": len(units),
        "modern_unit_count": len(units),
        "legacy_unit_count": 0,
        "virtual_unit_count": 0,
        "category_counts": {"infantry": len(units)},
        "required_categories": ["infantry"],
        "missing_categories": [],
        "units": units,
        "research_node_count": len(nodes),
        "research_nodes": nodes,
        "notes": [],
    }


def _payload() -> dict:
    actors = [
        _actor(
            "fra",
            "nato",
            [
                _unit(
                    "fra",
                    "fra_rifle(nato)",
                    "nato",
                    "2:codex/set/multiplayer/units/conquest/units_nato.set",
                    2,
                )
            ],
        ),
        _actor(
            "prc",
            "prc",
            [
                _unit(
                    "prc",
                    "aft-10",
                    "prc",
                    "2:codex/set/multiplayer/units/conquest/units_prc_era1960.set",
                    2,
                ),
                _unit(
                    "prc",
                    "squad_pla112_rifle",
                    "prc",
                    "2:codex/set/multiplayer/units/conquest/units_prc_era1960.set",
                    2,
                ),
            ],
        ),
    ]
    payload = {
        "schema": "gates-of-codex.resolved-factions",
        "schema_version": 1,
        "manifest_schema_version": 1,
        "stack_signature": "fixture-stack",
        "manifest_sha256": "fixture-manifest",
        "source_policy": {},
        "source_layers": [],
        "actor_count": len(actors),
        "actors": actors,
        "problems": [],
        "error_count": 0,
        "warning_count": 0,
    }
    payload["wiring_signature"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


if __name__ == "__main__":
    unittest.main()
