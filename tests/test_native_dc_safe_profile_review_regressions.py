from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gates_of_codex.native_dc_safe_profile import install_safe_profile, verify_safe_profile


class NativeDcSafeProfileReviewRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.workshop = self.root / "400750"
        self.gates = self.workshop / "3696721120"
        self.source.mkdir(parents=True)
        self.gates.mkdir(parents=True)
        for item in ("2897299509", "3261086933", "3636883799"):
            (self.workshop / item).mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _manifest() -> dict[str, object]:
        return {
            "schema": "gates-of-codex.expanded-nations-native-pair",
            "schema_version": 2,
            "native_recipe": "#201-final-layer-v1",
            "attacker_side": "goc_cze",
            "defender_side": "goc_rus",
            "installed_files": {},
            "backups": [],
        }

    @patch("gates_of_codex.native_dc_safe_profile._parent_roots", side_effect=RuntimeError("post-pair failure"))
    @patch("gates_of_codex.native_dc_safe_profile.restore_native_pair")
    @patch("gates_of_codex.native_dc_safe_profile.install_native_pair")
    def test_post_pair_failure_invokes_pair_rollback(self, install_mock, restore_mock, _roots_mock) -> None:
        install_mock.return_value = {"ok": True, "manifest": self._manifest()}
        restore_mock.return_value = {"ok": True, "restored": [], "removed": []}

        with self.assertRaisesRegex(RuntimeError, "post-pair failure"):
            install_safe_profile(self.source, self.gates, self.workshop, "cze", "rus")

        # install_safe_profile canonicalizes gates_root with Path.resolve() before
        # it mutates or rolls back.  On Windows CI the temp root can enter through
        # an 8.3 alias (RUNNER~1) and resolve to the long-form runneradmin path,
        # so assert the production canonical-path contract rather than the input
        # spelling.
        restore_mock.assert_called_once_with(self.gates.resolve())

    def _stage_pair_fixture(self) -> dict[str, object]:
        manifest = self._manifest()
        armies = self.gates / "resource/set/multiplayer/armies"
        armies.mkdir(parents=True, exist_ok=True)
        for side in ("goc_cze", "goc_rus"):
            (armies / f"{side}.set").write_text("fixture\n", encoding="utf-8")

        alliances = self.gates / "resource/set/multiplayer/games/presets/alliances_generic.inc"
        alliances.parent.mkdir(parents=True, exist_ok=True)
        alliances.write_text('{armies "goc_cze"}\n{armies "goc_rus"}\n', encoding="utf-8")

        roster = self.gates / "resource/set/multiplayer/units/roster_conquest.set"
        roster.parent.mkdir(parents=True, exist_ok=True)
        roster.write_text(
            '(include "conquest/inf_goc_cze.set")\n'
            '(include "conquest/units_goc_cze.set")\n'
            '(include "conquest/inf_goc_rus.set")\n'
            '(include "conquest/units_goc_rus.set")\n',
            encoding="utf-8",
        )

        values = self.gates / "resource/set/dynamic_campaign/values.set"
        values.parent.mkdir(parents=True, exist_ok=True)
        values.write_text(
            '{Europe {AvailableMatchups "goc_cze goc_rus" "goc_rus goc_cze"}}\n',
            encoding="utf-8",
        )

        ctf = self.gates / "resource/set/multiplayer/games/campaign_capture_the_flag.set"
        ctf.parent.mkdir(parents=True, exist_ok=True)
        ctf.write_text(
            '{settings}\ninclude "presets/alliances_generic.inc"\n{presets}\n{bots}\n',
            encoding="utf-8",
        )
        return {"ok": True, "manifest": manifest}

    @patch("gates_of_codex.native_dc_safe_profile.verify_native_pair", return_value=[])
    @patch("gates_of_codex.native_dc_safe_profile.install_native_pair")
    def test_png_only_flag_donor_preserves_png_extension(self, install_mock, _verify_mock) -> None:
        install_mock.side_effect = lambda *_args, **_kwargs: self._stage_pair_fixture()
        art = self.workshop / "3261086933" / "resource/interface/pages/main/dynamic_campaign"
        art.mkdir(parents=True, exist_ok=True)
        for side, marker in (("nato", b"WEST"), ("rusa", b"EAST")):
            (art / f"selected_army_{side}.tga").write_bytes(marker + b"-selected")
            (art / f"icon_{side}.tga").write_bytes(marker + b"-icon")
            (art / f"flag_{side}.png").write_bytes(marker + b"-png-flag")

        result = install_safe_profile(self.source, self.gates, self.workshop, "cze", "rus")
        self.assertTrue(result["ok"])
        live = self.gates / "resource/interface/pages/main/dynamic_campaign"
        self.assertEqual((live / "flag_goc_cze.png").read_bytes(), b"WEST-png-flag")
        self.assertEqual((live / "flag_goc_rus.png").read_bytes(), b"EAST-png-flag")
        self.assertFalse((live / "flag_goc_cze.tga").exists())
        self.assertFalse((live / "flag_goc_rus.tga").exists())
        self.assertEqual(verify_safe_profile(self.gates), [])


if __name__ == "__main__":
    unittest.main()
