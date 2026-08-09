from __future__ import annotations

import copy
import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gates_of_codex.actor_economy import (
    RESOLVED_SCHEMA,
    RESOLVED_SCHEMA_VERSION,
    _validate_resolved_payload,
    install_actor_content,
)
from gates_of_codex.earth3_bootstrap import (
    Earth3BootstrapError,
    _immutable_actor_content_digest,
    _validate_immutable_actor_content_provenance,
    build_earth3_v1_campaign,
)
from gates_of_codex.faction_wiring_manifest import load_faction_manifest
from gates_of_codex.models import Faction


def _resolved_payload(*, warning_count: int) -> dict[str, object]:
    return {
        "schema": RESOLVED_SCHEMA,
        "schema_version": RESOLVED_SCHEMA_VERSION,
        "stack_signature": "stack-signature",
        "wiring_signature": "wiring-signature",
        "manifest_sha256": "a" * 64,
        "source_policy": "ordered",
        "source_layers": [],
        "actor_count": 1,
        "error_count": 0,
        "warning_count": warning_count,
        "actors": [
            {
                "actor_id": "usa",
                "tactical_side": Faction.NATO.value,
                "units": [
                    {
                        "unit_name": "test_unit",
                        "actor_id": "usa",
                        "tactical_side": Faction.NATO.value,
                        "materializable": True,
                    }
                ],
                "research_nodes": [
                    {
                        "key": "actor:usa:root",
                        "node_type": "root",
                        "prerequisites": [],
                        "unlock_units": [],
                    }
                ],
            }
        ],
    }


def _compiled_catalog_with_warning() -> dict[str, object]:
    manifest = load_faction_manifest()
    manifest_sha256 = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return {
        "schema": RESOLVED_SCHEMA,
        "schema_version": RESOLVED_SCHEMA_VERSION,
        "stack_signature": "copied-stack-signature",
        "wiring_signature": "copied-wiring-signature",
        "manifest_sha256": manifest_sha256,
        "source_policy": manifest["source_policy"],
        "source_layers": [{"priority": 0, "name": "active", "path": "C:\\active-stack"}],
        "actor_count": len(manifest["actors"]),
        "error_count": 0,
        "warning_count": 1,
        "actors": [
            {
                "actor_id": row["actor_id"],
                "display_name": row["display_name"],
                "tactical_side": row["tactical_side"],
                "roster_class": row["roster_class"],
                "units": [],
                "research_nodes": [],
            }
            for row in manifest["actors"]
        ],
    }


def _immutable_runtime() -> dict[str, object]:
    return {
        "schema_version": 1,
        "resolved_schema": RESOLVED_SCHEMA,
        "resolved_schema_version": RESOLVED_SCHEMA_VERSION,
        "stack_signature": "copied-stack-signature",
        "wiring_signature": "copied-wiring-signature",
        "manifest_sha256": "b" * 64,
        "source_policy": {"mode": "ordered"},
        "source_layers": [{"priority": 0, "name": "base", "path": "C:\\not-authority"}],
        "actor_count": 1,
        "actors": {
            "usa": {
                "actor_id": "usa",
                "display_name": "United States",
                "tactical_side": Faction.NATO.value,
                "roster_class": "full_national",
                "units": {
                    "test_unit": {
                        "unit_name": "test_unit",
                        "actor_id": "usa",
                        "component_id": "usa_component",
                        "source_side": "nato",
                        "tactical_side": Faction.NATO.value,
                        "period": "modern",
                        "category": "infantry",
                        "members": {"rifleman": 8},
                        "vehicles": ["humvee"],
                        "actions": ["move", "attack"],
                        "materializable": True,
                        "source_files": ["units/usa/test_unit.json"],
                        "source_layer": "base",
                        "source_priority": 0,
                        "virtual": False,
                        "tier": 1,
                        "source_research_cost": 0,
                        "research_options": ["actor:usa:root"],
                        "purchase_cost": 270,
                        "maintenance_cost": 10,
                        "repair_cost_per_point": 1,
                        "manpower_estimate": 8,
                    }
                },
                "research_nodes": {
                    "actor:usa:root": {
                        "key": "actor:usa:root",
                        "actor_id": "usa",
                        "node_type": "root",
                        "display_name": "Root",
                        "cost": 0,
                        "source_cost": 0,
                        "prerequisites": [],
                        "unlock_units": ["test_unit"],
                        "source_node": "root",
                        "source_file": "research/usa/root.json",
                        "component_id": "usa_component",
                    }
                },
            }
        },
        "reinforcement_pool": [],
        "migration_exceptions": [],
        "warning_count": 0,
    }


