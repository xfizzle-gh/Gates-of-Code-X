from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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
from gates_of_codex.neutral_garrison import garrison_battalion_id, maybe_attach_neutral_garrison
from gates_of_codex.service import GatesOfCodeXService, _authenticated_neutral_garrison_profile
from gates_of_codex.state_io import save_campaign


ALEXANDRIA = "e3_1483"
LEGACY_IDS = ("ural375", "btr-60pb", "bmp-1", "t55a")


class RecordingScanner(CodeXCatalogScanner):
    def __init__(self) -> None:
        super().__init__()
        self.legacy_flags: list[bool] = []

    def scan_stack(self, resource_stack, *, include_legacy_sources: bool = False):
        self.legacy_flags.append(include_legacy_sources)
        return super().scan_stack(
            resource_stack,
            include_legacy_sources=include_legacy_sources,
        )


class West81LegacyGarrisonExportTests(unittest.TestCase):
    def _stack(self, root: Path) -> tuple[list[Path], Path]:
        game = root / "game"
        west = root / "2897299509"
        codex = root / "3261086933"
        ai = root / "3636883799"
        gates = root / "3696721120"
        for layer in (game, west, codex, ai, gates):
            (layer / "resource").mkdir(parents=True)

        west_conquest = west / "resource/set/multiplayer/units/conquest"
        west_conquest.mkdir(parents=True)
        west_conquest.joinpath("units_sov_era1960.set").write_text(
            "".join(
                f'{{\"{name}\"\n\t(\"vehicle\" side(sov) crew(sov_driver:1))\n}}\n'
                for name in LEGACY_IDS
            ),
            encoding="utf-8",
        )
        west_breed = west / "resource/set/breed/mp/sov"
        west_breed.mkdir(parents=True)
        west_breed.joinpath("sov_driver.set").write_text(
            '{breed\n\t{inventory\n\t\t{item "rifle" filled}\n\t}\n}\n',
            encoding="utf-8",
        )

        codex_conquest = codex / "resource/set/multiplayer/units/conquest"
        codex_conquest.mkdir(parents=True)
        codex_conquest.joinpath("units_rusa.set").write_text(
            "".join(
                [
                    '{"wgn_22_2"\n\t("squad" side(rusa) member(rusa_rifleman:2))\n}\n',
                    '{"rus90_inf_rifle"\n\t("squad" side(rusa) member(rusa_rifleman:2))\n}\n',
                    '{"122mm_d-30"\n\t("vehicle" side(rusa) crew(rusa_rifleman:1))\n}\n',
                    '{"rifle(nato)"\n\t("squad" side(nato) member(nato_rifleman:1))\n}\n',
                ]
            ),
            encoding="utf-8",
        )
        rusa_breed = codex / "resource/set/breed/mp/rusa"
        nato_breed = codex / "resource/set/breed/mp/nato"
        rusa_breed.mkdir(parents=True)
        nato_breed.mkdir(parents=True)
        rusa_breed.joinpath("rusa_rifleman.set").write_text(
            '{breed\n\t{inventory\n\t\t{item "rifle" filled}\n\t}\n}\n',
            encoding="utf-8",
        )
        nato_breed.joinpath("nato_rifleman.set").write_text(
            '{breed\n\t{inventory\n\t\t{item "rifle" filled}\n\t}\n}\n',
            encoding="utf-8",
        )

        for layer, label in (
            (west, "West81"),
            (codex, "Code:X"),
            (ai, "Code:X AI Overhaul"),
            (gates, "Gates of CodeX"),
        ):
            layer.joinpath("mod.info").write_text(f'{{mod {{name "{label}"}}}}\n', encoding="utf-8")

        return [game, west, codex, ai, gates], codex

    def _garrison_state(self, stack: list[Path], codex: Path) -> CampaignState:
        return CampaignState(
            campaign_name="Issue 48 West81 native-shape regression",
            selected_faction=Faction.NATO,
            current_faction=Faction.NATO,
            game_directory=str(stack[0]),
            code_x_directory=str(codex),
            map_metadata={
                "neutral_garrison_seed": "west81-live-shape",
                "resource_stack": [str(path) for path in stack],
            },
            factions={
                "nato": FactionState(Faction.NATO, resources=500, researched_keys=[]),
                "rusa": FactionState(Faction.RUSSIA, resources=500, researched_keys=[]),
                "neutral": FactionState(Faction.NEUTRAL, resources=0),
            },
            provinces={
                "home": Province("home", "Home", Faction.NATO, [ALEXANDRIA]),
                ALEXANDRIA: Province(
                    ALEXANDRIA,
                    "Alexandria",
                    Faction.NEUTRAL,
                    ["home"],
                    metadata={"source_id": 2662},
                ),
            },
            battalions={
                "atk": Battalion(
                    "atk",
                    Faction.NATO,
                    "home",
                    roster=[BattalionRosterEntry("rifle(nato)", 1, category="infantry")],
                )
            },
        )

    def _export_garrison(
        self,
        root: Path,
        *,
        graph_native: bool,
    ) -> tuple[RecordingScanner, object, str]:
        stack, codex = self._stack(root)
        state = self._garrison_state(stack, codex)
        pending = maybe_attach_neutral_garrison(
            state,
            ALEXANDRIA,
            attacker=state.battalions["atk"],
            encounter_node_id="node:e3_1483" if graph_native else "",
            attacker_formation_id="sf-nato" if graph_native else "",
        )
        self.assertIsNotNone(pending)
        self.assertEqual("rusa", pending.tactical_defender_side)
        if graph_native:
            self.assertEqual("neutral_garrison", pending.encounter_kind)
            self.assertEqual("node:e3_1483", pending.encounter_node_id)
        else:
            # Legacy province adjacency deliberately has no operational marker.
            self.assertEqual("", pending.encounter_kind)
            self.assertEqual("", pending.encounter_node_id)

        garrison = state.battalions[garrison_battalion_id(ALEXANDRIA)]
        selected_names = {entry.unit_name for entry in garrison.roster}
        self.assertIn("ural375", selected_names)
        self.assertIn("btr-60pb", selected_names)

        campaign = root / ("graph.json" if graph_native else "adjacency.json")
        save = root / ("graph.sav" if graph_native else "adjacency.sav")
        save_campaign(state, campaign)

        service = GatesOfCodeXService()
        scanner = RecordingScanner()
        service.scanner = scanner
        manifest = service.export_battle(
            campaign,
            code_x_directory=codex,
            save_path=save,
            map_name="multi/2x2/live_test",
            resource_stack=stack,
            mods=[],
        )
        contents = CampaignSaveArchive().read(manifest.save_path)
        return scanner, manifest, contents.status + "\n" + contents.campaign_scn

    def test_legacy_source_sides_are_explicit_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stack, _ = self._stack(Path(tmp))
            scanner = CodeXCatalogScanner()
            normal = scanner.scan_stack(stack)
            legacy = scanner.scan_stack(stack, include_legacy_sources=True)

            for name in LEGACY_IDS:
                with self.subTest(name=name):
                    self.assertNotIn(name, normal.units)
                    self.assertIn(name, legacy.units)
                    self.assertEqual("sov", legacy.units[name].side)
                    self.assertEqual([name], legacy.units[name].vehicles)
                    self.assertEqual({"sov_driver": 1}, legacy.units[name].members)

            self.assertIn("122mm_d-30", normal.units)
            self.assertEqual("rusa", normal.units["122mm_d-30"].side)

    def test_legacy_adjacency_garrison_authenticates_without_encounter_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scanner, manifest, text = self._export_garrison(Path(tmp), graph_native=False)
            self.assertEqual([True], scanner.legacy_flags)
            self.assertIn("{enemyArmy rusa}", text)
            self.assertNotIn("{enemyArmy neutral}", text)
            self.assertIn('Entity "ural375"', text)
            self.assertIn('Entity "btr-60pb"', text)
            self.assertIsNotNone(manifest.neutral_garrison)
            self.assertEqual("neutral", manifest.neutral_garrison["strategic_defender_faction"])
            self.assertEqual("rusa", manifest.neutral_garrison["tactical_defender_side"])

    def test_graph_native_garrison_uses_same_authenticated_export_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scanner, manifest, text = self._export_garrison(Path(tmp), graph_native=True)
            self.assertEqual([True], scanner.legacy_flags)
            self.assertIn('Entity "ural375"', text)
            self.assertIsNotNone(manifest.neutral_garrison)
            self.assertEqual("rusa", manifest.neutral_garrison["tactical_defender_side"])

    def test_normal_four_side_export_never_enables_legacy_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stack, codex = self._stack(root)
            state = self._garrison_state(stack, codex)
            state.provinces["enemy"] = Province("enemy", "Enemy", Faction.RUSSIA, ["home"])
            state.provinces["home"].neighbors.append("enemy")
            state.battalions["def"] = Battalion(
                "def",
                Faction.RUSSIA,
                "enemy",
                roster=[BattalionRosterEntry("rus90_inf_rifle", 1, category="infantry")],
            )
            state.pending_battle = PendingBattle(
                battle_id="ordinary-four-side",
                origin_province_id="home",
                target_province_id="enemy",
                attacker_faction=Faction.NATO,
                defender_faction=Faction.RUSSIA,
                attacking_participants=[BattleParticipant("atk", Faction.NATO, "stage_1", True)],
                defending_participants=[BattleParticipant("def", Faction.RUSSIA, "stage_2", True)],
                player_faction=Faction.NATO,
                player_is_attacker=True,
            )
            campaign = root / "ordinary.json"
            save_campaign(state, campaign)
            service = GatesOfCodeXService()
            scanner = RecordingScanner()
            service.scanner = scanner
            manifest = service.export_battle(
                campaign,
                code_x_directory=codex,
                save_path=root / "ordinary.sav",
                map_name="multi/2x2/live_test",
                resource_stack=stack,
                mods=[],
            )
            self.assertEqual([False], scanner.legacy_flags)
            self.assertIsNone(manifest.neutral_garrison)

    def test_spoofed_encounter_marker_cannot_unlock_legacy_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stack, codex = self._stack(root)
            state = self._garrison_state(stack, codex)
            pending = maybe_attach_neutral_garrison(
                state,
                ALEXANDRIA,
                attacker=state.battalions["atk"],
            )
            self.assertIsNotNone(pending)
            self.assertIsNotNone(_authenticated_neutral_garrison_profile(state))

            # The marker alone is not authority. Replace the authenticated
            # garrison participant with a non-garrison identity in-memory and
            # prove the admission helper refuses it before any legacy scan.
            pending.encounter_kind = "neutral_garrison"
            pending.defending_participants = [
                BattleParticipant("spoof-neutral", Faction.NEUTRAL, "stage_2", True)
            ]
            profile = _authenticated_neutral_garrison_profile(state)
            self.assertIsNone(profile)

            scanner = RecordingScanner()
            catalog = scanner.scan_stack(
                stack,
                include_legacy_sources=profile is not None,
            )
            self.assertEqual([False], scanner.legacy_flags)
            for name in LEGACY_IDS:
                with self.subTest(name=name):
                    self.assertNotIn(name, catalog.units)


if __name__ == "__main__":
    unittest.main()
