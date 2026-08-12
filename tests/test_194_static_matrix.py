"""#194 static/pre-native Expanded Nations matrix gate."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.expanded_nations_static_matrix import (
    NATIVE_REPRESENTATIVE_FAMILIES,
    PHASE1_ACTORS,
    PHASE1_EXPANDED_TACTICAL_SIDE,
    PHASE1_HOSTS,
    PHASE1_PLAYABLE,
    PHASE1_SOURCE_FAMILY,
    PLAYABLE_CHECKLIST,
    REQUIRED_BATTLE_PAIRS,
    STATIC_MATRIX_SCHEMA,
    STRATEGIC_ONLY_CHECKLIST,
    build_static_actor_matrix,
    render_native_acceptance_template,
    validate_static_actor_matrix,
    write_static_matrix_evidence,
    _canonical_file_digest,
)
from gates_of_codex.faction_wiring import load_faction_manifest, validate_faction_manifest
from gates_of_codex.goc_tactical_army_registry import load_goc_army_registry
from gates_of_codex.models import Faction
from gates_of_codex.scenario import load_bundled_scenario
from gates_of_codex.state_io import load_campaign, save_campaign
from gates_of_codex.strategic_actors import (
    install_bundled_strategic_actors,
    set_selected_actor,
)

ROOT = Path(__file__).resolve().parents[1]


class Phase194StaticMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        head = ""
        try:
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=ROOT,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except Exception:
            head = ""
        cls.matrix = build_static_actor_matrix(
            repo_root=ROOT,
            source_head=head,
            require_resolved_counts=True,
        )
        cls.by_id = {row["actor_id"]: row for row in cls.matrix["actors"]}

    def test_matrix_schema_and_validation_clean(self) -> None:
        self.assertEqual(self.matrix["schema"], STATIC_MATRIX_SCHEMA)
        self.assertEqual(self.matrix["schema_version"], 2)
        self.assertEqual(self.matrix["evidence_state"], "static_pre_native")
        self.assertEqual(validate_static_actor_matrix(self.matrix), [])
        self.assertTrue(self.matrix["architecture"]["expanded_mode_uses_gates_ids"])

    def test_phase1_source_families_frozen_and_expanded_sides_are_gates_ids(self) -> None:
        for actor_id in PHASE1_ACTORS:
            row = self.by_id[actor_id]
            self.assertEqual(row["source_compatibility_family"], PHASE1_SOURCE_FAMILY[actor_id])
            self.assertEqual(
                row["expanded_tactical_side"],
                PHASE1_EXPANDED_TACTICAL_SIDE[actor_id],
            )
            if actor_id == "prc":
                self.assertEqual(row["expanded_tactical_side"], "prc")
            elif actor_id in PHASE1_PLAYABLE or actor_id in PHASE1_HOSTS:
                if PHASE1_EXPANDED_TACTICAL_SIDE[actor_id] != "prc":
                    self.assertTrue(
                        str(row["expanded_tactical_side"]).startswith("goc_"),
                        actor_id,
                    )
        for actor_id, host in PHASE1_HOSTS.items():
            self.assertEqual(self.by_id[actor_id]["host_actor_id"], host)
            self.assertFalse(self.by_id[actor_id]["playable"])

    def test_playable_counts_and_opponents_are_populated(self) -> None:
        for row in self.matrix["actors"]:
            if not row["playable"]:
                continue
            self.assertIsInstance(row["unit_count"], int, row["actor_id"])
            self.assertIsInstance(row["research_node_count"], int, row["actor_id"])
            self.assertIsInstance(row["modern_unit_count"], int, row["actor_id"])
            self.assertIsInstance(row["legacy_unit_count"], int, row["actor_id"])
            self.assertIsInstance(row["opponent_availability_count"], int, row["actor_id"])
            self.assertGreater(row["unit_count"], 0, row["actor_id"])
            self.assertGreater(row["opponent_availability_count"], 0, row["actor_id"])
        # PRC legacy separation remains visible.
        prc = self.by_id["prc"]
        self.assertGreater(prc["legacy_unit_count"], 0)
        self.assertGreater(prc["modern_unit_count"], 0)
        self.assertEqual(prc["modern_unit_count"] + prc["legacy_unit_count"], prc["unit_count"])

    def test_strategic_only_checklist_and_no_recruitment(self) -> None:
        egy = self.by_id["egy"]
        self.assertTrue(egy["strategic_only"])
        self.assertEqual(egy["native_checklist"], list(STRATEGIC_ONLY_CHECKLIST))
        self.assertNotEqual(egy["native_checklist"], list(PLAYABLE_CHECKLIST))
        self.assertEqual(egy["unit_count"], 0)
        self.assertFalse(egy["ai_purchase_authority"]["may_purchase"])
        usa = self.by_id["usa"]
        self.assertEqual(usa["native_checklist"], list(PLAYABLE_CHECKLIST))

    def test_battle_pairs_use_gates_ids_not_generic_core_sides(self) -> None:
        pairs = {
            row["pair_id"]: row
            for row in self.matrix["native_harness"]["required_battle_pairs"]
        }
        usa_fra = pairs["usa_vs_fra_gates_ids_shared_nato_source_family"]
        self.assertEqual(usa_fra["attacker_expanded_tactical_side"], "goc_usa")
        self.assertEqual(usa_fra["defender_expanded_tactical_side"], "goc_fra")
        self.assertEqual(usa_fra["source_family"], "nato")
        srb_rus = pairs["srb_vs_rus_gates_ids_shared_rusa_source_family"]
        self.assertEqual(srb_rus["attacker_expanded_tactical_side"], "goc_srb")
        self.assertEqual(srb_rus["defender_expanded_tactical_side"], "goc_rus")
        self.assertEqual(len(REQUIRED_BATTLE_PAIRS), 4)
        self.assertEqual(len(NATIVE_REPRESENTATIVE_FAMILIES), 11)

    def test_canonical_file_digest_is_newline_stable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.set"
            path.write_bytes(b"a\r\nb\r\n")
            one = _canonical_file_digest(path)
            path.write_bytes(b"a\nb\n")
            two = _canonical_file_digest(path)
            self.assertEqual(one, two)

    def test_signatures_deterministic(self) -> None:
        again = build_static_actor_matrix(
            repo_root=ROOT,
            source_head=self.matrix.get("source_head") or "",
            require_resolved_counts=True,
        )
        self.assertEqual(again["matrix_signature"], self.matrix["matrix_signature"])

    def test_checked_in_evidence_matches_builder(self) -> None:
        json_path = ROOT / "docs/audits/expanded-nations-static-matrix.json"
        snap_path = ROOT / "docs/audits/expanded-nations-resolved-static-snapshot.json"
        template_path = ROOT / "docs/audits/native-acceptance-phase2-template.md"
        self.assertTrue(json_path.is_file())
        self.assertTrue(snap_path.is_file())
        self.assertTrue(template_path.is_file())
        checked = json.loads(json_path.read_text(encoding="utf-8"))
        live = build_static_actor_matrix(
            repo_root=ROOT,
            source_head=checked.get("source_head") or "",
            require_resolved_counts=True,
        )
        self.assertEqual(checked["matrix_signature"], live["matrix_signature"])
        self.assertEqual(validate_static_actor_matrix(checked), [])
        template = template_path.read_text(encoding="utf-8")
        self.assertIn("Strategic-only checklist", template)
        self.assertIn("goc_usa", template)
        self.assertIn("goc_fra", template)


class Phase194RuntimeAndManifestTests(unittest.TestCase):
    def test_manifest_phase1_expanded_sides_and_prc_passthrough(self) -> None:
        manifest = load_faction_manifest()
        validate_faction_manifest(manifest)
        actors = {row["actor_id"]: row for row in manifest["actors"]}
        self.assertEqual(actors["usa"]["tactical_side"], "goc_usa")
        self.assertEqual(actors["fra"]["tactical_side"], "goc_fra")
        self.assertEqual(actors["srb"]["tactical_side"], "goc_srb")
        self.assertEqual(actors["rus"]["tactical_side"], "goc_rus")
        self.assertEqual(actors["prc"]["tactical_side"], "prc")
        self.assertEqual(actors["ukr_ildu"]["tactical_side"], "goc_ukr")
        self.assertEqual(actors["wagner"]["tactical_side"], "goc_rus")

    def test_strategic_only_runtime_and_campaign_mapping(self) -> None:
        state = load_bundled_scenario("legacy_goe_europe")
        actors = install_bundled_strategic_actors(state, selected_actor_id="usa")
        self.assertEqual(actors["usa"].tactical_side.value, "goc_usa")
        self.assertEqual(actors["usa"].tactical_side.campaign_faction(), Faction.NATO)
        self.assertEqual(actors["fra"].tactical_side.value, "goc_fra")
        self.assertEqual(actors["ukr"].tactical_side.campaign_faction(), Faction.UKRAINE)
        self.assertEqual(actors["rus"].tactical_side.campaign_faction(), Faction.RUSSIA)
        self.assertEqual(state.selected_faction, Faction.NATO)
        with self.assertRaises(ValueError):
            set_selected_actor(state, "egy")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.json"
            save_campaign(state, path)
            loaded = load_campaign(path)
        restored = install_bundled_strategic_actors(loaded, selected_actor_id="usa")
        self.assertEqual(restored["usa"].tactical_side.value, "goc_usa")

    def test_registry_includes_phase1_expanded_ids(self) -> None:
        reg = load_goc_army_registry()
        self.assertEqual(int(reg["production_band"]["start"]), 14)
        self.assertIn("goc_usa", reg["armies"])
        self.assertEqual(reg["armies"]["goc_usa"]["numeric_id"], 14)
        self.assertEqual(reg["armies"]["goc_fra"]["numeric_id"], 17)
        self.assertEqual(reg["armies"]["goc_usa"]["core_transport_side"], "nato")
        self.assertEqual(reg["armies"]["goc_ukr"]["core_transport_side"], "ukr")
        self.assertEqual(reg["armies"]["goc_rus"]["core_transport_side"], "rusa")
        # #191/#192/#193 preserved
        self.assertEqual(reg["armies"]["goc_bel"]["numeric_id"], 70)
        self.assertEqual(reg["armies"]["goc_mda"]["numeric_id"], 96)
        self.assertEqual(reg["armies"]["goc_egy"]["numeric_id"], 67)


if __name__ == "__main__":
    unittest.main()
