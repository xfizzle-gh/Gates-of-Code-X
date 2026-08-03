from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from gates_of_codex.codex.locator import CodeXLocator
from gates_of_codex.doctor import DoctorReport
from gates_of_codex.entrypoint import main as entrypoint_main


class CodeXLocatorTests(unittest.TestCase):
    def test_infers_nondefault_steam_root_from_workshop_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Steam"
            repo = root / "steamapps/workshop/content/400750/Gates-of-Code-X"
            codex = root / "steamapps/workshop/content/400750/1234567890"
            game = root / "steamapps/common/Custom Gates of Hell"
            repo.mkdir(parents=True)
            codex.mkdir(parents=True)
            game.mkdir(parents=True)
            (codex / "mod.info").write_text('{name "Code:X"}\n', encoding="utf-8")
            (root / "steamapps/appmanifest_400750.acf").write_text(
                '"AppState"\n{\n\t"appid" "400750"\n\t"installdir" "Custom Gates of Hell"\n}\n',
                encoding="utf-8",
            )

            previous = Path.cwd()
            os.chdir(repo)
            try:
                locator = CodeXLocator()
                self.assertIn(root.resolve(), locator.steam_roots())
                self.assertIn(game.resolve(), locator.find_game_directories())
                self.assertIn(codex.resolve(), locator.find_codex_directories(game))
            finally:
                os.chdir(previous)

    def test_finds_onedrive_profile_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            one_drive = Path(temporary) / "OneDrive"
            profiles = one_drive / "Documents/My Games/gates of hell/profiles"
            profiles.mkdir(parents=True)
            with patch.dict(os.environ, {"OneDrive": str(one_drive)}, clear=False):
                self.assertIn(profiles.resolve(), CodeXLocator().find_profiles())


class DoctorEntrypointTests(unittest.TestCase):
    def test_explicit_doctor_paths_are_forwarded(self) -> None:
        report = DoctorReport(
            game_directories=[Path("game")],
            code_x_directories=[Path("codex")],
            profile_directories=[Path("profile")],
            unit_counts={"nato": 1, "ukr": 1, "rusa": 1, "prc": 1},
            errors=[],
        )
        with patch("gates_of_codex.entrypoint.diagnose", return_value=report) as diagnose:
            output = io.StringIO()
            with redirect_stdout(output):
                result = entrypoint_main([
                    "doctor",
                    "--game", "G:/GoH",
                    "--codex", "G:/CodeX",
                    "--profile", "G:/Profiles",
                ])

        self.assertEqual(0, result)
        diagnose.assert_called_once_with(
            code_x_directory="G:/CodeX",
            game_directory="G:/GoH",
            profile_directory="G:/Profiles",
        )
        self.assertTrue(json.loads(output.getvalue())["ok"])


if __name__ == "__main__":
    unittest.main()
