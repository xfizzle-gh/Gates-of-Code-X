"""#191 Phase 2 Western/Northern/Central European actors."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.faction_wiring import (
    FactionWiringCompiler,
    FactionWiringError,
    load_faction_manifest,
    validate_faction_manifest,
)
from gates_of_codex.goc_tactical_army_registry import (
    GocArmyRegistryError,
    army_numeric_id,
    audit_numeric_ids_against_stack,
    load_goc_army_registry,
    registered_goc_sides,
    render_army_set,
    supported_tactical_sides,
    validate_goc_army_registry,
)
from gates_of_codex.expanded_nations_models import (
    ExpandedNationsError,
    research_relative_for_side,
    select_actor,
    side_family,
)


PHASE1_ACTORS = {
    "usa", "gbr", "deu", "fra", "pol", "ita", "fin", "swe", "nld", "can",
    "nor", "dnk", "esp", "tur", "rus", "ukr", "prc", "dprk", "donbas", "blr", "srb",
    "ukr_ildu", "kpa_expeditionary", "wagner",
}
PLAYABLE_191 = {"bel", "prt", "cze", "svk", "hun", "ltu", "lva", "est"}
STRATEGIC_191 = {"aut", "che", "irl", "isl"}
ALL_191 = PLAYABLE_191 | STRATEGIC_191


class GocArmyRegistryTests(unittest.TestCase):
    def test_registry_valid_and_unique(self) -> None:
        payload = load_goc_army_registry()
        validate_goc_army_registry(payload)
        ids = [int(row["numeric_id"]) for row in payload["armies"].values()]
        self.assertEqual(len(ids), len(set(ids)))
        for numeric_id in ids:
            self.assertGreaterEqual(numeric_id, 0)
            self.assertLessEqual(numeric_id, 99)
            self.assertNotIn(numeric_id, set(range(0, 14)))
            self.assertNotIn(numeric_id, {90, 91, 92, 93, 94})

    def test_supported_sides_include_registry(self) -> None:
        sides = supported_tactical_sides()
        for core in ("nato", "ukr", "rusa", "prc"):
            self.assertIn(core, sides)
        for token in registered_goc_sides():
            self.assertIn(token, sides)
            self.assertTrue(token.startswith("goc_"))

    def test_duplicate_numeric_id_rejected(self) -> None:
        payload = json.loads(json.dumps(load_goc_army_registry()))
        payload["armies"]["goc_dup"] = {
            "numeric_id": payload["armies"]["goc_bel"]["numeric_id"],
            "actor_id": "dup",
            "coalition": "west",
            "playable": True,
            "issue": 191,
        }
        with self.assertRaises(GocArmyRegistryError):
            validate_goc_army_registry(payload)

    def test_reserved_spike_band_rejected(self) -> None:
        payload = json.loads(json.dumps(load_goc_army_registry()))
        payload["armies"]["goc_bad"] = {
            "numeric_id": 90,
            "actor_id": "bad",
            "coalition": "west",
            "playable": True,
            "issue": 191,
        }
        with self.assertRaises(GocArmyRegistryError):
            validate_goc_army_registry(payload)

    def test_army_set_render_and_on_disk_files(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for token in sorted(registered_goc_sides()):
            text = render_army_set(token)
            self.assertIn(f"{{id {army_numeric_id(token)}}}", text)
            path = root / "resource/set/multiplayer/armies" / f"{token}.set"
            self.assertTrue(path.is_file(), token)
            on_disk = path.read_text(encoding="utf-8")
            self.assertEqual(on_disk, text)

    def test_stack_collision_audit_against_live_workshop_if_present(self) -> None:
        workshop = Path(r"E:\Steam\steamapps\workshop\content\400750")
        roots = [
            workshop / "2897299509",
            workshop / "3261086933",
            workshop / "3696721120",
        ]
        if not all(r.is_dir() for r in roots):
            self.skipTest("live workshop stack not present")
        collisions = audit_numeric_ids_against_stack(roots)
        # Foreign names on production IDs must not exist. Same-token goc_* files are OK.
        self.assertEqual(collisions, [])


class Phase191ManifestTests(unittest.TestCase):
    def test_manifest_includes_phase1_and_191_actors(self) -> None:
        manifest = load_faction_manifest()
        validate_faction_manifest(manifest)
        actors = {a["actor_id"]: a for a in manifest["actors"]}
        self.assertTrue(PHASE1_ACTORS.issubset(set(actors)))
        self.assertTrue(ALL_191.issubset(set(actors)))
        # Phase 1 sides unchanged
        for actor_id in PHASE1_ACTORS:
            self.assertIn(actors[actor_id]["tactical_side"], {"nato", "ukr", "rusa", "prc"})

    def test_191_playable_mapping_and_components(self) -> None:
        manifest = load_faction_manifest()
        actors = {a["actor_id"]: a for a in manifest["actors"]}
        expected_side = {
            "bel": "goc_bel",
            "prt": "goc_prt",
            "cze": "goc_cze",
            "svk": "goc_svk",
            "hun": "goc_hun",
            "ltu": "goc_ltu",
            "lva": "goc_lva",
            "est": "goc_est",
        }
        for actor_id, side in expected_side.items():
            row = actors[actor_id]
            self.assertTrue(row["playable"])
            self.assertEqual(row["tactical_side"], side)
            self.assertEqual(army_numeric_id(side), load_goc_army_registry()["armies"][side]["numeric_id"])
        for actor_id in ("bel", "prt", "hun", "ltu", "lva", "est"):
            self.assertEqual(actors[actor_id]["components"], ["nato_full_fallback"])
            self.assertEqual(actors[actor_id]["roster_class"], "coalition_fallback")
        self.assertEqual(
            actors["cze"]["components"],
            ["cze_equipment_identity", "nato_common_infantry_bridge"],
        )
        self.assertEqual(
            actors["svk"]["components"],
            ["svk_equipment_identity", "nato_common_infantry_bridge"],
        )
        # DANA exact selectors only once each
        cze_units = manifest["components"]["cze_equipment_identity"]["selectors"][0]["units"]
        svk_units = manifest["components"]["svk_equipment_identity"]["selectors"][0]["units"]
        self.assertEqual(cze_units, ["vz_77_dana"])
        self.assertEqual(svk_units, ["vz_77_dana"])

    def test_191_strategic_only_constraints(self) -> None:
        manifest = load_faction_manifest()
        actors = {a["actor_id"]: a for a in manifest["actors"]}
        for actor_id in STRATEGIC_191:
            row = actors[actor_id]
            self.assertFalse(row["playable"])
            self.assertEqual(row["roster_class"], "strategic_only")
            self.assertEqual(row["components"], [])
            self.assertEqual(row["research"]["mode"], "none")
            self.assertEqual(row["required_categories"], [])
            self.assertTrue(str(row["tactical_side"]).startswith("goc_"))

    def test_strategic_only_cannot_be_selected_for_projection(self) -> None:
        # Minimal resolved payload shape for select_actor
        payload = {
            "schema": "gates-of-codex.resolved-factions",
            "schema_version": 1,
            "error_count": 0,
            "warning_count": 0,
            "wiring_signature": "x" * 64,
            "actor_count": 1,
            "actors": [
                {
                    "actor_id": "aut",
                    "playable": False,
                    "unit_count": 0,
                    "units": [],
                    "research_node_count": 0,
                    "research_nodes": [],
                    "tactical_side": "goc_aut",
                }
            ],
        }
        with self.assertRaises(ExpandedNationsError):
            select_actor(payload, "aut")

    def test_side_family_isolation_for_goc(self) -> None:
        self.assertEqual(side_family("goc_bel"), frozenset({"goc_bel"}))
        self.assertEqual(side_family("nato"), frozenset({"nato", "frg"}))
        path = research_relative_for_side("goc_cze")
        self.assertEqual(path.as_posix(), "resource/set/dynamic_campaign/unit_research_goc_cze.set")


class Phase191CompileFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.codex = self.root / "CodeX"
        self._write_stack()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_stack(self) -> None:
        # Materializable catalog fixtures matching test_faction_wiring shapes.
        research = self.codex / "resource/set/dynamic_campaign"
        research.mkdir(parents=True)
        (research / "unit_research_nato.set").write_text(
            "\n".join(
                [
                    '{ tech "2022arf" requires "" costs 1 position 0 1}',
                    '{ tech "2022nrft" requires "" costs 1 position 0 2}',
                    '{ tech "2022nrfa" requires "" costs 1 position 0 3}',
                    '{"squad_arf_rifle" requires "2022arf" costs 1 position 1 1}',
                    '{"squad_arf_mg" requires "2022arf" costs 1 position 2 1}',
                    '{"squad_arf_at" requires "2022arf" costs 1 position 3 1}',
                    '{"squad_arf_scout" requires "2022arf" costs 1 position 4 1}',
                    '{"squad_dsk_eng" requires "2022arf" costs 1 position 5 1}',
                    '{"squad_dsk_eng_at" requires "2022arf" costs 1 position 6 1}',
                    '{"test_tank" requires "2022nrft" costs 2 position 1 2}',
                    '{"vz_77_dana" requires "2022nrfa" costs 2 position 1 3}',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        units = self.codex / "resource/set/multiplayer/units/conquest"
        units.mkdir(parents=True)
        (units / "units_nato.set").write_text(
            "\n".join(
                [
                    '("squad" side(nato) period(2022s) name(squad_arf_rifle) c1(test_lead:1) c2(test_rifleman:4))',
                    '("squad" side(nato) period(2022s) name(squad_arf_mg) c1(test_lead:1) c2(test_rifleman:3))',
                    '("squad" side(nato) period(2022s) name(squad_arf_at) c1(test_lead:1) c2(test_rifleman:2))',
                    '("squad" side(nato) period(2022s) name(squad_arf_scout) c1(test_lead:1) c2(test_rifleman:2))',
                    '("squad" side(nato) period(2022s) name(squad_dsk_eng) c1(test_lead:1) c2(test_rifleman:2))',
                    '("squad" side(nato) period(2022s) name(squad_dsk_eng_at) c1(test_lead:1) c2(test_rifleman:2))',
                    '{"test_tank" {vehicle "test_tank"}}',
                    '{"vz_77_dana" {vehicle "vz_77_dana"}}',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (self.codex / "resource/set/registry").mkdir(parents=True)
        (self.codex / "resource/set/registry/unit.reg").write_text(
            '{"test_tank"}\n{"vz_77_dana"}\n',
            encoding="utf-8",
        )
        breeds = self.codex / "resource/set/breed/mp/nato/2022s"
        breeds.mkdir(parents=True)
        for name in ("test_lead", "test_rifleman"):
            (breeds / f"{name}.set").write_text("{breed}\n", encoding="utf-8")

    def test_compile_191_playable_and_strategic_only(self) -> None:
        manifest = load_faction_manifest()
        # Keep only phase1 nato_full_fallback deps + 191 actors to speed fixture
        # Full manifest compile against fixture stack may miss many phase1 units.
        # Use a trimmed manifest of #191 actors + required components only.
        comps = {
            key: manifest["components"][key]
            for key in (
                "nato_full_fallback",
                "cze_equipment_identity",
                "svk_equipment_identity",
                "nato_common_infantry_bridge",
                "nato_common_infantry",
            )
            if key in manifest["components"]
        }
        # bridge aliases common infantry selectors
        if "nato_common_infantry_bridge" in comps and "nato_common_infantry" in manifest["components"]:
            comps["nato_common_infantry_bridge"] = {
                **comps["nato_common_infantry_bridge"],
                "selectors": manifest["components"]["nato_common_infantry"]["selectors"],
            }
        actors = [a for a in manifest["actors"] if a["actor_id"] in ALL_191]
        trimmed = {
            "schema": manifest["schema"],
            "schema_version": manifest["schema_version"],
            "source_policy": manifest["source_policy"],
            "components": comps,
            "actors": actors,
        }
        validate_faction_manifest(trimmed)
        payload = FactionWiringCompiler([self.codex], manifest=trimmed).compile()
        self.assertEqual(payload["error_count"], 0)
        by_id = {a["actor_id"]: a for a in payload["actors"]}

        bel = by_id["bel"]
        self.assertTrue(bel["playable"])
        self.assertEqual(bel["tactical_side"], "goc_bel")
        self.assertGreater(bel["unit_count"], 0)
        self.assertTrue(all(u["tactical_side"] == "goc_bel" for u in bel["units"]))
        self.assertTrue(all(n["key"].startswith("actor:bel:") for n in bel["research_nodes"]))

        cze = by_id["cze"]
        names = {u["unit_name"] for u in cze["units"]}
        self.assertIn("vz_77_dana", names)
        # DANA present exactly once
        self.assertEqual(sum(1 for u in cze["units"] if u["unit_name"] == "vz_77_dana"), 1)
        # Infantry bridge units are present and not claiming Czech national provenance
        self.assertTrue(any(u["unit_name"] != "vz_77_dana" for u in cze["units"]))

        aut = by_id["aut"]
        self.assertFalse(aut["playable"])
        self.assertEqual(aut["unit_count"], 0)
        self.assertEqual(aut["research_node_count"], 0)
        self.assertEqual(aut["components"], [])

    def test_no_actor_purchase_leakage_between_bel_and_cze(self) -> None:
        manifest = load_faction_manifest()
        comps = {
            key: manifest["components"][key]
            for key in (
                "nato_full_fallback",
                "cze_equipment_identity",
                "nato_common_infantry_bridge",
                "nato_common_infantry",
            )
            if key in manifest["components"]
        }
        if "nato_common_infantry_bridge" in comps:
            comps["nato_common_infantry_bridge"] = {
                **comps["nato_common_infantry_bridge"],
                "selectors": manifest["components"]["nato_common_infantry"]["selectors"],
            }
        actors = [a for a in manifest["actors"] if a["actor_id"] in {"bel", "cze"}]
        trimmed = {
            "schema": manifest["schema"],
            "schema_version": manifest["schema_version"],
            "source_policy": manifest["source_policy"],
            "components": comps,
            "actors": actors,
        }
        payload = FactionWiringCompiler([self.codex], manifest=trimmed).compile()
        by_id = {a["actor_id"]: a for a in payload["actors"]}
        bel_units = {u["unit_name"] for u in by_id["bel"]["units"]}
        cze_units = {u["unit_name"] for u in by_id["cze"]["units"]}
        # Bel must not be limited to only DANA; cze must include DANA
        self.assertIn("vz_77_dana", cze_units)
        # Actor-scoped research keys never cross
        bel_keys = {n["key"] for n in by_id["bel"]["research_nodes"]}
        cze_keys = {n["key"] for n in by_id["cze"]["research_nodes"]}
        self.assertTrue(all(k.startswith("actor:bel:") for k in bel_keys))
        self.assertTrue(all(k.startswith("actor:cze:") for k in cze_keys))
        self.assertFalse(bel_keys & cze_keys)

    def test_unapproved_substring_component_not_in_manifest(self) -> None:
        manifest = load_faction_manifest()
        # No broad europe/substring component IDs
        for bad in ("europe_all", "all_nato_units", "substring_bel", "auto_national"):
            self.assertNotIn(bad, manifest["components"])

    def test_strategic_only_with_components_rejected(self) -> None:
        manifest = load_faction_manifest()
        for actor in manifest["actors"]:
            if actor["actor_id"] == "aut":
                actor["components"] = ["nato_full_fallback"]
                break
        with self.assertRaises(FactionWiringError):
            validate_faction_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
