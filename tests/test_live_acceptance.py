from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.acceptance import (
    backup_existing_files,
    discover_maps,
    prepare_tactical_handoff,
    restore_backup,
    validate_live_installation,
    verify_tactical_result,
)
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
from gates_of_codex.state_io import save_campaign


class LiveAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.game = self.root / "game"
        self.codex = self.root / "codex"
        self.profile = self.root / "profile"
        self.game.mkdir()
        self.codex.mkdir()
        self.profile.mkdir()
        (self.game / "binaries/x64").mkdir(parents=True)
        (self.game / "binaries/x64/gates_of_hell.exe").write_bytes(b"fixture")
        (self.game / "resource/map/multi/2x2/live_test").mkdir(parents=True)
        (self.game / "resource/map/multi/2x2/live_test/map").write_text("{map}\n", encoding="utf-8")
        self._write_codex_fixture()
        self.campaign = self.root / "campaign.json"
        self.save = self.root / "campaign.sav"
        self._write_campaign()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_codex_fixture(self) -> None:
        (self.codex / "resource/set/multiplayer/units/conquest/2022s").mkdir(parents=True)
        (self.codex / "resource/script/multiplayer/units/nato").mkdir(parents=True)
        for faction in ("nato", "ukr", "rusa", "prc"):
            breed_dir = self.codex / f"resource/set/breed/mp/{faction}"
            breed_dir.mkdir(parents=True)
            (breed_dir / f"rifleman_{faction}.set").write_text("{breed}\n", encoding="utf-8")
        units = []
        lua = []
        for faction in ("nato", "ukr", "rusa", "prc"):
            units.append(f'{{"rifle({faction})" {{member "rifleman_{faction}" 4}}}}\n')
            lua.append(f'{{priority=1, type={{"Infantry","Squad"}}, unit="rifle({faction})"}},\n')
        (self.codex / "resource/set/multiplayer/units/conquest/2022s/units.set").write_text("".join(units), encoding="utf-8")
        (self.codex / "resource/script/multiplayer/units/nato/2022s.nato.lua").write_text("".join(lua), encoding="utf-8")
        (self.codex / "mod.info").write_text('{name "Code:X"}\n', encoding="utf-8")

    def _write_campaign(self) -> None:
        catalog = CodeXCatalogScanner().scan(self.codex)
        state = CampaignState(
            campaign_name="Live acceptance",
            selected_faction=Faction.NATO,
            current_faction=Faction.NATO,
            code_x_directory=str(self.codex),
            catalog_signature=catalog.signature,
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
                battle_id="live-1",
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

    def test_discovers_maps_and_validates_installation(self) -> None:
        maps = discover_maps(self.game, self.codex)
        self.assertEqual("multi/2x2/live_test", maps[0].identifier)
        report = validate_live_installation(self.game, self.codex, self.profile)
        self.assertTrue(report.ok)
        self.assertEqual(4, len(report.unit_counts))
        self.assertTrue(report.catalog_signature)

    def test_backup_and_restore_round_trip(self) -> None:
        target = self.root / "important.txt"
        target.write_text("before", encoding="utf-8")
        backup = backup_existing_files([target], backup_root=self.root / "backups")
        target.write_text("after", encoding="utf-8")
        restored = restore_backup(backup)
        self.assertEqual([target.resolve()], restored)
        self.assertEqual("before", target.read_text(encoding="utf-8"))

    def test_safe_handoff_and_post_battle_verification(self) -> None:
        handoff = prepare_tactical_handoff(
            self.campaign,
            game_directory=self.game,
            code_x_directory=self.codex,
            save_path=self.save,
            map_name="multi/2x2/live_test",
            profile_directory=self.profile,
            backup_root=self.root / "backups",
        )
        self.assertTrue(self.save.is_file())
        self.assertTrue(Path(handoff.session_path).is_file())
        self.assertFalse(handoff.launched)
        initial = verify_tactical_result(self.campaign, save_path=self.save, code_x_directory=self.codex)
        self.assertFalse(initial.ok)
        self.assertIn("GoH has not recorded completion", " ".join(initial.errors))

        archive = CampaignSaveArchive()
        contents = archive.read(self.save)
        updated_status = contents.status.replace("{playedGames 0}", "{playedGames 1}").replace(
            "{wonGames 0}", "{wonGames 1}"
        )
        archive.write(self.save, status=updated_status, campaign_scn=contents.campaign_scn)
        completed = verify_tactical_result(self.campaign, save_path=self.save, code_x_directory=self.codex)
        self.assertTrue(completed.ok)
        self.assertEqual(1, completed.played_games_after)
        self.assertGreater(completed.surviving_squads, 0)

    def test_handoff_rejects_unknown_map(self) -> None:
        with self.assertRaisesRegex(ValueError, "Map identifier"):
            prepare_tactical_handoff(
                self.campaign,
                game_directory=self.game,
                code_x_directory=self.codex,
                save_path=self.save,
                map_name="multi/missing",
                profile_directory=self.profile,
            )

    def test_live_cli_parser(self) -> None:
        args = build_parser().parse_args(
            [
                "handoff",
                "campaign.json",
                "--game",
                "game",
                "--codex",
                "codex",
                "--save",
                "campaign.sav",
                "--map",
                "multi/test",
            ]
        )
        self.assertEqual("handoff", args.command)


if __name__ == "__main__":
    unittest.main()
