"""#192 Balkans/Eastern Europe production and strategic-only contracts."""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.goc_native_dc_seam import (
    render_alliances_generic,
    render_dlg_mp_keys,
    render_values_set,
    validate_repo_native_dc_seam,
)
from gates_of_codex.goc_tactical_army_registry import (
    army_numeric_id,
    load_goc_army_registry,
    nation_map_id,
    playable_goc_sides,
    validate_goc_army_registry,
)
from gates_of_codex.faction_wiring import load_faction_manifest, validate_faction_manifest
from gates_of_codex.models import Faction
from gates_of_codex.scenario import load_bundled_scenario
from gates_of_codex.state_io import load_campaign, save_campaign
from gates_of_codex.strategic_actors import (
    ACTOR_RUNTIME_KEY,
    install_bundled_strategic_actors,
    set_selected_actor,
    strategic_actor_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
PLAYABLE = {
    "grc": "goc_grc",
    "rou": "goc_rou",
    "bgr": "goc_bgr",
    "hrv": "goc_hrv",
}
STRATEGIC = {
    "svn": "goc_svn",
    "bih": "goc_bih",
    "mne": "goc_mne",
    "alb": "goc_alb",
    "mkd": "goc_mkd",
    "mda": "goc_mda",
}
ALL_192 = set(PLAYABLE) | set(STRATEGIC)
EXPECTED_NUMERIC = {
    "goc_grc": 82,
    "goc_rou": 83,
    "goc_bgr": 84,
    "goc_hrv": 85,
    "goc_svn": 86,
    "goc_bih": 87,
    "goc_mne": 88,
    "goc_alb": 89,
    "goc_mkd": 95,
    "goc_mda": 96,
}
EXPECTED_NATION_MAP = {
    "goc_grc": 26,
    "goc_rou": 27,
    "goc_bgr": 28,
    "goc_hrv": 29,
    "goc_svn": 30,
    "goc_bih": 31,
    "goc_mne": 32,
    "goc_alb": 33,
    "goc_mkd": 34,
    "goc_mda": 35,
}
_RESOLVED_UNIT_RE = re.compile(r"^;\s*resolved_unit=(.+?)\s*$", re.MULTILINE)
_LUA_PURCHASE_RE = re.compile(r'\bunit\s*=\s*"([^"]+)"')
_GOC_NODE_RE = re.compile(r"^;\s*goc-node\s+(\{.*\})\s*$", re.MULTILINE)
_GOC_INF_COST_RE = re.compile(r"^;\s*goc-inf-cost\s+(\{.*\})\s*$", re.MULTILINE)
_SIDE_CALL_RE = re.compile(r"\bside\(([^)]+)\)")


class Phase192AuditAuthorityTests(unittest.TestCase):
    def test_accepted_190_records_are_consumed_exactly(self) -> None:
        payload = json.loads(
            (ROOT / "docs/audits/expanded-nations-phase2-source-candidates.json").read_text(
                encoding="utf-8"
            )
        )
        candidates = {row["actor_id"]: row for row in payload["candidates"]}
        for actor_id, side in PLAYABLE.items():
            row = candidates[actor_id]
            self.assertEqual(row["disposition"], "coalition_fallback")
            self.assertEqual(row["tactical_side"], side)
            self.assertEqual(row["components"], ["nato_full_fallback"])
            self.assertEqual(row["exact_units"], [])
            self.assertEqual(row["research_roots"], [])
            self.assertEqual(row["provisional_coalition_family"], "nato")
        for actor_id, side in STRATEGIC.items():
            row = candidates[actor_id]
            self.assertEqual(row["disposition"], "strategic_only")
            self.assertEqual(row["tactical_side"], side)
            self.assertEqual(row["components"], [])
            self.assertEqual(row["exact_units"], [])
            self.assertEqual(row["research_roots"], [])
        self.assertEqual(candidates["mda"]["provisional_coalition_family"], "rusa")
        for actor_id in set(STRATEGIC) - {"mda"}:
            self.assertEqual(candidates[actor_id]["provisional_coalition_family"], "nato")


class Phase192RegistryTests(unittest.TestCase):
    def test_registry_ids_are_exact_unique_and_collision_free_against_accepted_inventory(self) -> None:
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
        self.assertTrue(set(range(70, 82)).issubset(all_ids))
        self.assertTrue(set(EXPECTED_NUMERIC.values()).issubset(all_ids))
        self.assertFalse(set(EXPECTED_NUMERIC.values()) & {90, 91, 92, 93, 94})

        audit = registry["stack_collision_audit"]
        self.assertEqual(
            audit["authority_order"], ["Vanilla", "West81", "Code:X", "AIO", "Gates"]
        )
        self.assertEqual(audit["result"], "no_collision")
        observed = set(int(value) for value in audit["observed_used_ids"])
        self.assertFalse(observed & set(EXPECTED_NUMERIC.values()))
        self.assertEqual(
            set(int(value) for value in audit["allocated_ids"]),
            {int(row["numeric_id"]) for row in rows.values()},
        )

    def test_registry_playability_and_coalition_mapping_are_exact(self) -> None:
        rows = load_goc_army_registry()["armies"]
        for actor_id, side in PLAYABLE.items():
            self.assertTrue(rows[side]["playable"], actor_id)
            self.assertEqual(rows[side]["coalition"], "west", actor_id)
            self.assertEqual(rows[side]["issue"], 192)
        for actor_id, side in STRATEGIC.items():
            self.assertFalse(rows[side]["playable"], actor_id)
            expected = "east" if actor_id == "mda" else "west"
            self.assertEqual(rows[side]["coalition"], expected, actor_id)
            self.assertEqual(rows[side]["issue"], 192)
        self.assertEqual(set(PLAYABLE.values()) & set(playable_goc_sides()), set(PLAYABLE.values()))
        self.assertFalse(set(STRATEGIC.values()) & set(playable_goc_sides()))


class Phase192ManifestTests(unittest.TestCase):
    def test_manifest_mapping_and_strategic_only_guards(self) -> None:
        manifest = load_faction_manifest()
        validate_faction_manifest(manifest)
        actors = {row["actor_id"]: row for row in manifest["actors"]}
        self.assertTrue(ALL_192.issubset(actors))
        for actor_id, side in PLAYABLE.items():
            row = actors[actor_id]
            self.assertTrue(row["playable"])
            self.assertEqual(row["tactical_side"], side)
            self.assertEqual(row["roster_class"], "coalition_fallback")
            self.assertEqual(row["components"], ["nato_full_fallback"])
            self.assertEqual(row["research"]["mode"], "generated")
            self.assertEqual(row["required_categories"], ["infantry", "tank", "artillery"])
            self.assertEqual(row["coalition_id"], "atlantic")
        for actor_id, side in STRATEGIC.items():
            row = actors[actor_id]
            self.assertFalse(row["playable"])
            self.assertEqual(row["tactical_side"], side)
            self.assertEqual(row["roster_class"], "strategic_only")
            self.assertEqual(row["components"], [])
            self.assertEqual(row["research"]["mode"], "none")
            self.assertEqual(row["required_categories"], [])
        self.assertEqual(actors["mda"]["coalition_id"], "eurasian")


class Phase192NativeSurfaceTests(unittest.TestCase):
    def test_committed_native_seam_is_complete(self) -> None:
        self.assertEqual(validate_repo_native_dc_seam(ROOT), [])
        for actor_id, side in {**PLAYABLE, **STRATEGIC}.items():
            self.assertTrue(
                (ROOT / "resource/set/multiplayer/armies" / f"{side}.set").is_file(),
                actor_id,
            )
            self.assertTrue(
                (ROOT / "resource/interface/pages/multi" / f"flag_{side}.tga").is_file(),
                actor_id,
            )

    def test_playable_units_research_ai_ids_match_and_do_not_leak(self) -> None:
        forbidden = re.compile(
            r"Serb_|side\(rusa\)|mp/rusa/|\bwagner\b|\bdonbas\b|\bkpa\b|\bkor_",
            re.IGNORECASE,
        )
        for actor_id, side in PLAYABLE.items():
            units = (ROOT / f"resource/set/multiplayer/units/conquest/units_{side}.set").read_text(
                encoding="utf-8"
            )
            research = (ROOT / f"resource/set/dynamic_campaign/unit_research_{side}.set").read_text(
                encoding="utf-8"
            )
            lua = (
                ROOT / f"resource/script/multiplayer/units/{side}/conquest.{side}.lua"
            ).read_text(encoding="utf-8")
            unit_ids = set(_RESOLVED_UNIT_RE.findall(units))
            research_ids = {
                str(json.loads(raw)["engine_id"]) for raw in _GOC_NODE_RE.findall(research)
            }
            lua_ids = set(_LUA_PURCHASE_RE.findall(lua))
            self.assertEqual(len(unit_ids), 55, actor_id)
            self.assertEqual(unit_ids, research_ids, actor_id)
            self.assertEqual(unit_ids, lua_ids, actor_id)
            self.assertIn("components=nato_full_fallback", units)
            self.assertIsNone(forbidden.search(units), actor_id)
            self.assertIsNone(forbidden.search(research), actor_id)
            self.assertIsNone(forbidden.search(lua), actor_id)

    def test_playable_committed_inf_namespace_is_actor_scoped_and_positive(self) -> None:
        for actor_id, side in PLAYABLE.items():
            text = (ROOT / f"resource/set/multiplayer/units/conquest/inf_{side}.set").read_text(
                encoding="utf-8"
            )
            metadata = [json.loads(raw) for raw in _GOC_INF_COST_RE.findall(text)]
            self.assertTrue(metadata, actor_id)
            for row in metadata:
                self.assertTrue(str(row["source_path"]).startswith("mp/nato/"), actor_id)
                self.assertTrue(str(row["target_path"]).startswith(f"mp/{side}/"), actor_id)
                self.assertGreater(float(row["cost"]), 0.0, actor_id)
            self.assertEqual(set(_SIDE_CALL_RE.findall(text)), {side})
            self.assertNotIn('"target_path":"mp/nato/', text)
            self.assertNotIn("side(nato)", text)
            self.assertNotIn("side(rusa)", text)

    def test_strategic_only_has_registration_but_no_purchase_authority(self) -> None:
        alliances = render_alliances_generic()
        values = render_values_set()
        conquest = (ROOT / "resource/script/multiplayer/modes/conquest.lua").read_text(
            encoding="utf-8"
        )
        for actor_id, side in STRATEGIC.items():
            self.assertNotIn(f'{{armies "{side}"}}', alliances, actor_id)
            self.assertNotIn(side, values, actor_id)
            self.assertNotIn(f"{side} =", conquest, actor_id)
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
                (ROOT / f"resource/script/multiplayer/units/{side}/conquest.{side}.lua").exists(),
                actor_id,
            )

    def test_shared_renderers_are_deterministic_and_localization_is_complete(self) -> None:
        self.assertEqual(render_alliances_generic(), render_alliances_generic())
        self.assertEqual(render_values_set(), render_values_set())
        labels = render_dlg_mp_keys()
        self.assertEqual(labels, render_dlg_mp_keys())
        for side in [*PLAYABLE.values(), *STRATEGIC.values()]:
            self.assertIn(f'msgid "mp/army/{side}"', labels)

    def test_all_four_fallback_materializations_are_source_equivalent(self) -> None:
        normalized = []
        for actor_id, side in PLAYABLE.items():
            text = (ROOT / f"resource/set/multiplayer/units/conquest/units_{side}.set").read_text(
                encoding="utf-8"
            )
            text = text.replace(side, "goc_actor")
            text = re.sub(r"^; actor_id=.*$", "; actor_id=actor", text, flags=re.MULTILINE)
            text = re.sub(r"^; display_name=.*$", "; display_name=Actor", text, flags=re.MULTILINE)
            normalized.append(text)
        self.assertEqual(len(set(normalized)), 1)


