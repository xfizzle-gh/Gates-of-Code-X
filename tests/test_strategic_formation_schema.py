from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.force_migration import (
    STRATEGIC_FORMATION_SCHEMA_VERSION,
    ensure_strategic_formations,
    strategic_formation_id_for_battalion,
)
from gates_of_codex.frontend import FRONTEND_SCHEMA_VERSION, build_frontend_snapshot
from gates_of_codex.models import (
    Battalion,
    BattalionRosterEntry,
    CampaignState,
    Commander,
    CommanderStatus,
    Faction,
    FactionState,
    ForceEchelon,
    Formation,
    FormationKind,
    PendingBattle,
    BattleParticipant,
    Province,
    StrategicFormation,
)
from gates_of_codex.state_io import campaign_from_dict, load_campaign, save_campaign


def _minimal_state(*, multi_province: bool = False) -> CampaignState:
    provinces = {
        "a": Province("a", "Alpha", owner=Faction.NATO, neighbors=["b"], x=0, y=0),
        "b": Province("b", "Bravo", owner=Faction.NATO, neighbors=["a"], x=1, y=0),
    }
    formations = {
        "toe-nato": Formation(
            formation_id="toe-nato",
            display_name="NATO Template",
            faction=Faction.NATO,
            nation="usa",
            kind=FormationKind.ARMORED_BRIGADE,
        )
    }
    battalions = {
        "bn-1": Battalion(
            battalion_id="bn-1",
            faction=Faction.NATO,
            province_id="a",
            formation_id="toe-nato",
            roster=[BattalionRosterEntry("tank(nato)", 2, category="tank")],
            authorized_roster=[BattalionRosterEntry("tank(nato)", 2, category="tank")],
            is_player_controlled=True,
        )
    }
    if multi_province:
        battalions["bn-2"] = Battalion(
            battalion_id="bn-2",
            faction=Faction.NATO,
            province_id="a",
            formation_id="toe-nato",
            roster=[BattalionRosterEntry("infantry(nato)", 4, category="infantry")],
            authorized_roster=[BattalionRosterEntry("infantry(nato)", 4, category="infantry")],
        )
        battalions["bn-3"] = Battalion(
            battalion_id="bn-3",
            faction=Faction.NATO,
            province_id="b",
            formation_id="toe-nato",
            roster=[BattalionRosterEntry("ifv(nato)", 1, category="ifv")],
            authorized_roster=[BattalionRosterEntry("ifv(nato)", 1, category="ifv")],
        )
    return CampaignState(
        campaign_name="Force schema test",
        factions={Faction.NATO.value: FactionState(Faction.NATO, resources=500, is_human_controlled=True)},
        formations=formations,
        provinces=provinces,
        battalions=battalions,
        schema_version=5,
    )


