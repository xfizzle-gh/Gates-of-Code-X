"""#273 Phase A: morale-profile mapping and AIO inventory-marker proof.

The Phase A carrier is the Human ``{Inventory}`` item
``aio_marker_morale_{low,regular,trained,elite}``. Diagnostic
``{Tags "goc_morale_profile:*"}`` and SCN comments are observability only.
They are not a second morale system and are not the AIO apply-trigger carrier.
"""

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
from gates_of_codex.bridge.scn import BreedInventoryItem
from gates_of_codex.tactical_morale_profile import (
    AIO_MORALE_MARKERS,
    DEFAULT_MORALE_PROFILE,
    UnknownMoraleProfileError,
    aio_morale_marker_for_profile,
    apply_aio_morale_marker,
    morale_profile_from_unit_definition,
    morale_profile_tag,
    normalize_morale_profile,
    parse_entity_aio_morale_markers,
    parse_human_aio_morale_markers,
    parse_morale_profile_logs,
    parse_morale_profile_visibility_tags,
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


class AioMoraleMarkerMappingTests(unittest.TestCase):
    def test_five_profiles_collapse_onto_four_aio_markers(self) -> None:
        self.assertEqual("aio_marker_morale_low", aio_morale_marker_for_profile("militia"))
        self.assertEqual("aio_marker_morale_regular", aio_morale_marker_for_profile("regular"))
        self.assertEqual("aio_marker_morale_regular", aio_morale_marker_for_profile(""))
        self.assertEqual("aio_marker_morale_trained", aio_morale_marker_for_profile("contractor"))
        self.assertEqual("aio_marker_morale_elite", aio_morale_marker_for_profile("sof"))
        self.assertEqual("aio_marker_morale_elite", aio_morale_marker_for_profile("elite"))
        self.assertEqual(
            aio_morale_marker_for_profile("sof"),
            aio_morale_marker_for_profile("elite"),
        )

    def test_unknown_profile_does_not_invent_an_aio_marker(self) -> None:
        with self.assertRaises(UnknownMoraleProfileError):
            aio_morale_marker_for_profile("guards")
        with self.assertRaises(UnknownMoraleProfileError):
            aio_morale_marker_for_profile("aio_marker_morale_sof")

    def test_catalog_profile_replaces_breed_copied_aio_marker(self) -> None:
        items = [
            BreedInventoryItem(name="ak74m", filled=True),
            BreedInventoryItem(name="aio_marker_morale_trained"),
        ]
        rewritten = apply_aio_morale_marker(items, "regular")
        names = [item.name for item in rewritten]
        self.assertEqual(["ak74m", "aio_marker_morale_regular"], names)
        self.assertNotIn("aio_marker_morale_trained", names)
        self.assertEqual("aio_marker_morale_trained", items[1].name)


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


class AioMoraleInventoryCarrierTests(unittest.TestCase):
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
                "contractor_rifle(nato)": UnitDefinition(
                    name="contractor_rifle(nato)",
                    side="nato",
                    members={"rifleman": 1},
                    morale_profile="contractor",
                ),
                "elite_rifle(nato)": UnitDefinition(
                    name="elite_rifle(nato)",
                    side="nato",
                    members={"rifleman": 1},
                    morale_profile="elite",
                ),
                "wagner_rifle": UnitDefinition(
                    name="wagner_rifle",
                    side="nato",
                    members={"wagner_rifleman": 1},
                ),
            },
            signature="fixture",
        )

    def test_profile_survives_on_human_inventory_aio_marker(self) -> None:
        """Phase A carrier proof: Human Inventory emits exactly one AIO marker."""

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

        human_markers = parse_human_aio_morale_markers(text)
        self.assertTrue(human_markers)
        self.assertEqual(4, len(human_markers))
        for markers in human_markers.values():
            self.assertEqual(1, len(markers))
            self.assertIn(markers[0], AIO_MORALE_MARKERS)
        self.assertEqual(
            {"aio_marker_morale_low", "aio_marker_morale_regular", "aio_marker_morale_elite"},
            {marker for markers in human_markers.values() for marker in markers},
        )
        entity_markers = parse_entity_aio_morale_markers(text)
        self.assertTrue(entity_markers)
        self.assertTrue(all(markers == () for markers in entity_markers.values()))

    def test_goc_tags_and_scn_comments_are_observability_only(self) -> None:
        """Diagnostic Tags/comments are logging only, not the morale carrier."""

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

        visibility = parse_morale_profile_visibility_tags(text)
        self.assertTrue(visibility)
        kinds = {kind for kind, _object_id, _profile in visibility}
        self.assertEqual({"Human", "Entity"}, kinds)
        self.assertIn(f'{{Tags "{morale_profile_tag("militia")}"}}', text)
        self.assertIn(f'{{Tags "{morale_profile_tag("regular")}"}}', text)
        self.assertIn(f'{{Tags "{morale_profile_tag("sof")}"}}', text)
        logs = parse_morale_profile_logs(text)
        self.assertEqual(len(visibility), len(logs))
        self.assertTrue(
            any(row["unit"] == "militia_rifle(nato)" and row["profile"] == "militia" for row in logs)
        )
        self.assertTrue(any(row["unit"] == "line_rifle(nato)" and row["profile"] == "regular" for row in logs))
        # Log field "carrier" names the GEM object kind (human|entity), not a
        # second morale system and not the AIO apply-trigger inventory item.
        self.assertTrue(any(row["object_kind"] == "entity" and row["profile"] == "sof" for row in logs))

    def test_default_regular_is_present_after_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            stack = self._stack(Path(raw))
            catalog = self._catalog()
            state = self._state([BattalionRosterEntry("line_rifle(nato)", quantity=1, category="infantry")])
            text = CampaignScnBuilder(catalog, resource_stack=[stack]).build(state, state.pending_battle)

        human_markers = parse_human_aio_morale_markers(text)
        self.assertTrue(human_markers)
        self.assertEqual(
            {("aio_marker_morale_regular",)},
            set(human_markers.values()),
        )
        self.assertTrue(all(len(markers) == 1 and markers[0] in AIO_MORALE_MARKERS for markers in human_markers.values()))
        self.assertIn('{item "aio_marker_morale_regular"', text)

    def test_scoped_builder_writes_human_inventory_aio_markers(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            stack = self._stack(Path(raw))
            catalog = self._catalog()
            state = self._state([BattalionRosterEntry("militia_rifle(nato)", quantity=1, category="infantry")])
            text = ParticipantScopedCampaignScnBuilder(catalog, resource_stack=[stack]).build(
                state, state.pending_battle
            )

        human_markers = parse_human_aio_morale_markers(text)
        self.assertIn(("aio_marker_morale_low",), human_markers.values())
        self.assertIn(("aio_marker_morale_regular",), human_markers.values())
        self.assertTrue(all(len(markers) == 1 and markers[0] in AIO_MORALE_MARKERS for markers in human_markers.values()))
        self.assertIn('{item "aio_marker_morale_low"', text)

    def test_human_inventory_emits_mapped_aio_markers_for_regular_and_militia(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            stack = self._stack(Path(raw))
            catalog = self._catalog()
            state = self._state(
                [
                    BattalionRosterEntry("line_rifle(nato)", quantity=1, category="infantry"),
                    BattalionRosterEntry("militia_rifle(nato)", quantity=1, category="infantry"),
                ]
            )
            text = CampaignScnBuilder(catalog, resource_stack=[stack]).build(state, state.pending_battle)

        human_markers = parse_human_aio_morale_markers(text)
        self.assertTrue(human_markers)
        emitted = {markers[0] for markers in human_markers.values() if markers}
        self.assertIn("aio_marker_morale_regular", emitted)
        self.assertIn("aio_marker_morale_low", emitted)
        self.assertTrue(all(len(markers) == 1 for markers in human_markers.values()))
        self.assertRegex(
            text,
            r'\{Inventory 0x[0-9a-fA-F]+[\s\S]*?\{item "aio_marker_morale_regular"',
        )
        self.assertRegex(
            text,
            r'\{Inventory 0x[0-9a-fA-F]+[\s\S]*?\{item "aio_marker_morale_low"',
        )

    def test_sof_and_elite_both_emit_aio_marker_morale_elite(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            stack = self._stack(Path(raw))
            catalog = self._catalog()
            state = self._state(
                [
                    BattalionRosterEntry("sof_rifle(nato)", quantity=1, category="recon"),
                    BattalionRosterEntry("elite_rifle(nato)", quantity=1, category="infantry"),
                ]
            )
            text = CampaignScnBuilder(catalog, resource_stack=[stack]).build(state, state.pending_battle)

        human_markers = parse_human_aio_morale_markers(text)
        self.assertTrue(human_markers)
        self.assertEqual({"aio_marker_morale_elite", "aio_marker_morale_regular"}, {
            marker
            for markers in human_markers.values()
            for marker in markers
        })
        self.assertIn('{item "aio_marker_morale_elite"', text)
        self.assertNotIn("aio_marker_morale_sof", text)
        entity_markers = parse_entity_aio_morale_markers(text)
        self.assertTrue(entity_markers)
        self.assertTrue(all(markers == () for markers in entity_markers.values()))

    def test_contractor_emits_aio_marker_morale_trained(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            stack = self._stack(Path(raw))
            catalog = self._catalog()
            state = self._state(
                [BattalionRosterEntry("contractor_rifle(nato)", quantity=1, category="infantry")]
            )
            text = CampaignScnBuilder(catalog, resource_stack=[stack]).build(state, state.pending_battle)

        human_markers = parse_human_aio_morale_markers(text)
        self.assertIn(("aio_marker_morale_trained",), set(human_markers.values()))
        self.assertIn('{item "aio_marker_morale_trained"', text)
        self.assertNotIn("aio_marker_morale_contractor", text)

    def test_catalog_regular_overrides_breed_trained_marker_on_wagner_named_unit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            stack = self._stack(root)
            breed = root / "resource/set/breed/mp/nato"
            breed.joinpath("wagner_rifleman.set").write_text(
                "{breed\n"
                "\t{inventory\n"
                '\t\t{item "ak74m" filled}\n'
                '\t\t{item "aio_marker_morale_trained"}\n'
                "\t}\n"
                "}\n",
                encoding="utf-8",
            )
            catalog = self._catalog()
            state = self._state([BattalionRosterEntry("wagner_rifle", quantity=1, category="infantry")])
            text = CampaignScnBuilder(catalog, resource_stack=[stack]).build(state, state.pending_battle)

        human_markers = parse_human_aio_morale_markers(text)
        self.assertTrue(human_markers)
        self.assertIn(("aio_marker_morale_regular",), set(human_markers.values()))
        self.assertNotIn("aio_marker_morale_trained", text)
        self.assertIn('{item "ak74m" filled', text)
        self.assertIn('{item "aio_marker_morale_regular"', text)
        self.assertEqual("regular", morale_profile_from_unit_definition(catalog.units["wagner_rifle"]))


if __name__ == "__main__":
    unittest.main()
