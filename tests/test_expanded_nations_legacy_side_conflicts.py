from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.expanded_nations import (
    ExpandedNationsError,
    OPPONENT_UNITS_RELATIVE,
    activate_actor_projection,
    verify_actor_projection,
)
from gates_of_codex.goh_source import scan_source_entries
from tests.test_expanded_nations import _payload


class ExpandedNationsLegacySideConflictTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.layers = [
            self.root / name
            for name in ("vanilla", "west81", "codex", "ai", "gates")
        ]
        for layer in self.layers:
            (layer / "resource").mkdir(parents=True)
        self.gates = self.layers[-1]
        self._write_core_sources()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write(self, priority: int, include: str, text: str) -> None:
        path = self.layers[priority] / "resource/set/multiplayer/units" / include
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _write_core_sources(self) -> None:
        self._write(
            2,
            "conquest/units_ukr.set",
            '{"core_ukr(ukr)" ("squad_with1types_conquest" side(ukr) c1(ukr_rifle:5))}\n',
        )
        self._write(
            3,
            "conquest/units_rusa.set",
            '("squad_with1types_conquest" side(rusa) name(serb_line) c1(Serb_rifleman:5))\n'
            '{"core_rusa(rusa)" ("squad_with1types_conquest" side(rusa) c1(rus_rifle:5))}\n',
        )
        self._write(
            2,
            "conquest/units_nato.set",
            '{"core_nato(nato)" ("squad_with1types_conquest" side(nato) c1(nato_rifle:5))}\n',
        )
        self._write(
            2,
            "conquest/units_sov_era1960.set",
            '{"core_sov(sov)" ("squad_with1types_conquest" side(sov) c1(sov_rifle:5))}\n',
        )
        self._write(
            2,
            "conquest/units_csa_era1960.set",
            '{"squad_pzgren_moto2_con_nato(frg)"\n'
            '  ("squad_vehicle8_warsaw" period(era1960) nation(frg) side(csa) vehicle(m113g) crew1(pzg_vehicleman:2))\n'
            '}\n'
            '{"squad_pzgren_mech_con3_nato(frg)"\n'
            '  ("squad_vehicle8_warsaw" period(era1960) nation(frg) side(csa) vehicle(marder1a1) crew1(pzg_vehicleman:2))\n'
            '}\n'
            '{"squad_jager_moto_con(frg)"\n'
            '  ("squad_vehicle8_warsaw" period(era1960) nation(frg) side(csa) vehicle(m113g) crew1(pzg_vehicleman:2))\n'
            '}\n',
        )
        self._write(
            2,
            "conquest/units_frg_era1960.set",
            '{"core_frg(frg)" ("squad_with1types_conquest" side(frg) c1(frg_rifle:5))}\n',
        )
        self._write(
            2,
            "conquest/units_prc_era1960.set",
            '{"core_prc(prc)" ("squad_with1types_conquest" side(prc) c1(prc_rifle:5))}\n',
        )

    def test_full_activation_preserves_source_backed_legacy_native_side(self) -> None:
        activate_actor_projection(_payload(), self.layers, "srb")
        manifest = verify_actor_projection(self.gates)
        self.assertEqual(manifest["schema_version"], 4)

        expected_names = {
            "squad_pzgren_moto2_con_nato(frg)",
            "squad_pzgren_mech_con3_nato(frg)",
            "squad_jager_moto_con(frg)",
        }
        rows = {
            str(row["entry_name"]): row
            for row in manifest["opponent_units"]
            if str(row["entry_name"]) in expected_names
        }
        self.assertEqual(set(rows), expected_names)
        for row in rows.values():
            self.assertEqual(row["tactical_side"], "frg")
            self.assertEqual(row["native_side"], "csa")
            self.assertNotEqual(row["source_sha256"], "")
            self.assertEqual(row["source_sha256"], row["projected_sha256"])

        generated = (self.gates / OPPONENT_UNITS_RELATIVE).read_text(encoding="utf-8")
        scan = scan_source_entries(generated, OPPONENT_UNITS_RELATIVE.as_posix())
        self.assertFalse(scan.diagnostics)
        sides = {
            entry.name: [
                call.value.lower()
                for call in entry.calls
                if call.family == "side"
            ]
            for entry in scan.entries
            if entry.name in expected_names
        }
        self.assertEqual(set(sides), expected_names)
        self.assertTrue(all(value == ["csa"] for value in sides.values()))

    def test_unbacked_suffix_explicit_conflict_fails_closed(self) -> None:
        self._write(
            2,
            "conquest/units_nato.set",
            '{"ambiguous(frg)" ("squad_with1types_conquest" side(csa) c1(frg_rifle:5))}\n',
        )
        with self.assertRaisesRegex(ExpandedNationsError, "ambiguous side authority"):
            activate_actor_projection(_payload(), self.layers, "srb")


if __name__ == "__main__":
    unittest.main()