class P2CatalogProvenanceCorrectionTests(unittest.TestCase):
    def test_existing_installer_rejects_resolved_catalog_warnings_but_accepts_zero(self) -> None:
        actors = {
            "usa": SimpleNamespace(tactical_side=Faction.NATO, playable=True),
        }
        _validate_resolved_payload(_resolved_payload(warning_count=0), actors, allow_warnings=False)
        with self.assertRaisesRegex(ValueError, "warning"):
            _validate_resolved_payload(_resolved_payload(warning_count=1), actors, allow_warnings=False)

    def test_warning_bearing_active_stack_fails_before_campaign_publication(self) -> None:
        catalog = _compiled_catalog_with_warning()
        with (
            patch(
                "gates_of_codex.faction_wiring_compiler.FactionWiringCompiler"
            ) as compiler,
            patch("gates_of_codex.earth3_bootstrap._materialize_roster", return_value=[]),
            patch(
                "gates_of_codex.actor_economy.install_actor_content",
                wraps=install_actor_content,
            ) as installer,
        ):
            compiler.return_value.compile.return_value = catalog
            with self.assertRaisesRegex(ValueError, "warning"):
                build_earth3_v1_campaign(resource_stack=["C:\\active-stack"])
        installer.assert_called_once()
        self.assertNotIn("allow_warnings", installer.call_args.kwargs)

    def test_immutable_runtime_mutations_fail_with_copied_signatures_unchanged(self) -> None:
        runtime = _immutable_runtime()
        expected_identity = _immutable_actor_content_digest(runtime)
        mutations = (
            lambda value: value["actors"]["usa"]["units"]["test_unit"]["members"].__setitem__("rifleman", 9),
            lambda value: value["actors"]["usa"]["units"]["test_unit"].__setitem__("category", "recon"),
            lambda value: value["actors"]["usa"]["units"]["test_unit"].__setitem__("source_layer", "override"),
            lambda value: value["actors"]["usa"]["research_nodes"]["actor:usa:root"].__setitem__("prerequisites", ["actor:usa:other"]),
            lambda value: value["actors"]["usa"]["research_nodes"]["actor:usa:root"].__setitem__("unlock_units", []),
            lambda value: value["actors"]["usa"]["units"]["test_unit"].__setitem__("purchase_cost", 275),
            lambda value: value["actors"]["usa"]["units"]["test_unit"].__setitem__("maintenance_cost", 11),
        )
        for mutate in mutations:
            tampered = copy.deepcopy(runtime)
            mutate(tampered)
            self.assertEqual(tampered["stack_signature"], runtime["stack_signature"])
            self.assertEqual(tampered["wiring_signature"], runtime["wiring_signature"])
            with self.assertRaises(Earth3BootstrapError):
                _validate_immutable_actor_content_provenance(tampered, expected_identity)

    def test_mutable_actor_economy_state_is_excluded_but_migration_exceptions_fail(self) -> None:
        runtime = _immutable_runtime()
        expected_identity = _immutable_actor_content_digest(runtime)
        evolved = copy.deepcopy(runtime)
        evolved["reinforcement_pool"] = [
            {
                "actor_id": "usa",
                "strategic_formation_id": "force_usa",
                "unit_name": "test_unit",
                "quantity": 2,
                "unit_cost": 270,
            }
        ]
        evolved["last_round_economy"] = [{"actor_id": "usa", "resources_remaining": 500}]
        _validate_immutable_actor_content_provenance(evolved, expected_identity)

        invalid_opening = copy.deepcopy(runtime)
        invalid_opening["migration_exceptions"] = [{"unit_name": "grandfathered"}]
        with self.assertRaises(Earth3BootstrapError):
            _validate_immutable_actor_content_provenance(invalid_opening, expected_identity)
