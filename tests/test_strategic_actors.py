from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.models import Faction
from gates_of_codex.scenario import load_bundled_scenario
from gates_of_codex.state_io import load_campaign, save_campaign
from gates_of_codex.strategic_actors import (
    ACTOR_RUNTIME_KEY,
    CAMPAIGN_SCHEMA_VERSION,
    assign_province_actor,
    ensure_strategic_actor_runtime,
    install_bundled_strategic_actors,
    selected_actor,
    set_selected_actor,
    strategic_actor_snapshot,
    validate_strategic_actor_runtime,
)


class StrategicActorMigrationTest(unittest.TestCase):
    def test_legacy_campaign_receives_compatibility_actors(self) -> None:
        state = load_bundled_scenario()
        actors = ensure_strategic_actor_runtime(state)
        self.assertEqual(set(actors), set(state.factions) - {Faction.NEUTRAL.value})
        self.assertEqual(selected_actor(state).actor_id, state.selected_faction.value)
        self.assertGreaterEqual(state.schema_version, CAMPAIGN_SCHEMA_VERSION)
        validate_strategic_actor_runtime(state)
        for force in state.strategic_formations.values():
            self.assertIn(force.actor_id, actors)
            self.assertEqual(actors[force.actor_id].tactical_side, force.faction)

    def test_save_load_round_trip_preserves_actor_runtime(self) -> None:
        state = load_bundled_scenario()
        install_bundled_strategic_actors(state, selected_actor_id="fra")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.json"
            save_campaign(state, path)
            loaded = load_campaign(path)
        self.assertEqual(strategic_actor_snapshot(loaded), strategic_actor_snapshot(state))
        self.assertEqual(loaded.selected_faction, Faction.NATO)
        self.assertEqual(selected_actor(loaded).actor_id, "fra")


class BundledStrategicActorTest(unittest.TestCase):
    def test_installs_all_audited_actors_and_selects_france(self) -> None:
        state = load_bundled_scenario()
        actors = install_bundled_strategic_actors(state, selected_actor_id="fra")
        self.assertEqual(len(actors), 24)
        self.assertEqual(state.selected_faction, Faction.NATO)
        self.assertEqual(state.current_faction, Faction.NATO)
        self.assertTrue(actors["fra"].is_human_controlled)
        self.assertFalse(actors["usa"].is_human_controlled)
        self.assertEqual(actors["ukr_ildu"].host_actor_id, "ukr")
        self.assertEqual(actors["kpa_expeditionary"].host_actor_id, "rus")
        self.assertEqual(actors["wagner"].host_actor_id, "rus")
        validate_strategic_actor_runtime(state)

    def test_north_korea_selects_russian_tactical_side(self) -> None:
        state = load_bundled_scenario()
        install_bundled_strategic_actors(state, selected_actor_id="dprk")
        self.assertEqual(state.selected_faction, Faction.RUSSIA)
        self.assertEqual(selected_actor(state).actor_id, "dprk")

    def test_non_playable_auxiliary_cannot_be_selected(self) -> None:
        state = load_bundled_scenario()
        install_bundled_strategic_actors(state, selected_actor_id="ukr")
        with self.assertRaises(ValueError):
            set_selected_actor(state, "ukr_ildu")

    def test_province_actor_must_match_tactical_owner(self) -> None:
        state = load_bundled_scenario()
        actors = install_bundled_strategic_actors(state, selected_actor_id="fra")
        province = next(value for value in state.provinces.values() if value.owner == Faction.NATO)
        assign_province_actor(state, province.province_id, "fra")
        self.assertEqual(province.metadata["owner_actor_id"], "fra")
        with self.assertRaises(ValueError):
            assign_province_actor(state, province.province_id, "dprk")
        self.assertIn(ACTOR_RUNTIME_KEY, state.map_metadata)
        self.assertEqual(actors["fra"].tactical_side, province.owner)


if __name__ == "__main__":
    unittest.main()
