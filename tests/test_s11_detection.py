from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gates_of_codex.models import (
    Battalion,
    BattalionRosterEntry,
    CampaignState,
    Faction,
    FactionState,
    ForceEchelon,
    Formation,
    FormationKind,
    InformationTier,
    Province,
    StrategicFormation,
)
from gates_of_codex.observation import (
    ObservationMutationContext,
    combine_detection_tier,
    current_and_last_known_records,
    opaque_contact_id,
    project_operational_observation,
    refresh_all_observer_knowledge,
)
from gates_of_codex.operational_capture import ensure_site_control_state
from gates_of_codex.operational_schema import FormationOperationalPosition, PositionMode


def _node(node_id: str, province: str) -> dict:
    return {
        "node_id": node_id,
        "display_name": node_id,
        "pixel": [0, 0],
        "province_id": province,
        "site_id": None,
        "kind": "anchor",
        "terrain": "plain",
        "metadata": {},
    }


def _edge(edge_id: str, a: str, b: str) -> dict:
    return {
        "edge_id": edge_id,
        "a": a,
        "b": b,
        "kind": "corridor",
        "authority": "authored",
        "length_px": 10,
        "base_move_points_milli": 1000,
        "movement_cost_milli": 1000,
        "requires_port": False,
        "can_be_blockaded": False,
        "traversal_enabled": True,
        "bidirectional": True,
        "province_ids": [a, b],
        "metadata": {},
    }


def _site(site_id: str, node: str, province: str, kind: str, *, synthetic: bool = False) -> dict:
    return {
        "site_id": site_id,
        "display_name": site_id,
        "kind": kind,
        "province_id": province,
        "pixel": [0, 0],
        "route_node_id": node,
        "control_weight_milli": 1000,
        "capture_threshold_milli": 1000,
        "owner_faction": "nato",
        "metadata": {"synthetic_anchor_control_site": synthetic},
    }


def _force(fid: str, faction: Faction, province: str, node: str, *, recon: bool = False) -> StrategicFormation:
    bid = f"bn-{fid}"
    return StrategicFormation(
        strategic_formation_id=fid,
        display_name=fid,
        faction=faction,
        province_id=province,
        echelon=ForceEchelon.BATTALION,
        battalion_ids=[bid],
        template_formation_id=f"toe-{faction.value}",
        recon_capability=recon,
        position=FormationOperationalPosition(
            mode=PositionMode.AT_NODE.value,
            node_id=node,
            progress_milli=0,
        ),
    )


def _state(tmp: Path, *, sites: list[dict] | None = None) -> CampaignState:
    graph = {
        "schema": "gates-of-codex.operational-graph",
        "schema_version": 2,
        "map_id": "s11",
        "rules": {"ticks_per_strategic_turn": 10, "capture_hold_ticks": 2, "max_friendly_formations_per_node": 3},
        "nodes": [_node("na", "a"), _node("nb", "b"), _node("nc", "c")],
        "edges": [_edge("eab", "na", "nb"), _edge("ebc", "nb", "nc")],
        "sites": sites or [],
        "metadata": {},
    }
    path = tmp / "graph.json"
    path.write_text(json.dumps(graph), encoding="utf-8")
    forces = {
        "recon-a": _force("recon-a", Faction.NATO, "a", "na", recon=True),
        "enemy-c": _force("enemy-c", Faction.RUSSIA, "c", "nc"),
    }
    battalions = {
        f"bn-{fid}": Battalion(
            battalion_id=f"bn-{fid}", faction=force.faction, province_id=force.province_id,
            formation_id=f"toe-{force.faction.value}", strategic_formation_id=fid,
            roster=[BattalionRosterEntry("u", 2)], authorized_roster=[BattalionRosterEntry("u", 2)],
        )
        for fid, force in forces.items()
    }
    state = CampaignState(
        campaign_name="S11 detection",
        map_id="s11",
        map_metadata={"operational_graph": str(path), "operational_maneuver_enabled": True},
        factions={
            "nato": FactionState(Faction.NATO, is_human_controlled=True),
            "rusa": FactionState(Faction.RUSSIA),
        },
        formations={
            "toe-nato": Formation("toe-nato", "N", Faction.NATO, "usa", FormationKind.AIRBORNE_BRIGADE),
            "toe-rusa": Formation("toe-rusa", "R", Faction.RUSSIA, "rus"),
        },
        strategic_formations=forces,
        battalions=battalions,
        provinces={
            "a": Province("a", "A", Faction.NATO, ["b"]),
            "b": Province("b", "B", Faction.NEUTRAL, ["a", "c"]),
            "c": Province("c", "C", Faction.RUSSIA, ["b"]),
        },
        fog_of_war_enabled=True,
        schema_version=11,
    )
    ensure_site_control_state(state)
    return state


