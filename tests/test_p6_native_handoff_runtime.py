"""P6 regressions for explicit template selection and player GoH launch."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.bridge.archive import CampaignSaveArchive
from gates_of_codex.p6_handoff_runtime import (
    append_template_launch_args,
    handoff_with_player_launch,
    validate_status_template,
)
from gates_of_codex.player_shell import PlayerShellError


ROOT = Path(__file__).resolve().parents[1]


def _write_valid_template(path: Path) -> Path:
    status = (
        "{saveinfo\n"
        "\t{version 7}\n"
        '\t{gameVersion "1.065.0"}\n'
        "\t{timestamp 1}\n"
        '\t{name "Owner Template"}\n'
        "\t{army ger}\n"
        "\t{enemyArmy rus}\n"
        "\t{difficulty normal}\n"
        "\t{duration 3}\n"
        "\t{resources 2}\n"
        "\t{selectedMapPoint point_0_0}\n"
        "\t{playedGames 0}\n"
        "\t{wonGames 0}\n"
        "\t{mapPoints\n"
        "\t\t{\n"
        "\t\t\t{name point_0_0}\n"
        '\t\t\t{map "multi/test:campaign_capture_the_flag:4x4"}\n'
        "\t\t}\n"
        "\t}\n"
        "\t{roundsHistory}\n"
        "}\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    CampaignSaveArchive().write(path, status=status, campaign_scn="{campaign}\n")
    return path


class P6NativeHandoffRuntimeTests(unittest.TestCase):
    def test_explicit_template_must_be_a_real_valid_conquest_save(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            missing = root / "missing.sav"
            with self.assertRaises(PlayerShellError) as raised:
                validate_status_template(missing)
            self.assertIn("--template-save", str(raised.exception))

            invalid = root / "invalid.sav"
            invalid.write_bytes(b"not-a-conquest-save")
            with self.assertRaises(PlayerShellError) as raised:
                validate_status_template(invalid)
            self.assertIn("valid Conquest save", str(raised.exception))

            valid = _write_valid_template(root / "owner template.sav")
            self.assertEqual(str(valid.resolve()), validate_status_template(valid))

    def test_explicit_template_is_replayed_by_new_and_continue(self) -> None:
        block = {
            "enabled": True,
            "new_args": ["play", "--new"],
            "continue_args": ["play", "--continue"],
        }
        template = "C:/profile/campaign/owner template.sav"

        updated = append_template_launch_args(block, template)

        self.assertEqual(
            ["--template-save", template],
            updated["new_args"][-2:],
        )
        self.assertEqual(
            ["--template-save", template],
            updated["continue_args"][-2:],
        )
        self.assertNotIn("--template-save", block["new_args"])

    def test_template_replay_is_idempotent(self) -> None:
        template = "C:/profile/campaign/owner.sav"
        block = {
            "new_args": ["play", "--new", "--template-save", template],
            "continue_args": ["play", "--continue", "--template-save", template],
        }

        updated = append_template_launch_args(block, template)

        self.assertEqual(1, updated["new_args"].count("--template-save"))
        self.assertEqual(1, updated["continue_args"].count("--template-save"))

    def test_player_handoff_defaults_to_launch_but_explicit_false_is_preserved(self) -> None:
        self.assertTrue(handoff_with_player_launch({"op": "handoff"})["launch"])
        self.assertFalse(
            handoff_with_player_launch({"op": "handoff", "launch": False})["launch"]
        )

    def test_runtime_wiring_covers_player_launch_and_apply_frontend_backend(self) -> None:
        source = (ROOT / "src/gates_of_codex/fast_entrypoint.py").read_text(
            encoding="utf-8"
        )
        runtime = (ROOT / "src/gates_of_codex/p6_handoff_runtime.py").read_text(
            encoding="utf-8"
        )
        p5 = (ROOT / "src/gates_of_codex/play_context.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("install_p6_handoff_runtime_contracts()", source)
        self.assertIn('["apply-frontend"]', source)
        self.assertIn('parser.add_argument(\n                    "--template-save"', runtime)
        self.assertIn('effective.setdefault("launch", True)', runtime)
        self.assertIn('state.map_metadata["status_template_path"] = template', runtime)
        # P5 #166 remains fail closed. The P6 adapter supplies explicit authority;
        # it does not reintroduce newest-save guessing or adopt a foreign sidecar.
        self.assertIn("if foreign_generated:", p5)
        self.assertIn("Refusing to pick a saveinfo template by modification time", p5)
        self.assertIn("not bound to this campaign", p5)


if __name__ == "__main__":
    unittest.main()
