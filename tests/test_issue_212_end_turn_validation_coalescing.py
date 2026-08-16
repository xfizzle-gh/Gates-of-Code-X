from __future__ import annotations

import unittest

from gates_of_codex.actor_ai_economy import (
    defer_actor_ai_assignment_full_validation,
    run_actor_ai_economy,
)
from gates_of_codex.actor_economy import install_actor_content
from gates_of_codex.force_migration import ensure_strategic_formations
from gates_of_codex.frontend import build_frontend_snapshot
from gates_of_codex.models import Faction
from gates_of_codex.scenario import load_bundled_scenario
from gates_of_codex.state_io import campaign_from_dict
from gates_of_codex.strategic_actors import (
    ACTOR_RUNTIME_KEY,
    assign_strategic_formation_actor,
)

from test_actor_economy import _resolved_payload, _single_battalion_force


class EndTurnValidationCoalescingTests(unittest.TestCase):
    def _prepared_ai_campaign(self):
        state = load_bundled_scenario("legacy_goe_europe")
        ensure_strategic_formations(state)
        install_actor_content(
            state,
            _resolved_payload(),
            selected_actor_id="fra",
        )
        force = _single_battalion_force(state, Faction.NATO)
        assign_strategic_formation_actor(
            state,
            force.strategic_formation_id,
            "deu",
        )
        runtime = state.map_metadata[ACTOR_RUNTIME_KEY]
        runtime["actors"]["deu"]["resources"] = 5000
        state.validate()
        return state

    def test_deferred_ai_assignment_is_state_and_snapshot_equivalent(self) -> None:
        baseline = self._prepared_ai_campaign()
        eager = campaign_from_dict(baseline.to_dict())
        deferred = campaign_from_dict(baseline.to_dict())

        eager_actions = run_actor_ai_economy(eager, Faction.NATO)
        with defer_actor_ai_assignment_full_validation() as tracker:
            deferred_actions = run_actor_ai_economy(deferred, Faction.NATO)

        self.assertGreater(tracker["assignments"], 0)
        self.assertTrue(
            any(item.get("action") == "actor_recruit" for item in eager_actions)
        )

        # This is the coalesced full validation that turn_cycle performs before
        # global round rollover. The eager path already validated each assignment.
        deferred.validate()

        self.assertEqual(eager_actions, deferred_actions)
        self.assertEqual(eager.to_dict(), deferred.to_dict())
        self.assertEqual(
            build_frontend_snapshot(eager),
            build_frontend_snapshot(deferred),
        )


if __name__ == "__main__":
    unittest.main()
