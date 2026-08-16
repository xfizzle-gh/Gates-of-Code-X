from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gates_of_codex import command_cycle_perf, earth3_operational, operational_position


class P3SavePositionFastPathTests(unittest.TestCase):
    def test_authenticated_p3_save_skips_duplicate_validate_only_position_pass(self) -> None:
        state = SimpleNamespace(
            map_metadata={earth3_operational.P3_AUTHORITY_METADATA_KEY: {}}
        )
        with patch.object(
            operational_position,
            "ensure_operational_positions",
            side_effect=AssertionError(
                "authenticated P3 save must defer position authority validation to final state.validate"
            ),
        ):
            self.assertIsNone(
                command_cycle_perf._ensure_runtime_operational_positions(state)
            )

    def test_non_p3_save_retains_position_normalization(self) -> None:
        state = SimpleNamespace(map_metadata={})
        sentinel = object()
        with patch.object(
            operational_position,
            "ensure_operational_positions",
            return_value=sentinel,
        ) as ensure:
            result = command_cycle_perf._ensure_runtime_operational_positions(state)

        self.assertIs(sentinel, result)
        ensure.assert_called_once_with(state)

    def test_final_authoritative_state_validation_remains_in_save_pipeline(self) -> None:
        import inspect

        save_source = inspect.getsource(command_cycle_perf._compact_save_campaign)
        validation_source = inspect.getsource(command_cycle_perf._profiled_campaign_validation)
        self.assertIn('_profiled_campaign_validation(state, subphase_seconds)', save_source)
        self.assertIn('state.validate()', validation_source)
        self.assertIn('_ensure_runtime_operational_positions(state)', save_source)


if __name__ == "__main__":
    unittest.main()