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

    @classmethod
    def _strip_all_eight_recognition_signals(cls, state) -> None:
        cls._strip_all_three_identity_markers(state)
        state.catalog_signature = ""
        for key in (
            "earth3_p2_capitals",
            "earth3_p2_site_intents",
            "earth3_p2_deployment_zones",
            "earth3_p2_tactical_map_preferences",
        ):
            state.map_metadata.pop(key, None)

    def test_simultaneous_identity_marker_removal_cannot_downgrade_p2_state(self) -> None:
        state = _campaign()
        self._strip_all_three_identity_markers(state)

        self.assertTrue(is_earth3_p2_bearing_state(state))
        with self.assertRaisesRegex(Earth3BootstrapError, "bootstrap provenance is missing"):
            state.validate()

    def test_top_level_catalog_identity_independently_recognizes_stripped_p2(self) -> None:
        state = _campaign()
        self._strip_all_three_identity_markers(state)

        self.assertTrue(state.catalog_signature)
        self.assertTrue(is_earth3_p2_bearing_state(state))

    def test_postbootstrap_state_still_identifies_p2_when_catalog_signature_is_removed(self) -> None:
        state = _campaign()
        self._strip_all_three_identity_markers(state)
        state.catalog_signature = ""

        self.assertTrue(is_earth3_p2_bearing_state(state))
        with self.assertRaisesRegex(Earth3BootstrapError, "top-level catalog identity is missing"):
            state.validate()

    def test_all_eight_signals_removed_still_identifies_retained_p2_structure(self) -> None:
        state = _campaign()
        self._strip_all_eight_recognition_signals(state)

        self.assertIn("sf_deu_berlin", state.strategic_formations)
        self.assertIn("bn_sf_deu_berlin", state.battalions)
        self.assertIn("strategic_actor_runtime", state.map_metadata)
        self.assertIn("actor_content_runtime", state.map_metadata)
        self.assertTrue(is_earth3_p2_bearing_state(state))
        with self.assertRaisesRegex(Earth3BootstrapError, "top-level catalog identity is missing"):
            state.validate()

    def test_all_eight_signals_and_objectives_removed_still_uses_capital_structure(self) -> None:
        state = _campaign()
        self._strip_all_eight_recognition_signals(state)
        state.map_metadata.pop("operational_objectives", None)

        self.assertTrue(is_earth3_p2_bearing_state(state))
        with self.assertRaisesRegex(Earth3BootstrapError, "top-level catalog identity is missing"):
            state.validate()

    def test_serialized_all_eight_signal_removal_cannot_downgrade_p2(self) -> None:
        state = _campaign()
        self._strip_all_eight_recognition_signals(state)
        payload = state.to_dict()
        payload["map_metadata"]["manifest_sha256"] = "0" * 64
        payload["strategic_formations"]["sf_deu_berlin"]["actor_id"] = "usa"

        with self.assertRaisesRegex(Earth3BootstrapError, "top-level catalog identity is missing"):
            campaign_from_dict(payload)

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

    def test_removing_runtime_identity_objects_still_cannot_hide_p2(self) -> None:
        state = _campaign()
        state.map_metadata.pop("earth3_bootstrap", None)
        state.map_metadata.pop("scenario_content_phase", None)
        state.map_metadata.pop("actor_content_runtime", None)
        state.map_metadata.pop("strategic_actor_runtime", None)

        self.assertTrue(is_earth3_p2_bearing_state(state))
        with self.assertRaisesRegex(Earth3BootstrapError, "bootstrap provenance is missing"):
            state.validate()

    def test_valid_p2_construction_completes_with_full_identity(self) -> None:
        state = _campaign()

        self.assertTrue(state.catalog_signature)
        self.assertEqual(
            "p2_campaign_bootstrap",
            state.map_metadata["scenario_content_phase"],
        )
        self.assertEqual(
            "earth3_v1_campaign_bootstrap",
            state.map_metadata["earth3_bootstrap"]["bootstrap_id"],
        )
        self.assertEqual(
            "earth3_v1_campaign_bootstrap",
            state.map_metadata["actor_content_runtime"]["earth3_bootstrap_id"],
        )
        state.validate()

    def test_p1_authority_skeleton_is_not_misclassified_as_p2(self) -> None:
        state = build_earth3_campaign()

        self.assertFalse(state.catalog_signature)
        self.assertFalse(is_earth3_p2_bearing_state(state))
        state.validate()


if __name__ == "__main__":
    unittest.main()
