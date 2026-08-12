"""#194 static/pre-native Expanded Nations matrix gate."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.expanded_nations_battle_pair import (
    ENGINE_OVERLAY_RELS,
    materialize_battle_pair,
    render_battle_pair_alliances,
    restore_battle_pair,
    verify_battle_pair,
)
from gates_of_codex.expanded_nations_models import GENERATED_MARKER
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
    load_resolved_static_snapshot,
    manifest_authority_fingerprint,
    pack_count_authority_fingerprint,
    render_native_acceptance_template,
    validate_static_actor_matrix,
    write_static_matrix_evidence,
    _canonical_file_digest,
)
from gates_of_codex.expanded_nations_cli import main as expanded_cli_main
from gates_of_codex.goc_tactical_army_registry import playable_goc_sides
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
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
        self.assertEqual(
            snap.get("manifest_authority_fingerprint"),
            manifest_authority_fingerprint(ROOT),
        )
        self.assertEqual(
            snap.get("pack_count_authority_fingerprint"),
            pack_count_authority_fingerprint(ROOT),
        )
        loaded = load_resolved_static_snapshot(ROOT)
        self.assertIsNotNone(loaded)
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
        harness = live["native_harness"]
        self.assertIn("battle-pair", harness["battle_pair_install_command"])

    def test_all_playable_goc_sides_have_committed_native_packs(self) -> None:
        for side in playable_goc_sides():
            for rel in (
                f"resource/set/multiplayer/units/conquest/inf_{side}.set",
                f"resource/set/multiplayer/units/conquest/units_{side}.set",
                f"resource/set/dynamic_campaign/unit_research_{side}.set",
                f"resource/script/multiplayer/units/{side}/conquest.{side}.lua",
            ):
                self.assertTrue((ROOT / rel).is_file(), rel)

    def test_battle_pair_alliances_stage_both_gates_ids(self) -> None:
        text = render_battle_pair_alliances("goc_usa", "goc_fra")
        self.assertIn('{armies "goc_usa"}', text)
        self.assertIn('{armies "goc_fra"}', text)
        self.assertIn('"West"', text)
        self.assertIn('"East"', text)

    def test_snapshot_rejects_component_selector_authority_drift(self) -> None:
        snap_path = ROOT / "docs/audits/expanded-nations-resolved-static-snapshot.json"
        original = snap_path.read_text(encoding="utf-8")
        try:
            payload = json.loads(original)
            payload["manifest_authority_fingerprint"] = "0" * 64
            snap_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaisesRegex(ValueError, "stale relative to current manifest"):
                load_resolved_static_snapshot(ROOT)
        finally:
            snap_path.write_text(original, encoding="utf-8", newline="\n")

    def test_snapshot_rejects_pack_authority_drift(self) -> None:
        snap_path = ROOT / "docs/audits/expanded-nations-resolved-static-snapshot.json"
        original = snap_path.read_text(encoding="utf-8")
        try:
            payload = json.loads(original)
            payload["pack_count_authority_fingerprint"] = "1" * 64
            snap_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaisesRegex(ValueError, "stale relative to committed pack"):
                load_resolved_static_snapshot(ROOT)
        finally:
            snap_path.write_text(original, encoding="utf-8", newline="\n")

    def test_snapshot_rejects_units_pack_tamper(self) -> None:
        pack = ROOT / "resource/set/multiplayer/units/conquest/units_goc_usa.set"
        original = pack.read_bytes()
        try:
            pack.write_bytes(original + b"\n; tamper\n")
            with self.assertRaisesRegex(ValueError, "stale relative to committed pack"):
                load_resolved_static_snapshot(ROOT)
        finally:
            pack.write_bytes(original)


class Phase194BattlePairInstallTests(unittest.TestCase):
    def _install_pair(self, dest: Path, attacker: str, defender: str) -> dict:
        return materialize_battle_pair(
            ROOT,
            attacker_actor_id=attacker,
            defender_actor_id=defender,
            output_root=dest,
            source_pack_root=ROOT,
        )

    def test_required_pairs_install_into_engine_paths(self) -> None:
        pairs = (
            ("usa", "fra", "goc_usa", "goc_fra"),
            ("srb", "rus", "goc_srb", "goc_rus"),
            ("usa", "dprk", "goc_usa", "goc_dprk"),
        )
        for attacker, defender, left, right in pairs:
            with self.subTest(pair=f"{attacker}_vs_{defender}"):
                with tempfile.TemporaryDirectory() as directory:
                    dest = Path(directory)
                    source_marker = ROOT / "resource/set/dynamic_campaign/values.set"
                    before = source_marker.read_bytes() if source_marker.is_file() else None
                    result = self._install_pair(dest, attacker, defender)
                    self.assertTrue(result["ok"])
                    self.assertTrue(result["source_unmodified"])
                    if before is not None:
                        self.assertEqual(source_marker.read_bytes(), before)
                    for rel in ENGINE_OVERLAY_RELS:
                        path = dest / rel
                        self.assertTrue(path.is_file(), rel)
                        text = path.read_text(encoding="utf-8")
                        self.assertIn(GENERATED_MARKER, text)
                    values = (dest / ENGINE_OVERLAY_RELS[1]).read_text(encoding="utf-8")
                    self.assertIn(f'"{left} {right}"', values)
                    self.assertIn(f'"{right} {left}"', values)
                    alliances = (dest / ENGINE_OVERLAY_RELS[0]).read_text(encoding="utf-8")
                    self.assertIn(f'{{armies "{left}"}}', alliances)
                    self.assertIn(f'{{armies "{right}"}}', alliances)
                    for side in (left, right):
                        self.assertTrue(
                            (
                                dest
                                / f"resource/set/multiplayer/units/conquest/units_{side}.set"
                            ).is_file()
                        )
                    self.assertEqual(verify_battle_pair(dest), [])

    def test_source_repo_unmodified_when_destination_differs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory)
            values = ROOT / "resource/set/dynamic_campaign/values.set"
            alliances = ROOT / "resource/set/multiplayer/games/presets/alliances_generic.inc"
            before_values = values.read_bytes()
            before_alliances = alliances.read_bytes()
            self._install_pair(dest, "usa", "fra")
            self.assertEqual(values.read_bytes(), before_values)
            self.assertEqual(alliances.read_bytes(), before_alliances)
            self.assertFalse(
                (ROOT / "live/expanded_nations/battle_pair/active.json").exists()
            )

    def test_tampered_pair_fails_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory)
            self._install_pair(dest, "usa", "fra")
            target = dest / ENGINE_OVERLAY_RELS[1]
            target.write_text(target.read_text(encoding="utf-8") + "\n; tamper\n", encoding="utf-8")
            problems = verify_battle_pair(dest)
            self.assertTrue(any("tampered" in item for item in problems), problems)

    def test_restore_removes_pair_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory)
            # Seed a prior multi-faction-looking overlay to prove restore.
            prior = dest / ENGINE_OVERLAY_RELS[1]
            prior.parent.mkdir(parents=True, exist_ok=True)
            prior.write_text("; prior values\n", encoding="utf-8")
            self._install_pair(dest, "srb", "rus")
            self.assertIn("goc_srb", (dest / ENGINE_OVERLAY_RELS[1]).read_text(encoding="utf-8"))
            result = restore_battle_pair(dest)
            self.assertTrue(result["ok"])
            self.assertEqual(
                (dest / ENGINE_OVERLAY_RELS[1]).read_text(encoding="utf-8"),
                "; prior values\n",
            )
            self.assertFalse(
                (dest / "live/expanded_nations/battle_pair/active.json").is_file()
            )

    def test_cli_battle_pair_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory)
            rc = expanded_cli_main(
                [
                    "battle-pair",
                    "--attacker",
                    "usa",
                    "--defender",
                    "fra",
                    "--gates-root",
                    str(dest),
                    "--source-repo",
                    str(ROOT),
                ]
            )
            self.assertEqual(rc, 0)
            rc = expanded_cli_main(["battle-pair-verify", "--gates-root", str(dest)])
            self.assertEqual(rc, 0)
            rc = expanded_cli_main(["battle-pair-restore", "--gates-root", str(dest)])
            self.assertEqual(rc, 0)


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
