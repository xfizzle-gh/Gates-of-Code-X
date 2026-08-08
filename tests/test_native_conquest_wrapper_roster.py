from __future__ import annotations

import re
import unittest
from pathlib import Path


class NativeConquestWrapperRosterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.roster_path = cls.root / "resource/set/multiplayer/units/roster_conquest.set"
        cls.wrapper_path = (
            cls.root
            / "resource/set/multiplayer/units/conquest/units_goc_national_wrappers.set"
        )
        cls.roster_text = cls.roster_path.read_text(encoding="utf-8")
        cls.wrapper_text = cls.wrapper_path.read_text(encoding="utf-8")

    def test_final_layer_roster_preserves_authoritative_codex_include_order(self) -> None:
        includes = re.findall(r'\(include\s+"([^"]+)"\)', self.roster_text)
        self.assertEqual(
            includes,
            [
                "conquest/settings.set",
                "conquest/inf_ukr.set",
                "conquest/inf_rusa.set",
                "conquest/inf_nato.set",
                "conquest/inf_prc_era1960.set",
                "conquest/inf_sov_era1960.set",
                "conquest/inf_csa_era1960.set",
                "conquest/inf_frg_era1960.set",
                "conquest/units_ukr.set",
                "conquest/units_rusa.set",
                "conquest/units_nato.set",
                "conquest/units_sov_era1960.set",
                "conquest/units_csa_era1960.set",
                "conquest/units_frg_era1960.set",
                "conquest/units_prc_era1960.set",
                "conquest/units_goc_national_wrappers.set",
            ],
        )

    def test_roster_override_contains_only_include_graph_structure(self) -> None:
        without_comments = re.sub(r";[^\n]*", "", self.roster_text)
        without_includes = re.sub(r'\(include\s+"[^"]+"\)', "", without_comments)
        remaining = re.sub(r"[\s{}]", "", without_includes)
        self.assertEqual(remaining, "units")
        self.assertNotIn("(define", self.roster_text)
        self.assertNotRegex(self.roster_text, r'\{"')

    def test_all_wrappers_are_native_roster_reachable_and_player_sale_eligible(self) -> None:
        wrapper_ids = re.findall(r'^\{"([^"]+)"', self.wrapper_text, flags=re.MULTILINE)
        self.assertEqual(
            wrapper_ids,
            [
                "goc_ildu_rifle(ukr)",
                "goc_ildu_at(ukr)",
                "goc_ildu_javelin(ukr)",
                "goc_ildu_recon(ukr)",
                "goc_ildu_engineer(ukr)",
                "goc_ildu_manpads(ukr)",
                "goc_sparta_rifle(rusa)",
                "goc_sparta_recon(rusa)",
                "goc_vostok_rifle(rusa)",
                "goc_vostok_mortar(rusa)",
                "goc_vostok_spg9(rusa)",
                "goc_serb_rifle(rusa)",
                "goc_serb_at(rusa)",
                "goc_serb_recon(rusa)",
            ],
        )
        self.assertIn(
            '(include "conquest/units_goc_national_wrappers.set")',
            self.roster_text,
        )
        self.assertNotIn("not_for_player_sale", self.wrapper_text)
        self.assertEqual(sum(name.endswith("(ukr)") for name in wrapper_ids), 6)
        self.assertEqual(sum(name.endswith("(rusa)") for name in wrapper_ids), 8)

    def test_fix_does_not_override_dynamic_campaign_values(self) -> None:
        values_path = self.root / "resource/set/dynamic_campaign/values.set"
        self.assertFalse(values_path.exists())


if __name__ == "__main__":
    unittest.main()
