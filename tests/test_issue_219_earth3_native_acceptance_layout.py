from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.bridge.archive import CampaignSaveArchive
from gates_of_codex.bridge.scn import CampaignScnParser
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
    Earth3OperationalAuthorityError,
    load_authenticated_p3_graph,
    validate_earth3_p3_campaign_extension,
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
from gates_of_codex.scenario import EARTH3_V1_SCENARIO_ID, build_scenario, get_scenario
from gates_of_codex.service import GatesOfCodeXService
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
    NATO_FORMATION_ID: "e3_1961",
    UKR_FORMATION_ID: "e3_1961",
    RUSA_FORMATION_ID: "e3_3380",
    PRC_FORMATION_ID: "e3_1747",
}
IDENTITIES = {
    NATO_FORMATION_ID: ("pol", Faction.NATO, "toe_sf_pol_vilnius"),
    UKR_FORMATION_ID: ("ukr", Faction.UKRAINE, "toe_sf_ukr_zaporizhzhia"),
    RUSA_FORMATION_ID: ("rus", Faction.RUSSIA, "toe_sf_rus_donetsk"),
    PRC_FORMATION_ID: ("prc", Faction.PRC, "toe_sf_fix_prc_acceptance"),
}
REQUIRED_PAIRS = (
    (NATO_FORMATION_ID, RUSA_FORMATION_ID),
    (UKR_FORMATION_ID, RUSA_FORMATION_ID),
    (PRC_FORMATION_ID, RUSA_FORMATION_ID),
    (NATO_FORMATION_ID, PRC_FORMATION_ID),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _production():
    return build_scenario(EARTH3_V1_SCENARIO_ID, resolved_catalog=_resolved_catalog())


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


def _generate_contact(state, attacker_id: str, defender_id: str):
    option = _option_to(state, attacker_id, defender_id)
    issue_move_order(
        state,
        attacker_id,
        path_node_ids=option["path_node_ids"],
        path_edge_ids=option["path_edge_ids"],
        order_id=f"issue-219-{attacker_id}-{defender_id}",
    )
    committed = commit_move_orders(state)
    if attacker_id not in committed:
        raise AssertionError(f"{attacker_id} order did not commit")
    activate_committed_orders(state)
    for _ in range(12):
        advance_operational_tick(state)
        pending = state.pending_battle
        if pending is None:
            continue
        participants = {pending.attacker_formation_id, pending.defender_formation_id}
        if participants != {attacker_id, defender_id}:
            raise AssertionError(
                f"{attacker_id} vs {defender_id} intercepted by {participants}"
            )
        return pending
    raise AssertionError(f"no contact generated for {attacker_id} vs {defender_id}")


def _write_export_codex(root: Path, state, attacker_id: str, defender_id: str) -> Path:
    codex = root / "codex"
    (codex / "resource/set/multiplayer/units/conquest/2022s").mkdir(parents=True)
    (codex / "resource/script/multiplayer/units/nato").mkdir(parents=True)
    names: set[str] = set()
    for formation_id in (attacker_id, defender_id):
        force = state.strategic_formations[formation_id]
        for battalion_id in force.battalion_ids:
            for entry in state.battalions[battalion_id].roster:
                names.add(entry.unit_name)
    units: list[str] = []
    lua: list[str] = []
    for faction in ("nato", "ukr", "rusa", "prc"):
        breed_dir = codex / f"resource/set/breed/mp/{faction}"
        breed_dir.mkdir(parents=True)
        (breed_dir / f"rifleman_{faction}.set").write_text("{breed}\n", encoding="utf-8")
        names.add(f"rifle({faction})")
    for name in sorted(names):
        side = "nato"
        for faction in ("nato", "ukr", "rusa", "prc"):
            if f"_{faction}_" in f"_{name}_" or name.endswith(f"({faction})"):
                side = faction
                break
        units.append(f'{{"{name}" {{side {side}}} {{member "rifleman_{side}" 1}}}}\n')
    for faction in ("nato", "ukr", "rusa", "prc"):
        lua.append(f'{{priority=1, type={{"Infantry","Squad"}}, unit="rifle({faction})"}},\n')
    (codex / "resource/set/multiplayer/units/conquest/2022s/units.set").write_text(
        "".join(units), encoding="utf-8"
    )
    (codex / "resource/script/multiplayer/units/nato/2022s.nato.lua").write_text(
        "".join(lua), encoding="utf-8"
    )
    (codex / "mod.info").write_text('{name "Code:X"}\n', encoding="utf-8")
    return codex


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
        from gates_of_codex.scenario import DEFAULT_SCENARIO_ID

        self.assertEqual("earth3_v1", EARTH3_V1_SCENARIO_ID)
        self.assertEqual("production", get_scenario(EARTH3_V1_SCENARIO_ID).status)
        self.assertEqual("ww3_2028_core", DEFAULT_SCENARIO_ID)
        self.assertNotEqual(DEFAULT_SCENARIO_ID, EARTH3_V1_SCENARIO_ID)
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
        self.assertEqual(
            stable_node_id("e3_1961"),
            self.fixture.strategic_formations[NATO_FORMATION_ID].position.node_id,
        )
        self.assertEqual(
            self.fixture.strategic_formations[NATO_FORMATION_ID].position.node_id,
            self.fixture.strategic_formations[UKR_FORMATION_ID].position.node_id,
        )

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

    def test_required_pairs_are_offered_on_the_authenticated_graph(self) -> None:
        for attacker_id, defender_id in REQUIRED_PAIRS:
            option = _option_to(self.fixture, attacker_id, defender_id)
            self.assertGreaterEqual(option["hop_count"], 1)
            self.assertEqual("approved", option["edge_authority"])

    def test_ownership_and_retreat_graph_remain_valid(self) -> None:
        self.assertEqual(
            {pid: row.owner for pid, row in self.production.provinces.items()},
            {pid: row.owner for pid, row in self.fixture.provinces.items()},
        )
        for province_id in ("e3_1747", "e3_1961", "e3_2795", "e3_2796"):
            self.assertEqual(Faction.NEUTRAL, self.fixture.provinces[province_id].owner)
        require_operational_retreat_graph(self.fixture)

    def test_independent_fixture_saves_are_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "a.json"
            second = Path(temporary) / "b.json"
            save_campaign(_fixture(), first)
            save_campaign(_fixture(), second)
            self.assertEqual(first.read_bytes(), second.read_bytes())

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
        prc = state.strategic_formations[PRC_FORMATION_ID]
        prc.province_id = "e3_2796"
        prc.position.node_id = stable_node_id("e3_2796")
        validate_earth3_native_acceptance_fixture(state)

    def test_production_validator_still_rejects_fixture_state(self) -> None:
        with self.assertRaisesRegex(
            Earth3OperationalAuthorityError,
            "outside the authorized P2 initialization set",
        ):
            validate_earth3_p3_campaign_extension(self._fixture_copy())

    def test_layout_parser_rejects_extra_or_prc_mismatch(self) -> None:
        payload = load_fixture_manifest()
        payload["compact_contact_layout"]["sf_deu_berlin"] = "e3_0592"
        with self.assertRaisesRegex(Earth3FixtureAuthorityError, "layout is not exact"):
            _require_exact_manifest(payload)
        payload = load_fixture_manifest()
        payload["compact_contact_layout"][PRC_FORMATION_ID] = "e3_0442"
        with self.assertRaisesRegex(Earth3FixtureAuthorityError, "PRC layout province"):
            _require_exact_manifest(payload)


class RequiredContactTests(_CachedStates):
    def test_fresh_fixture_generates_all_four_required_pair_contacts(self) -> None:
        for attacker_id, defender_id in REQUIRED_PAIRS:
            state = self._fixture_copy()
            pending = _generate_contact(state, attacker_id, defender_id)
            self.assertEqual({attacker_id, defender_id}, {
                pending.attacker_formation_id,
                pending.defender_formation_id,
            })
            for formation_id in (attacker_id, defender_id):
                actor_id, faction, template_id = IDENTITIES[formation_id]
                force = state.strategic_formations[formation_id]
                self.assertEqual(actor_id, force.actor_id)
                self.assertEqual(faction, force.faction)
                self.assertEqual(template_id, force.template_formation_id)
            validate_earth3_operational_authority(state)
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "campaign.json"
                save_campaign(state, path)
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
            validate_earth3_operational_authority(loaded)
            for formation_id in (attacker_id, defender_id):
                actor_id, faction, template_id = IDENTITIES[formation_id]
                force = loaded.strategic_formations[formation_id]
                self.assertEqual(actor_id, force.actor_id)
                self.assertEqual(faction, force.faction)
                self.assertEqual(template_id, force.template_formation_id)


class HandoffIdentityTests(_CachedStates):
    def test_export_battle_preserves_selected_actor_identities(self) -> None:
        attacker_id, defender_id = NATO_FORMATION_ID, RUSA_FORMATION_ID
        state = self._fixture_copy()
        pending = _generate_contact(state, attacker_id, defender_id)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign_path = root / "campaign.json"
            save_path = root / "battle.sav"
            save_campaign(state, campaign_path)
            codex = _write_export_codex(root, state, attacker_id, defender_id)
            manifest = GatesOfCodeXService().export_battle(
                campaign_path,
                code_x_directory=codex,
                save_path=save_path,
                map_name="multi/2x2/live_test",
                allow_overwrite=True,
            )
            loaded = campaign_from_dict(json.loads(campaign_path.read_text(encoding="utf-8")))
            archive = CampaignSaveArchive().read(save_path)
        self.assertEqual(pending.battle_id, manifest.battle_id)
        loaded_pending = loaded.pending_battle
        self.assertIsNotNone(loaded_pending)
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
        self.assertIn("{army nato}", archive.status)
        self.assertIn("{enemyArmy rusa}", archive.status)
        squads = CampaignScnParser().parse_squads(archive.campaign_scn)
        self.assertTrue(squads)
        survivor = CampaignScnParser().survivor_rosters(archive.campaign_scn, loaded_pending)
        expected_battalions = set()
        for formation_id in (attacker_id, defender_id):
            expected_battalions.update(loaded.strategic_formations[formation_id].battalion_ids)
        self.assertTrue(expected_battalions.intersection(survivor))


if __name__ == "__main__":
    unittest.main()
