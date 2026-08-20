"""#273 Phase A: morale-profile mapping and tactical-carrier survival."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.bridge.scoped_scn import ParticipantScopedCampaignScnBuilder
from gates_of_codex.bridge.scn import CampaignScnBuilder
from gates_of_codex.codex.catalog import CodeXCatalog, CodeXCatalogScanner, UnitDefinition
from gates_of_codex.models import (
    Battalion,
    BattalionRosterEntry,
    BattleParticipant,
    CampaignState,
    Faction,
    PendingBattle,
)
from gates_of_codex.tactical_morale_profile import (
    ALLOWED_MORALE_PROFILES,
    DEFAULT_MORALE_PROFILE,
    UnknownMoraleProfileError,
    morale_profile_from_unit_definition,
    morale_profile_tag,
    normalize_morale_profile,
    parse_morale_profile_carriers,
    parse_morale_profile_logs,
)


class MoraleProfileMappingTests(unittest.TestCase):
    def test_blank_and_omitted_values_default_to_regular(self) -> None:
        self.assertEqual("regular", DEFAULT_MORALE_PROFILE)
        self.assertEqual("regular", normalize_morale_profile(None))
        self.assertEqual("regular", normalize_morale_profile(""))
        self.assertEqual("regular", normalize_morale_profile("   "))
        self.assertEqual(
            "regular",
            morale_profile_from_unit_definition(UnitDefinition(name="rifle(nato)", side="nato")),
        )

    def test_explicit_unit_definition_profiles_map_exactly(self) -> None:
        expected = {
            "militia_rifle": "militia",
            "line_rifle": "regular",
            "contractor_rifle": "contractor",
            "sof_rifle": "sof",
            "elite_rifle": "elite",
        }
        for name, profile in expected.items():
            definition = UnitDefinition(name=name, side="nato", morale_profile=profile)
            with self.subTest(name=name, profile=profile):
                self.assertEqual(profile, morale_profile_from_unit_definition(definition))

    def test_unknown_profile_string_fails_closed(self) -> None:
        for value in ("guards", "REGULAR", "special", "unbending"):
            with self.subTest(value=value):
                with self.assertRaises(UnknownMoraleProfileError):
                    normalize_morale_profile(value)
        with self.assertRaises(UnknownMoraleProfileError):
            UnitDefinition(name="bad", side="nato", morale_profile="unbending")

    def test_mapping_ignores_faction_and_organization_names(self) -> None:
        for name, side in (
            ("rifle(nato)", "nato"),
            ("rifle(rusa)", "rusa"),
            ("wagner_rifle", "rusa"),
            ("spetsnaz_squad", "rusa"),
            ("azov_rifle", "ukr"),
            ("legion_volunteer", "ukr"),
        ):
            definition = UnitDefinition(
                name=name,
                side=side,
                type_tags=["Infantry", "Squad"],
                category="infantry",
            )
            with self.subTest(name=name, side=side):
                self.assertEqual("regular", morale_profile_from_unit_definition(definition))

    def test_catalog_round_trip_preserves_omitted_default(self) -> None:
        catalog = CodeXCatalog(
            units={
                "rifle(nato)": UnitDefinition(name="rifle(nato)", side="nato", members={"rifleman": 1}),
            },
            signature="fixture",
        )
        restored = CodeXCatalog.from_dict(catalog.to_dict())
        self.assertEqual("", restored.units["rifle(nato)"].morale_profile)
        self.assertEqual("regular", morale_profile_from_unit_definition(restored.units["rifle(nato)"]))


class MoraleProfileCatalogSeamTests(unittest.TestCase):
    def test_lua_row_morale_profile_is_scanned_from_unit_definition(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            lua_dir = root / "resource/script/multiplayer/units/nato"
            lua_dir.mkdir(parents=True)
            lua_dir.joinpath("2022s.lua").write_text(
                """
                return {
                  { unit = "militia_rifle(nato)", type = {"Infantry","Squad"}, morale_profile = "militia", cost = 4 },
                  { unit = "line_rifle(nato)", type = {"Infantry","Squad"}, cost = 6 },
                }
                """,
                encoding="utf-8",
            )
            catalog = CodeXCatalogScanner().scan(root)

        self.assertEqual("militia", catalog.units["militia_rifle(nato)"].morale_profile)
        self.assertEqual("", catalog.units["line_rifle(nato)"].morale_profile)
        self.assertEqual("regular", morale_profile_from_unit_definition(catalog.units["line_rifle(nato)"]))

    def test_source_macro_morale_profile_is_scanned_from_unit_definition(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source_dir = root / "resource/set/multiplayer/units/conquest"
            source_dir.mkdir(parents=True)
            source_dir.joinpath("units_nato.goh").write_text(
                '("squad" side(nato) name(sof_rifle) morale_profile(sof) member(sof_operator:2))\n',
                encoding="utf-8",
            )
            catalog = CodeXCatalogScanner().scan(root)

        self.assertEqual("sof", catalog.units["sof_rifle"].morale_profile)
        self.assertEqual({"sof_operator": 2}, catalog.units["sof_rifle"].members)

    def test_unknown_lua_profile_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            lua_dir = root / "resource/script/multiplayer/units/nato"
            lua_dir.mkdir(parents=True)
            lua_dir.joinpath("2022s.lua").write_text(
                '{ unit = "bad(nato)", type = {"Infantry"}, morale_profile = "guards" }\n',
                encoding="utf-8",
            )
            with self.assertRaises(UnknownMoraleProfileError):
                CodeXCatalogScanner().scan(root)


class MoraleProfileCarrierTests(unittest.TestCase):
    def _stack(self, root: Path) -> Path:
        breed = root / "resource/set/breed/mp/nato"
        breed.mkdir(parents=True)
        breed.joinpath("rifleman.set").write_text(
            '{breed\n\t{inventory\n\t\t{item "m4" filled}\n\t}\n}\n',
            encoding="utf-8",
        )
        return root

    def _state(self, roster: list[BattalionRosterEntry]) -> CampaignState:
        attacker = Battalion(
            battalion_id="bn-attacker",
            faction=Faction.NATO,
            province_id="a",
            roster=roster,
        )
        defender = Battalion(
            battalion_id="bn-defender",
            faction=Faction.RUSSIA,
            province_id="b",
            roster=[BattalionRosterEntry("line_rifle(nato)", quantity=1, category="infantry")],
        )
        return CampaignState(
            campaign_name="morale-profile-phase-a",
            battalions={attacker.battalion_id: attacker, defender.battalion_id: defender},
            pending_battle=PendingBattle(
                battle_id="goc-morale-1",
                origin_province_id="a",
                target_province_id="b",
                attacker_faction=Faction.NATO,
                defender_faction=Faction.RUSSIA,
                attacking_participants=[
                    BattleParticipant("bn-attacker", Faction.NATO, "stage-a", is_primary=True)
                ],
                defending_participants=[
                    BattleParticipant("bn-defender", Faction.RUSSIA, "stage-d", is_primary=True)
                ],
                player_faction=Faction.NATO,
                player_is_attacker=True,
            ),
        )

    def _catalog(self) -> CodeXCatalog:
        return CodeXCatalog(
            units={
                "militia_rifle(nato)": UnitDefinition(
                    name="militia_rifle(nato)",
                    side="nato",
                    members={"rifleman": 2},
                    morale_profile="militia",
                ),
                "line_rifle(nato)": UnitDefinition(
                    name="line_rifle(nato)",
                    side="nato",
                    members={"rifleman": 1},
                ),
                "sof_rifle(nato)": UnitDefinition(
                    name="sof_rifle(nato)",
                    side="nato",
                    members={"rifleman": 1},
                    vehicles=["humvee"],
                    morale_profile="sof",
                ),
            },
            signature="fixture",
        )

    def test_profile_survives_on_existing_human_entity_tag_carrier(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            stack = self._stack(Path(raw))
            catalog = self._catalog()
            state = self._state(
                [
                    BattalionRosterEntry("militia_rifle(nato)", quantity=1, category="infantry"),
                    BattalionRosterEntry("sof_rifle(nato)", quantity=1, category="recon"),
                ]
            )
            text = CampaignScnBuilder(catalog, resource_stack=[stack]).build(state, state.pending_battle)

        carriers = parse_morale_profile_carriers(text)
        self.assertTrue(carriers)
        kinds = {kind for kind, _object_id, _profile in carriers}
        self.assertEqual({"Human", "Entity"}, kinds)
        profiles_by_kind: dict[str, set[str]] = {}
        for kind, _object_id, profile in carriers:
            profiles_by_kind.setdefault(kind, set()).add(profile)
            self.assertIn(profile, ALLOWED_MORALE_PROFILES)
            self.assertIn(f'{{Tags "{morale_profile_tag(profile)}"}}', text)
        self.assertIn("militia", profiles_by_kind["Human"])
        self.assertIn("regular", profiles_by_kind["Human"])
        self.assertIn("sof", profiles_by_kind["Human"])
        self.assertEqual({"sof"}, profiles_by_kind["Entity"])

        humans = [row for row in carriers if row[0] == "Human"]
        self.assertEqual(4, len(humans))
        entities = [row for row in carriers if row[0] == "Entity"]
        self.assertEqual(1, len(entities))

        logs = parse_morale_profile_logs(text)
        self.assertEqual(len(carriers), len(logs))
        self.assertEqual(
            {object_id for _kind, object_id, _profile in carriers},
            {row["object_id"] for row in logs},
        )
        self.assertTrue(any(row["unit"] == "militia_rifle(nato)" and row["profile"] == "militia" for row in logs))
        self.assertTrue(any(row["unit"] == "line_rifle(nato)" and row["profile"] == "regular" for row in logs))
        self.assertTrue(any(row["carrier"] == "entity" and row["profile"] == "sof" for row in logs))

    def test_default_regular_is_present_after_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            stack = self._stack(Path(raw))
            catalog = self._catalog()
            state = self._state([BattalionRosterEntry("line_rifle(nato)", quantity=1, category="infantry")])
            text = CampaignScnBuilder(catalog, resource_stack=[stack]).build(state, state.pending_battle)

        profiles = [profile for _kind, _object_id, profile in parse_morale_profile_carriers(text)]
        self.assertEqual({"regular"}, set(profiles))
        self.assertGreaterEqual(len(profiles), 2)

    def test_scoped_builder_uses_the_same_human_carrier(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            stack = self._stack(Path(raw))
            catalog = self._catalog()
            state = self._state([BattalionRosterEntry("militia_rifle(nato)", quantity=1, category="infantry")])
            text = ParticipantScopedCampaignScnBuilder(catalog, resource_stack=[stack]).build(
                state, state.pending_battle
            )

        human_profiles = [
            profile for kind, _object_id, profile in parse_morale_profile_carriers(text) if kind == "Human"
        ]
        self.assertIn("militia", human_profiles)
        self.assertIn("regular", human_profiles)
        self.assertIn('{Tags "goc_morale_profile:militia"}', text)


if __name__ == "__main__":
    unittest.main()
