from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gates_of_codex import strategic_ai, turn_cycle
from gates_of_codex.models import Faction
from gates_of_codex.observation import ObservationMutationContext


class StrategicAIEngineReuseTests(unittest.TestCase):
    def test_provided_engine_avoids_reconstructing_campaign_engine(self) -> None:
        state = object()
        supplied = SimpleNamespace(state=state)
        with patch.object(
            strategic_ai,
            "CampaignEngine",
            side_effect=AssertionError("CampaignEngine must not be reconstructed"),
        ):
            ai = strategic_ai.StrategicAI(state, engine=supplied)  # type: ignore[arg-type]
        self.assertIs(supplied, ai.engine)

    def test_provided_engine_must_reference_same_state(self) -> None:
        with self.assertRaisesRegex(ValueError, "same campaign state"):
            strategic_ai.StrategicAI(
                object(),  # type: ignore[arg-type]
                engine=SimpleNamespace(state=object()),  # type: ignore[arg-type]
            )


class PlayerRoundEngineReuseTests(unittest.TestCase):
    def test_operational_round_reuses_one_validated_engine_for_all_ai_seats(self) -> None:
        state = SimpleNamespace(
            pending_battle=None,
            selected_faction=Faction.NATO,
            current_faction=Faction.NATO,
            turn_number=12,
            factions={
                faction.value: SimpleNamespace(is_eliminated=False)
                for faction in (
                    Faction.NATO,
                    Faction.UKRAINE,
                    Faction.RUSSIA,
                    Faction.PRC,
                )
            },
        )

        class FakeEngine:
            TURN_ORDER = (
                Faction.NATO,
                Faction.UKRAINE,
                Faction.RUSSIA,
                Faction.PRC,
            )
            instances: list["FakeEngine"] = []

            def __init__(self, engine_state) -> None:
                self.state = engine_state
                self.instances.append(self)

            @property
            def observation_context(self) -> ObservationMutationContext:
                return ObservationMutationContext()

            def end_turn(self) -> Faction:
                active = list(self.TURN_ORDER)
                index = active.index(self.state.current_faction)
                next_faction = active[(index + 1) % len(active)]
                if index == len(active) - 1:
                    self.state.turn_number += 1
                self.state.current_faction = next_faction
                return next_faction

        class FakeAI:
            instances: list["FakeAI"] = []

            def __init__(self, ai_state, *, random_seed: int = 0, engine=None) -> None:
                self.state = ai_state
                self.engine = engine
                self.random_seed = random_seed
                self.instances.append(self)

            @property
            def observation_context(self) -> ObservationMutationContext:
                return ObservationMutationContext()

            def take_turn(self, _faction: Faction) -> list:
                return []

        with (
            patch.object(turn_cycle, "CampaignEngine", FakeEngine),
            patch.object(turn_cycle, "StrategicAI", FakeAI),
            patch(
                "gates_of_codex.operational_ai.operational_graph_authority_present",
                return_value=True,
            ),
            patch.object(turn_cycle, "ensure_strategic_actor_runtime", return_value=None),
        ):
            result = turn_cycle.end_player_round(state)  # type: ignore[arg-type]

        self.assertEqual(1, len(FakeEngine.instances))
        self.assertEqual(1, len(FakeAI.instances))
        self.assertIs(FakeEngine.instances[0], FakeAI.instances[0].engine)
        self.assertEqual(["ukr", "rusa", "prc"], result["ai_factions"])
        self.assertEqual(Faction.NATO, state.current_faction)
        self.assertEqual(13, state.turn_number)
        perf = result["perf_turn_cycle"]
        self.assertTrue(perf["shared_operational_ai"])
        self.assertIn("engine_init_ms", perf)


if __name__ == "__main__":
    unittest.main()
