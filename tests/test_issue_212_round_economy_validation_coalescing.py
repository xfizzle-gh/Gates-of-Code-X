from __future__ import annotations

import unittest
from unittest.mock import patch

from gates_of_codex import economy, round_economy_validation
from gates_of_codex.actor_economy import install_actor_content
from gates_of_codex.force_migration import ensure_strategic_formations
from gates_of_codex.frontend import build_frontend_snapshot
from gates_of_codex.models import CampaignState, Faction
from gates_of_codex.round_economy_validation import (
    defer_actor_round_settlement_full_validation,
)
from gates_of_codex.scenario import load_bundled_scenario
from gates_of_codex.state_io import campaign_from_dict
from gates_of_codex.strategic_actors import assign_strategic_formation_actor

from test_actor_economy import _resolved_payload, _single_battalion_force


class RoundEconomyValidationCoalescingTests(unittest.TestCase):
    def _prepared_campaign(self):
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
        state.validate()
        return state

    def test_deferred_actor_settlement_is_state_and_snapshot_equivalent(self) -> None:
        baseline = self._prepared_campaign()
        eager = campaign_from_dict(baseline.to_dict())
        deferred = campaign_from_dict(baseline.to_dict())

        eager_reports = economy.settle_round_economy(eager)
        with defer_actor_round_settlement_full_validation() as tracker:
            deferred_reports = economy.settle_round_economy(deferred)

        self.assertEqual(1, tracker["settlements"])

        # This is the exact full validation retained by the authoritative save
        # after the rollover. The public settlement path already ran it eagerly.
        deferred.validate()

        self.assertEqual(eager_reports, deferred_reports)
        self.assertEqual(eager.to_dict(), deferred.to_dict())
        self.assertEqual(
            build_frontend_snapshot(eager),
            build_frontend_snapshot(deferred),
        )

    def test_context_defers_only_full_validation_and_public_path_stays_eager(self) -> None:
        deferred = self._prepared_campaign()
        with (
            patch.object(CampaignState, "validate", autospec=True) as full_validate,
            patch.object(
                round_economy_validation,
                "validate_actor_content_runtime",
                wraps=round_economy_validation.validate_actor_content_runtime,
            ) as focused_validate,
        ):
            with defer_actor_round_settlement_full_validation() as tracker:
                economy.settle_round_economy(deferred)
            self.assertEqual(1, tracker["settlements"])
            self.assertEqual(0, full_validate.call_count)
            self.assertEqual(1, focused_validate.call_count)

        eager = self._prepared_campaign()
        with patch.object(CampaignState, "validate", autospec=True) as full_validate:
            economy.settle_round_economy(eager)
            self.assertEqual(1, full_validate.call_count)


if __name__ == "__main__":
    unittest.main()
