from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.acceptance import prepare_tactical_handoff, verify_tactical_result
from gates_of_codex.bridge.archive import CampaignSaveArchive
from gates_of_codex.codex.catalog import CodeXCatalogScanner
from gates_of_codex.first_engine_test import FirstEngineTestResult
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
from gates_of_codex.service import (
    BattleExportManifest,
    GatesOfCodeXService,
    apply_installed_fingerprint,
    fingerprint_save,
    goh_conquest_save_filename,
    read_status_campaign_name,
    unique_acceptance_campaign_name,
)
from gates_of_codex.state_io import save_campaign


class AcceptanceUniqueNameTests(unittest.TestCase):
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
        self.save = self.root / "gates_of_codex_acceptance.sav"
        self.template = self.root / "gates of codex acceptance.sav"
        self._write_campaign()
        self._write_template_save()

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
        (self.codex / "resource/set/multiplayer/units/conquest/2022s/units.set").write_text(
            "".join(units), encoding="utf-8"
        )
        (self.codex / "resource/script/multiplayer/units/nato/2022s.nato.lua").write_text(
            "".join(lua), encoding="utf-8"
        )
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
                battle_id="goc-1-b714b08b42",
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

    def _write_template_save(self) -> None:
        status = (
            "{saveinfo\n"
            "\t{version 9}\n"
            '\t{name "Gates of CodeX Acceptance"}\n'
            "\t{army ger}\n"
            "\t{enemyArmy rus}\n"
            "\t{playedGames 0}\n"
            "\t{wonGames 0}\n"
            "}\n"
        )
        CampaignSaveArchive().write(
            self.template,
            status=status,
            campaign_scn=(
                "{campaign\n"
                '\t{Human "mp/nato/rifleman_nato" 0x1\n'
                "\t\t{Position 0 0}\n"
                "\t\t{Player 0}\n"
                "\t\t{MID 1}\n"
                "\t}\n"
                "\t{Inventory 0x1\n"
                "\t\t{box\n"
                "\t\t\t{clear}\n"
                "\t\t}\n"
                "\t}\n"
                '\t{CampaignSquads\n'
                '\t\t{"rifle(nato)" "stage_1" 0x1}\n'
                "\t}\n"
                "}\n"
            ),
        )

    def test_unique_name_is_deterministic_and_short(self) -> None:
        first = unique_acceptance_campaign_name("goc-1-b714b08b42")
        second = unique_acceptance_campaign_name("goc-1-b714b08b42")
        self.assertEqual(first, second)
        self.assertEqual("Gates of CodeX Test b714b08b", first)
        self.assertLessEqual(len(first), 40)

    def test_goh_install_filename_matches_live_rewrite_behavior(self) -> None:
        # Observed live: GoH rewrote "gates of codex test 39379c4c.sav"
        # instead of the underscored gates_of_codex_acceptance.sav install path.
        self.assertEqual(
            "gates of codex test 39379c4c.sav",
            goh_conquest_save_filename("Gates of CodeX Test 39379c4c"),
        )
        self.assertEqual(
            "gates of codex test b714b08b.sav",
            goh_conquest_save_filename(unique_acceptance_campaign_name("goc-1-b714b08b42")),
        )

    def test_unique_name_avoids_template_collision(self) -> None:
        reserved = {"Gates of CodeX Test b714b08b"}
        name = unique_acceptance_campaign_name("goc-1-b714b08b42", reserved=reserved)
        self.assertNotEqual("Gates of CodeX Test b714b08b", name)
        self.assertTrue(name.startswith("Gates of CodeX Test "))

    def test_two_saves_same_internal_name_are_disambiguated_on_export(self) -> None:
        service = GatesOfCodeXService()
        generated = service.export_battle(
            self.campaign,
            code_x_directory=self.codex,
            save_path=self.save,
            map_name="multi/2x2/live_test",
            status_template_path=self.template,
            allow_overwrite=True,
        )
        template_name = read_status_campaign_name(CampaignSaveArchive().read(self.template).status)
        generated_name = read_status_campaign_name(CampaignSaveArchive().read(self.save).status)
        self.assertEqual("Gates of CodeX Acceptance", template_name)
        self.assertEqual(generated.visible_campaign_name, generated_name)
        self.assertNotEqual(template_name, generated_name)
        self.assertEqual("Gates of CodeX Test b714b08b", generated_name)
        # Template file remains untouched.
        self.assertEqual(
            "Gates of CodeX Acceptance",
            read_status_campaign_name(CampaignSaveArchive().read(self.template).status),
        )

    def test_first_test_result_exposes_visible_name(self) -> None:
        from gates_of_codex.acceptance import BackupRecord, HandoffResult, LiveValidationReport

        manifest = BattleExportManifest(
            battle_id="goc-1-b714b08b42",
            campaign_path=str(self.campaign),
            save_path=str(self.save),
            catalog_signature="sig",
            played_games=0,
            won_games=0,
            visible_campaign_name="Gates of CodeX Test b714b08b",
        )
        handoff = HandoffResult(
            manifest=manifest,
            validation=LiveValidationReport(str(self.game), str(self.codex), str(self.profile)),
            backup=BackupRecord(str(self.root), {}, "now"),
        )
        result = FirstEngineTestResult(
            session_directory=str(self.root),
            campaign_path=str(self.campaign),
            export_save_path=str(self.save),
            installed_save_path=str(self.save),
            status_template_path=str(self.template),
            map_name="multi/2x2/live_test",
            profile_directory=str(self.profile),
            install_directory=str(self.profile),
            selection=__import__("gates_of_codex.first_engine_test", fromlist=["AcceptanceBattleSelection"]).AcceptanceBattleSelection(
                "nato-1",
                "nato",
                "a",
                "A",
                "rusa-1",
                "rusa",
                "b",
                "B",
                "goc-1-b714b08b42",
            ),
            handoff=handoff,
            verify_command="verify",
            import_command="import",
            visible_campaign_name="Gates of CodeX Test b714b08b",
        )
        payload = result.to_dict()
        self.assertEqual("Gates of CodeX Test b714b08b", payload["visible_campaign_name"])
        self.assertIn("Gates of CodeX Test b714b08b", payload["load_instruction"])

    def test_handoff_records_fingerprint_and_detects_untouched_save(self) -> None:
        installed = self.profile / "gates_of_codex_acceptance.sav"
        handoff = prepare_tactical_handoff(
            self.campaign,
            game_directory=self.game,
            code_x_directory=self.codex,
            save_path=self.save,
            map_name="multi/2x2/live_test",
            profile_directory=self.profile,
            install_save_path=installed,
            backup_root=self.root / "backups",
        )
        self.assertTrue(handoff.manifest.visible_campaign_name)
        self.assertTrue(handoff.manifest.has_installed_fingerprint)
        self.assertEqual(fingerprint_save(installed).sha256, handoff.manifest.installed_sha256)

        untouched = verify_tactical_result(self.campaign, save_path=installed, code_x_directory=self.codex)
        self.assertFalse(untouched.ok)
        self.assertIn("Installed acceptance save was not rewritten by GoH", untouched.errors)
        self.assertIn("GoH has not recorded completion of this battle", untouched.errors)
        self.assertIs(False, untouched.installed_save_rewritten)

        archive = CampaignSaveArchive()
        contents = archive.read(installed)
        updated = contents.status.replace("{playedGames 0}", "{playedGames 1}")
        archive.write(installed, status=updated, campaign_scn=contents.campaign_scn)
        rewritten = verify_tactical_result(self.campaign, save_path=installed, code_x_directory=self.codex)
        self.assertTrue(rewritten.ok)
        self.assertIs(True, rewritten.installed_save_rewritten)
        self.assertEqual(1, rewritten.played_games_after)

    def test_catalog_mismatch_still_fails(self) -> None:
        installed = self.profile / "gates_of_codex_acceptance.sav"
        prepare_tactical_handoff(
            self.campaign,
            game_directory=self.game,
            code_x_directory=self.codex,
            save_path=self.save,
            map_name="multi/2x2/live_test",
            profile_directory=self.profile,
            install_save_path=installed,
            backup_root=self.root / "backups",
        )
        archive = CampaignSaveArchive()
        contents = archive.read(installed)
        archive.write(
            installed,
            status=contents.status.replace("{playedGames 0}", "{playedGames 1}"),
            campaign_scn=contents.campaign_scn,
        )
        manifest_path = GatesOfCodeXService.manifest_path(installed)
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["catalog_signature"] = "not-the-real-signature"
        manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        report = verify_tactical_result(self.campaign, save_path=installed, code_x_directory=self.codex)
        self.assertFalse(report.ok)
        self.assertFalse(report.catalog_matches)

    def test_old_manifest_without_fingerprint_warns_but_still_checks_counters(self) -> None:
        installed = self.profile / "gates_of_codex_acceptance.sav"
        prepare_tactical_handoff(
            self.campaign,
            game_directory=self.game,
            code_x_directory=self.codex,
            save_path=self.save,
            map_name="multi/2x2/live_test",
            profile_directory=self.profile,
            install_save_path=installed,
            backup_root=self.root / "backups",
        )
        manifest_path = GatesOfCodeXService.manifest_path(installed)
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["installed_sha256"] = ""
        payload["installed_size"] = 0
        payload["installed_mtime_ns"] = 0
        manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        report = verify_tactical_result(self.campaign, save_path=installed, code_x_directory=self.codex)
        self.assertFalse(report.ok)
        self.assertTrue(any("fingerprint was not recorded" in value for value in report.warnings))
        self.assertIn("GoH has not recorded completion of this battle", report.errors)

    def test_apply_installed_fingerprint_round_trip(self) -> None:
        CampaignSaveArchive().write(
            self.save,
            status='{saveinfo\n\t{name "x"}\n\t{playedGames 0}\n\t{wonGames 0}\n}\n',
            campaign_scn=(
                "{campaign\n"
                '\t{Human "mp/nato/rifleman_nato" 0x1\n\t\t{Position 0 0}\n\t\t{Player 0}\n\t\t{MID 1}\n\t}\n'
                "\t{Inventory 0x1\n\t\t{box\n\t\t\t{clear}\n\t\t}\n\t}\n"
                '\t{CampaignSquads\n\t\t{"rifle(nato)" "stage_1" 0x1}\n\t}\n}\n'
            ),
        )
        manifest = BattleExportManifest(
            battle_id="b",
            campaign_path=str(self.campaign),
            save_path=str(self.save),
            catalog_signature="s",
            played_games=0,
            won_games=0,
        )
        apply_installed_fingerprint(manifest, self.save)
        self.assertTrue(manifest.has_installed_fingerprint)
        self.assertEqual(fingerprint_save(self.save).sha256, manifest.installed_sha256)


if __name__ == "__main__":
    unittest.main()
