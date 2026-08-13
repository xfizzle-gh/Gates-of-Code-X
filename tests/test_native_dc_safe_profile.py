"""Regression coverage for the bounded GoH v1.065 native DC create-menu profile."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gates_of_codex.expanded_nations_native_pair import MANIFEST_REL as PAIR_MANIFEST_REL
from gates_of_codex.native_dc_safe_profile import (
    MANIFEST_REL,
    install_safe_profile,
    restore_safe_profile,
    verify_safe_profile,
)


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
        for side in ("goc_cze", "goc_rus", "goc_bel", "goc_aut", "goc_egy"):
            (armies / f"{side}.set").write_text(f"{{army {side}}}\n", encoding="utf-8")

        art = (
            self.workshop
            / "3261086933"
            / "resource/interface/pages/main/dynamic_campaign"
        )
        art.mkdir(parents=True)
        for side, marker in (("nato", b"WEST"), ("rusa", b"EAST")):
            (art / f"selected_army_{side}.tga").write_bytes(marker + b"-selected")
            (art / f"icon_{side}.tga").write_bytes(marker + b"-icon")
            (art / f"flag_{side}.tga").write_bytes(marker + b"-flag")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _fake_pair_install(self, *_args, **_kwargs):
        pair_manifest = {
            "schema": "gates-of-codex.expanded-nations-native-pair",
            "schema_version": 2,
            "native_recipe": "#201-final-layer-v1",
            "attacker_side": "goc_cze",
            "defender_side": "goc_rus",
            "installed_files": {},
            "backups": [],
        }
        pair_path = self.gates / PAIR_MANIFEST_REL
        pair_path.parent.mkdir(parents=True, exist_ok=True)
        pair_path.write_text(json.dumps(pair_manifest), encoding="utf-8")

        alliances = self.gates / "resource/set/multiplayer/games/presets/alliances_generic.inc"
        alliances.parent.mkdir(parents=True, exist_ok=True)
        alliances.write_text(
            '{"West"\n{armies "nato"}\n{armies "ukr"}\n{armies "goc_cze"}\n}\n'
            '{"East"\n{armies "rusa"}\n{armies "prc"}\n{armies "goc_rus"}\n}\n',
            encoding="utf-8",
        )

        roster = self.gates / "resource/set/multiplayer/units/roster_conquest.set"
        roster.parent.mkdir(parents=True, exist_ok=True)
        roster.write_text(
            '{units\n'
            '(include "conquest/inf_goc_cze.set")\n'
            '(include "conquest/inf_goc_rus.set")\n'
            '(include "conquest/units_goc_cze.set")\n'
            '(include "conquest/units_goc_rus.set")\n'
            '}\n',
            encoding="utf-8",
        )

        values = self.gates / "resource/set/dynamic_campaign/values.set"
        values.parent.mkdir(parents=True, exist_ok=True)
        regions = (
            "Ostfront",
            "Talvisota",
            "West",
            "Finest_Hour",
            "West_FH",
            "Europe",
            "Asia",
            "Test",
        )
        values.write_text(
            "{Regions\n"
            + "".join(
                f'{{{region}\n{{AvailableMatchups\n"goc_cze goc_rus"\n"goc_rus goc_cze"\n}}\n}}\n'
                for region in regions
            )
            + "}\n",
            encoding="utf-8",
        )

        ctf = self.gates / "resource/set/multiplayer/games/campaign_capture_the_flag.set"
        ctf.parent.mkdir(parents=True, exist_ok=True)
        ctf.write_text(
            '{game\n'
            '{settings {difficulty multiplayer}}\n'
            '{teamSettings {alliances (include "presets/alliances_generic.inc")}}\n'
            '{presets {"d:campaign" {bots {normal 1}}}}\n'
            '}\n',
            encoding="utf-8",
        )
        return {"ok": True, "manifest": pair_manifest}

    def _fake_pair_restore(self, *_args, **_kwargs):
        path = self.gates / PAIR_MANIFEST_REL
        if path.is_file():
            path.unlink()
        return {"ok": True, "restored": [], "removed": []}

    @patch("gates_of_codex.native_dc_safe_profile.verify_native_pair", return_value=[])
    @patch("gates_of_codex.native_dc_safe_profile.restore_native_pair")
    @patch("gates_of_codex.native_dc_safe_profile.install_native_pair")
    def test_install_bounds_picker_to_selected_pair_and_materializes_dc_art(
        self,
        install_mock,
        restore_mock,
        _verify_mock,
    ) -> None:
        install_mock.side_effect = self._fake_pair_install
        restore_mock.side_effect = self._fake_pair_restore

        result = install_safe_profile(
            self.source,
            self.gates,
            self.workshop,
            "cze",
            "rus",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["selected_goc_sides"], ["goc_cze", "goc_rus"])
        self.assertIn("goc_bel", result["quarantined_goc_armies"])
        self.assertIn("goc_aut", result["quarantined_goc_armies"])
        self.assertIn("goc_egy", result["quarantined_goc_armies"])

        armies = self.gates / "resource/set/multiplayer/armies"
        self.assertEqual(
            {path.stem for path in armies.glob("goc_*.set")},
            {"goc_cze", "goc_rus"},
        )

        dc = self.gates / "resource/interface/pages/main/dynamic_campaign"
        self.assertEqual((dc / "selected_army_goc_cze.tga").read_bytes(), b"WEST-selected")
        self.assertEqual((dc / "icon_goc_cze.tga").read_bytes(), b"WEST-icon")
        self.assertEqual((dc / "flag_goc_cze.tga").read_bytes(), b"WEST-flag")
        self.assertEqual((dc / "selected_army_goc_rus.tga").read_bytes(), b"EAST-selected")
        self.assertEqual(verify_safe_profile(self.gates), [])

        restored = restore_safe_profile(self.gates)
        self.assertTrue(restored["ok"])
        self.assertEqual(
            {path.stem for path in armies.glob("goc_*.set")},
            {"goc_cze", "goc_rus", "goc_bel", "goc_aut", "goc_egy"},
        )
        self.assertFalse((dc / "selected_army_goc_cze.tga").exists())
        self.assertFalse((self.gates / MANIFEST_REL).exists())

    @patch("gates_of_codex.native_dc_safe_profile.verify_native_pair", return_value=[])
    @patch("gates_of_codex.native_dc_safe_profile.restore_native_pair")
    @patch("gates_of_codex.native_dc_safe_profile.install_native_pair")
    def test_missing_required_picker_art_rolls_back_quarantine(
        self,
        install_mock,
        restore_mock,
        _verify_mock,
    ) -> None:
        install_mock.side_effect = self._fake_pair_install
        restore_mock.side_effect = self._fake_pair_restore
        (
            self.workshop
            / "3261086933"
            / "resource/interface/pages/main/dynamic_campaign/icon_nato.tga"
        ).unlink()

        with self.assertRaisesRegex(Exception, "Cannot resolve required Dynamic Conquest art"):
            install_safe_profile(
                self.source,
                self.gates,
                self.workshop,
                "cze",
                "rus",
            )

        armies = self.gates / "resource/set/multiplayer/armies"
        self.assertEqual(
            {path.stem for path in armies.glob("goc_*.set")},
            {"goc_cze", "goc_rus", "goc_bel", "goc_aut", "goc_egy"},
        )
        self.assertFalse((self.gates / MANIFEST_REL).exists())
        restore_mock.assert_called_once()

    @patch("gates_of_codex.native_dc_safe_profile.verify_native_pair", return_value=[])
    def test_verify_rejects_extra_army_and_missing_visible_region(self, _verify_mock) -> None:
        self._fake_pair_install()
        manifest_path = self.gates / MANIFEST_REL
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "schema": "gates-of-codex.native-dc-safe-profile",
                    "schema_version": 1,
                    "native_recipe": "#201-bounded-create-menu-v1",
                    "attacker_side": "goc_cze",
                    "defender_side": "goc_rus",
                    "selected_goc_sides": ["goc_cze", "goc_rus"],
                    "installed_files": {},
                    "backups": [],
                }
            ),
            encoding="utf-8",
        )
        # Delete one region block by replacing one marker so only seven remain.
        values = self.gates / "resource/set/dynamic_campaign/values.set"
        text = values.read_text(encoding="utf-8")
        values.write_text(text.replace("{AvailableMatchups", "{UnavailableMatchups", 1), encoding="utf-8")

        problems = verify_safe_profile(self.gates)
        self.assertTrue(any("not bounded to selected pair" in item for item in problems))
        self.assertTrue(any("requires all 8 visible regions" in item for item in problems))


if __name__ == "__main__":
    unittest.main()
