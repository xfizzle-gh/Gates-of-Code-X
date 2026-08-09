from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gates_of_codex.cli import build_parser, main as cli_main
from gates_of_codex.entrypoint import main as entrypoint_main
from gates_of_codex.models import Faction
from gates_of_codex.scenario import load_bundled_scenario
from gates_of_codex.starter import set_player_faction


class S11CliTests(unittest.TestCase):
    def test_new_parser_defaults_fog_off_and_accepts_on(self) -> None:
        default = build_parser().parse_args(["new", "--codex", "codex"])
        enabled = build_parser().parse_args(
            ["new", "--codex", "codex", "--fog-of-war", "on"]
        )
        self.assertEqual("off", default.fog_of_war)
        self.assertEqual("on", enabled.fog_of_war)

    def test_basic_new_command_persists_requested_fog_state(self) -> None:
        for setting, expected in (("off", False), ("on", True)):
            with self.subTest(setting=setting), tempfile.TemporaryDirectory() as td:
                state = load_bundled_scenario("legacy_goe_europe")
                scanner = MagicMock()
                scanner.scan.return_value = MagicMock()
                with (
                    patch("gates_of_codex.cli.load_bundled_scenario", return_value=state),
                    patch("gates_of_codex.cli.CodeXCatalogScanner", return_value=scanner),
                    patch("gates_of_codex.cli.populate_starter_rosters"),
                    patch("gates_of_codex.cli.initialize_economy"),
                    patch("gates_of_codex.cli.evaluate_campaign_outcome"),
                    patch("gates_of_codex.cli.save_campaign") as save,
                ):
                    result = cli_main(
                        [
                            "new",
                            "--codex",
                            td,
                            "--output",
                            str(Path(td) / "campaign.json"),
                            "--fog-of-war",
                            setting,
                        ]
                    )
                self.assertEqual(0, result)
                saved_state = save.call_args.args[0]
                self.assertIs(expected, saved_state.fog_of_war_enabled)
                humans = [
                    row for row in saved_state.factions.values()
                    if row.is_human_controlled
                ]
                self.assertEqual(1, len(humans))

    def test_full_new_entrypoint_applies_fog_on_to_selected_map(self) -> None:
        state = load_bundled_scenario("legacy_goe_europe")
        set_player_faction(state, Faction.NATO)
        with (
            tempfile.TemporaryDirectory() as td,
            patch(
                "gates_of_codex.europe_mediterranean_from_goe."
                "build_europe_mediterranean_from_goe_campaign",
                return_value=state,
            ),
            patch("gates_of_codex.entrypoint.evaluate_campaign_outcome"),
            patch("gates_of_codex.entrypoint.save_campaign") as save,
        ):
            result = entrypoint_main(
                [
                    "new",
                    "--strategic-map",
                    "europe_mediterranean_from_goe",
                    "--output",
                    str(Path(td) / "campaign.json"),
                    "--fog-of-war",
                    "on",
                ]
            )
        self.assertEqual(0, result)
        self.assertTrue(save.call_args.args[0].fog_of_war_enabled)

    def test_fog_on_new_command_rejects_multiple_humans(self) -> None:
        state = load_bundled_scenario("legacy_goe_europe")
        state.factions["nato"].is_human_controlled = True
        state.factions["rusa"].is_human_controlled = True
        with tempfile.TemporaryDirectory() as td, patch(
            "gates_of_codex.europe_mediterranean_from_goe."
            "build_europe_mediterranean_from_goe_campaign",
            return_value=state,
        ), patch("gates_of_codex.entrypoint.evaluate_campaign_outcome"):
            with self.assertRaisesRegex(
                ValueError, "fog_of_war_requires_single_human_faction"
            ):
                entrypoint_main(
                    [
                        "new",
                        "--strategic-map",
                        "europe_mediterranean_from_goe",
                        "--output",
                        str(Path(td) / "campaign.json"),
                        "--fog-of-war",
                        "on",
                    ]
                )


if __name__ == "__main__":
    unittest.main()
