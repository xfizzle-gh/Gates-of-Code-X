"""Regression coverage for bounded native Dynamic Conquest staging."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gates_of_codex.expanded_nations_native_pair import MANIFEST_REL as PAIR_MANIFEST_REL
from gates_of_codex.native_dc_safe_profile import MANIFEST_REL, install_safe_profile, verify_safe_profile


class NativeDcSafeProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.gates = self.root / "400750" / "3696721120"
        self.workshop = self.root / "400750"
        self.source.mkdir(parents=True)
        self.gates.mkdir(parents=True)
        for workshop_id in ("2897299509", "3261086933", "3636883799"):
            (self.workshop / workshop_id).mkdir(parents=True)

        armies = self.gates / "resource/set/multiplayer/armies"
        armies.mkdir(parents=True)
        for side in ("goc_cze", "goc_rus", "goc_bel"):
            (armies / f"{side}.set").write_text("fixture\n", encoding="utf-8")

        art = self.workshop / "3261086933" / "resource/interface/pages/main/dynamic_campaign"
        art.mkdir(parents=True)
        for side, marker in (("nato", b"WEST"), ("rusa", b"EAST")):
            (art / f"selected_army_{side}.tga").write_bytes(marker + b"-selected")
            (art / f"icon_{side}.tga").write_bytes(marker + b"-icon")
            (art / f"flag_{side}.tga").write_bytes(marker + b"-flag")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _fake_pair_install(self, *_args, **_kwargs):
        manifest = {
            "schema": "gates-of-codex.expanded-nations-native-pair",
            "schema_version": 2,
            "native_recipe": "#201-final-layer-v1",
            "attacker_side": "goc_cze",
            "defender_side": "goc_rus",
            "installed_files": {},
            "backups": [],
        }
        path = self.gates / PAIR_MANIFEST_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest), encoding="utf-8")

        alliances = self.gates / "resource/set/multiplayer/games/presets/alliances_generic.inc"
        alliances.parent.mkdir(parents=True, exist_ok=True)
        alliances.write_text('{armies "nato"}\n{armies "ukr"}\n{armies "goc_cze"}\n{armies "rusa"}\n{armies "prc"}\n{armies "goc_rus"}\n', encoding="utf-8")

        roster = self.gates / "resource/set/multiplayer/units/roster_conquest.set"
        roster.parent.mkdir(parents=True, exist_ok=True)
        roster.write_text('(include "conquest/inf_goc_cze.set")\n(include "conquest/units_goc_cze.set")\n(include "conquest/inf_goc_rus.set")\n(include "conquest/units_goc_rus.set")\n', encoding="utf-8")

        values = self.gates / "resource/set/dynamic_campaign/values.set"
        values.parent.mkdir(parents=True, exist_ok=True)
        values.write_text(
            '{Europe {AvailableMatchups "goc_cze goc_rus" "goc_rus goc_cze"}}\n'
            '{Asia {AvailableMatchups "goc_cze goc_rus" "goc_rus goc_cze"}}\n'
            '{Test {AvailableMatchups "goc_cze goc_rus" "goc_rus goc_cze"}}\n',
            encoding="utf-8",
        )

        ctf = self.gates / "resource/set/multiplayer/games/campaign_capture_the_flag.set"
        ctf.parent.mkdir(parents=True, exist_ok=True)
        ctf.write_text('{settings}\n{alliances (include "presets/alliances_generic.inc")}\n{presets}\n{bots}\n', encoding="utf-8")
        return {"ok": True, "manifest": manifest}

    @patch("gates_of_codex.native_dc_safe_profile.verify_native_pair", return_value=[])
    @patch("gates_of_codex.native_dc_safe_profile.restore_native_pair", return_value={"ok": True, "restored": [], "removed": []})
    @patch("gates_of_codex.native_dc_safe_profile.install_native_pair")
    def test_real_parent_three_matchup_blocks_are_valid(self, install_mock, _restore_mock, _verify_mock) -> None:
        install_mock.side_effect = self._fake_pair_install
        result = install_safe_profile(self.source, self.gates, self.workshop, "cze", "rus")
        self.assertTrue(result["ok"])
        self.assertEqual(verify_safe_profile(self.gates), [])
        self.assertEqual(
            {path.stem for path in (self.gates / "resource/set/multiplayer/armies").glob("goc_*.set")},
            {"goc_cze", "goc_rus"},
        )

    @patch("gates_of_codex.native_dc_safe_profile.verify_native_pair", return_value=[])
    def test_missing_pair_direction_is_rejected(self, _verify_mock) -> None:
        self._fake_pair_install()
        manifest_path = self.gates / MANIFEST_REL
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({
            "schema": "gates-of-codex.native-dc-safe-profile",
            "schema_version": 1,
            "native_recipe": "#201-bounded-create-menu-v1",
            "attacker_side": "goc_cze",
            "defender_side": "goc_rus",
            "selected_goc_sides": ["goc_cze", "goc_rus"],
            "installed_files": {},
            "backups": [],
        }), encoding="utf-8")
        values = self.gates / "resource/set/dynamic_campaign/values.set"
        text = values.read_text(encoding="utf-8")
        values.write_text(text.replace('"goc_rus goc_cze"', '"rusa nato"', 1), encoding="utf-8")
        problems = verify_safe_profile(self.gates)
        self.assertTrue(any("lacks selected pair in both directions" in item for item in problems))

    @patch("gates_of_codex.native_dc_safe_profile.verify_native_pair", return_value=[])
    def test_zero_matchup_blocks_is_rejected(self, _verify_mock) -> None:
        self._fake_pair_install()
        manifest_path = self.gates / MANIFEST_REL
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({
            "schema": "gates-of-codex.native-dc-safe-profile",
            "schema_version": 1,
            "native_recipe": "#201-bounded-create-menu-v1",
            "attacker_side": "goc_cze",
            "defender_side": "goc_rus",
            "selected_goc_sides": ["goc_cze", "goc_rus"],
            "installed_files": {},
            "backups": [],
        }), encoding="utf-8")
        (self.gates / "resource/set/dynamic_campaign/values.set").write_text("{Regions}\n", encoding="utf-8")
        problems = verify_safe_profile(self.gates)
        self.assertTrue(any("no AvailableMatchups blocks" in item for item in problems))


if __name__ == "__main__":
    unittest.main()
