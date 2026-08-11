from __future__ import annotations

import unittest

from gates_of_codex.faction_wiring_manifest import (
    load_faction_manifest,
    validate_faction_manifest,
)


class FranceArfInfantryContractTests(unittest.TestCase):
    def test_france_retains_complete_canonical_arf_line_infantry_set(self) -> None:
        manifest = load_faction_manifest()
        validate_faction_manifest(manifest)

        france = next(
            actor for actor in manifest["actors"] if actor["actor_id"] == "fra"
        )
        self.assertIn("nato_common_infantry", france["components"])
        self.assertIn("france_national", france["components"])

        expected = {
            "squad_arf_rifle(nato)",
            "squad_arf_rifle_spike(nato)",
            "squad_arf_mg(nato)",
            "squad_arf_at(nato)",
            "squad_arf_scout(nato)",
            "squad_dsk_eng(nato)",
            "squad_dsk_eng_at(nato)",
        }
        france_national = manifest["components"]["france_national"]
        actual = {
            unit
            for selector in france_national["selectors"]
            if selector["kind"] == "exact"
            for unit in selector["units"]
        }
        self.assertTrue(expected.issubset(actual))

        notes = "\n".join(france["notes"])
        self.assertIn("ARF", notes)
        self.assertIn("line-infantry", notes)


if __name__ == "__main__":
    unittest.main()
