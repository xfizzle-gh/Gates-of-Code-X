from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.bridge.archive import CampaignSaveArchive
from gates_of_codex.campaign_loop import continue_campaign
from gates_of_codex.codex.catalog import CodeXCatalogScanner
from gates_of_codex.europe import build_goe_europe_campaign
from gates_of_codex.front_attack import DEFAULT_VISIBLE_NAME, attack_front
from gates_of_codex.models import (
    Battalion,
    BattalionRosterEntry,
    CampaignState,
    Faction,
    FactionState,
    Province,
)
from gates_of_codex.service import GatesOfCodeXService
from gates_of_codex.state_io import load_campaign, save_campaign
from gates_of_codex.starter import set_player_faction


def _write_codex(root: Path) -> Path:
    codex = root / "codex"
    (codex / "resource/set/multiplayer/units/conquest/2022s").mkdir(parents=True)
    (codex / "resource/script/multiplayer/units/nato").mkdir(parents=True)
    for faction in ("nato", "ukr", "rusa", "prc"):
        breed = codex / f"resource/set/breed/mp/{faction}"
        breed.mkdir(parents=True)
        (breed / f"rifleman_{faction}.set").write_text(
            '{breed\n\t{inventory\n\t\t{item "rifle" filled}\n\t\t{item "rifle ammo" 30}\n\t}\n}\n',
            encoding="utf-8",
        )
    units = "".join(
        f'{{"rifle({faction})" {{member "rifleman_{faction}" 1}}}}\n'
        for faction in ("nato", "ukr", "rusa", "prc")
    )
    lua = "".join(
        f'{{priority=1, type={{"Infantry","Squad"}}, unit="rifle({faction})"}},\n'
        for faction in ("nato", "ukr", "rusa", "prc")
    )
    (codex / "resource/set/multiplayer/units/conquest/2022s/units.set").write_text(units, encoding="utf-8")
    (codex / "resource/script/multiplayer/units/nato/2022s.nato.lua").write_text(lua, encoding="utf-8")
    (codex / "mod.info").write_text('{name "Code:X"}\n', encoding="utf-8")
    return codex


def _two_province_campaign(root: Path, codex: Path) -> tuple[Path, Path]:
    catalog = CodeXCatalogScanner().scan(codex)
    campaign = root / "campaign.json"
    save_path = root / "gatesofcodex.sav"
    state = CampaignState(
        campaign_name="Loop",
        selected_faction=Faction.NATO,
        current_faction=Faction.NATO,
        code_x_directory=str(codex),
        catalog_signature=catalog.signature,
        profile_directory=str(root),
        map_metadata={"install_directory": str(root)},
        factions={
            "nato": FactionState(Faction.NATO, is_human_controlled=True),
            "ukr": FactionState(Faction.UKRAINE),
            "rusa": FactionState(Faction.RUSSIA),
            "prc": FactionState(Faction.PRC),
        },
        provinces={
            "a": Province("a", "A", Faction.NATO, ["b", "c"], metadata={"tactical_map": "multi/dcg_[cwa71]_fulda"}),
            "b": Province("b", "B", Faction.RUSSIA, ["a", "c"], metadata={"tactical_map": "multi/dcg_[cwa71]_fulda"}),
            "c": Province("c", "C", Faction.RUSSIA, ["a", "b"], metadata={"tactical_map": "multi/dcg_[cwa71]_fulda"}),
        },
        battalions={
            "nato-1": Battalion(
                "nato-1",
                Faction.NATO,
                "a",
                roster=[BattalionRosterEntry("rifle(nato)", 2, category="infantry")],
            ),
            "rusa-1": Battalion(
                "rusa-1",
                Faction.RUSSIA,
                "b",
                roster=[BattalionRosterEntry("rifle(rusa)", 1, category="infantry")],
            ),
            "rusa-2": Battalion(
                "rusa-2",
                Faction.RUSSIA,
                "c",
                roster=[BattalionRosterEntry("rifle(rusa)", 1, category="infantry")],
            ),
        },
    )
    save_campaign(state, campaign)
    return campaign, save_path


