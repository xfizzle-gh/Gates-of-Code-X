from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.earth3_fixture_authority import (
    FIXTURE_AUTHORITY_KEY,
    FIXTURE_SCENARIO_ID,
    Earth3FixtureAuthorityError,
    _require_exact_manifest,
    load_fixture_manifest,
    validate_earth3_native_acceptance_fixture,
    validate_earth3_operational_authority,
)
from gates_of_codex.earth3_operational import (
    P3_STARTING_FORMATION_IDS,
    load_authenticated_p3_graph,
)
from gates_of_codex.frontend import build_frontend_snapshot
from gates_of_codex.models import Faction
from gates_of_codex.operational_movement import (
    activate_committed_orders,
    advance_operational_tick,
    commit_move_orders,
    issue_move_order,
)
from gates_of_codex.operational_order_options import list_operational_move_options
from gates_of_codex.operational_retreat import require_operational_retreat_graph
from gates_of_codex.operational_schema import stable_node_id
from gates_of_codex.scenario import DEFAULT_SCENARIO_ID, build_scenario, get_scenario
from gates_of_codex.state_io import campaign_from_dict, save_campaign

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_p2_earth3_campaign_bootstrap import _resolved_catalog


ROOT = Path(__file__).resolve().parents[1]
FROZEN_PATHS = (
    ROOT / "config/earth3/production_authority.json",
    ROOT / "config/earth3/p3_operational_authority.json",
    ROOT / "godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json",
    ROOT / "godot/assets/maps/earth3_europe_mediterranean/p3_authority/p3_operational_graph.json",
    ROOT / "src/gates_of_codex/data/earth3_v1/formations.json",
)
PRC_FORMATION_ID = "sf_fix_prc_acceptance"
NATO_FORMATION_ID = "sf_pol_vilnius"
UKR_FORMATION_ID = "sf_ukr_zaporizhzhia"
RUSA_FORMATION_ID = "sf_rus_donetsk"
LAYOUT = {
    NATO_FORMATION_ID: "e3_2796",
    UKR_FORMATION_ID: "e3_1962",
    RUSA_FORMATION_ID: "e3_3380",
    PRC_FORMATION_ID: "e3_2795",
}
IDENTITIES = {
    NATO_FORMATION_ID: ("pol", Faction.NATO, "toe_sf_pol_vilnius"),
    UKR_FORMATION_ID: ("ukr", Faction.UKRAINE, "toe_sf_ukr_zaporizhzhia"),
    RUSA_FORMATION_ID: ("rus", Faction.RUSSIA, "toe_sf_rus_donetsk"),
    PRC_FORMATION_ID: ("prc", Faction.PRC, "toe_sf_fix_prc_acceptance"),
}
ONE_HOP_PAIRS = (
    (NATO_FORMATION_ID, RUSA_FORMATION_ID),
    (NATO_FORMATION_ID, PRC_FORMATION_ID),
    (UKR_FORMATION_ID, PRC_FORMATION_ID),
)
QUICK_PAIRS = (
    (NATO_FORMATION_ID, RUSA_FORMATION_ID, 1),
    (NATO_FORMATION_ID, PRC_FORMATION_ID, 1),
    (UKR_FORMATION_ID, RUSA_FORMATION_ID, 3),
    (PRC_FORMATION_ID, RUSA_FORMATION_ID, 2),
    (UKR_FORMATION_ID, PRC_FORMATION_ID, 1),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _production():
    return build_scenario(DEFAULT_SCENARIO_ID, resolved_catalog=_resolved_catalog())


def _fixture():
    return build_scenario(FIXTURE_SCENARIO_ID, resolved_catalog=_resolved_catalog())


def _option_to(state, formation_id: str, target_formation_id: str) -> dict:
    force = state.strategic_formations[formation_id]
    target = state.strategic_formations[target_formation_id]
    matches = [
        row
        for row in list_operational_move_options(state, force.faction)
        if row["formation_id"] == formation_id
        and row["target_node_id"] == target.position.node_id
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"{formation_id} -> {target_formation_id} options: {len(matches)}"
        )
    return matches[0]


class _CachedStates(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.production = _production()
        cls.fixture = _fixture()

    def _production_copy(self):
        return copy.deepcopy(self.production)

    def _fixture_copy(self):
        return copy.deepcopy(self.fixture)


class FrozenAuthorityTests(_CachedStates):
    def test_frozen_earth3_bytes_and_production_start_remain_unchanged(self) -> None:
        self.assertEqual(
            "e8ae502e05ea30233d52257a3cfba7509250601015c2ea00f1acdbe32c63b31c",
            _sha256(ROOT / "src/gates_of_codex/data/earth3_v1/formations.json"),
        )
        for path in FROZEN_PATHS:
            self.assertTrue(path.is_file(), path)
        self.assertEqual(P3_STARTING_FORMATION_IDS, set(self.production.strategic_formations))
        self.assertNotIn(PRC_FORMATION_ID, P3_STARTING_FORMATION_IDS)
        self.assertEqual("earth3_v1", DEFAULT_SCENARIO_ID)
        self.assertEqual("production", get_scenario(DEFAULT_SCENARIO_ID).status)
        self.assertEqual("debug", get_scenario(FIXTURE_SCENARIO_ID).status)
        self.assertEqual(self.production.to_dict(), _production().to_dict())
        self.assertNotIn(FIXTURE_AUTHORITY_KEY, self.production.map_metadata)
        graph = load_authenticated_p3_graph()
        self.assertEqual(64, len(graph["nodes"]))
        self.assertEqual(65, len(graph["edges"]))


class CompactLayoutTests(_CachedStates):
    def test_authored_layout_places_the_four_selected_actors(self) -> None:
        manifest = load_fixture_manifest()
        self.assertEqual(2, manifest["schema_version"])
        self.assertEqual(LAYOUT, manifest["compact_contact_layout"])
        self.assertIsNone(self.fixture.pending_battle)
        for formation_id, province_id in LAYOUT.items():
            force = self.fixture.strategic_formations[formation_id]
            actor_id, faction, template_id = IDENTITIES[formation_id]
            self.assertEqual(province_id, force.province_id)
            self.assertEqual(stable_node_id(province_id), force.position.node_id)
            self.assertEqual(actor_id, force.actor_id)
            self.assertEqual(faction, force.faction)
            self.assertEqual(template_id, force.template_formation_id)
            for battalion_id in force.battalion_ids:
                self.assertEqual(province_id, self.fixture.battalions[battalion_id].province_id)

    def test_unselected_production_formations_stay_put(self) -> None:
        selected = set(LAYOUT)
        for formation_id, force in self.production.strategic_formations.items():
            if formation_id in selected:
                continue
            relocated = self.fixture.strategic_formations[formation_id]
            self.assertEqual(force.province_id, relocated.province_id)
            self.assertEqual(force.position.node_id, relocated.position.node_id)
            self.assertEqual(force.actor_id, relocated.actor_id)
            self.assertEqual(force.faction, relocated.faction)
            self.assertEqual(force.template_formation_id, relocated.template_formation_id)

    def test_required_pairs_are_reachable_on_the_authenticated_corridor(self) -> None:
        for formation_id, target_id, hops in QUICK_PAIRS:
            option = _option_to(self.fixture, formation_id, target_id)
            self.assertEqual(hops, option["hop_count"], (formation_id, target_id))
            self.assertEqual("approved", option["edge_authority"])
        for formation_id, target_id in ONE_HOP_PAIRS:
            self.assertEqual(1, _option_to(self.fixture, formation_id, target_id)["hop_count"])

    def test_each_selected_actor_has_a_one_hop_opponent(self) -> None:
        opponents = {
            NATO_FORMATION_ID: (RUSA_FORMATION_ID, PRC_FORMATION_ID),
            UKR_FORMATION_ID: (PRC_FORMATION_ID,),
            RUSA_FORMATION_ID: (NATO_FORMATION_ID,),
            PRC_FORMATION_ID: (NATO_FORMATION_ID, UKR_FORMATION_ID),
        }
        for formation_id, targets in opponents.items():
            hops = [
                _option_to(self.fixture, formation_id, target_id)["hop_count"]
                for target_id in targets
            ]
            self.assertIn(1, hops, formation_id)

    def test_ownership_and_retreat_graph_remain_valid(self) -> None:
        self.assertEqual(
            {pid: row.owner for pid, row in self.production.provinces.items()},
            {pid: row.owner for pid, row in self.fixture.provinces.items()},
        )
        self.assertEqual(Faction.NEUTRAL, self.fixture.provinces["e3_2795"].owner)
        self.assertEqual(Faction.NEUTRAL, self.fixture.provinces["e3_2796"].owner)
        require_operational_retreat_graph(self.fixture)

    def test_deterministic_and_round_trip_stable(self) -> None:
        self.assertEqual(self.fixture.to_dict(), _fixture().to_dict())
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "campaign.json"
            save_campaign(self._fixture_copy(), path)
            loaded = campaign_from_dict(json.loads(path.read_text(encoding="utf-8")))
        self.assertEqual(FIXTURE_SCENARIO_ID, loaded.map_metadata["scenario_id"])
        for formation_id, province_id in LAYOUT.items():
            self.assertEqual(province_id, loaded.strategic_formations[formation_id].province_id)
        validate_earth3_operational_authority(loaded)

    def test_frontend_snapshot_identifies_debug_fixture(self) -> None:
        snapshot = build_frontend_snapshot(self._fixture_copy())
        encoded = json.dumps(snapshot)
        self.assertIn(FIXTURE_SCENARIO_ID, encoded)
        self.assertNotIn('"scenario_id": "earth3_v1"', encoded)


class AdversarialLayoutTests(_CachedStates):
    def test_runtime_validation_allows_selected_formation_to_leave_start_node(self) -> None:
        state = self._fixture_copy()
        force = state.strategic_formations[NATO_FORMATION_ID]
        force.province_id = "e3_0442"
        force.position.node_id = stable_node_id("e3_0442")
        validate_earth3_native_acceptance_fixture(state)

    def test_production_validator_still_rejects_fixture_state(self) -> None:
        from gates_of_codex.earth3_operational import (
            Earth3OperationalAuthorityError,
            validate_earth3_p3_campaign_extension,
        )

        with self.assertRaisesRegex(
            Earth3OperationalAuthorityError,
            "outside the authorized P2 initialization set",
        ):
            validate_earth3_p3_campaign_extension(self._fixture_copy())

    def test_layout_parser_rejects_extra_or_duplicate_entries(self) -> None:
        payload = load_fixture_manifest()
        payload["compact_contact_layout"]["sf_deu_berlin"] = "e3_0592"
        with self.assertRaisesRegex(Earth3FixtureAuthorityError, "layout is not exact"):
            _require_exact_manifest(payload)
        payload = load_fixture_manifest()
        payload["compact_contact_layout"][NATO_FORMATION_ID] = payload["compact_contact_layout"][
            UKR_FORMATION_ID
        ]
        with self.assertRaisesRegex(Earth3FixtureAuthorityError, "duplicate provinces"):
            _require_exact_manifest(payload)

    def test_layout_parser_rejects_prc_province_mismatch(self) -> None:
        payload = load_fixture_manifest()
        payload["compact_contact_layout"][PRC_FORMATION_ID] = "e3_0442"
        with self.assertRaisesRegex(Earth3FixtureAuthorityError, "PRC layout province"):
            _require_exact_manifest(payload)


class HandoffIdentityTests(_CachedStates):
    def test_one_hop_contacts_preserve_selected_actor_identities(self) -> None:
        last_state = None
        last_pair = None
        for attacker_id, defender_id in ONE_HOP_PAIRS:
            state = self._fixture_copy()
            pending = self._generate_contact(state, attacker_id, defender_id)
            participants = {
                pending.attacker_formation_id,
                pending.defender_formation_id,
            }
            self.assertEqual({attacker_id, defender_id}, participants)
            for formation_id in participants:
                actor_id, faction, template_id = IDENTITIES[formation_id]
                force = state.strategic_formations[formation_id]
                self.assertEqual(actor_id, force.actor_id)
                self.assertEqual(faction, force.faction)
                self.assertEqual(template_id, force.template_formation_id)
            validate_earth3_operational_authority(state)
            last_state = state
            last_pair = (attacker_id, defender_id)
        self.assertIsNotNone(last_state)
        self.assertIsNotNone(last_pair)
        attacker_id, defender_id = last_pair
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "campaign.json"
            save_campaign(last_state, path)
            loaded = campaign_from_dict(json.loads(path.read_text(encoding="utf-8")))
        self.assertIsNotNone(loaded.pending_battle)
        loaded_pending = loaded.pending_battle
        self.assertEqual(
            {attacker_id, defender_id},
            {
                loaded_pending.attacker_formation_id,
                loaded_pending.defender_formation_id,
            },
        )
        for formation_id in (attacker_id, defender_id):
            actor_id, faction, template_id = IDENTITIES[formation_id]
            force = loaded.strategic_formations[formation_id]
            self.assertEqual(actor_id, force.actor_id)
            self.assertEqual(faction, force.faction)
            self.assertEqual(template_id, force.template_formation_id)

    def _generate_contact(self, state, attacker_id: str, defender_id: str):
        option = _option_to(state, attacker_id, defender_id)
        self.assertEqual(1, option["hop_count"])
        issue_move_order(
            state,
            attacker_id,
            path_node_ids=option["path_node_ids"],
            path_edge_ids=option["path_edge_ids"],
            order_id=f"issue-219-{attacker_id}-{defender_id}",
        )
        commit_move_orders(state)
        activate_committed_orders(state)
        for _ in range(4):
            advance_operational_tick(state)
            if state.pending_battle is not None:
                return state.pending_battle
        raise AssertionError(f"no contact generated for {attacker_id} vs {defender_id}")


if __name__ == "__main__":
    unittest.main()
