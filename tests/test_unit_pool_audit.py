from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from gates_of_codex.entrypoint import main as entrypoint_main
from gates_of_codex.unit_pool_audit import UnitPoolAuditor


class UnitPoolAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.west81 = self.root / "2897299509-West81"
        self.codex = self.root / "3261086933-CodeX"
        self.overlay = self.root / "3700832981-Gates-of-Code-X"
        self._write_fixture()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @property
    def stack(self) -> list[Path]:
        return [self.west81, self.codex, self.overlay]

    def _write_fixture(self) -> None:
        self._write_layer(
            self.west81,
            "West81",
            [
                ("westgermany_panzer(nato)", [], ["leopard1"], ["Tank"]),
                ("nva_rifle(rusa)", ["nva_rifleman"], [], ["Infantry", "Squad"]),
                ("soviet_legacy_tank(rusa)", [], ["t72"], ["Tank"]),
            ],
        )
        self._write_breed(self.west81, "rusa", "nva_rifleman", complete=True)

        self._write_layer(
            self.codex,
            "Code:X",
            [
                ("usarmy_rifle(nato)", ["usarmy_rifleman"], [], ["Infantry", "Squad"]),
                ("nato_line(nato)", ["rifleman_generic"], [], ["Infantry", "Squad"]),
                ("russian_motor(rusa)", ["russian_rifleman"], ["btr80"], ["Infantry", "APC"]),
                ("kpa_rifle(rusa)", ["kpa_rifleman"], [], ["Infantry", "Squad"]),
                ("expeditionary_rifle(prc)", ["pla_rifleman"], [], ["Infantry", "Squad"]),
                ("bundeswehr_kpa(rusa)", ["kpa_conflict_rifleman"], [], ["Infantry", "Squad"]),
                ("owl_guard(nato)", ["owl_guard"], [], ["Infantry", "Squad"]),
                ("mystery_scout(nato)", ["mystery_scout"], [], ["Recon", "Squad"]),
                ("doctrine_placeholder(nato)", [], [], ["Doctrine"]),
            ],
        )
        for side, breed in (
            ("nato", "usarmy_rifleman"),
            ("nato", "rifleman_generic"),
            ("rusa", "russian_rifleman"),
            ("rusa", "kpa_rifleman"),
            ("rusa", "kpa_conflict_rifleman"),
            ("prc", "pla_rifleman"),
            ("nato", "owl_guard"),
        ):
            self._write_breed(self.codex, side, breed, complete=True)
        self._write_breed(self.codex, "nato", "mystery_scout", complete=False)

        self._write_layer(
            self.overlay,
            "Gates of CodeX",
            [
                ("usarmy_rifle(nato)", ["usarmy_rifleman"] * 6, [], ["Infantry", "Squad"]),
            ],
        )

    @staticmethod
    def _write_layer(
        root: Path,
        display_name: str,
        units: list[tuple[str, list[str], list[str], list[str]]],
    ) -> None:
        source_dir = root / "resource/set/multiplayer/units/conquest/2022s"
        lua_dir = root / "resource/script/multiplayer/units/all"
        source_dir.mkdir(parents=True, exist_ok=True)
        lua_dir.mkdir(parents=True, exist_ok=True)
        source_rows: list[str] = []
        lua_rows: list[str] = []
        for name, members, vehicles, tags in units:
            body = [f'{{"{name}"']
            for member in members:
                body.append(f' {{member "{member}" 1}}')
            for vehicle in vehicles:
                body.append(f' {{vehicle "{vehicle}"}}')
            body.append("}\n")
            source_rows.append("".join(body))
            rendered_tags = ",".join(f'"{tag}"' for tag in tags)
            lua_rows.append(f'{{priority=1, type={{{rendered_tags}}}, unit="{name}"}},\n')
        (source_dir / "units.set").write_text("".join(source_rows), encoding="utf-8")
        (lua_dir / "2022s.lua").write_text("".join(lua_rows), encoding="utf-8")
        (root / "mod.info").write_text(f'{{name "{display_name}"}}\n', encoding="utf-8")

    @staticmethod
    def _write_breed(root: Path, side: str, name: str, *, complete: bool) -> None:
        path = root / f"resource/set/breed/mp/{side}/{name}.set"
        path.parent.mkdir(parents=True, exist_ok=True)
        items = ['{item "service_rifle" filled}']
        if complete:
            items.append('{item "service_rifle ammo" 120}')
        else:
            items = ['{item "bandage" 3}']
        path.write_text(
            "{breed\n\t{inventory\n\t\t" + "\n\t\t".join(items) + "\n\t}\n}\n",
            encoding="utf-8",
        )

    def test_classification_keeps_tactical_side_separate(self) -> None:
        payload, _, _ = UnitPoolAuditor(self.stack).run()
        rows = {row["unit_name"]: row for row in payload["rows"]}

        self.assertEqual("usa", rows["usarmy_rifle(nato)"]["inferred_nation"])
        self.assertEqual("nato", rows["usarmy_rifle(nato)"]["tactical_side"])
        self.assertEqual("generic_nato", rows["nato_line(nato)"]["inferred_nation"])
        self.assertEqual("russia", rows["russian_motor(rusa)"]["inferred_nation"])
        self.assertEqual("dprk", rows["kpa_rifle(rusa)"]["inferred_nation"])
        self.assertEqual("rusa", rows["kpa_rifle(rusa)"]["tactical_side"])
        self.assertEqual("prc", rows["expeditionary_rifle(prc)"]["inferred_nation"])
        self.assertEqual("germany", rows["westgermany_panzer(nato)"]["inferred_nation"])
        self.assertEqual("east_germany", rows["nva_rifle(rusa)"]["inferred_nation"])
        self.assertEqual("soviet_legacy", rows["soviet_legacy_tank(rusa)"]["inferred_nation"])
        self.assertEqual("unknown", rows["bundeswehr_kpa(rusa)"]["inferred_nation"])
        self.assertEqual(
            "conflicting_evidence",
            rows["bundeswehr_kpa(rusa)"]["inference_method"],
        )

    def test_provenance_loadouts_and_materialization_are_separate(self) -> None:
        payload, _, _ = UnitPoolAuditor(self.stack).run()
        rows = {row["unit_name"]: row for row in payload["rows"]}

        overlaid = rows["usarmy_rifle(nato)"]
        self.assertEqual("Gates of CodeX", overlaid["source_layer"])
        self.assertEqual(2, overlaid["overlay_priority"])
        self.assertEqual("modern", overlaid["content_role"])
        self.assertEqual(6, overlaid["breed_counts"]["usarmy_rifleman"])
        self.assertTrue(overlaid["loadout_complete"])

        legacy = rows["westgermany_panzer(nato)"]
        self.assertEqual("West81", legacy["source_layer"])
        self.assertEqual("legacy_reserve", legacy["content_role"])
        self.assertTrue(legacy["vehicle_materializable"])
        self.assertFalse(legacy["human_materializable"])
        self.assertTrue(legacy["loadout_complete"])

        incomplete = rows["mystery_scout(nato)"]
        self.assertTrue(incomplete["human_materializable"])
        self.assertFalse(incomplete["loadout_complete"])

        placeholder = rows["doctrine_placeholder(nato)"]
        self.assertFalse(placeholder["materializable"])
        self.assertFalse(placeholder["vehicle_materializable"])
        self.assertFalse(placeholder["human_materializable"])

    def test_outputs_are_deterministic_and_include_unclassified_tokens(self) -> None:
        first = self.root / "first"
        second = self.root / "second"
        auditor = UnitPoolAuditor(self.stack)
        auditor.write(
            first / "unit-pools.json",
            first / "unit-pools-summary.md",
            first / "unclassified-unit-tokens.json",
        )
        auditor.write(
            second / "unit-pools.json",
            second / "unit-pools-summary.md",
            second / "unclassified-unit-tokens.json",
        )
        self.assertEqual(
            (first / "unit-pools.json").read_bytes(),
            (second / "unit-pools.json").read_bytes(),
        )
        self.assertEqual(
            (first / "unit-pools-summary.md").read_bytes(),
            (second / "unit-pools-summary.md").read_bytes(),
        )
        token_payload = json.loads(
            (first / "unclassified-unit-tokens.json").read_text(encoding="utf-8")
        )
        tokens = {row["token"] for row in token_payload["tokens"]}
        self.assertIn("owl", tokens)
        self.assertIn("guard", tokens)
        summary = (first / "unit-pools-summary.md").read_text(encoding="utf-8")
        self.assertIn("Actor decision table", summary)
        self.assertIn("reserve_or_auxiliary_only", summary)

    def test_cli_writes_all_three_reports(self) -> None:
        output = self.root / "CLI Output" / "unit-pools.json"
        summary = self.root / "CLI Output" / "unit-pools-summary.md"
        unclassified = self.root / "CLI Output" / "unclassified-unit-tokens.json"
        arguments = ["audit-unit-pools"]
        for root in self.stack:
            arguments.extend(["--stack", str(root)])
        arguments.extend([
            "--output", str(output),
            "--summary", str(summary),
            "--unclassified", str(unclassified),
        ])
        with redirect_stdout(io.StringIO()) as stdout:
            code = entrypoint_main(arguments)
        self.assertEqual(0, code)
        self.assertTrue(output.is_file())
        self.assertTrue(summary.is_file())
        self.assertTrue(unclassified.is_file())
        result = json.loads(stdout.getvalue())
        self.assertTrue(result["ok"])
        self.assertGreater(result["rows"], 0)


if __name__ == "__main__":
    unittest.main()
