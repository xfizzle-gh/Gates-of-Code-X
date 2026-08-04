from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.acceptance_cli import build_parser
from gates_of_codex.bridge.archive import CampaignSaveArchive
from gates_of_codex.codex.catalog import CodeXCatalogScanner
from gates_of_codex.models import (
    Battalion,
    BattalionRosterEntry,
    BattleParticipant,
    CampaignState,
    Faction,
    FactionState,
    PendingBattle,
    Province,
)
from gates_of_codex.play_context import allocate_visible_campaign_name, default_install_save_path
from gates_of_codex.service import goh_conquest_save_filename
from gates_of_codex.stack_acceptance import prepare_stack_handoff
from gates_of_codex.state_io import load_campaign, save_campaign


class CampaignPlayLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.game = self.root / "game"
        self.west = self.root / "2897299509"
        self.codex = self.root / "3261086933"
        self.ai = self.root / "3636883799"
        self.gocx = self.root / "3700832981"
        self.profile = self.root / "profile"
        self.install = self.profile / "campaign"
        for path in (self.game, self.west, self.codex, self.ai, self.gocx, self.install):
            path.mkdir(parents=True, exist_ok=True)
            (path / "resource").mkdir(exist_ok=True)
        (self.game / "binaries/x64").mkdir(parents=True)
        (self.game / "binaries/x64/gates_of_hell.exe").write_bytes(b"fixture")
        (self.game / "resource/map/multi/2x2/live_test").mkdir(parents=True)
        (self.game / "resource/map/multi/2x2/live_test/map").write_text("{map}\n", encoding="utf-8")
        (self.west / "mod.info").write_text('{name "West-81"}\n', encoding="utf-8")
        (self.ai / "mod.info").write_text('{name "CodeX Conquest AI Overhaul 1.5"}\n', encoding="utf-8")
        (self.gocx / "mod.info").write_text('{name "Gates of CodeX"}\n', encoding="utf-8")
        self._write_codex()
        self._write_template()
        self.campaign = self.root / "campaign.json"
        self._write_campaign()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_codex(self) -> None:
        (self.codex / "resource/set/multiplayer/units/conquest/2022s").mkdir(parents=True)
        (self.codex / "resource/script/multiplayer/units/nato").mkdir(parents=True)
        for faction in ("nato", "ukr", "rusa", "prc"):
            breed_dir = self.codex / f"resource/set/breed/mp/{faction}"
            breed_dir.mkdir(parents=True)
            (breed_dir / f"rifleman_{faction}.set").write_text(
                '{breed\n\t{inventory\n\t\t{item "rifle" filled}\n\t}\n}\n',
                encoding="utf-8",
            )
        units = []
        lua = []
        for faction in ("nato", "ukr", "rusa", "prc"):
            units.append(f'{{"rifle({faction})" {{member "rifleman_{faction}" 2}}}}\n')
            lua.append(f'{{priority=1, type={{"Infantry","Squad"}}, unit="rifle({faction})"}},\n')
        (self.codex / "resource/set/multiplayer/units/conquest/2022s/units.set").write_text("".join(units), encoding="utf-8")
        (self.codex / "resource/script/multiplayer/units/nato/2022s.nato.lua").write_text("".join(lua), encoding="utf-8")
        (self.codex / "mod.info").write_text('{name "Code:X"}\n', encoding="utf-8")

    def _write_template(self) -> None:
        CampaignSaveArchive().write(
            self.install / "conquest 1.sav",
            status=(
                "{saveinfo\n"
                "\t{version 9}\n"
                '\t{name "Conquest 1"}\n'
                "\t{army ger}\n"
                "\t{enemyArmy rus}\n"
                "\t{playedGames 0}\n"
                "\t{wonGames 0}\n"
                "}\n"
            ),
            campaign_scn=(
                "{campaign\n"
                '\t{Human "mp/nato/rifleman_nato" 0x1\n\t\t{Position 0 0}\n\t\t{Player 0}\n\t\t{MID 1}\n\t}\n'
                "\t{Inventory 0x1\n\t\t{box\n\t\t\t{clear}\n\t\t}\n\t}\n"
                '\t{CampaignSquads\n\t\t{"rifle(nato)" "stage_1" 0x1}\n\t}\n}\n'
            ),
        )

    def _write_campaign(self) -> None:
        stack = [self.game, self.west, self.codex, self.ai, self.gocx]
        catalog = CodeXCatalogScanner().scan_stack(stack)
        state = CampaignState(
            campaign_name="Play loop",
            selected_faction=Faction.NATO,
            current_faction=Faction.NATO,
            game_directory=str(self.game),
            profile_directory=str(self.profile),
            code_x_directory=str(self.codex),
            catalog_signature=catalog.signature,
            map_metadata={
                "resource_stack": [str(path) for path in stack],
                "preferred_map": "multi/2x2/live_test",
                "install_directory": str(self.install),
            },
            factions={
                "nato": FactionState(Faction.NATO),
                "rusa": FactionState(Faction.RUSSIA),
            },
            provinces={
                "a": Province("a", "A", Faction.NATO, ["b"]),
                "b": Province("b", "B", Faction.RUSSIA, ["a"]),
            },
            battalions={
                "nato-1": Battalion(
                    "nato-1",
                    Faction.NATO,
                    "a",
                    roster=[BattalionRosterEntry("rifle(nato)", 1, category="infantry")],
                ),
                "rusa-1": Battalion(
                    "rusa-1",
                    Faction.RUSSIA,
                    "b",
                    roster=[BattalionRosterEntry("rifle(rusa)", 1, category="infantry")],
                ),
            },
            pending_battle=PendingBattle(
                battle_id="goc-1-playloop01",
                origin_province_id="a",
                target_province_id="b",
                attacker_faction=Faction.NATO,
                defender_faction=Faction.RUSSIA,
                attacking_participants=[BattleParticipant("nato-1", Faction.NATO, "stage_1", True)],
                defending_participants=[BattleParticipant("rusa-1", Faction.RUSSIA, "stage_2", True)],
                player_faction=Faction.NATO,
                player_is_attacker=True,
            ),
        )
        save_campaign(state, self.campaign)

    def test_handoff_defaults_install_path_and_operator_commands(self) -> None:
        expected_name = allocate_visible_campaign_name("goc-1-playloop01", install_root=self.install)
        expected_path = default_install_save_path(self.install, expected_name)
        result = prepare_stack_handoff(
            self.campaign,
            work_root=self.root / "live",
            backup_root=self.root / "backups",
        )
        self.assertEqual(expected_name, result.visible_campaign_name)
        self.assertEqual(str(expected_path), result.installed_save_path)
        self.assertTrue(Path(result.installed_save_path).is_file())
        self.assertTrue(result.verify_command)
        self.assertTrue(result.import_command)
        self.assertIn("verify", result.verify_command)
        self.assertIn("import-battle", result.import_command)
        self.assertEqual(
            goh_conquest_save_filename(expected_name),
            Path(result.installed_save_path).name,
        )
        # Campaign remembers play context for the next battle.
        state = load_campaign(self.campaign)
        self.assertEqual(str(self.game), state.game_directory)
        self.assertEqual(str(self.profile), state.profile_directory)
        self.assertEqual("multi/2x2/live_test", state.map_metadata.get("preferred_map"))

    def test_handoff_cli_args_are_optional(self) -> None:
        args = build_parser().parse_args(["handoff", "campaign.json", "--launch"])
        self.assertEqual("handoff", args.command)
        self.assertIsNone(args.save)
        self.assertIsNone(args.map)


if __name__ == "__main__":
    unittest.main()