class DetectionCombinationTests(unittest.TestCase):
    def test_complete_combination_table(self) -> None:
        cases = [
            (True, 0, 0, InformationTier.FULLY_OBSERVED),
            (False, 0, 0, InformationTier.UNKNOWN),
            (False, 0, 1, InformationTier.CONTACT),
            (False, 0, 2, InformationTier.IDENTIFIED),
            (False, 1, 0, InformationTier.IDENTIFIED),
            (False, 1, 1, InformationTier.ASSESSED),
            (False, 2, 0, InformationTier.ASSESSED),
            (False, 5, 5, InformationTier.ASSESSED),
        ]
        for direct, recon, site, expected in cases:
            with self.subTest(direct=direct, recon=recon, site=site):
                self.assertEqual(expected, combine_detection_tier(direct=direct, recon_count=recon, site_count=site))

    def test_recon_node_covers_incident_edge_and_opposite_endpoint_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            observations = project_operational_observation(state, Faction.NATO)
            self.assertNotIn("enemy-c", observations)
            state.strategic_formations["enemy-c"].position.node_id = "nb"
            observations = project_operational_observation(state, Faction.NATO)
            self.assertEqual(InformationTier.IDENTIFIED, observations["enemy-c"].tier)
            state.strategic_formations["enemy-c"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value, edge_id="eab", facing_node_id="nb", progress_milli=500
            )
            observations = project_operational_observation(state, Faction.NATO)
            self.assertEqual(InformationTier.IDENTIFIED, observations["enemy-c"].tier)

    def test_sites_require_exact_kind_authored_node_control_and_not_synthetic(self) -> None:
        sites = [
            _site("obs", "nb", "b", "observation"),
            _site("cmd", "nb", "b", "command"),
            _site("objective", "nb", "b", "objective"),
            _site("synthetic", "nb", "b", "observation", synthetic=True),
        ]
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td), sites=sites)
            state.strategic_formations["recon-a"].recon_capability = False
            state.strategic_formations["enemy-c"].position.node_id = "nc"
            obs = project_operational_observation(state, Faction.NATO)["enemy-c"]
            self.assertEqual(InformationTier.IDENTIFIED, obs.tier)
            self.assertEqual(["site:cmd", "site:obs"], obs.source_ids)



    def test_destroyed_formations_neither_detect_nor_appear_as_current_contacts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            state.strategic_formations["enemy-c"].position.node_id = "nb"
            state.battalions["bn-recon-a"].roster = []
            self.assertNotIn(
                "enemy-c", project_operational_observation(state, Faction.NATO)
            )

            state.battalions["bn-recon-a"].roster = [BattalionRosterEntry("u", 1)]
            state.battalions["bn-enemy-c"].roster = []
            self.assertNotIn(
                "enemy-c", project_operational_observation(state, Faction.NATO)
            )

    def test_same_edge_without_authoritative_encounter_is_not_direct_contact(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            state.strategic_formations["recon-a"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id="eab",
                facing_node_id="nb",
                progress_milli=100,
            )
            state.strategic_formations["enemy-c"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id="eab",
                facing_node_id="na",
                progress_milli=100,
            )
            observed = project_operational_observation(state, Faction.NATO)["enemy-c"]
            self.assertEqual(InformationTier.IDENTIFIED, observed.tier)


    def test_uncontrolled_site_does_not_fall_back_to_authored_owner(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td), sites=[_site("obs", "nb", "b", "observation")])
            state.strategic_formations["recon-a"].recon_capability = False
            state.map_metadata["operational_site_control"]["obs"][
                "controller_faction"
            ] = None
            self.assertNotIn(
                "enemy-c", project_operational_observation(state, Faction.NATO)
            )

    def test_no_graph_fallback_uses_province_contact_and_adjacent_recon(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            state.map_metadata.pop("operational_graph", None)
            enemy = state.strategic_formations["enemy-c"]

            enemy.province_id = "b"
            state.battalions["bn-enemy-c"].province_id = "b"
            observed = project_operational_observation(state, Faction.NATO)["enemy-c"]
            self.assertEqual(InformationTier.IDENTIFIED, observed.tier)

            enemy.province_id = "a"
            state.battalions["bn-enemy-c"].province_id = "a"
            observed = project_operational_observation(state, Faction.NATO)["enemy-c"]
            self.assertEqual(InformationTier.FULLY_OBSERVED, observed.tier)

    def test_no_graph_sites_use_persisted_authored_province_authority(self) -> None:
        cases = (
            ([ _site("obs", "nb", "b", "observation") ], False, "c", InformationTier.CONTACT, ["site:obs"]),
            ([ _site("obs", "nb", "b", "observation"), _site("cmd", "nb", "b", "command") ], False, "c", InformationTier.IDENTIFIED, ["site:cmd", "site:obs"]),
            ([ _site("obs", "nb", "b", "observation") ], True, "b", InformationTier.ASSESSED, ["recon:recon-a", "site:obs"]),
            ([ _site("obs", "nb", "b", "observation") ], False, "b", InformationTier.CONTACT, ["site:obs"]),
        )
        for sites, recon, province, expected, sources in cases:
            with self.subTest(expected=expected.value, recon=recon, province=province), tempfile.TemporaryDirectory() as td:
                state = _state(Path(td), sites=sites)
                state.strategic_formations["recon-a"].recon_capability = recon
                enemy = state.strategic_formations["enemy-c"]
                enemy.province_id = province
                state.battalions["bn-enemy-c"].province_id = province
                state.map_metadata.pop("operational_graph", None)
                observed = project_operational_observation(state, Faction.NATO)["enemy-c"]
                self.assertEqual(expected, observed.tier)
                self.assertEqual(sources, observed.source_ids)

    def test_no_graph_sites_reject_ineligible_synthetic_uncontrolled_and_hostile(self) -> None:
        sites = [
            _site("objective", "nb", "b", "objective"),
            _site("synthetic", "nb", "b", "observation", synthetic=True),
            _site("uncontrolled", "nb", "b", "observation"),
            _site("hostile", "nb", "b", "command"),
        ]
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td), sites=sites)
            state.strategic_formations["recon-a"].recon_capability = False
            control = state.map_metadata["operational_site_control"]
            control["uncontrolled"]["controller_faction"] = None
            control["hostile"]["controller_faction"] = "rusa"
            state.map_metadata.pop("operational_graph", None)
            self.assertNotIn(
                "enemy-c", project_operational_observation(state, Faction.NATO)
            )

    def test_no_graph_duplicate_authored_source_ids_are_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td), sites=[_site("obs", "nb", "b", "observation")])
            state.strategic_formations["recon-a"].recon_capability = False
            duplicate = dict(state.map_metadata["operational_site_control"]["obs"])
            duplicate["authored_site_id"] = "obs"
            state.map_metadata["operational_site_control"]["duplicate-storage-key"] = duplicate
            state.map_metadata.pop("operational_graph", None)
            observed = project_operational_observation(state, Faction.NATO)["enemy-c"]
            self.assertEqual(InformationTier.CONTACT, observed.tier)
            self.assertEqual(["site:obs"], observed.source_ids)

    def test_no_graph_ambush_reduces_site_tier_and_fog_off_stays_complete(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(
                Path(td),
                sites=[
                    _site("obs", "nb", "b", "observation"),
                    _site("cmd", "nb", "b", "command"),
                ],
            )
            state.strategic_formations["recon-a"].recon_capability = False
            state.map_metadata.pop("operational_graph", None)
            enemy = state.strategic_formations["enemy-c"]
            enemy.stance = "ambush"
            enemy.ambush_ready_tick = 1
            observed = project_operational_observation(state, Faction.NATO)["enemy-c"]
            self.assertEqual(InformationTier.CONTACT, observed.tier)

            state.fog_of_war_enabled = False
            from gates_of_codex.frontend import build_frontend_snapshot
            snapshot = build_frontend_snapshot(state)
            self.assertEqual(2, len(snapshot["strategic_formations"]))

    def test_ambush_reduces_noncontact_but_not_direct(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            enemy = state.strategic_formations["enemy-c"]
            enemy.position.node_id = "nb"
            enemy.stance = "ambush"
            enemy.ambush_ready_tick = 1
            self.assertEqual(InformationTier.CONTACT, project_operational_observation(state, Faction.NATO)["enemy-c"].tier)
            enemy.position.node_id = "na"
            self.assertEqual(InformationTier.FULLY_OBSERVED, project_operational_observation(state, Faction.NATO)["enemy-c"].tier)


class KnowledgeLifecycleTests(unittest.TestCase):
    def test_refresh_stale_reacquire_promote_and_confirmed_remove(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td), sites=[_site("obs", "nb", "b", "observation")])
            state.strategic_formations["recon-a"].recon_capability = False
            enemy = state.strategic_formations["enemy-c"]
            refresh_all_observer_knowledge(state)
            scope = "faction:nato"
            rows = state.knowledge_by_observer[scope]
            self.assertEqual(1, len(rows))
            first = next(iter(rows.values()))
            self.assertEqual(InformationTier.CONTACT, first.tier)
            opaque_key = first.record_key

            enemy.position.node_id = "na"  # direct contact -> promotion
            refresh_all_observer_knowledge(state)
            rows = state.knowledge_by_observer[scope]
            self.assertNotIn(opaque_key, rows)
            self.assertIn("formation:enemy-c", rows)
            self.assertEqual(InformationTier.FULLY_OBSERVED, rows["formation:enemy-c"].tier)

            enemy.position.node_id = "nc"
            state.map_metadata["operational_site_control"]["obs"]["controller_faction"] = "rusa"
            refresh_all_observer_knowledge(state)
            stale = state.knowledge_by_observer[scope]["formation:enemy-c"]
            self.assertFalse(stale.current)
            self.assertEqual("na", stale.last_seen_node_id)

            refresh_all_observer_knowledge(
                state,
                ObservationMutationContext({scope: frozenset({"enemy-c"})}),
            )
            self.assertEqual({}, state.knowledge_by_observer[scope])


    def test_stale_formerly_fully_observed_subject_is_not_inferred_destroyed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            enemy = state.strategic_formations["enemy-c"]
            enemy.position.node_id = "na"
            refresh_all_observer_knowledge(state)
            scope = "faction:nato"
            self.assertEqual(
                InformationTier.FULLY_OBSERVED,
                state.knowledge_by_observer[scope]["formation:enemy-c"].tier,
            )

            enemy.position.node_id = "nc"
            state.strategic_formations["recon-a"].recon_capability = False
            refresh_all_observer_knowledge(state)
            stale = state.knowledge_by_observer[scope]["formation:enemy-c"]
            self.assertFalse(stale.current)

            state.strategic_formations.pop("enemy-c")
            state.battalions.pop("bn-enemy-c")
            refresh_all_observer_knowledge(state)
            retained = state.knowledge_by_observer[scope]["formation:enemy-c"]
            self.assertFalse(retained.current)
            self.assertEqual("na", retained.last_seen_node_id)


    def test_unknown_mutation_context_scope_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            with self.assertRaisesRegex(
                ValueError, "unknown_observation_mutation_scope:faction:ukr"
            ):
                refresh_all_observer_knowledge(
                    state,
                    ObservationMutationContext(
                        {"faction:ukr": frozenset({"enemy-c"})}
                    ),
                )


    def test_fully_observed_missing_subject_is_confirmed_removed_without_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            enemy = state.strategic_formations["enemy-c"]
            enemy.position.node_id = "na"
            refresh_all_observer_knowledge(state)
            scope = "faction:nato"
            self.assertEqual(
                InformationTier.FULLY_OBSERVED,
                state.knowledge_by_observer[scope]["formation:enemy-c"].tier,
            )

            state.strategic_formations.pop("enemy-c")
            state.battalions.pop("bn-enemy-c")
            refresh_all_observer_knowledge(state)
            self.assertEqual({}, state.knowledge_by_observer[scope])


    def test_identified_identity_survives_current_contact_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td), sites=[_site("obs", "nb", "b", "observation")])
            state.strategic_formations["recon-a"].recon_capability = False
            enemy = state.strategic_formations["enemy-c"]
            enemy.position.node_id = "na"
            refresh_all_observer_knowledge(state)
            scope = "faction:nato"
            persisted = state.knowledge_by_observer[scope]["formation:enemy-c"]
            self.assertEqual(InformationTier.FULLY_OBSERVED, persisted.tier)

            enemy.position.node_id = "nb"
            enemy.province_id = "b"
            state.battalions["bn-enemy-c"].province_id = "b"
            before = json.dumps(state.to_dict(), sort_keys=True)
            current, stale = current_and_last_known_records(state, Faction.NATO)
            after = json.dumps(state.to_dict(), sort_keys=True)

            self.assertEqual(before, after)
            self.assertEqual([], stale)
            observed = current["enemy-c"]
            self.assertEqual(InformationTier.IDENTIFIED, observed.tier)
            self.assertEqual("enemy-c", observed.display_name)
            self.assertEqual("rusa", observed.faction_id)
            self.assertEqual("battalion", observed.echelon)
            self.assertEqual("", observed.strength_band)
            self.assertEqual("", observed.last_seen_direction)

            refresh_all_observer_knowledge(state)
            refreshed = state.knowledge_by_observer[scope]["formation:enemy-c"]
            self.assertEqual(InformationTier.IDENTIFIED, refreshed.tier)
            self.assertEqual("enemy-c", refreshed.display_name)
            refreshed.validate()


    def test_pure_reacquisition_does_not_duplicate_stale_record(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td), sites=[_site("obs", "nb", "b", "observation")])
            state.strategic_formations["recon-a"].recon_capability = False
            enemy = state.strategic_formations["enemy-c"]
            refresh_all_observer_knowledge(state)
            state.map_metadata["operational_site_control"]["obs"]["controller_faction"] = "rusa"
            refresh_all_observer_knowledge(state)
            self.assertFalse(
                state.knowledge_by_observer["faction:nato"][
                    next(iter(state.knowledge_by_observer["faction:nato"]))
                ].current
            )

            state.map_metadata["operational_site_control"]["obs"]["controller_faction"] = "nato"
            current, stale = current_and_last_known_records(state, Faction.NATO)
            self.assertIn(enemy.strategic_formation_id, current)
            self.assertEqual([], stale)

    def test_same_location_multiplicity_and_collision_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td), sites=[_site("obs", "nb", "b", "observation")])
            state.strategic_formations["recon-a"].recon_capability = False
            second = _force("enemy-2", Faction.RUSSIA, "c", "nc")
            state.strategic_formations["enemy-2"] = second
            state.battalions["bn-enemy-2"] = Battalion(
                "bn-enemy-2", Faction.RUSSIA, "c", roster=[BattalionRosterEntry("u", 1)],
                authorized_roster=[BattalionRosterEntry("u", 1)], formation_id="toe-rusa",
                strategic_formation_id="enemy-2",
            )
            refresh_all_observer_knowledge(state)
            rows = state.knowledge_by_observer["faction:nato"]
            self.assertEqual(2, len(rows))
            self.assertEqual(2, len({row.record_key for row in rows.values()}))
            with patch("gates_of_codex.observation.opaque_contact_id", return_value="contact-" + "0" * 64):
                with self.assertRaisesRegex(ValueError, "opaque_contact_collision"):
                    refresh_all_observer_knowledge(state)

    def test_opaque_is_observer_scoped(self) -> None:
        self.assertNotEqual(
            opaque_contact_id("faction:nato", "enemy-c"),
            opaque_contact_id("faction:ukr", "enemy-c"),
        )


if __name__ == "__main__":
    unittest.main()
