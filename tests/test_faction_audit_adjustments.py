from __future__ import annotations

import unittest

from gates_of_codex.faction_wiring_manifest import load_faction_manifest, validate_faction_manifest


class FactionAuditAdjustmentTest(unittest.TestCase):
    def test_canada_receives_directly_source_backed_leopard_2a4m(self) -> None:
        manifest = load_faction_manifest()
        validate_faction_manifest(manifest)
        component = manifest["components"]["canada_national"]
        exact_units = {
            unit
            for selector in component["selectors"]
            if selector["kind"] == "exact"
            for unit in selector["units"]
        }
        self.assertIn("leopard_c2_mexas", exact_units)
        self.assertIn("leopord_2a4m", exact_units)

    def test_finland_does_not_inherit_the_complete_soviet_legacy_pool(self) -> None:
        manifest = load_faction_manifest()
        validate_faction_manifest(manifest)
        finland = next(actor for actor in manifest["actors"] if actor["actor_id"] == "fin")
        self.assertNotIn("soviet_legacy_core", finland["components"])
        self.assertIn("finland_national", finland["components"])
        self.assertIn("nato_common_infantry", finland["components"])
        self.assertIn("nato_common_support", finland["components"])
        self.assertTrue(any("broad Soviet legacy pool" in note for note in finland["notes"]))

    def test_audit_notes_are_applied_without_duplicates(self) -> None:
        first = load_faction_manifest()
        second = load_faction_manifest()
        self.assertEqual(first, second)
        for actor_id in ("fin", "can"):
            actor = next(actor for actor in first["actors"] if actor["actor_id"] == actor_id)
            self.assertEqual(len(actor["notes"]), len(set(actor["notes"])))


if __name__ == "__main__":
    unittest.main()
