from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.codex.catalog import CodeXCatalogScanner
from gates_of_codex.modstack import (
    load_stack_config,
    normalize_stack,
    validate_known_order,
)
from gates_of_codex.stack_acceptance import validate_mod_stack


class OrderedModStackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.game = self.root / "Call to Arms - Gates of Hell"
        self.west = self.root / "2897299509"
        self.codex = self.root / "3261086933"
        self.ai = self.root / "3636883799"
        self.gates = self.root / "Gates-of-Code-X"
        self.profile = self.root / "profiles"
        for path in (self.game, self.west, self.codex, self.ai, self.gates, self.profile):
            path.mkdir(parents=True)
        for path, name in (
            (self.west, "West81"),
            (self.codex, "Code:X"),
            (self.ai, "CodeX Conquest AI Overhaul"),
            (self.gates, "Gates of Code:X"),
        ):
            (path / "resource").mkdir()
            (path / "mod.info").write_text(f'{{mod {{name "{name}"}}}}\n', encoding="utf-8")
        (self.game / "resource/map/multi/2x2/stack_test").mkdir(parents=True)
        (self.game / "resource/map/multi/2x2/stack_test/map").write_text("{map}\n", encoding="utf-8")
        (self.game / "binaries/x64").mkdir(parents=True)
        (self.game / "binaries/x64/gates_of_hell.exe").write_bytes(b"fixture")
        self._write_codex_units()
        (self.ai / "resource/script").mkdir(parents=True)
        (self.ai / "resource/script/ai-overhaul.lua").write_text("return { recognizeTime = 0.05 }\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    @property
    def stack(self) -> list[Path]:
        return [self.game / "resource", self.west / "resource", self.codex, self.ai, self.gates]

    def _write_codex_units(self) -> None:
        conquest = self.codex / "resource/set/multiplayer/units/conquest/2022s"
        scripts = self.codex / "resource/script/multiplayer/units/nato"
        conquest.mkdir(parents=True)
        scripts.mkdir(parents=True)
        units = []
        lua = []
        for faction in ("nato", "ukr", "rusa", "prc"):
            breed = self.codex / f"resource/set/breed/mp/{faction}"
            breed.mkdir(parents=True)
            (breed / f"rifleman_{faction}.set").write_text("{breed}\n", encoding="utf-8")
            units.append(f'{{"rifle({faction})" {{member "rifleman_{faction}" 4}}}}\n')
            lua.append(f'{{priority=1, type={{"Infantry","Squad"}}, unit="rifle({faction})"}},\n')
        (conquest / "units.set").write_text("".join(units), encoding="utf-8")
        (scripts / "2022s.nato.lua").write_text("".join(lua), encoding="utf-8")

    def test_normalizes_resource_paths_and_confirms_known_order(self) -> None:
        roots = normalize_stack(self.stack)
        self.assertEqual(self.game.resolve(), roots[0])
        self.assertEqual(self.west.resolve(), roots[1])
        ok, detail = validate_known_order(roots)
        self.assertTrue(ok, detail)

    def test_stack_signature_includes_ai_overhaul_runtime(self) -> None:
        scanner = CodeXCatalogScanner()
        before = scanner.scan_stack(self.stack)
        self.assertEqual(1, len(before.by_faction("nato")))
        self.assertEqual(1, len(before.by_faction("prc")))
        (self.ai / "resource/script/ai-overhaul.lua").write_text("return { recognizeTime = 0.04 }\n", encoding="utf-8")
        after = scanner.scan_stack(self.stack)
        self.assertNotEqual(before.signature, after.signature)

    def test_validates_complete_stack(self) -> None:
        report = validate_mod_stack(
            self.game,
            self.codex,
            resource_stack=self.stack,
            profile_directory=self.profile,
        )
        self.assertTrue(report.ok, [check.detail for check in report.checks if not check.ok])
        self.assertEqual(5, len(report.resource_stack))
        self.assertEqual(4, len(report.unit_counts))
        self.assertEqual("multi/2x2/stack_test", report.maps[0].identifier)

    def test_loads_stack_config_in_order(self) -> None:
        config = self.root / "stack.json"
        config.write_text(
            json.dumps({"layers": [{"path": str(path)} for path in self.stack]}),
            encoding="utf-8",
        )
        roots = load_stack_config(config)
        self.assertEqual([self.game.resolve(), self.west.resolve(), self.codex.resolve(), self.ai.resolve(), self.gates.resolve()], roots)


if __name__ == "__main__":
    unittest.main()
