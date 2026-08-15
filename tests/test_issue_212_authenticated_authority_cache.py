from __future__ import annotations

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gates_of_codex import command_scoped_p2_auth


class AuthenticatedAuthorityCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        command_scoped_p2_auth._clear_process_semantic_caches_for_tests()

    def tearDown(self) -> None:
        command_scoped_p2_auth._clear_process_semantic_caches_for_tests()

    def test_cache_values_are_detached_and_bounded(self) -> None:
        cache = command_scoped_p2_auth.OrderedDict()
        original = {"nested": {"value": 1}}
        for index in range(command_scoped_p2_auth._PROCESS_CACHE_MAX + 2):
            command_scoped_p2_auth._cache_put(cache, (index,), original)
        self.assertEqual(command_scoped_p2_auth._PROCESS_CACHE_MAX, len(cache))
        self.assertNotIn((0,), cache)
        detached = command_scoped_p2_auth._cache_get(
            cache,
            (command_scoped_p2_auth._PROCESS_CACHE_MAX + 1,),
        )
        detached["nested"]["value"] = 99
        pristine = command_scoped_p2_auth._cache_get(
            cache,
            (command_scoped_p2_auth._PROCESS_CACHE_MAX + 1,),
        )
        self.assertEqual(1, pristine["nested"]["value"])

    def test_process_cache_reuses_semantics_only_for_same_authenticated_identity(self) -> None:
        from gates_of_codex import earth3_bootstrap, earth3_campaign

        original_p1 = earth3_campaign.load_earth3_authority
        original_p2 = earth3_bootstrap.load_earth3_bootstrap
        p1_calls: list[str] = []
        p2_calls: list[str] = []
        current_p1_key = ["p1-bytes-a"]
        current_p2_key = ["p2-bytes-a"]

        authority = SimpleNamespace(
            root="/authority",
            manifest_sha256="manifest",
            dataset_sha256="dataset",
            embedded_dataset_sha256="embedded",
            geometry_sha256="geometry",
            production_asset_version="v1",
            topology_edge_count=10249,
            included_ids_sha256="ids",
        )
        bundle = SimpleNamespace(root="/p2", documents={"x": {"value": 1}})

        def fake_p1(_authority_root=None):
            p1_calls.append(current_p1_key[0])
            return copy.deepcopy(authority)

        def fake_p2(*, authority_root=None):
            p2_calls.append(current_p2_key[0])
            return copy.deepcopy(bundle)

        earth3_campaign.load_earth3_authority = fake_p1
        earth3_bootstrap.load_earth3_bootstrap = fake_p2
        try:
            with (
                patch.object(
                    command_scoped_p2_auth,
                    "_capture_p1_identity",
                    side_effect=lambda _root: (current_p1_key[0],),
                ),
                patch.object(
                    command_scoped_p2_auth,
                    "_capture_p2_identity",
                    side_effect=lambda _root, authenticated_p1: (
                        current_p2_key[0],
                        authenticated_p1.dataset_sha256,
                    ),
                ),
            ):
                command_scoped_p2_auth._install_process_semantic_authority_cache()

                first = earth3_bootstrap.load_earth3_bootstrap()
                second = earth3_bootstrap.load_earth3_bootstrap()
                self.assertEqual(["p1-bytes-a"], p1_calls)
                self.assertEqual(["p2-bytes-a"], p2_calls)
                second.documents["x"]["value"] = 99
                third = earth3_bootstrap.load_earth3_bootstrap()
                self.assertEqual(1, third.documents["x"]["value"])

                # A P2 byte change cannot hit the prior semantic bundle.
                current_p2_key[0] = "p2-bytes-b"
                changed_p2 = earth3_bootstrap.load_earth3_bootstrap()
                self.assertEqual(1, changed_p2.documents["x"]["value"])
                self.assertEqual(["p2-bytes-a", "p2-bytes-b"], p2_calls)

                # A P1 byte change also invalidates P2 reuse, even if P2 bytes
                # themselves did not change.
                current_p1_key[0] = "p1-bytes-b"
                current_p2_key[0] = "p2-bytes-a"
                earth3_bootstrap.load_earth3_bootstrap()
                self.assertEqual(["p1-bytes-a", "p1-bytes-b"], p1_calls)
                self.assertEqual(3, len(p2_calls))
        finally:
            earth3_campaign.load_earth3_authority = original_p1
            earth3_bootstrap.load_earth3_bootstrap = original_p2

    def test_capture_is_performed_before_semantic_cache_lookup(self) -> None:
        """The cache never turns authentication itself into a process-wide trust."""
        cache = command_scoped_p2_auth._P1_SEMANTIC_CACHE
        command_scoped_p2_auth._cache_put(cache, ("approved",), {"ok": True})
        captured: list[str] = []

        def authenticated_key() -> tuple[str]:
            captured.append("read-and-hash")
            return ("approved",)

        key = authenticated_key()
        value = command_scoped_p2_auth._cache_get(cache, key)
        self.assertEqual(["read-and-hash"], captured)
        self.assertEqual({"ok": True}, value)


if __name__ == "__main__":
    unittest.main()
