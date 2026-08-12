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
    PHASE1_HOSTS,
    PHASE1_PLAYABLE,
    PHASE1_TACTICAL_SIDES,
    REQUIRED_BATTLE_PAIRS,
    STATIC_MATRIX_SCHEMA,
    build_static_actor_matrix,
    render_native_acceptance_template,
    validate_static_actor_matrix,
    write_static_matrix_evidence,
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
            head = (
                subprocess.check_output(
                    ["git", "rev-parse", "HEAD"],
                    cwd=ROOT,
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()
            )
        except Exception:
            head = ""
        cls.matrix = build_static_actor_matrix(repo_root=ROOT, source_head=head)
        cls.by_id = {row["actor_id"]: row for row in cls.matrix["actors"]}

    def test_matrix_schema_and_validation_clean(self) -> None:
        self.assertEqual(self.matrix["schema"], STATIC_MATRIX_SCHEMA)
        self.assertEqual(self.matrix["evidence_state"], "static_pre_native")
        self.assertEqual(validate_static_actor_matrix(self.matrix), [])
        self.assertTrue(self.matrix.get("matrix_signature"))

    def test_counts_match_authored_manifest_and_registry(self) -> None:
        manifest = load_faction_manifest()
        validate_faction_manifest(manifest)
        self.assertEqual(
            self.matrix["counts"]["actor_count"],
            len(manifest["actors"]),
        )
        playable = sum(1 for row in manifest["actors"] if row["playable"])
        strategic = sum(
            1 for row in manifest["actors"] if row["roster_class"] == "strategic_only"
        )
        self.assertEqual(self.matrix["counts"]["playable_actor_count"], playable)
        self.assertEqual(self.matrix["counts"]["strategic_only_actor_count"], strategic)
        registry = load_goc_army_registry()
        self.assertEqual(
            self.matrix["counts"]["registered_goc_side_count"],
            len(registry["armies"]),
        )
        self.assertEqual(int(registry["production_band"]["start"]), 55)
        self.assertEqual(int(registry["production_band"]["end"]), 99)

    def test_phase1_regression_boundaries_frozen(self) -> None:
        for actor_id in PHASE1_ACTORS:
            self.assertIn(actor_id, self.by_id)
            row = self.by_id[actor_id]
            self.assertEqual(row["tactical_side"], PHASE1_TACTICAL_SIDES[actor_id])
            self.assertTrue(row["phase1_actor"])
        for actor_id in PHASE1_PLAYABLE:
            self.assertTrue(self.by_id[actor_id]["playable"], actor_id)
        for actor_id, host in PHASE1_HOSTS.items():
            self.assertFalse(self.by_id[actor_id]["playable"], actor_id)
            self.assertEqual(self.by_id[actor_id]["host_actor_id"], host)
        # Core four sides preserved in architecture block.
        self.assertEqual(
            self.matrix["architecture"]["core_sides_preserved"],
            ["nato", "ukr", "rusa", "prc"],
        )
        self.assertTrue(self.matrix["architecture"]["mixed_architecture_forbidden"])

    def test_phase1_attention_actors_still_present_with_expected_sides(self) -> None:
        expected = {
            "fra": ("nato", "national_hybrid"),
            "esp": ("nato", "coalition_fallback"),
            "ukr": ("ukr", "full_national"),
            "rus": ("rusa", "full_national"),
            "dprk": ("rusa", "proxy_hybrid"),
            "srb": ("rusa", "proxy_hybrid"),
            "prc": ("prc", "full_national"),
            "ukr_ildu": ("ukr", "nonstate"),
            "wagner": ("rusa", "nonstate"),
            "kpa_expeditionary": ("rusa", "nonstate"),
        }
        for actor_id, (side, roster) in expected.items():
            row = self.by_id[actor_id]
            self.assertEqual(row["tactical_side"], side, actor_id)
            self.assertEqual(row["roster_class"], roster, actor_id)

    def test_strategic_only_have_no_recruitment_or_ai_authority(self) -> None:
        strategic = [
            row for row in self.matrix["actors"] if row["roster_class"] == "strategic_only"
        ]
        self.assertGreaterEqual(len(strategic), 25)
        for row in strategic:
            self.assertFalse(row["playable"], row["actor_id"])
            self.assertEqual(row["components"], [])
            self.assertEqual(row["research_mode"], "none")
            self.assertEqual(row["unit_count"], 0)
            self.assertEqual(row["research_node_count"], 0)
            self.assertFalse(row["ai_purchase_authority"]["may_purchase"])
            self.assertFalse(row["ai_purchase_authority"]["may_research"])
            self.assertEqual(row["native_acceptance_status"], "not_run")

    def test_playable_goc_packs_have_positive_counts_and_hashes(self) -> None:
        # Production playable goc armies must already have committed native packs.
        for actor_id in ("bel", "cze", "grc", "rou"):
            row = self.by_id[actor_id]
            self.assertTrue(row["playable"], actor_id)
            self.assertTrue(str(row["tactical_side"]).startswith("goc_"), actor_id)
            self.assertIsInstance(row["unit_count"], int)
            self.assertGreater(row["unit_count"], 0, actor_id)
            self.assertIsInstance(row["research_node_count"], int)
            self.assertGreater(row["research_node_count"], 0, actor_id)
            self.assertTrue(row["managed_file_hashes"], actor_id)
            units_key = (
                f"resource/set/multiplayer/units/conquest/units_{row['tactical_side']}.set"
            )
            self.assertIn(units_key, row["managed_file_hashes"], actor_id)

    def test_cze_family_still_records_dana_authority_on_disk(self) -> None:
        cze_units = (
            ROOT / "resource/set/multiplayer/units/conquest/units_goc_cze.set"
        ).read_text(encoding="utf-8")
        self.assertIn("vz_77_dana", cze_units)
        self.assertNotIn("usmc_rifleman", cze_units)
        self.assertEqual(self.by_id["cze"]["roster_class"], "national_hybrid")

    def test_native_harness_defines_families_and_battle_pairs(self) -> None:
        harness = self.matrix["native_harness"]
        self.assertEqual(
            len(harness["representative_families"]),
            len(NATIVE_REPRESENTATIVE_FAMILIES),
        )
        self.assertEqual(len(harness["required_battle_pairs"]), len(REQUIRED_BATTLE_PAIRS))
        reps = {
            row["representative_actor_id"]
            for row in harness["representative_families"]
        }
        for required in ("usa", "fra", "esp", "ukr", "rus", "dprk", "srb", "prc", "bel", "cze", "egy"):
            self.assertIn(required, reps)
        pair_ids = {row["pair_id"] for row in harness["required_battle_pairs"]}
        self.assertIn("usa_vs_fra_shared_nato_transport", pair_ids)
        self.assertIn("srb_vs_rus_shared_rusa_transport", pair_ids)
        self.assertIn("usa_vs_dprk_cross_coalition", pair_ids)
        self.assertIn("regional_garrison_48", pair_ids)
        self.assertIn("core --gates-root", harness["core_restore_command"])
        self.assertEqual(harness["status"], "harness_defined_native_runs_pending_owner")

    def test_signatures_are_deterministic(self) -> None:
        again = build_static_actor_matrix(
            repo_root=ROOT,
            source_head=self.matrix.get("source_head") or "",
        )
        self.assertEqual(again["matrix_signature"], self.matrix["matrix_signature"])
        a = {row["actor_id"]: row["actor_authority_signature"] for row in again["actors"]}
        b = {
            row["actor_id"]: row["actor_authority_signature"]
            for row in self.matrix["actors"]
        }
        self.assertEqual(a, b)

    def test_write_evidence_and_native_template(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / "static-matrix.json"
            md_path = Path(directory) / "static-matrix.md"
            write_static_matrix_evidence(
                self.matrix,
                json_output=json_path,
                markdown_output=md_path,
            )
            loaded = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["matrix_signature"], self.matrix["matrix_signature"])
            text = md_path.read_text(encoding="utf-8")
            self.assertIn("static_pre_native", text)
            self.assertIn("| bel |", text)
            self.assertIn("usa_vs_fra_shared_nato_transport", text)
        template = render_native_acceptance_template()
        self.assertIn("Core restoration", template)
        self.assertIn("usa_vs_dprk_cross_coalition", template)
        self.assertIn("issue_48_regional_local_garrison", template)


class Phase194StrategicOnlyRuntimeTests(unittest.TestCase):
    def test_strategic_only_cannot_be_selected_and_round_trips(self) -> None:
        state = load_bundled_scenario("legacy_goe_europe")
        actors = install_bundled_strategic_actors(state, selected_actor_id="usa")
        self.assertIn("egy", actors)
        self.assertFalse(actors["egy"].playable)
        self.assertEqual(actors["egy"].tactical_side.campaign_faction(), Faction.NATO)
        self.assertEqual(actors["syr"].tactical_side.campaign_faction(), Faction.RUSSIA)
        with self.assertRaises(ValueError):
            set_selected_actor(state, "egy")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.json"
            save_campaign(state, path)
            loaded = load_campaign(path)
        restored = install_bundled_strategic_actors(loaded, selected_actor_id="usa")
        self.assertFalse(restored["egy"].playable)
        self.assertEqual(restored["egy"].roster_class, "strategic_only")


class Phase194CheckedInEvidenceFreshnessTests(unittest.TestCase):
    def test_checked_in_static_matrix_matches_builder_when_present(self) -> None:
        json_path = ROOT / "docs/audits/expanded-nations-static-matrix.json"
        md_path = ROOT / "docs/audits/expanded-nations-static-matrix.md"
        template_path = ROOT / "docs/audits/native-acceptance-phase2-template.md"
        self.assertTrue(json_path.is_file())
        self.assertTrue(md_path.is_file())
        self.assertTrue(template_path.is_file())
        checked = json.loads(json_path.read_text(encoding="utf-8"))
        # Recompute without pinning source_head so signature compares authority bytes.
        live = build_static_actor_matrix(repo_root=ROOT, source_head=checked.get("source_head") or "")
        self.assertEqual(checked["matrix_signature"], live["matrix_signature"])
        self.assertEqual(validate_static_actor_matrix(checked), [])
        self.assertIn("not_run", md_path.read_text(encoding="utf-8"))
        self.assertIn("harness only", template_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
