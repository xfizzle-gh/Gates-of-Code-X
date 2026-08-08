from __future__ import annotations

import unittest

from gates_of_codex.goh_source import (
    MAX_CALLS_PER_ENTRY,
    MAX_ENTRY_CHARS,
    MAX_NESTING_DEPTH,
    SourceDiagnostic,
    SourceLocation,
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
        self.assertEqual((2, 1), (
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

        diagnostic = result.diagnostics[0]
        self.assertEqual("nesting_depth_exceeded", diagnostic.code)
        self.assertEqual((1, text.rfind("(") + 1), (
            diagnostic.location.line,
            diagnostic.location.column,
        ))
        self.assertGreater(
            diagnostic.state.paren_depth + diagnostic.state.brace_depth,
            MAX_NESTING_DEPTH,
        )
        self.assertLessEqual(len(diagnostic.captured), MAX_ENTRY_CHARS)

    def test_call_count_is_bounded_at_the_4097th_recognized_call(self):
        calls = " ".join(
            f"vehicle{ordinal}(tank{ordinal})"
            for ordinal in range(1, MAX_CALLS_PER_ENTRY + 2)
        )
        text = f'("many" {calls})\n{{"valid" {{entity "radar"}}}}\n'
        failure_index = text.index(f"vehicle{MAX_CALLS_PER_ENTRY + 1}(")

        result = scan_source_entries(text, "many.set")

        self.assertEqual(["call_limit_exceeded"], [item.code for item in result.diagnostics])
        self.assertEqual((1, failure_index + 1), (
            result.diagnostics[0].location.line,
            result.diagnostics[0].location.column,
        ))
        self.assertEqual("calls", result.diagnostics[0].state.phase)
        self.assertEqual(["valid"], [entry.name for entry in result.entries])

    def test_arbitrarily_long_numeric_suffix_is_diagnosed_without_crashing(self):
        macro_name = "vehicle" + ("9" * 5_000)
        text = f'("bad_ordinal" name(unit) {macro_name}(tank))\n'
        failure_index = text.index(macro_name)

        result = scan_source_entries(text, "ordinal.set")

        self.assertEqual(["invalid_ordinal"], [item.code for item in result.diagnostics])
        self.assertEqual(failure_index + 1, result.diagnostics[0].location.column)
        self.assertEqual("calls", result.diagnostics[0].state.phase)

    def test_semantic_duplicate_calls_collapse_to_first_source_evidence(self):
        text = '''("duplicates" name(unit)
vehicle(tank) vehicle1( "tank" ) vehicle2(tank ; comment
)
entity(radar) entity1("radar"))
'''

        result = scan_source_entries(text, "duplicates.set")
        references = [
            call
            for call in result.entries[0].calls
            if call.family in {"vehicle", "entity"}
        ]

        self.assertEqual([], result.diagnostics)
        self.assertEqual(
            [("vehicle", "tank"), ("entity", "radar")],
            [(call.name, call.value) for call in references],
        )
        self.assertEqual([None, None], [call.ordinal for call in references])

    def test_comments_are_removed_from_unquoted_call_values(self):
        text = '''("comments" name(unit)
vehicle(tank ; explanation
)
entity(radar // explanation
))
'''

        entry = scan_source_entries(text, "call-comments.set").entries[0]

        self.assertEqual(
            ["tank", "radar"],
            [
                call.value
                for call in entry.calls
                if call.family in {"vehicle", "entity"}
            ],
        )

    def test_diagnostic_state_defaults_and_exact_unexpected_closer_location(self):
        defaulted = SourceDiagnostic(
            code="example",
            message="example",
            location=SourceLocation("example.set", 1, 1),
            captured="",
        )
        result = scan_source_entries('("kind"\n})\n', "closer.set")
        diagnostic = result.diagnostics[0]

        self.assertEqual("", defaulted.state.form)
        self.assertEqual("unexpected_closer", diagnostic.code)
        self.assertEqual((2, 1), (diagnostic.location.line, diagnostic.location.column))
        self.assertEqual("macro", diagnostic.state.form)
        self.assertEqual("capture", diagnostic.state.phase)
        self.assertEqual(-1, diagnostic.state.brace_depth)

    def test_unterminated_entry_at_eof_reports_eof_and_parser_state(self):
        text = '("kind"\n name(unit)'

        diagnostic = scan_source_entries(text, "eof.set").diagnostics[0]

        self.assertEqual("unterminated_entry", diagnostic.code)
        self.assertEqual((2, len(" name(unit)") + 1), (
            diagnostic.location.line,
            diagnostic.location.column,
        ))
        self.assertEqual("macro", diagnostic.state.form)
        self.assertEqual(1, diagnostic.state.paren_depth)

    def test_unterminated_quoted_declaration_header_is_diagnosed(self):
        text = '("broken'

        diagnostic = scan_source_entries(text, "header.set").diagnostics[0]

        self.assertEqual("unterminated_declaration_header", diagnostic.code)
        self.assertEqual((1, len(text) + 1), (
            diagnostic.location.line,
            diagnostic.location.column,
        ))
        self.assertEqual("header", diagnostic.state.phase)
        self.assertTrue(diagnostic.state.in_quote)

    def test_recovery_ignores_definition_shaped_lines_at_nested_depth(self):
        text = '''("broken" name(broken)
wrapper(
{"nested" {vehicle "nested_entity"}}
)
{"valid" {vehicle "valid_entity"}}
'''

        result = scan_source_entries(text, "recovery.set")

        self.assertEqual(["unterminated_entry"], [item.code for item in result.diagnostics])
        self.assertEqual(["valid"], [entry.name for entry in result.entries])
        self.assertNotIn("valid_entity", result.diagnostics[0].captured)

    def test_malformed_diagnostics_are_deterministic(self):
        text = '("broken" name(unit)\n{"valid" {vehicle "tank"}}\n'

        first = scan_source_entries(text, "deterministic.set")
        second = scan_source_entries(text, "deterministic.set")

        self.assertEqual(first.diagnostics, second.diagnostics)
        self.assertEqual(first.entries, second.entries)

    def test_unexpected_closer_recovery_skips_declarations_nested_in_wrapper(self):
        text = '''("broken" name(unit)
})
wrapper(
("nested_macro" name(nested_macro))
{"nested_block" {vehicle "nested_entity"}}
)
{"valid" {vehicle "valid_entity"}}
'''

        first = scan_source_entries(text, "closer-recovery.set")
        second = scan_source_entries(text, "closer-recovery.set")

        self.assertEqual(["unexpected_closer"], [item.code for item in first.diagnostics])
        self.assertEqual(["valid"], [entry.name for entry in first.entries])
        self.assertEqual(first.diagnostics, second.diagnostics)
        self.assertEqual(first.entries, second.entries)


if __name__ == "__main__":
    unittest.main()