class CampaignLoopTests(unittest.TestCase):
    def test_continue_waits_until_goh_rewrites_the_save(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            codex = _write_codex(root)
            campaign, save_path = _two_province_campaign(root, codex)
            first = attack_front(campaign, code_x_directory=codex, save_path=save_path)
            self.assertTrue(save_path.is_file())
            waiting = continue_campaign(
                campaign,
                save_path=save_path,
                code_x_directory=codex,
            )
            self.assertEqual("waiting_for_conquest", waiting["status"])
            self.assertEqual(first["pending_battle"], waiting["pending_battle"])
            state = load_campaign(campaign)
            self.assertIsNotNone(state.pending_battle)
            before = save_path.read_bytes()
            again = continue_campaign(campaign, save_path=save_path, code_x_directory=codex)
            self.assertEqual("waiting_for_conquest", again["status"])
            self.assertEqual(before, save_path.read_bytes())

    def test_continue_imports_completed_save_then_exports_next_fight(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            codex = _write_codex(root)
            campaign, save_path = _two_province_campaign(root, codex)
            attack_front(campaign, code_x_directory=codex, save_path=save_path)
            first_id = load_campaign(campaign).pending_battle.battle_id
            contents = CampaignSaveArchive().read(save_path)
            rewritten = root / f"gatesofcodex_battle_{first_id}.sav"
            CampaignSaveArchive().write(
                rewritten,
                status=contents.status.replace("{playedGames 0}", "{playedGames 1}").replace(
                    "{wonGames 0}", "{wonGames 1}"
                ),
                campaign_scn=contents.campaign_scn,
            )
            payload = continue_campaign(
                campaign,
                save_path=save_path,
                code_x_directory=codex,
            )
            imported = next(step for step in payload["steps"] if step["op"] == "import")
            self.assertTrue(imported["player_won"])
            self.assertEqual("nato", imported["winner"])
            self.assertTrue(any(step.get("op") == "advance" for step in payload["steps"]))
            self.assertIn(payload["status"], {"waiting_for_conquest", "ready"})
            state = load_campaign(campaign)
            if state.pending_battle is not None:
                self.assertNotEqual(first_id, state.pending_battle.battle_id)
                self.assertTrue(Path(payload["save"]).is_file())

    def test_simulate_runs_multiple_europe_player_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            campaign = Path(raw) / "europe.json"
            state = build_goe_europe_campaign()
            set_player_faction(state, Faction.NATO)
            save_campaign(state, campaign)
            from gates_of_codex.campaign_loop import overmap_campaign

            before = load_campaign(campaign)
            owners_before = {
                faction: sum(1 for province in before.provinces.values() if province.owner.value == faction)
                for faction in ("nato", "ukr", "rusa", "prc")
            }
            payload = overmap_campaign(campaign, turns=3, seed=7)
            self.assertEqual(3, payload["turns_run"])
            after = load_campaign(campaign)
            self.assertGreaterEqual(after.turn_number, 2)
            owners_after = {
                faction: sum(1 for province in after.provinces.values() if province.owner.value == faction)
                for faction in ("nato", "ukr", "rusa", "prc")
            }
            self.assertTrue(
                owners_before != owners_after or after.turn_number > before.turn_number
            )

    def test_economy_skips_blank_and_crew_stubs(self) -> None:
        from gates_of_codex.codex.catalog import CodeXCatalog, UnitDefinition
        from gates_of_codex.economy import build_unit_economy, is_campaign_unit

        catalog = CodeXCatalog(
            units={
                "squad_inf2_rifle(nato)": UnitDefinition(
                    name="squad_inf2_rifle(nato)",
                    side="nato",
                    category="infantry",
                    members={"rifleman": 8},
                ),
                "conquest_blank": UnitDefinition(
                    name="conquest_blank",
                    side="prc",
                    category="infantry",
                    members={"blank": 1},
                ),
                "rus_vehicleman": UnitDefinition(
                    name="rus_vehicleman",
                    side="rusa",
                    category="infantry",
                    members={"rus_vehicleman": 3},
                ),
            },
            signature="junk",
        )
        economy = build_unit_economy(catalog)
        self.assertIn("squad_inf2_rifle(nato)", economy)
        self.assertNotIn("conquest_blank", economy)
        self.assertNotIn("rus_vehicleman", economy)
        self.assertFalse(is_campaign_unit(catalog.units["conquest_blank"]))

    def test_play_parser_defaults_to_europe(self) -> None:
        from gates_of_codex.cli import build_parser

        args = build_parser().parse_args(["play"])
        self.assertEqual("play", args.command)
        self.assertEqual("live/europe.json", args.campaign)
        self.assertFalse(args.no_launch)

    def test_next_turn_parser_defaults_to_europe(self) -> None:
        from gates_of_codex.cli import build_parser

        args = build_parser().parse_args(["next-turn"])
        self.assertEqual("next-turn", args.command)
        self.assertEqual("live/europe.json", args.campaign)


if __name__ == "__main__":
    unittest.main()
