from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gates_of_codex.cli import main as cli_main
from gates_of_codex.frontend import build_frontend_snapshot
from gates_of_codex.models import (
    BattleParticipant,
    BattalionRosterEntry,
    Faction,
    FactionState,
    InformationTier,
    KnowledgeRecord,
    PendingBattle,
)
from gates_of_codex.observation import opaque_contact_id
from gates_of_codex.state_io import load_campaign, save_campaign
from tests.test_s11_detection import _state


class S11BlockingReviewRegressionTests(unittest.TestCase):
    def test_enemy_neutral_option_never_enters_human_fog_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            state.current_faction = Faction.RUSSIA
            state.provinces["b"].owner = Faction.NEUTRAL

            # Fully observe the enemy without granting command authority over it.
            friendly = state.strategic_formations["recon-a"]
            friendly.position.node_id = "nc"
            friendly.province_id = "c"
            state.battalions["bn-recon-a"].province_id = "c"

            snapshot = build_frontend_snapshot(state)

            self.assertEqual([], snapshot["front_options"])
            enemy = snapshot["battalion_presentations"]["bn-enemy-c"]
            self.assertFalse(enemy["can_act"])
            self.assertEqual(0, enemy["legal_option_count"])
            self.assertEqual([], enemy["legal_options"])
            serialized = json.dumps(snapshot, sort_keys=True)
            self.assertNotIn("move bn-enemy-c b", serialized)
            self.assertNotIn('"target_owner": "neutral"', serialized)

            state.fog_of_war_enabled = False
            fog_off = build_frontend_snapshot(state)
            option = next(
                row
                for row in fog_off["front_options"]
                if row["battalion_id"] == "bn-enemy-c"
                and row["target"] == "b"
            )
            self.assertEqual("neutral", option["kind"])
            self.assertEqual([], option["enemies"])

    def test_cli_auto_resolve_persists_witness_context_without_manual_save(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "campaign.json"
            state = _state(root)
            state.factions["ukr"] = FactionState(Faction.UKRAINE)
            state.battalions["bn-recon-a"].roster = [
                BattalionRosterEntry("u", 100)
            ]
            state.battalions["bn-enemy-c"].roster = [
                BattalionRosterEntry("u", 1)
            ]
            state.pending_battle = PendingBattle(
                battle_id="battle-cli-witness",
                origin_province_id="a",
                target_province_id="c",
                attacker_faction=Faction.NATO,
                defender_faction=Faction.RUSSIA,
                attacking_participants=[
                    BattleParticipant(
                        "bn-recon-a", Faction.NATO, "attacker", is_primary=True
                    )
                ],
                defending_participants=[
                    BattleParticipant(
                        "bn-enemy-c", Faction.RUSSIA, "defender", is_primary=True
                    )
                ],
                player_faction=Faction.NATO,
                player_is_attacker=True,
            )
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

            def attacker_wins(engine) -> Faction:
                engine.apply_battle_result(Faction.NATO)
                return Faction.NATO

            with patch(
                "gates_of_codex.cli.CampaignEngine.auto_resolve_pending_battle",
                attacker_wins,
            ):
                self.assertEqual(0, cli_main(["auto-resolve", str(path)]))

            loaded = load_campaign(path)
            self.assertNotIn("enemy-c", loaded.strategic_formations)
            self.assertNotIn(
                "formation:enemy-c",
                loaded.knowledge_by_observer["faction:nato"],
            )
            retained = next(
                iter(loaded.knowledge_by_observer[ukr_scope].values())
            )
            self.assertEqual("enemy-c", retained.subject_formation_id)
            self.assertFalse(retained.current)


if __name__ == "__main__":
    unittest.main()