class Phase192StrategicPersistenceTests(unittest.TestCase):
    def test_new_actors_persist_and_strategic_only_cannot_be_selected(self) -> None:
        state = load_bundled_scenario("legacy_goe_europe")
        actors = install_bundled_strategic_actors(state, selected_actor_id="grc")
        self.assertEqual(actors["grc"].tactical_side.campaign_faction(), Faction.NATO)
        self.assertEqual(actors["mda"].tactical_side.campaign_faction(), Faction.RUSSIA)
        for actor_id in STRATEGIC:
            with self.subTest(actor_id=actor_id):
                with self.assertRaises(ValueError):
                    set_selected_actor(state, actor_id)

        runtime_rows = state.map_metadata[ACTOR_RUNTIME_KEY]["actors"]
        runtime_rows["grc"]["researched_keys"] = ["actor:grc:test"]
        runtime_rows["rou"]["researched_keys"] = []
        before = strategic_actor_snapshot(state)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.json"
            save_campaign(state, path)
            loaded = load_campaign(path)
        after = strategic_actor_snapshot(loaded)
        self.assertEqual(after, before)
        by_id = {row["actor_id"]: row for row in after["actors"]}
        self.assertEqual(by_id["grc"]["researched_keys"], ["actor:grc:test"])
        self.assertEqual(by_id["rou"]["researched_keys"], [])
        for actor_id in STRATEGIC:
            self.assertFalse(by_id[actor_id]["playable"])


if __name__ == "__main__":
    unittest.main()
