from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.bridge.archive import CampaignSaveArchive
from gates_of_codex.bridge.scn import CampaignScnBuilder, parse_breed_inventory
from gates_of_codex.bridge.status import BattleStatusOptions, StatusBuilder
from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.codex.catalog import CodeXCatalogScanner
from gates_of_codex.europe import CODEX_MAPS, build_goe_europe_campaign
from gates_of_codex.front_attack import DEFAULT_VISIBLE_NAME, attack_front, pick_front_option
from gates_of_codex.play_context import list_front_options
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
from gates_of_codex.service import GatesOfCodeXService, resolve_completed_save
from gates_of_codex.state_io import save_campaign


class LiveBridgeTests(unittest.TestCase):
    def test_fallback_status_uses_europe_three_point_graph(self) -> None:
        pending = PendingBattle(
            battle_id="goc-1-live",
            origin_province_id="a",
            target_province_id="b",
            attacker_faction=Faction.NATO,
            defender_faction=Faction.RUSSIA,
            attacking_participants=[BattleParticipant("nato-1", Faction.NATO, "stage_1", True)],
            defending_participants=[BattleParticipant("rusa-1", Faction.RUSSIA, "stage_2", True)],
            player_faction=Faction.NATO,
            player_is_attacker=True,
        )
        text = StatusBuilder().build(
            pending,
            BattleStatusOptions("multi/dcg_[cwa71]_fulda", campaign_name="GatesOfCodeX"),
        )
        self.assertIn("{version 9}", text)
        self.assertIn("{region europe}", text)
        self.assertIn("{selectedMapPoint point_1_1}", text)
        self.assertIn("{duration 3}", text)
        self.assertIn("{resources 2}", text)
        self.assertIn("{manualControlMode 3}", text)
        self.assertIn("{fogofwar fog_off}", text)
        self.assertIn('"mod_2897299509:0"', text)
        self.assertIn('"mod_3261086933:0"', text)
        self.assertIn('"mod_3636883799:0"', text)
        self.assertIn("{name hq_a}", text)
        self.assertIn("{name point_1_1}", text)
        self.assertIn("{name hq_b}", text)
        self.assertIn("multi/dcg_[cwa71]_fulda:campaign_capture_the_flag:4x4", text)

    def test_parse_breed_inventory_includes_armor(self) -> None:
        items = parse_breed_inventory(
            '{breed\n{armors\n{head ihps_new_1}\n{body "msv_2"}\n}\n'
            '{inventory\n{item "m4a1_v4b" filled}\n{item "m16a2 ammo" 180}\n}\n}\n'
        )
        names = [item.name for item in items]
        self.assertIn("m4a1_v4b", names)
        self.assertIn("m16a2", names)
        self.assertIn("ihps_new_1", names)
        self.assertIn("msv_2", names)
        self.assertEqual("head", next(item for item in items if item.name == "ihps_new_1").user)

    def test_europe_provinces_carry_codex_maps(self) -> None:
        state = build_goe_europe_campaign()
        maps = {province.metadata.get("tactical_map") for province in state.provinces.values()}
        self.assertTrue(maps.issubset(set(CODEX_MAPS)))
        self.assertEqual("europe", next(iter(state.provinces.values())).map_region)
        self.assertIn("tactical_map", state.provinces["Warszawa"].metadata)
        options = list_front_options(state)
        self.assertTrue(options)
        if any(row["kind"] == "battle" for row in options):
            option = pick_front_option(state)
            self.assertEqual("battle", option["kind"])

    def test_attack_without_contact_stages_nato_russia_border(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            campaign = Path(raw) / "europe.json"
            save_campaign(build_goe_europe_campaign(), campaign)
            payload = attack_front(campaign, export=False)
        self.assertTrue(payload.get("moved") or payload.get("pending_created"))

    def test_resolve_completed_save_prefers_rewritten_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            original = folder / "gatesofcodex.sav"
            rewritten = folder / "gatesofcodex_battle_goc-1-deadbeef.sav"
            scn = (
                "{campaign\n"
                '\t{Human "mp/nato/rifleman" 0xc000\n\t}\n'
                "\t{Inventory 0xc000\n\t\t{box\n\t\t\t{clear}\n\t\t}\n\t}\n"
                '\t{CampaignSquads\n\t\t{"rifle(nato)" "stage_1" 0xc000}\n\t}\n}\n'
            )
            archive = CampaignSaveArchive()
            archive.write(
                original,
                status="{saveinfo\n\t{version 9}\n\t{playedGames 0}\n\t{wonGames 0}\n}\n",
                campaign_scn=scn,
            )
            archive.write(
                rewritten,
                status="{saveinfo\n\t{version 9}\n\t{playedGames 1}\n\t{wonGames 0}\n}\n",
                campaign_scn=scn,
            )
            found = resolve_completed_save(
                original,
                previous_status=StatusBuilder().parse_result("{saveinfo\n\t{playedGames 0}\n\t{wonGames 0}\n}\n"),
                visible_campaign_name="GatesOfCodeX",
            )
            self.assertEqual(rewritten.resolve(), found.resolve())


class FrontAttackExportTests(unittest.TestCase):
    def test_export_uses_gatesofcodex_name_and_c000_ids(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            codex = root / "codex"
            (codex / "resource/set/multiplayer/units/conquest/2022s").mkdir(parents=True)
            (codex / "resource/script/multiplayer/units/nato").mkdir(parents=True)
            for faction in ("nato", "ukr", "rusa", "prc"):
                breed = codex / f"resource/set/breed/mp/{faction}"
                breed.mkdir(parents=True)
                (breed / f"rifleman_{faction}.set").write_text(
                    '{breed\n\t{inventory\n\t\t{item "rifle" filled}\n\t\t{item "rifle ammo" 30}\n\t}\n'
                    "\t{armors\n\t\t{head helmet}\n\t}\n}\n",
                    encoding="utf-8",
                )
            units = "".join(f'{{"rifle({faction})" {{member "rifleman_{faction}" 1}}}}\n' for faction in ("nato", "ukr", "rusa", "prc"))
            lua = "".join(f'{{priority=1, type={{"Infantry","Squad"}}, unit="rifle({faction})"}},\n' for faction in ("nato", "ukr", "rusa", "prc"))
            (codex / "resource/set/multiplayer/units/conquest/2022s/units.set").write_text(units, encoding="utf-8")
            (codex / "resource/script/multiplayer/units/nato/2022s.nato.lua").write_text(lua, encoding="utf-8")
            (codex / "mod.info").write_text('{name "Code:X"}\n', encoding="utf-8")
            catalog = CodeXCatalogScanner().scan(codex)
            campaign = root / "campaign.json"
            save_path = root / "gatesofcodex.sav"
            state = CampaignState(
                campaign_name="Europe",
                selected_faction=Faction.NATO,
                current_faction=Faction.NATO,
                code_x_directory=str(codex),
                catalog_signature=catalog.signature,
                factions={
                    "nato": FactionState(Faction.NATO, is_human_controlled=True),
                    "rusa": FactionState(Faction.RUSSIA),
                },
                provinces={
                    "a": Province("a", "A", Faction.NATO, ["b"], metadata={"tactical_map": "multi/dcg_[cwa71]_fulda"}),
                    "b": Province("b", "B", Faction.RUSSIA, ["a"], metadata={"tactical_map": "multi/dcg_[cwa71]_fulda"}),
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
            )
            CampaignEngine(state).move_or_attack("nato-1", "b")
            save_campaign(state, campaign)
            manifest = GatesOfCodeXService().export_battle(
                campaign,
                code_x_directory=codex,
                save_path=save_path,
                map_name="",
                allow_overwrite=True,
                campaign_name=DEFAULT_VISIBLE_NAME,
            )
            contents = CampaignSaveArchive().read(save_path)
            self.assertEqual(str(save_path.resolve()), manifest.save_path)
            self.assertIn("{name \"GatesOfCodeX\"}", contents.status)
            self.assertIn("{region europe}", contents.status)
            self.assertIn("0xc000", contents.campaign_scn)
            self.assertIn("{NameId", contents.campaign_scn)
            self.assertIn("{clear}", contents.campaign_scn)
            self.assertIn('{item "rifle" filled', contents.campaign_scn)
            self.assertIn('{user "head"}', contents.campaign_scn)
            self.assertNotIn("{Position 0 0}", contents.campaign_scn)
            self.assertIn("rifle(nato)", contents.campaign_scn)
            self.assertNotIn("rifle(rusa)", contents.campaign_scn)
            self.assertNotIn("/rusa/", contents.campaign_scn)
            self.assertEqual("multi/dcg_[cwa71]_fulda", manifest.map_name)
            self.assertEqual(contents.campaign_scn.count("{Player 0}"), contents.campaign_scn.count("{Human "))


if __name__ == "__main__":
    unittest.main()
