from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from gates_of_codex.effective_definitions import (
    DefinitionCandidate,
    DefinitionKind,
    EffectiveDefinitionIndex,
)
from gates_of_codex.faction_wiring_types import ReferenceKind
from gates_of_codex.faction_wiring_scan import SourceUnitIndex


class EffectiveDefinitionIndexTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    @staticmethod
    def index_with_candidate(identifier: str, kind: DefinitionKind) -> EffectiveDefinitionIndex:
        return EffectiveDefinitionIndex([
            DefinitionCandidate(
                identifier=identifier,
                kind=kind,
                layer="fixture",
                priority=0,
                path="fixture/source.set",
                line=1,
                column=1,
                packed=False,
                parser_form="fixture",
                source_order=0,
            )
        ])

    def test_call_in_cannot_satisfy_vehicle_lookup(self) -> None:
        index = self.index_with_candidate("support_id", DefinitionKind.STRATEGIC_CALL_IN)
        resolution = index.resolve("support_id", ReferenceKind.VEHICLE_ENTITY)
        self.assertFalse(resolution.ok)

    def test_vehicle_cannot_satisfy_call_in_lookup(self) -> None:
        index = self.index_with_candidate("tank_id", DefinitionKind.VEHICLE_ENTITY)
        resolution = index.resolve("tank_id", ReferenceKind.STRATEGIC_CALL_IN)
        self.assertFalse(resolution.ok)

    def test_interaction_reference_alone_does_not_create_candidate(self) -> None:
        self.write(
            "layer/resource/set/interaction_entity/test.inc",
            '{"declared" {spawn "referenced_only"}}\n',
        )
        index = EffectiveDefinitionIndex.build([self.root / "layer"])
        self.assertTrue(index.resolve("declared", ReferenceKind.INTERACTION_OBJECT).ok)
        self.assertTrue(index.resolve("declared", ReferenceKind.VEHICLE_ENTITY).ok)
        self.assertFalse(index.resolve("referenced_only", ReferenceKind.INTERACTION_OBJECT).ok)

    def test_interaction_class_suffix_declares_the_exact_entity_key(self) -> None:
        self.write(
            "layer/resource/set/interaction_entity/vehicles.inc",
            '{"gaz-51_eng car" {tags add "truck"}}\n',
        )

        index = EffectiveDefinitionIndex.build([self.root / "layer"])

        vehicle = index.resolve("gaz-51_eng", ReferenceKind.VEHICLE_ENTITY)
        interaction = index.resolve("gaz-51_eng", ReferenceKind.INTERACTION_OBJECT)
        self.assertTrue(vehicle.ok)
        self.assertTrue(interaction.ok)
        self.assertEqual("interaction_entity", vehicle.terminal.parser_form)
        self.assertEqual((), index.candidates_for("gaz-51_eng car"))

    def test_loose_definition_wins_packed_collision_within_layer(self) -> None:
        layer = self.root / "layer"
        archive = layer / "resource/entities.pak"
        archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("entity/test/collision.def", "{packed definition}\n")
        loose = self.write(
            "layer/resource/entity/test/collision.def",
            "{loose definition}\n",
        )

        resolution = EffectiveDefinitionIndex.build([layer]).resolve(
            "collision", ReferenceKind.VEHICLE_ENTITY
        )

        self.assertEqual("resolved", resolution.status)
        self.assertFalse(resolution.terminal.packed)
        self.assertEqual(loose.relative_to(layer / "resource").as_posix(), resolution.terminal.path)
        self.assertEqual(2, len(resolution.candidates))
        self.assertTrue(any(candidate.packed for candidate in resolution.shadowed))

    def test_identical_loose_duplicates_are_retained_and_semantically_deduplicated(self) -> None:
        self.write("layer/resource/entity/a/duplicate.def", "{same body}\n")
        self.write("layer/resource/entity/b/duplicate.def", "{same body}\n")

        index = EffectiveDefinitionIndex.build([self.root / "layer"])
        resolution = index.resolve("duplicate", ReferenceKind.VEHICLE_ENTITY)

        self.assertEqual("resolved", resolution.status)
        self.assertEqual(2, len(resolution.candidates))
        self.assertEqual(1, len(resolution.shadowed))

    def test_concrete_def_file_wins_compatible_loose_declarations(self) -> None:
        self.write("layer/resource/entity/test/declared.def", "{concrete body}\n")
        self.write(
            "layer/resource/set/interaction_entity/declared.inc",
            '{"declared" {tags add "vehicle"}}\n',
        )
        self.write(
            "layer/resource/set/registry/unit.reg",
            '{"declared"}\n',
        )

        resolution = EffectiveDefinitionIndex.build([self.root / "layer"]).resolve(
            "declared", ReferenceKind.VEHICLE_ENTITY
        )

        self.assertTrue(resolution.ok)
        self.assertEqual("def_file", resolution.terminal.parser_form)
        self.assertEqual(3, len(resolution.shadowed))

    def test_conflicting_purchase_wrappers_at_same_priority_are_ambiguous(self) -> None:
        self.write(
            "layer/resource/set/multiplayer/units/conquest/a.set",
            '("squad_vehicle" side(nato) name(shared) vehicle(tank_a))\n',
        )
        self.write(
            "layer/resource/set/multiplayer/units/conquest/b.set",
            '("squad_vehicle" side(nato) name(shared) vehicle(tank_b))\n',
        )

        resolution = EffectiveDefinitionIndex.build([self.root / "layer"]).resolve(
            "shared", ReferenceKind.PURCHASE_UNIT
        )

        self.assertEqual("ambiguous", resolution.status)
        self.assertEqual(2, len(resolution.ambiguity.candidates))

    def test_wrapper_wins_complementary_interaction_and_registry_evidence(self) -> None:
        self.write(
            "layer/resource/set/multiplayer/units/conquest/wrapper.set",
            '{"shared" ("squad_vehicle" side(nato) vehicle(shared) crew(driver:1))}\n',
        )
        self.write(
            "layer/resource/set/interaction_entity/shared.inc",
            '{"shared car" {tags add "vehicle"}}\n',
        )
        self.write(
            "layer/resource/set/registry/unit.reg",
            '{"shared"}\n',
        )

        resolution = EffectiveDefinitionIndex.build([self.root / "layer"]).resolve(
            "shared", ReferenceKind.VEHICLE_ENTITY
        )

        self.assertTrue(resolution.ok)
        self.assertEqual("implicit_vehicle_wrapper", resolution.terminal.parser_form)
        self.assertGreaterEqual(len(resolution.shadowed), 2)

    def test_conflicting_loose_candidates_at_same_effective_priority_are_ambiguous(self) -> None:
        self.write("layer/resource/entity/a/conflict.def", "{first body}\n")
        self.write("layer/resource/entity/b/conflict.def", "{second body}\n")

        resolution = EffectiveDefinitionIndex.build([self.root / "layer"]).resolve(
            "conflict", ReferenceKind.VEHICLE_ENTITY
        )

        self.assertEqual("ambiguous", resolution.status)
        self.assertFalse(resolution.ok)
        self.assertIsNotNone(resolution.ambiguity)
        self.assertEqual(2, len(resolution.ambiguity.candidates))

    def test_later_layer_wins_over_earlier_layer(self) -> None:
        self.write("early/resource/entity/test/layered.def", "{early}\n")
        late = self.write("late/resource/entity/test/layered.def", "{late}\n")

        resolution = EffectiveDefinitionIndex.build([
            self.root / "early",
            self.root / "late",
        ]).resolve("layered", ReferenceKind.VEHICLE_ENTITY)

        self.assertEqual("resolved", resolution.status)
        self.assertEqual("late", resolution.terminal.layer)
        self.assertEqual(1, resolution.terminal.priority)
        self.assertEqual(late.relative_to(self.root / "late/resource").as_posix(), resolution.terminal.path)
        self.assertEqual(1, len(resolution.shadowed))

    def test_gates_wins_over_codex_through_layer_priority(self) -> None:
        self.write("CodeX/resource/entity/test/owned.def", "{codex}\n")
        self.write("Gates/resource/entity/test/owned.def", "{gates}\n")

        resolution = EffectiveDefinitionIndex.build([
            self.root / "CodeX",
            self.root / "Gates",
        ]).resolve("owned", ReferenceKind.VEHICLE_ENTITY)

        self.assertEqual("resolved", resolution.status)
        self.assertEqual("Gates", resolution.terminal.layer)
        self.assertEqual(1, resolution.terminal.priority)

    def test_candidate_chains_are_byte_stable_across_builds(self) -> None:
        self.write("layer/resource/entity/z/stable.def", "{same}\n")
        self.write("layer/resource/entity/a/stable.def", "{same}\n")

        first = EffectiveDefinitionIndex.build([self.root / "layer"])
        second = EffectiveDefinitionIndex.build([self.root / "layer"])

        self.assertEqual(2, len(first.candidates_for("stable")))
        self.assertEqual(
            repr(first.candidates_for("stable")).encode("utf-8"),
            repr(second.candidates_for("stable")).encode("utf-8"),
        )

    def test_purchase_ready_wrapper_is_typed_and_retains_location(self) -> None:
        self.write(
            "layer/resource/set/multiplayer/units/conquest/wrappers.set",
            "\n{\"buy_me(nato)\"\n"
            "  (\"squad_with1types_conquest\" side(nato) c1(rifleman:2))\n"
            "}\n",
        )

        index = EffectiveDefinitionIndex.build([self.root / "layer"])
        resolution = index.resolve("buy_me(nato)", ReferenceKind.PURCHASE_UNIT)

        self.assertEqual("resolved", resolution.status)
        self.assertEqual(DefinitionKind.PURCHASE_UNIT_WRAPPER, resolution.terminal.kind)
        self.assertEqual("set/multiplayer/units/conquest/wrappers.set", resolution.terminal.path)
        self.assertEqual((2, 1, False, "block", 0), (
            resolution.terminal.line,
            resolution.terminal.column,
            resolution.terminal.packed,
            resolution.terminal.parser_form,
            resolution.terminal.source_order,
        ))

    def test_strategic_declaration_requires_explicit_kind_and_action_shape(self) -> None:
        self.write(
            "layer/resource/set/multiplayer/units/conquest/support.set",
            '("offmap_support" name(support_id) action(callin) vehicle1(body_reference))\n'
            '("offmap_support" name(no_action) vehicle1(other_reference))\n',
        )

        index = EffectiveDefinitionIndex.build([self.root / "layer"])

        resolution = index.resolve("support_id", ReferenceKind.STRATEGIC_CALL_IN)
        self.assertEqual("resolved", resolution.status)
        self.assertEqual(DefinitionKind.STRATEGIC_CALL_IN, resolution.terminal.kind)
        self.assertEqual("macro", resolution.terminal.parser_form)
        self.assertEqual(0, resolution.terminal.source_order)
        self.assertEqual("missing", index.resolve(
            "no_action", ReferenceKind.STRATEGIC_CALL_IN
        ).status)
        self.assertEqual("missing", index.resolve(
            "body_reference", ReferenceKind.STRATEGIC_CALL_IN
        ).status)

    def test_explicit_inherit_and_registry_alias_rows_are_alias_candidates(self) -> None:
        self.write("layer/resource/entity/base/base_tank.def", "{base}\n")
        self.write(
            "layer/resource/set/entity/controlled.set",
            '{"controlled_tank" {inherit "vehicle/base_tank"}}\n',
        )
        self.write(
            "layer/resource/set/registry/vehicle.reg",
            '{"registered_tank" {alias "base_tank"}}\n',
        )

        index = EffectiveDefinitionIndex.build([self.root / "layer"])

        inherited = index.candidates_for("controlled_tank")
        registered = index.candidates_for("registered_tank")
        self.assertEqual((DefinitionKind.REGISTRY_ALIAS,), tuple(item.kind for item in inherited))
        self.assertEqual("base_tank", inherited[0].alias_target)
        self.assertEqual("set/entity/controlled.set", inherited[0].path)
        self.assertEqual((DefinitionKind.REGISTRY_ALIAS,), tuple(item.kind for item in registered))
        self.assertEqual("base_tank", registered[0].alias_target)
        self.assertTrue(index.resolve("controlled_tank", ReferenceKind.VEHICLE_ENTITY).ok)
        self.assertTrue(index.resolve("registered_tank", ReferenceKind.VEHICLE_ENTITY).ok)

    def test_exact_match_precedes_alias(self) -> None:
        self.write("layer/resource/entity/test/exact_id.def", "{exact}\n")
        self.write("layer/resource/entity/test/other_id.def", "{other}\n")
        self.write(
            "layer/resource/set/registry/unit.reg",
            '{"exact_id" {alias "other_id"}}\n',
        )

        resolution = EffectiveDefinitionIndex.build([self.root / "layer"]).resolve(
            "exact_id", ReferenceKind.VEHICLE_ENTITY
        )

        self.assertEqual("resolved", resolution.status)
        self.assertEqual(2, len(resolution.candidates))
        self.assertEqual((), resolution.alias_chain)
        self.assertEqual(DefinitionKind.VEHICLE_ENTITY, resolution.terminal.kind)
        self.assertEqual("exact_id", resolution.terminal.identifier)
        self.assertEqual("entity/test/exact_id.def", resolution.terminal.path)

    def test_explicit_source_case_alias_resolves(self) -> None:
        self.write("layer/resource/entity/test/TankExact.def", "{terminal}\n")
        self.write(
            "layer/resource/set/registry/unit.reg",
            '{"tankexact" {alias "TankExact"}}\n',
        )

        resolution = EffectiveDefinitionIndex.build([self.root / "layer"]).resolve(
            "tankexact", ReferenceKind.VEHICLE_ENTITY
        )

        self.assertEqual("resolved", resolution.status)
        self.assertEqual(2, len(resolution.candidates))
        self.assertEqual(("tankexact", "TankExact"), (
            resolution.alias_chain[0].identifier,
            resolution.alias_chain[0].target,
        ))
        self.assertEqual("TankExact", resolution.terminal.identifier)
        self.assertEqual("entity/test/TankExact.def", resolution.terminal.path)

    def test_unique_file_stem_alias_is_recorded_as_registry_alias(self) -> None:
        self.write("layer/resource/entity/test/TankExact.def", "{terminal}\n")
        self.write(
            "layer/resource/set/multiplayer/units/conquest/units_nato.set",
            '("vehicle_conquest" side(nato) name(wrapper) vehicle1(tankexact))\n',
        )

        index = EffectiveDefinitionIndex.build([self.root / "layer"])
        resolution = index.resolve("tankexact", ReferenceKind.VEHICLE_ENTITY)

        aliases = index.candidates_for("tankexact")
        self.assertEqual(1, len(aliases))
        self.assertEqual(DefinitionKind.REGISTRY_ALIAS, aliases[0].kind)
        self.assertEqual("TankExact", aliases[0].alias_target)
        self.assertEqual("case_alias:def_stem", aliases[0].parser_form)
        self.assertEqual("resolved", resolution.status)
        self.assertEqual(2, len(resolution.candidates))
        self.assertEqual("entity/test/TankExact.def", resolution.terminal.path)

    def test_ambiguous_case_collision_is_blocking(self) -> None:
        self.write("layer/resource/entity/a/TankExact.def", "{one}\n")
        self.write("layer/resource/entity/b/TANKEXACT.def", "{two}\n")
        self.write(
            "layer/resource/set/multiplayer/units/conquest/units_nato.set",
            '("vehicle_conquest" side(nato) name(wrapper) vehicle1(tankexact))\n',
        )

        index = EffectiveDefinitionIndex.build([self.root / "layer"])
        resolution = index.resolve("tankexact", ReferenceKind.VEHICLE_ENTITY)

        self.assertEqual("ambiguous", resolution.status)
        self.assertFalse(resolution.ok)
        self.assertEqual(2, len(index.candidates_for("tankexact")))
        self.assertEqual(
            {"TankExact", "TANKEXACT"},
            {candidate.alias_target for candidate in resolution.ambiguity.candidates},
        )
        self.assertIsNone(resolution.terminal)

    def test_unrelated_casefold_lookup_does_not_fallback(self) -> None:
        self.write("layer/resource/entity/test/TankExact.def", "{terminal}\n")

        index = EffectiveDefinitionIndex.build([self.root / "layer"])
        resolution = index.resolve("tankexact", ReferenceKind.VEHICLE_ENTITY)

        self.assertEqual("missing", resolution.status)
        self.assertEqual((), resolution.candidates)
        self.assertIsNone(resolution.terminal)

    def test_alias_cycle_is_reported(self) -> None:
        self.write(
            "layer/resource/set/registry/unit.reg",
            '{"cycle_a" {alias "cycle_b"}}\n'
            '{"cycle_b" {alias "cycle_a"}}\n',
        )

        resolution = EffectiveDefinitionIndex.build([self.root / "layer"]).resolve(
            "cycle_a", ReferenceKind.VEHICLE_ENTITY
        )

        self.assertEqual("alias_cycle", resolution.status)
        self.assertEqual(2, len(resolution.candidates))
        self.assertEqual(["cycle_a", "cycle_b"], [hop.identifier for hop in resolution.alias_chain])
        self.assertIsNone(resolution.terminal)

    def test_dangling_alias_is_reported(self) -> None:
        self.write(
            "layer/resource/set/registry/unit.reg",
            '{"dangling" {alias "absent"}}\n',
        )

        resolution = EffectiveDefinitionIndex.build([self.root / "layer"]).resolve(
            "dangling", ReferenceKind.VEHICLE_ENTITY
        )

        self.assertEqual("alias_dangling", resolution.status)
        self.assertEqual(1, len(resolution.candidates))
        self.assertEqual("absent", resolution.alias_chain[0].target)
        self.assertIsNone(resolution.terminal)

    def test_alias_depth_is_bounded(self) -> None:
        rows = "".join(
            f'{{"alias_{index}" {{alias "alias_{index + 1}"}}}}\n'
            for index in range(EffectiveDefinitionIndex.MAX_ALIAS_DEPTH + 1)
        )
        self.write("layer/resource/set/registry/unit.reg", rows)
        self.write(
            f"layer/resource/entity/test/alias_{EffectiveDefinitionIndex.MAX_ALIAS_DEPTH + 1}.def",
            "{terminal}\n",
        )

        resolution = EffectiveDefinitionIndex.build([self.root / "layer"]).resolve(
            "alias_0", ReferenceKind.VEHICLE_ENTITY
        )

        self.assertEqual("alias_depth_exceeded", resolution.status)
        self.assertEqual(EffectiveDefinitionIndex.MAX_ALIAS_DEPTH, len(resolution.alias_chain))
        self.assertEqual(EffectiveDefinitionIndex.MAX_ALIAS_DEPTH + 1, len(resolution.candidates))
        self.assertIsNone(resolution.terminal)

    def test_alias_depth_allows_exactly_the_documented_maximum(self) -> None:
        rows = "".join(
            f'{{"alias_{index}" {{alias "alias_{index + 1}"}}}}\n'
            for index in range(EffectiveDefinitionIndex.MAX_ALIAS_DEPTH)
        )
        self.write("layer/resource/set/registry/unit.reg", rows)
        self.write(
            f"layer/resource/entity/test/alias_{EffectiveDefinitionIndex.MAX_ALIAS_DEPTH}.def",
            "{terminal}\n",
        )

        resolution = EffectiveDefinitionIndex.build([self.root / "layer"]).resolve(
            "alias_0", ReferenceKind.VEHICLE_ENTITY
        )

        self.assertEqual("resolved", resolution.status)
        self.assertEqual(EffectiveDefinitionIndex.MAX_ALIAS_DEPTH, len(resolution.alias_chain))
        self.assertEqual(
            f"alias_{EffectiveDefinitionIndex.MAX_ALIAS_DEPTH}",
            resolution.terminal.identifier,
        )

    def test_alias_chain_retains_terminal_provenance(self) -> None:
        self.write("West81/resource/entity/test/legacy_tank.def", "{legacy}\n")
        self.write(
            "CodeX/resource/set/registry/unit.reg",
            '{"middle_alias" {alias "legacy_tank"}}\n'
            '{"modern_alias" {alias "middle_alias"}}\n',
        )

        resolution = EffectiveDefinitionIndex.build([
            self.root / "West81",
            self.root / "CodeX",
        ]).resolve("modern_alias", ReferenceKind.VEHICLE_ENTITY)

        self.assertEqual("resolved", resolution.status)
        self.assertEqual(3, len(resolution.candidates))
        self.assertEqual(["modern_alias", "middle_alias"], [
            hop.identifier for hop in resolution.alias_chain
        ])
        self.assertEqual("CodeX", resolution.winner.layer)
        self.assertEqual("West81", resolution.terminal.layer)
        self.assertEqual(0, resolution.terminal.priority)
        self.assertEqual("entity/test/legacy_tank.def", resolution.terminal.path)
        self.assertEqual((), resolution.shadowed)

    def test_build_accepts_prebuilt_source_unit_index(self) -> None:
        layer = self.root / "layer"
        self.write("layer/resource/entity/test/TankExact.def", "{terminal}\n")
        self.write(
            "layer/resource/set/multiplayer/units/conquest/units_nato.set",
            '("vehicle_conquest" side(nato) name(wrapper) vehicle1(tankexact))\n',
        )
        unit_index = SourceUnitIndex.build([layer])

        index = EffectiveDefinitionIndex.build([layer], unit_index=unit_index)
        resolution = index.resolve("tankexact", ReferenceKind.VEHICLE_ENTITY)

        self.assertEqual("resolved", resolution.status)
        self.assertEqual("TankExact", resolution.terminal.identifier)

    def test_arbitrary_target_and_non_vehicle_inherit_calls_do_not_create_aliases(self) -> None:
        self.write(
            "layer/resource/set/entity/not_aliases.set",
            '{"ordinary_target" {target "referenced_only"}}\n'
            '{"breed_child" {inherit "breed/base_breed"}}\n',
        )

        index = EffectiveDefinitionIndex.build([self.root / "layer"])

        self.assertEqual((), index.candidates_for("ordinary_target"))
        self.assertEqual((), index.candidates_for("breed_child"))

    def test_control_vehicle_wrapper_without_explicit_reference_declares_same_name_entity(self) -> None:
        self.write(
            "layer/resource/set/multiplayer/units/conquest/vehicles.set",
            '("vehicle_with_control" side(nato) name(controlled_vehicle) crew1(driver:1))\n',
        )

        index = EffectiveDefinitionIndex.build([self.root / "layer"])
        vehicle = index.resolve("controlled_vehicle", ReferenceKind.VEHICLE_ENTITY)
        purchase = index.resolve("controlled_vehicle", ReferenceKind.PURCHASE_UNIT)

        self.assertEqual("resolved", vehicle.status)
        self.assertEqual(DefinitionKind.VEHICLE_ENTITY, vehicle.terminal.kind)
        self.assertEqual("implicit_vehicle_wrapper", vehicle.terminal.parser_form)
        self.assertEqual("resolved", purchase.status)
        self.assertEqual(DefinitionKind.PURCHASE_UNIT_WRAPPER, purchase.terminal.kind)

    def test_purchase_wrapper_with_same_name_vehicle_declares_typed_entity(self) -> None:
        self.write(
            "layer/resource/set/multiplayer/units/conquest/vehicles.set",
            '{"wrapped_vehicle"\n'
            '  ("squad_vehicle" side(nato) vehicle(wrapped_vehicle) crew(driver:1))\n'
            '}\n',
        )

        index = EffectiveDefinitionIndex.build([self.root / "layer"])

        vehicle = index.resolve("wrapped_vehicle", ReferenceKind.VEHICLE_ENTITY)
        purchase = index.resolve("wrapped_vehicle", ReferenceKind.PURCHASE_UNIT)
        self.assertTrue(vehicle.ok)
        self.assertTrue(purchase.ok)
        self.assertEqual("implicit_vehicle_wrapper", vehicle.terminal.parser_form)


if __name__ == "__main__":
    unittest.main()
