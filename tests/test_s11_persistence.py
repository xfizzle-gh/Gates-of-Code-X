from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.cli import main as cli_main
from gates_of_codex.models import (
    BattleParticipant,
    BattalionRosterEntry,
    Faction,
    FactionState,
    InformationTier,
    KnowledgeRecord,
    PendingBattle,
)
from gates_of_codex.observation import ObservationMutationContext, opaque_contact_id
from gates_of_codex.state_io import load_campaign, save_campaign
from tests.test_s11_detection import _site, _state


class S11PersistenceTests(unittest.TestCase):
    @staticmethod
    def _battle_state(root: Path):
        state = _state(root)
        state.battalions["bn-recon-a"].roster = [
            BattalionRosterEntry("u", 100)
        ]
        state.battalions["bn-enemy-c"].roster = [
            BattalionRosterEntry("u", 1)
        ]
        state.pending_battle = PendingBattle(
            battle_id="battle-removal",
            origin_province_id="a",
            target_province_id="c",
            attacker_faction=Faction.NATO,
            defender_faction=Faction.RUSSIA,
            attacking_participants=[
                BattleParticipant("bn-recon-a", Faction.NATO, "attacker", True)
            ],
            defending_participants=[
                BattleParticipant("bn-enemy-c", Faction.RUSSIA, "defender", True)
            ],
            player_faction=Faction.NATO,
            player_is_attacker=True,
        )
        return state

    def test_schema_11_save_load_save_is_byte_stable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "campaign.json"
            state = _state(root, sites=[_site("obs", "nb", "b", "observation")])
            state.strategic_formations["recon-a"].recon_capability = False

            save_campaign(state, path)
            first = path.read_bytes()
            loaded = load_campaign(path)
            save_campaign(loaded, path)

            self.assertEqual(first, path.read_bytes())
            self.assertEqual(11, loaded.schema_version)
            self.assertIn("faction:nato", loaded.knowledge_by_observer)

    def test_refresh_or_validation_failure_preserves_previous_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "campaign.json"
            state = _state(root)
            save_campaign(state, path)
            before = path.read_bytes()

            state.factions["rusa"].is_human_controlled = True
            with self.assertRaisesRegex(
                ValueError, "fog_of_war_requires_single_human_faction"
            ):
                save_campaign(state, path)
            self.assertEqual(before, path.read_bytes())

    def test_confirmed_removal_context_is_persisted_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "campaign.json"
            state = _state(root, sites=[_site("obs", "nb", "b", "observation")])
            state.strategic_formations["recon-a"].recon_capability = False
            save_campaign(state, path)
            self.assertEqual(1, len(state.knowledge_by_observer["faction:nato"]))

            state.strategic_formations.pop("enemy-c")
            state.battalions.pop("bn-enemy-c")
            context = ObservationMutationContext(
                {"faction:nato": frozenset({"enemy-c"})}
            )
            save_campaign(state, path, observation_context=context)

            loaded = load_campaign(path)
            self.assertEqual({}, loaded.knowledge_by_observer["faction:nato"])

    def test_cli_frontend_export_is_read_only_for_campaign_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "campaign.json"
            snapshot = root / "snapshot.json"
            state = _state(root, sites=[_site("obs", "nb", "b", "observation")])
            state.strategic_formations["recon-a"].recon_capability = False
            save_campaign(state, path)
            before = path.read_bytes()

            self.assertEqual(
                0,
                cli_main(
                    [
                        "export-frontend",
                        str(path),
                        "--output",
                        str(snapshot),
                    ]
                ),
            )
            self.assertTrue(snapshot.is_file())
            self.assertEqual(before, path.read_bytes())

    def test_auto_resolution_builds_participant_context_and_retains_unrelated_stale(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "campaign.json"
            state = self._battle_state(root)
            state.factions["ukr"] = FactionState(Faction.UKRAINE)
            save_campaign(state, path)
            ukr_scope = "faction:ukr"
            opaque = opaque_contact_id(ukr_scope, "enemy-c")
            state.knowledge_by_observer[ukr_scope] = {
                f"contact:{opaque}": KnowledgeRecord(
                    observer_scope_id=ukr_scope,
                    record_key=f"contact:{opaque}",
                    subject_formation_id="enemy-c",
                    tier=InformationTier.CONTACT,
                    opaque_contact_id=opaque,
                    first_seen_turn=1,
                    last_seen_turn=1,
                    last_seen_tick=0,
                    source_ids=["site:old-report"],
                    current=False,
                    last_seen_province_id="c",
                )
            }
            save_campaign(state, path)

            engine = CampaignEngine(state, random_seed=0)
            self.assertEqual(Faction.NATO, engine.auto_resolve_pending_battle())
            self.assertNotIn("enemy-c", state.strategic_formations)
            context = engine.observation_context
            self.assertIn(
                "enemy-c",
                context.confirmed_removed_formation_ids_by_observer["faction:nato"],
            )
            save_campaign(state, path, observation_context=context)

            loaded = load_campaign(path)
            self.assertNotIn(
                "formation:enemy-c",
                loaded.knowledge_by_observer["faction:nato"],
            )
            retained = next(iter(loaded.knowledge_by_observer[ukr_scope].values()))
            self.assertEqual("enemy-c", retained.subject_formation_id)
            self.assertFalse(retained.current)

    def test_direct_removal_supports_fully_observed_and_explicit_witnesses(self) -> None:
        for explicit in (False, True):
            with self.subTest(explicit=explicit), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                path = root / "campaign.json"
                state = _state(
                    root, sites=[_site("obs", "nb", "b", "observation")]
                )
                if explicit:
                    state.strategic_formations["recon-a"].recon_capability = False
                else:
                    friendly = state.strategic_formations["recon-a"]
                    friendly.position.node_id = "nc"
                    friendly.province_id = "c"
                    state.battalions["bn-recon-a"].province_id = "c"
                save_campaign(state, path)
                engine = CampaignEngine(state)
                witnesses = (Faction.NATO,) if explicit else ()
                engine.remove_strategic_formation(
                    "enemy-c", authoritative_witness_factions=witnesses
                )
                context = engine.observation_context
                self.assertIn(
                    "enemy-c",
                    context.confirmed_removed_formation_ids_by_observer["faction:nato"],
                )
                save_campaign(state, path, observation_context=context)
                loaded = load_campaign(path)
                self.assertEqual({}, loaded.knowledge_by_observer["faction:nato"])

    def test_production_removal_context_preserves_previous_file_on_save_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "campaign.json"
            state = _state(root, sites=[_site("obs", "nb", "b", "observation")])
            state.strategic_formations["recon-a"].recon_capability = False
            save_campaign(state, path)
            before = path.read_bytes()

            engine = CampaignEngine(state)
            engine.remove_strategic_formation(
                "enemy-c", authoritative_witness_factions=(Faction.NATO,)
            )
            state.factions["rusa"].is_human_controlled = True
            with self.assertRaisesRegex(
                ValueError, "fog_of_war_requires_single_human_faction"
            ):
                save_campaign(
                    state, path, observation_context=engine.observation_context
                )
            self.assertEqual(before, path.read_bytes())

    def test_empty_observer_stores_round_trip_and_frontend_read_is_byte_neutral(self) -> None:
        from gates_of_codex.frontend import build_frontend_snapshot
        from gates_of_codex.models import Alliance

        for stores in (
            {},
            {"faction:nato": {}},
            {"faction:nato": {}, "faction:rusa": {}},
        ):
            with self.subTest(stores=sorted(stores)), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                path = root / "campaign.json"
                state = _state(root)
                state.fog_of_war_enabled = False
                state.alliances = {
                    "one": Alliance("one", "One", [Faction.NATO, Faction.RUSSIA]),
                    "two": Alliance("two", "Two", [Faction.NATO, Faction.RUSSIA]),
                }
                state.knowledge_by_observer = stores
                save_campaign(state, path)
                before = path.read_bytes()
                loaded = load_campaign(path)
                self.assertEqual(stores, loaded.knowledge_by_observer)
                snapshot = build_frontend_snapshot(loaded)
                self.assertFalse(snapshot["fog_of_war"]["enabled"])
                self.assertEqual(before, path.read_bytes())


if __name__ == "__main__":
    unittest.main()
