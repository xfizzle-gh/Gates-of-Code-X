"""#193 Near East / Caucasus / North Africa strategic-only contracts."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.faction_wiring import load_faction_manifest, validate_faction_manifest
from gates_of_codex.goc_native_dc_seam import (
    playable_goc_sides,
    render_alliances_generic,
    validate_repo_native_dc_seam,
)
from gates_of_codex.goc_tactical_army_registry import (
    army_numeric_id,
    load_goc_army_registry,
    nation_map_id,
    validate_goc_army_registry,
)
from gates_of_codex.models import Faction
from gates_of_codex.scenario import load_bundled_scenario
from gates_of_codex.state_io import load_campaign, save_campaign
from gates_of_codex.strategic_actors import (
    install_bundled_strategic_actors,
    set_selected_actor,
    strategic_actor_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]

# Issue #193 crop-conditional candidates; #190 marks all theatre_present + strategic_only.
STRATEGIC_193 = {
    "geo": "goc_geo",
    "arm": "goc_arm",
    "aze": "goc_aze",
    "isr": "goc_isr",
    "lbn": "goc_lbn",
    "syr": "goc_syr",
    "jor": "goc_jor",
    "irq": "goc_irq",
    "mar": "goc_mar",
    "dza": "goc_dza",
    "tun": "goc_tun",
    "lby": "goc_lby",
    "egy": "goc_egy",
    "cyp": "goc_cyp",
    "mlt": "goc_mlt",
}
EAST_FAMILY = {"arm", "syr", "dza", "lby"}
EXPECTED_NUMERIC = {
    "goc_geo": 55,
    "goc_arm": 56,
    "goc_aze": 57,
    "goc_isr": 58,
    "goc_lbn": 59,
    "goc_syr": 60,
    "goc_jor": 61,
    "goc_irq": 62,
    "goc_mar": 63,
    "goc_dza": 64,
    "goc_tun": 65,
    "goc_lby": 66,
    "goc_egy": 67,
    "goc_cyp": 68,
    "goc_mlt": 69,
}
EXPECTED_NATION_MAP = {
    "goc_geo": 36,
    "goc_arm": 37,
    "goc_aze": 38,
    "goc_isr": 39,
    "goc_lbn": 40,
    "goc_syr": 41,
    "goc_jor": 42,
    "goc_irq": 43,
    "goc_mar": 44,
    "goc_dza": 45,
    "goc_tun": 46,
    "goc_lby": 47,
    "goc_egy": 48,
    "goc_cyp": 49,
    "goc_mlt": 50,
}
# Immutable prior production IDs from accepted #191/#192 baseline.
BASELINE_191_192 = {
    "goc_bel",
    "goc_prt",
    "goc_cze",
    "goc_svk",
    "goc_hun",
    "goc_ltu",
    "goc_lva",
    "goc_est",
    "goc_aut",
    "goc_che",
    "goc_irl",
    "goc_isl",
    "goc_grc",
    "goc_rou",
    "goc_bgr",
    "goc_hrv",
    "goc_svn",
    "goc_bih",
    "goc_mne",
    "goc_alb",
    "goc_mkd",
    "goc_mda",
}


class Phase193AuditAuthorityTests(unittest.TestCase):
    def test_accepted_190_theatre_present_strategic_only_consumed_exactly(self) -> None:
        payload = json.loads(
            (ROOT / "docs/audits/expanded-nations-phase2-source-candidates.json").read_text(
                encoding="utf-8"
            )
        )
        candidates = {row["actor_id"]: row for row in payload["candidates"]}
        for actor_id, side in STRATEGIC_193.items():
            row = candidates[actor_id]
            self.assertTrue(row["theatre_present"], actor_id)
            self.assertEqual(row["disposition"], "strategic_only", actor_id)
            self.assertEqual(row["tactical_side"], side, actor_id)
            self.assertEqual(row.get("components") or [], [], actor_id)
            self.assertEqual(row.get("exact_units") or [], [], actor_id)
            self.assertEqual(row.get("research_roots") or [], [], actor_id)
            self.assertFalse(row.get("national_infantry_present"), actor_id)
            self.assertFalse(row.get("national_equipment_present"), actor_id)
            family = row["provisional_coalition_family"]
            if actor_id in EAST_FAMILY:
                self.assertEqual(family, "rusa", actor_id)
            else:
                self.assertEqual(family, "nato", actor_id)

    def test_out_of_scope_candidates_are_not_silently_added(self) -> None:
        # #193 scope is only the crop-conditional list; do not invent extras.
        manifest = load_faction_manifest()
        actors = {row["actor_id"] for row in manifest["actors"]}
        for forbidden in ("sau", "irn", "yem", "sdn", "som", "qat", "are", "kwt"):
            self.assertNotIn(forbidden, actors)


class Phase193RegistryTests(unittest.TestCase):
    def test_registry_ids_unique_and_disjoint_from_baseline_and_spike(self) -> None:
        registry = load_goc_army_registry()
        validate_goc_army_registry(registry)
        rows = registry["armies"]
        self.assertEqual(
            {side: army_numeric_id(side) for side in EXPECTED_NUMERIC},
            EXPECTED_NUMERIC,
        )
        self.assertEqual(
            {side: nation_map_id(side) for side in EXPECTED_NATION_MAP},
            EXPECTED_NATION_MAP,
        )
        all_ids = [int(row["numeric_id"]) for row in rows.values()]
        self.assertEqual(len(all_ids), len(set(all_ids)))
        self.assertTrue(set(EXPECTED_NUMERIC.values()).issubset(all_ids))
        self.assertFalse(set(EXPECTED_NUMERIC.values()) & set(range(90, 95)))
        self.assertFalse(set(EXPECTED_NUMERIC.values()) & set(range(70, 90)))
        self.assertFalse(set(EXPECTED_NUMERIC.values()) & {95, 96})
        # Declared production band must include #193 and exclude reserved spike IDs.
        band = registry["production_band"]
        self.assertEqual(int(band["start"]), 55)
        self.assertEqual(int(band["end"]), 99)
        for numeric_id in all_ids:
            self.assertGreaterEqual(numeric_id, 55)
            self.assertLessEqual(numeric_id, 99)
            self.assertNotIn(numeric_id, set(range(90, 95)))
        sub = registry["allocation_sub_bands"]["phase2_193_near_east_africa_strategic_only"]
        self.assertEqual(int(sub["start"]), 55)
        self.assertEqual(int(sub["end"]), 69)
        self.assertEqual(int(sub["issue"]), 193)
        # Baseline #191/#192 tokens remain present with prior IDs.
        self.assertTrue(BASELINE_191_192.issubset(rows))
        self.assertEqual(army_numeric_id("goc_bel"), 70)
        self.assertEqual(army_numeric_id("goc_mda"), 96)
        audit = registry["stack_collision_audit"]
        self.assertEqual(audit["result"], "no_collision")
        observed = set(int(value) for value in audit["observed_used_ids"])
        self.assertFalse(observed & set(EXPECTED_NUMERIC.values()))

    def test_validator_rejects_id_outside_declared_production_band(self) -> None:
        registry = json.loads(json.dumps(load_goc_army_registry()))
        registry["armies"]["goc_bad"] = {
            "numeric_id": 40,
            "nation_map_id": 99,
            "actor_id": "bad",
            "coalition": "west",
            "playable": False,
            "issue": 193,
        }
        with self.assertRaises(Exception):
            validate_goc_army_registry(registry)

    def test_committed_flags_are_tga_not_png(self) -> None:
        for side in STRATEGIC_193.values():
            path = ROOT / "resource/interface/pages/multi" / f"flag_{side}.tga"
            data = path.read_bytes()
            self.assertFalse(data.startswith(b"\x89PNG"), side)
            # Uncompressed true-color TGA signature used by existing placeholders.
            self.assertEqual(data[0:3], b"\x00\x00\x02", side)

    def test_registry_all_non_playable_and_coalition_mapping(self) -> None:
        rows = load_goc_army_registry()["armies"]
        for actor_id, side in STRATEGIC_193.items():
            self.assertFalse(rows[side]["playable"], actor_id)
            self.assertEqual(rows[side]["issue"], 193, actor_id)
            expected = "east" if actor_id in EAST_FAMILY else "west"
            self.assertEqual(rows[side]["coalition"], expected, actor_id)
        self.assertFalse(set(STRATEGIC_193.values()) & set(playable_goc_sides()))


class Phase193ManifestTests(unittest.TestCase):
    def test_manifest_strategic_only_guards_and_no_recruitment(self) -> None:
        manifest = load_faction_manifest()
        validate_faction_manifest(manifest)
        actors = {row["actor_id"]: row for row in manifest["actors"]}
        self.assertTrue(set(STRATEGIC_193).issubset(actors))
        for actor_id, side in STRATEGIC_193.items():
            row = actors[actor_id]
            self.assertFalse(row["playable"], actor_id)
            self.assertEqual(row["tactical_side"], side, actor_id)
            self.assertEqual(row["roster_class"], "strategic_only", actor_id)
            self.assertEqual(row["components"], [], actor_id)
            self.assertEqual(row["research"]["mode"], "none", actor_id)
            self.assertEqual(row["required_categories"], [], actor_id)
            expected_coalition = "eurasian" if actor_id in EAST_FAMILY else "atlantic"
            self.assertEqual(row["coalition_id"], expected_coalition, actor_id)
            # No Wagner/militia/PMC component leakage into sovereign recruitment authority.
            self.assertEqual(row["components"], [])
            self.assertEqual(row["research"]["mode"], "none")
            for component_id in row["components"]:
                lowered = str(component_id).lower()
                for forbidden in ("wagner", "militia", "insurgent", "pmc", "africa_corps"):
                    self.assertNotIn(forbidden, lowered, actor_id)


class Phase193NativeSurfaceTests(unittest.TestCase):
    def test_committed_surfaces_and_no_fabricated_roster_research_purchase(self) -> None:
        self.assertEqual(validate_repo_native_dc_seam(ROOT), [])
        alliances = render_alliances_generic()
        for actor_id, side in STRATEGIC_193.items():
            self.assertTrue(
                (ROOT / "resource/set/multiplayer/armies" / f"{side}.set").is_file(),
                actor_id,
            )
            self.assertTrue(
                (ROOT / "resource/interface/pages/multi" / f"flag_{side}.tga").is_file(),
                actor_id,
            )
            # strategic_only must not enter the alliance picker.
            self.assertNotIn(f'{{armies "{side}"}}', alliances, actor_id)
            # No fabricated native DC recruitment packs.
            self.assertFalse(
                (ROOT / f"resource/set/multiplayer/units/conquest/units_{side}.set").exists(),
                actor_id,
            )
            self.assertFalse(
                (ROOT / f"resource/set/multiplayer/units/conquest/inf_{side}.set").exists(),
                actor_id,
            )
            self.assertFalse(
                (ROOT / f"resource/set/dynamic_campaign/unit_research_{side}.set").exists(),
                actor_id,
            )
            self.assertFalse(
                (
                    ROOT
                    / "resource/script/multiplayer/units"
                    / side
                    / f"conquest.{side}.lua"
                ).exists(),
                actor_id,
            )


class Phase193RuntimeTests(unittest.TestCase):
    def test_strategic_only_persist_and_cannot_be_selected(self) -> None:
        state = load_bundled_scenario("legacy_goe_europe")
        actors = install_bundled_strategic_actors(state, selected_actor_id="fra")
        for actor_id, side in STRATEGIC_193.items():
            self.assertIn(actor_id, actors)
            self.assertFalse(actors[actor_id].playable)
            self.assertEqual(actors[actor_id].tactical_side.value, side)
            if actor_id in EAST_FAMILY:
                self.assertEqual(
                    actors[actor_id].tactical_side.campaign_faction(), Faction.RUSSIA
                )
            else:
                self.assertEqual(
                    actors[actor_id].tactical_side.campaign_faction(), Faction.NATO
                )
            with self.assertRaises(ValueError):
                set_selected_actor(state, actor_id)

        # Save/load preserves strategic-only runtime rows without granting recruitment.
        runtime = state.map_metadata["strategic_actor_runtime"]
        runtime["actors"]["egy"]["researched_keys"] = ["actor:egy:should-not-recruit"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.json"
            save_campaign(state, path)
            loaded = load_campaign(path)
        snap = strategic_actor_snapshot(loaded)
        by_id = {row["actor_id"]: row for row in snap["actors"]}
        self.assertEqual(by_id["egy"]["researched_keys"], ["actor:egy:should-not-recruit"])
        self.assertFalse(by_id["egy"]["playable"])
        self.assertEqual(by_id["egy"]["roster_class"], "strategic_only")
        self.assertEqual(by_id["syr"]["tactical_side"], "goc_syr")


if __name__ == "__main__":
    unittest.main()
