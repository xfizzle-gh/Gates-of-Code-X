from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from gates_of_codex.bridge.archive import CampaignSaveArchive
from gates_of_codex.bridge.scn import CampaignScnBuilder, CampaignScnParser
from gates_of_codex.bridge.status import BattleStatusOptions, StatusBuilder, StatusResult
from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.cli import build_parser
from gates_of_codex.codex.catalog import CodeXCatalogScanner
from gates_of_codex.models import Faction
from gates_of_codex.scenario import load_bundled_scenario
from gates_of_codex.starter import populate_starter_rosters
from gates_of_codex.state_io import load_campaign, save_campaign


NATO_BATTALION = "formation-01"
RUSSIAN_BATTALION = "formation-08"


class GatesOfCodeXTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.codex = self.root / "codex"
        self._write_codex_fixture()

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
        for faction in ("nato", "ukr", "rusa", "prc"):
            units.append(
                f'{{"rifle({faction})" {{member "rifleman_{faction}" 4}}}}\n'
                f'{{"tank({faction})" {{vehicle "tank_{faction}"}}}}\n'
            )
        (self.codex / "resource/set/multiplayer/units/conquest/2022s/units.set").write_text("".join(units), encoding="utf-8")
        lua = []
        for faction in ("nato", "ukr", "rusa", "prc"):
            lua.append(f'{{priority=1, type={{"Infantry","Squad"}}, unit="rifle({faction})"}},\n')
            lua.append(f'{{priority=1, type={{"Tank"}}, unit="tank({faction})"}},\n')
        (self.codex / "resource/script/multiplayer/units/nato/2022s.nato.lua").write_text("".join(lua), encoding="utf-8")
        (self.codex / "mod.info").write_text('{name "Code:X"}\n', encoding="utf-8")

    @staticmethod
    def _prepare_nato_russia_battle(state) -> None:
        engine = CampaignEngine(state)
        engine.move_or_attack(NATO_BATTALION, "Westfalen")
        state.battalions[NATO_BATTALION].movement_remaining = 1
        state.battalions[RUSSIAN_BATTALION].province_id = "Hessen"
        state.provinces["Hessen"].owner = Faction.RUSSIA
        engine.move_or_attack(NATO_BATTALION, "Hessen")

    def test_bundled_scenario_validates(self) -> None:
        state = load_bundled_scenario()
        state.validate()
        self.assertEqual(set(state.factions), {"nato", "ukr", "rusa", "prc"})
        self.assertEqual(517, len(state.provinces))
        self.assertGreaterEqual(len(state.formations), 14)

    def test_campaign_round_trip(self) -> None:
        state = load_bundled_scenario()
        path = self.root / "campaign.json"
        save_campaign(state, path)
        loaded = load_campaign(path)
        self.assertEqual(loaded.campaign_name, state.campaign_name)
        self.assertEqual(len(loaded.provinces), len(state.provinces))
        self.assertEqual(len(loaded.formations), len(state.formations))

    def test_neutral_capture(self) -> None:
        state = load_bundled_scenario()
        result = CampaignEngine(state).move_or_attack(NATO_BATTALION, "Westfalen")
        self.assertTrue(result.moved)
        self.assertEqual(state.provinces["Westfalen"].owner, Faction.NATO)

    def test_catalog_scans_all_factions(self) -> None:
        catalog = CodeXCatalogScanner().scan(self.codex)
        for faction in ("nato", "ukr", "rusa", "prc"):
            self.assertGreaterEqual(len(catalog.by_faction(faction)), 2)

    def test_starter_rosters_use_catalog(self) -> None:
        state = load_bundled_scenario()
        catalog = CodeXCatalogScanner().scan(self.codex)
        populate_starter_rosters(state, catalog)
        for battalion in state.battalions.values():
            self.assertNotIn("placeholder", battalion.roster[0].unit_name)

    def test_status_round_trip(self) -> None:
        state = load_bundled_scenario()
        self._prepare_nato_russia_battle(state)
        text = StatusBuilder().build(state.pending_battle, BattleStatusOptions("multi/4x4/test", played_games=4, won_games=2))
        result = StatusBuilder().parse_result(text)
        self.assertEqual(result, StatusResult(4, 2))

    def test_campaign_scn_graph(self) -> None:
        state = load_bundled_scenario()
        catalog = CodeXCatalogScanner().scan(self.codex)
        populate_starter_rosters(state, catalog)
        self._prepare_nato_russia_battle(state)
        text = CampaignScnBuilder(catalog, self.codex).build(state, state.pending_battle)
        self.assertTrue(CampaignScnParser().parse_squads(text))

    def test_archive_round_trip(self) -> None:
        save = self.root / "campaign.sav"
        CampaignSaveArchive().write(save, status="{status}\n", campaign_scn="{campaign}\n")
        with zipfile.ZipFile(save) as archive:
            self.assertEqual(set(archive.namelist()), {"status", "campaign.scn"})
        contents = CampaignSaveArchive().read(save)
        self.assertIn("status", contents.status)

    def test_cli_parser(self) -> None:
        args = build_parser().parse_args(["new", "--codex", str(self.codex), "--output", "test.json"])
        self.assertEqual(args.command, "new")


if __name__ == "__main__":
    unittest.main()
