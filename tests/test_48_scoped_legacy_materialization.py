from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.bridge.archive import CampaignSaveArchive
from gates_of_codex.bridge.scn import CampaignScnParser
from gates_of_codex.models import (
    Battalion,
    BattalionRosterEntry,
    CampaignState,
    Faction,
    FactionState,
    Province,
)
from gates_of_codex.neutral_garrison import (
    garrison_battalion_id,
    maybe_attach_neutral_garrison,
    select_neutral_garrison,
)
from gates_of_codex.service import GatesOfCodeXService
from gates_of_codex.state_io import save_campaign


JERUSALEM = "e3_2711"
WEST81_LEGACY_IDS = ("ural375", "bmp-1", "t55a", "122mm_d-30")


class ScopedLegacyMaterializationTests(unittest.TestCase):
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
                for name in WEST81_LEGACY_IDS
            ),
            encoding="utf-8",
        )
        west_breed = west / "resource/set/breed/mp/sov"
        west_breed.mkdir(parents=True)
        west_breed.joinpath("sov_driver.set").write_text(
            '{breed\n\t{inventory\n\t\t{item "west81_marker" filled}\n\t}\n}\n',
            encoding="utf-8",
        )

        codex_conquest = codex / "resource/set/multiplayer/units/conquest"
        codex_conquest.mkdir(parents=True)
        codex_conquest.joinpath("units_rusa.set").write_text(
            "".join(
                [
                    '{"rus90_inf_rifle"\n\t("squad" side(rusa) member(rusa_rifleman:2))\n}\n',
                    '{"rus90_inf_at"\n\t("squad" side(rusa) member(rusa_rifleman:1))\n}\n',
                    '{"rus90_inf_mg"\n\t("squad" side(rusa) member(rusa_rifleman:1))\n}\n',
                    '{"122mm_d-30"\n\t("vehicle" side(rusa) crew(rusa_d30_driver:1))\n}\n',
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
            '{breed\n\t{inventory\n\t\t{item "rusa_rifle" filled}\n\t}\n}\n',
            encoding="utf-8",
        )
        rusa_breed.joinpath("rusa_d30_driver.set").write_text(
            '{breed\n\t{inventory\n\t\t{item "modern_d30_marker" filled}\n\t}\n}\n',
            encoding="utf-8",
        )
        nato_breed.joinpath("nato_rifleman.set").write_text(
            '{breed\n\t{inventory\n\t\t{item "nato_rifle" filled}\n\t}\n}\n',
            encoding="utf-8",
        )

        # Same-name later breed override: the authenticated garrison must not
        # consume this file even though ordinary CampaignScnBuilder resolution
        # would search the stack in reverse order.
        gates_sov_breed = gates / "resource/set/breed/mp/sov"
        gates_sov_breed.mkdir(parents=True)
        gates_sov_breed.joinpath("sov_driver.set").write_text(
            '{breed\n\t{inventory\n\t\t{item "later_override_marker" filled}\n\t}\n}\n',
            encoding="utf-8",
        )

        for layer, label in (
            (west, "West81"),
            (codex, "Code:X"),
            (ai, "Code:X AI Overhaul"),
            (gates, "Gates of CodeX"),
        ):
            layer.joinpath("mod.info").write_text(
                f'{{mod {{name "{label}"}}}}\n',
                encoding="utf-8",
            )

        return [game, west, codex, ai, gates], codex

    @staticmethod
    def _home_region_seed() -> str:
        for index in range(4096):
            seed = f"scoped-legacy-{index:04d}"
            selection = select_neutral_garrison(
                JERUSALEM,
                campaign_seed=seed,
            )
            if (
                selection.region == "middle_east"
                and selection.tier == "capital"
                and not selection.variation_applied
            ):
                return seed
        raise AssertionError("could not find deterministic Jerusalem home-region seed")

    def _state(self, stack: list[Path], codex: Path) -> CampaignState:
        return CampaignState(
            campaign_name="Issue 48 participant-scoped legacy regression",
            selected_faction=Faction.NATO,
            current_faction=Faction.NATO,
            game_directory=str(stack[0]),
            code_x_directory=str(codex),
            map_metadata={
                "neutral_garrison_seed": self._home_region_seed(),
                "resource_stack": [str(path) for path in stack],
            },
            factions={
                "nato": FactionState(Faction.NATO, resources=500, researched_keys=[]),
                "rusa": FactionState(Faction.RUSSIA, resources=500, researched_keys=[]),
                "neutral": FactionState(Faction.NEUTRAL, resources=0),
            },
            provinces={
                "home": Province("home", "Home", Faction.NATO, [JERUSALEM]),
                JERUSALEM: Province(
                    JERUSALEM,
                    "Jerusalem",
                    Faction.NEUTRAL,
                    ["home"],
                ),
            },
            battalions={
                "atk": Battalion(
                    "atk",
                    Faction.NATO,
                    "home",
                    roster=[
                        BattalionRosterEntry("rifle(nato)", 1, category="infantry"),
                        # Same ID as an authorized West81 garrison row, but this
                        # sovereign participant must retain the ordinary RUSA
                        # definition from the four-side catalog.
                        BattalionRosterEntry("122mm_d-30", 1, category="artillery"),
                    ],
                )
            },
        )

    @staticmethod
    def _squad_object_ids(text: str, *, unit_name: str, stage: str) -> list[str]:
        matches = [
            row
            for row in CampaignScnParser().parse_squads(text)
            if row.unit_name == unit_name and row.stage == stage
        ]
        if len(matches) != 1:
            raise AssertionError(
                f"expected one {unit_name}/{stage} squad row, got {len(matches)}"
            )
        return matches[0].object_ids

    def test_same_id_collision_and_same_name_breed_override_remain_participant_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stack, codex = self._stack(root)
            state = self._state(stack, codex)
            pending = maybe_attach_neutral_garrison(
                state,
                JERUSALEM,
                attacker=state.battalions["atk"],
            )
            self.assertIsNotNone(pending)
            garrison = state.battalions[garrison_battalion_id(JERUSALEM)]
            selected_names = {entry.unit_name for entry in garrison.roster}
            self.assertIn("122mm_d-30", selected_names)
            self.assertIn("ural375", selected_names)

            campaign = root / "jerusalem.json"
            save_campaign(state, campaign)
            manifest = GatesOfCodeXService().export_battle(
                campaign,
                code_x_directory=codex,
                save_path=root / "jerusalem.sav",
                map_name="multi/2x2/live_test",
                resource_stack=stack,
                mods=[],
            )
            contents = CampaignSaveArchive().read(manifest.save_path)
            scn = contents.campaign_scn

            attacker_ids = self._squad_object_ids(
                scn,
                unit_name="122mm_d-30",
                stage="stage_1",
            )
            garrison_ids = self._squad_object_ids(
                scn,
                unit_name="122mm_d-30",
                stage="stage_2",
            )

            self.assertTrue(any(
                f'Human "mp/rusa/rusa_d30_driver" {object_id}' in scn
                for object_id in attacker_ids
            ))
            self.assertFalse(any(
                f'Human "mp/sov/sov_driver" {object_id}' in scn
                for object_id in attacker_ids
            ))
            self.assertTrue(any(
                f'Human "mp/sov/sov_driver" {object_id}' in scn
                for object_id in garrison_ids
            ))

            # The legacy crew closure is bound to the West81 layer. A later
            # same-name sov_driver file cannot replace its inventory payload.
            self.assertIn('item "west81_marker"', scn)
            self.assertNotIn('item "later_override_marker"', scn)
            self.assertIn('item "modern_d30_marker"', scn)


if __name__ == "__main__":
    unittest.main()
