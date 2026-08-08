from __future__ import annotations

import unittest

from gates_of_codex.goh_source import (
    MAX_ENTRY_CHARS,
    MAX_NESTING_DEPTH,
    scan_source_entries,
)


class GoHSourceParserTests(unittest.TestCase):
    def test_numbered_and_unnumbered_vehicle_entity_macros_are_tokenized(self):
        result = scan_source_entries(
            '("mixed" side(nato) name(test) vehicle(apc) vehicle1(apc1) vehicle2(apc2) '
            'entity(radar) entity1(radar1))\n',
            "fixture.set",
        )

        self.assertEqual([], result.diagnostics)
        self.assertEqual(
            [
                ("vehicle", "apc"),
                ("vehicle1", "apc1"),
                ("vehicle2", "apc2"),
                ("entity", "radar"),
                ("entity1", "radar1"),
            ],
            [
                (call.name, call.value)
                for call in result.entries[0].calls
                if call.family in {"vehicle", "entity"}
            ],
        )

    def test_block_vehicle_and_entity_forms_remain_supported(self):
        result = scan_source_entries(
            '{"tank" {vehicle "m1"} {entity "radar"}}\n',
            "fixture.set",
        )

        self.assertEqual("tank", result.entries[0].name)
        self.assertEqual(["m1", "radar"], [call.value for call in result.entries[0].calls])

    def test_multiline_name_and_nested_syntax_are_captured(self):
        text = '''("squad_with2types_conquest" side(rusa)
name(kor_inf_rifle) ; current GoH comment
c1(kor_lead:1) c2(kor_rifle:7) note("ignore ( { )"))
'''

        entry = scan_source_entries(text, "units_rusa.set").entries[0]

        self.assertEqual("kor_inf_rifle", entry.name)
        self.assertEqual(1, entry.location.line)
        self.assertEqual("squad_with2types_conquest", entry.macro_kind)
        self.assertIn('note("ignore ( { )")', entry.raw)

    def test_unindented_nested_block_is_not_treated_as_recovery_boundary(self):
        text = '''("vehicle_conquest" name(tank_unit)
{vehicle "tank_entity"}
)
'''

        result = scan_source_entries(text, "nested-block.set")

        self.assertEqual([], result.diagnostics)
        self.assertEqual(["tank_unit"], [entry.name for entry in result.entries])
        self.assertIn('{vehicle "tank_entity"}', result.entries[0].raw)

    def test_only_supported_comments_are_ignored_outside_quotes(self):
        text = '''; ("ignored" name(semicolon))
// {"ignored" {vehicle "commented"}}
("kept" name(real) note("; // still quoted") vehicle(real_vehicle))
'''

        result = scan_source_entries(text, "comments.set")

        self.assertEqual([], result.diagnostics)
        self.assertEqual(["real"], [entry.name for entry in result.entries])
        self.assertEqual("; // still quoted", result.entries[0].calls[1].value)

    def test_definition_shaped_macro_inside_unrelated_parentheses_is_not_top_level(self):
        result = scan_source_entries(
            'wrapper(("inner" name(child)))\n',
            "nested-macro.set",
        )

        self.assertEqual([], result.entries)
        self.assertEqual([], result.diagnostics)

    def test_definition_shaped_block_inside_unrelated_parentheses_is_not_top_level(self):
        result = scan_source_entries(
            'wrapper({"inner" {vehicle "tank"}})\n',
            "nested-block.set",
        )

        self.assertEqual([], result.entries)
        self.assertEqual([], result.diagnostics)

    def test_entry_and_call_locations_are_exact_and_one_based(self):
        text = '\n  ("kind"\n    name(unit)\n    vehicle2(tank))\n'

        entry = scan_source_entries(text, "locations.set").entries[0]
        vehicle = next(call for call in entry.calls if call.name == "vehicle2")

        self.assertEqual((2, 3), (entry.location.line, entry.location.column))
        self.assertEqual((4, 5), (vehicle.location.line, vehicle.location.column))
        self.assertEqual("locations.set", vehicle.location.source)
        self.assertEqual("vehicle", vehicle.family)
        self.assertEqual(2, vehicle.ordinal)

    def test_unterminated_entry_recovers_without_swallowing_next_definition(self):
        text = '("broken" name(broken) vehicle(x)\n{"valid" {vehicle "valid_entity"}}\n'

        result = scan_source_entries(text, "broken.set")

        self.assertEqual("unterminated_entry", result.diagnostics[0].code)
        self.assertEqual((1, 1), (
            result.diagnostics[0].location.line,
            result.diagnostics[0].location.column,
        ))
        self.assertNotIn("valid_entity", result.diagnostics[0].captured)
        self.assertEqual((2, 1), (
            result.entries[-1].location.line,
            result.entries[-1].location.column,
        ))
        self.assertEqual("valid", result.entries[-1].name)

    def test_unclosed_nested_block_is_diagnosed_separately(self):
        result = scan_source_entries(
            '("broken_nested" name(broken) {vehicle "tank")\n',
            "nested.set",
        )

        self.assertEqual(["malformed_nested_block"], [item.code for item in result.diagnostics])

    def test_entry_capture_is_bounded_and_scanning_recovers(self):
        oversized = '("oversized" name(too_big) note("' + ("x" * MAX_ENTRY_CHARS) + '\n'
        text = oversized + '{"valid" {entity "radar"}}\n'

        result = scan_source_entries(text, "large.set")

        self.assertEqual("entry_too_large", result.diagnostics[0].code)
        self.assertEqual(MAX_ENTRY_CHARS, len(result.diagnostics[0].captured))
        self.assertEqual("valid", result.entries[-1].name)

    def test_nesting_depth_is_bounded(self):
        text = '("deep" name(deep)' + ("(" * MAX_NESTING_DEPTH) + "x"

        result = scan_source_entries(text, "deep.set")

        self.assertEqual("nesting_depth_exceeded", result.diagnostics[0].code)
        self.assertLessEqual(len(result.diagnostics[0].captured), MAX_ENTRY_CHARS)


if __name__ == "__main__":
    unittest.main()
