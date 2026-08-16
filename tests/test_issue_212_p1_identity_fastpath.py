from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

from gates_of_codex import command_scoped_p2_auth, earth3_campaign


class P1IdentityFastPathTests(unittest.TestCase):
    def test_identity_capture_rereads_and_hashes_without_json_reparse(self) -> None:
        capture_source = inspect.getsource(command_scoped_p2_auth._capture_p1_identity)
        helper_source = inspect.getsource(command_scoped_p2_auth._read_fixed_p1_bytes)

        self.assertIn("_read_fixed_p1_bytes", capture_source)
        self.assertNotIn("_read_fixed_authority_json", capture_source)
        for required in (
            "_canonical_authority_root",
            "_is_symlink_or_reparse_point",
            "os.open",
            "os.fstat",
            "_revalidate_captured_authority_path",
            "hashlib.sha256(raw_bytes)",
        ):
            self.assertIn(required, helper_source)

    def test_exact_approved_identity_succeeds_without_json_reader(self) -> None:
        with patch.object(
            earth3_campaign,
            "_read_fixed_authority_json",
            side_effect=AssertionError("semantic-cache hit must not reparse P1 JSON"),
        ):
            identity = command_scoped_p2_auth._capture_p1_identity(None)

        self.assertEqual(earth3_campaign.APPROVED_MANIFEST_SHA256, identity[1])
        self.assertEqual(earth3_campaign.APPROVED_DATASET_RAW_SHA256, identity[2])
        self.assertEqual(earth3_campaign.APPROVED_EMBEDDED_DATASET_SHA256, identity[3])


if __name__ == "__main__":
    unittest.main()
