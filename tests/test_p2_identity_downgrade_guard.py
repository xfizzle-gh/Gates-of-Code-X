from __future__ import annotations

import unittest

from gates_of_codex.earth3_bootstrap import Earth3BootstrapError
from gates_of_codex.earth3_campaign import build_earth3_campaign
from gates_of_codex.p2_identity import is_earth3_p2_bearing_state
from gates_of_codex.state_io import campaign_from_dict

from test_p2_earth3_campaign_bootstrap import _campaign


class P2IdentityDowngradeGuardTests(unittest.TestCase):
    @staticmethod
    def _strip_all_three_identity_markers(state) -> None:
        state.map_metadata.pop("earth3_bootstrap", None)
        state.map_metadata.pop("scenario_content_phase", None)
        actor_content = state.map_metadata["actor_content_runtime"]
        actor_content.pop("earth3_bootstrap_id", None)

    def test_simultaneous_identity_marker_removal_cannot_downgrade_p2_state(self) -> None:
        state = _campaign()
        self._strip_all_three_identity_markers(state)

        self.assertTrue(is_earth3_p2_bearing_state(state))
        with self.assertRaisesRegex(Earth3BootstrapError, "bootstrap provenance is missing"):
            state.validate()

    def test_serialized_marker_removal_rejects_before_other_p2_tampering_can_load(self) -> None:
        payload = _campaign().to_dict()
        payload["map_metadata"].pop("earth3_bootstrap", None)
        payload["map_metadata"].pop("scenario_content_phase", None)
        payload["map_metadata"]["actor_content_runtime"].pop(
            "earth3_bootstrap_id", None
        )
        payload["map_metadata"]["manifest_sha256"] = "0" * 64
        payload["strategic_formations"]["sf_deu_berlin"]["actor_id"] = "usa"

        with self.assertRaisesRegex(Earth3BootstrapError, "bootstrap provenance is missing"):
            campaign_from_dict(payload)

    def test_serialized_construction_token_lookalike_cannot_bypass_identity_guard(self) -> None:
        payload = _campaign().to_dict()
        payload["map_metadata"].pop("earth3_bootstrap", None)
        payload["map_metadata"].pop("scenario_content_phase", None)
        payload["map_metadata"]["actor_content_runtime"].pop(
            "earth3_bootstrap_id", None
        )
        payload["map_metadata"]["_earth3_p2_construction_token"] = "forged"

        with self.assertRaisesRegex(Earth3BootstrapError, "bootstrap provenance is missing"):
            campaign_from_dict(payload)

    def test_completed_campaign_does_not_retain_construction_token(self) -> None:
        state = _campaign()

        self.assertNotIn("_earth3_p2_construction_token", state.map_metadata)
        self.assertNotIn("_earth3_p2_construction_token", state.to_dict()["map_metadata"])
        state.validate()

    def test_removing_runtime_identity_objects_still_cannot_hide_p2_formations(self) -> None:
        state = _campaign()
        state.map_metadata.pop("earth3_bootstrap", None)
        state.map_metadata.pop("scenario_content_phase", None)
        state.map_metadata.pop("actor_content_runtime", None)
        state.map_metadata.pop("strategic_actor_runtime", None)

        self.assertTrue(is_earth3_p2_bearing_state(state))
        with self.assertRaisesRegex(Earth3BootstrapError, "bootstrap provenance is missing"):
            state.validate()

    def test_p1_authority_skeleton_is_not_misclassified_as_p2(self) -> None:
        state = build_earth3_campaign()

        self.assertFalse(is_earth3_p2_bearing_state(state))
        state.validate()


if __name__ == "__main__":
    unittest.main()