class StrategicFormationSchemaTests(unittest.TestCase):
    def test_single_battalion_migrates_to_independent_formation(self) -> None:
        state = _minimal_state()
        report = ensure_strategic_formations(state)
        self.assertEqual(1, report["created"])
        self.assertEqual(0, report["commanders_invented"])
        force_id = strategic_formation_id_for_battalion("bn-1")
        self.assertIn(force_id, state.strategic_formations)
        force = state.strategic_formations[force_id]
        self.assertEqual(ForceEchelon.BATTALION, force.echelon)
        self.assertEqual(["bn-1"], force.battalion_ids)
        self.assertIsNone(force.commander_id)
        self.assertEqual(force_id, state.battalions["bn-1"].strategic_formation_id)
        self.assertIsNone(state.battalions["bn-1"].commander_id)
        self.assertEqual({}, state.commanders)
        self.assertGreaterEqual(state.schema_version, STRATEGIC_FORMATION_SCHEMA_VERSION)
        state.validate()

    def test_multiple_battalions_same_province_get_distinct_formations(self) -> None:
        state = _minimal_state(multi_province=True)
        ensure_strategic_formations(state)
        self.assertEqual(3, len(state.strategic_formations))
        ids = {force.strategic_formation_id for force in state.strategic_formations.values()}
        self.assertEqual(
            {
                strategic_formation_id_for_battalion("bn-1"),
                strategic_formation_id_for_battalion("bn-2"),
                strategic_formation_id_for_battalion("bn-3"),
            },
            ids,
        )
        self.assertEqual("a", state.strategic_formations[strategic_formation_id_for_battalion("bn-2")].province_id)
        state.validate()

    def test_migration_is_idempotent_and_deterministic(self) -> None:
        state = _minimal_state(multi_province=True)
        first = ensure_strategic_formations(state)
        snapshot = copy.deepcopy(state.to_dict())
        second = ensure_strategic_formations(state)
        self.assertEqual(0, second["created"])
        self.assertEqual(snapshot["strategic_formations"], state.to_dict()["strategic_formations"])
        self.assertEqual(first["created"], 3)

    def test_serialization_round_trip_preserves_empty_commanders(self) -> None:
        state = _minimal_state()
        ensure_strategic_formations(state)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "campaign.json"
            save_campaign(state, path)
            loaded = load_campaign(path)
        self.assertEqual({}, loaded.commanders)
        self.assertEqual(len(state.strategic_formations), len(loaded.strategic_formations))
        self.assertIsNone(next(iter(loaded.strategic_formations.values())).commander_id)
        self.assertIsNone(next(iter(loaded.battalions.values())).commander_id)

    def test_nullable_commander_ids_survive_round_trip(self) -> None:
        state = _minimal_state()
        ensure_strategic_formations(state)
        payload = state.to_dict()
        restored = campaign_from_dict(payload)
        force = next(iter(restored.strategic_formations.values()))
        self.assertIsNone(force.commander_id)
        self.assertIsNone(restored.battalions["bn-1"].commander_id)

    def test_commander_cannot_own_both_assignment_fields(self) -> None:
        state = _minimal_state()
        ensure_strategic_formations(state)
        force_id = strategic_formation_id_for_battalion("bn-1")
        state.commanders["cmd-1"] = Commander(
            commander_id="cmd-1",
            display_name="Test",
            assigned_strategic_formation_id=force_id,
            assigned_battalion_id="bn-1",
            status=CommanderStatus.ACTIVE,
        )
        with self.assertRaises(ValueError):
            state.validate()

    def test_battalion_cannot_belong_to_two_formations(self) -> None:
        state = _minimal_state()
        ensure_strategic_formations(state)
        state.strategic_formations["sf-extra"] = StrategicFormation(
            strategic_formation_id="sf-extra",
            display_name="Extra",
            faction=Faction.NATO,
            province_id="a",
            battalion_ids=["bn-1"],
        )
        with self.assertRaises(ValueError):
            state.validate()

    def test_actor_mismatch_rejected(self) -> None:
        state = _minimal_state()
        ensure_strategic_formations(state)
        force = state.strategic_formations[strategic_formation_id_for_battalion("bn-1")]
        force.faction = Faction.RUSSIA
        with self.assertRaises(ValueError):
            state.validate()

    def test_province_mismatch_rejected_after_migration(self) -> None:
        state = _minimal_state()
        ensure_strategic_formations(state)
        state.battalions["bn-1"].province_id = "b"
        with self.assertRaises(ValueError):
            state.validate()

    def test_migration_normalizes_province_drift(self) -> None:
        state = _minimal_state()
        ensure_strategic_formations(state)
        force = state.strategic_formations[strategic_formation_id_for_battalion("bn-1")]
        force.province_id = "b"
        state.battalions["bn-1"].province_id = "a"
        ensure_strategic_formations(state)
        self.assertEqual("b", state.battalions["bn-1"].province_id)
        state.validate()

    def test_pending_battle_preserved_byte_for_byte_fields(self) -> None:
        state = _minimal_state()
        state.pending_battle = PendingBattle(
            battle_id="battle-1",
            origin_province_id="a",
            target_province_id="b",
            attacker_faction=Faction.NATO,
            defender_faction=Faction.RUSSIA,
            attacking_participants=[
                BattleParticipant(battalion_id="bn-1", faction=Faction.NATO, stage="1", is_primary=True)
            ],
            defending_participants=[],
            player_faction=Faction.NATO,
            player_is_attacker=True,
            exported_save_path="x.sav",
            started=True,
            completed=False,
        )
        before = copy.deepcopy(state.to_dict()["pending_battle"])
        ensure_strategic_formations(state)
        self.assertEqual(before, state.to_dict()["pending_battle"])

    def test_old_dict_without_strategic_formations_loads(self) -> None:
        state = _minimal_state(multi_province=True)
        payload = state.to_dict()
        payload.pop("strategic_formations", None)
        payload.pop("commanders", None)
        for battalion in payload["battalions"].values():
            battalion.pop("strategic_formation_id", None)
            battalion.pop("commander_id", None)
        payload["schema_version"] = 5
        loaded = campaign_from_dict(payload)
        self.assertEqual(3, len(loaded.strategic_formations))
        self.assertEqual({}, loaded.commanders)
        loaded.validate()

    def test_frontend_snapshot_includes_strategic_formations(self) -> None:
        state = _minimal_state()
        ensure_strategic_formations(state)
        snapshot = build_frontend_snapshot(state)
        self.assertEqual(FRONTEND_SCHEMA_VERSION, snapshot["schema_version"])
        self.assertEqual(1, len(snapshot["strategic_formations"]))
        self.assertEqual([], snapshot["commanders"])
        row = snapshot["strategic_formations"][0]
        self.assertEqual("Unassigned Commander", row["commander_display_name"])
        self.assertIsNone(row["commander_id"])
        self.assertEqual("bn-1", snapshot["battalions"][0]["id"])
        self.assertEqual(row["id"], snapshot["battalions"][0]["strategic_formation_id"])

    def test_europe_campaign_remains_playable(self) -> None:
        from gates_of_codex.europe import build_goe_europe_campaign

        state = build_goe_europe_campaign()
        ensure_strategic_formations(state)
        self.assertEqual(len(state.battalions), len(state.strategic_formations))
        self.assertEqual({}, state.commanders)
        state.validate()
        snapshot = build_frontend_snapshot(state)
        self.assertEqual(len(state.battalions), len(snapshot["strategic_formations"]))


if __name__ == "__main__":
    unittest.main()
