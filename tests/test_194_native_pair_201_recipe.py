"""Regression: #194 native staging must preserve the proven #201 recipe."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.expanded_nations_native_pair import (
    ALLIANCES_REL,
    CTF_REL,
    PARENT_NAMES,
    PARENT_RELS,
    ROSTER_REL,
    VALUES_REL,
    install_native_pair,
    restore_native_pair,
    verify_native_pair,
)

ROOT = Path(__file__).resolve().parents[1]


class Phase194NativePair201RecipeTests(unittest.TestCase):
    def _fake_workshop(self, root: Path) -> Path:
        west = root / "2897299509"
        codex = root / "3261086933"
        aio = root / "3636883799"
        for layer in (west, codex, aio):
            layer.mkdir(parents=True, exist_ok=True)

        for rel, name in zip(PARENT_RELS, PARENT_NAMES):
            path = codex / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"; codex parent {name}\n", encoding="utf-8")
        settings = aio / PARENT_RELS[0]
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text("; aio effective settings\n", encoding="utf-8")

        values = codex / VALUES_REL
        values.parent.mkdir(parents=True, exist_ok=True)
        values.write_text(
            "; PARENT_VALUES_SENTINEL\n"
            "{Regions\n"
            "\t{Europe\n\t\t{AvailableMatchups\n\t\t\t\"nato rusa\"\n\t\t}\n\t}\n"
            "\t{Asia\n\t\t{AvailableMatchups\n\t\t\t\"ukr rusa\"\n\t\t}\n\t}\n"
            "\t{Test\n\t\t{AvailableMatchups\n\t\t\t\"usa rus\"\n\t\t}\n\t}\n"
            "}\n{GameModes\n\t\"campaign_capture_the_flag\"\n}\n",
            encoding="utf-8",
        )

        ctf = aio / CTF_REL
        ctf.parent.mkdir(parents=True, exist_ok=True)
        ctf.write_text(
            "; FULL_AIO_CTF_SENTINEL\n"
            "(define \"bot_state\" {unitset {value \"conquest\"}})\n"
            "{game\n"
            "\t{settings {difficulty multiplayer} {enableBots 1}}\n"
            "\t{teamSettings\n"
            "\t\t{armySelectionMode alliance}\n"
            "\t\t{alliances (include \"presets/alliances_generic.inc\")}\n"
            "\t}\n"
            "\t{presets {\"d:campaign\" {bots {normal (\"bot_state\")}}}}\n"
            "}\n",
            encoding="utf-8",
        )
        return root

    def test_real_stack_projection_matches_201_native_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workshop = self._fake_workshop(Path(directory) / "400750")
            gates = workshop / "3696721120"
            gates.mkdir()

            result = install_native_pair(
                ROOT,
                gates,
                workshop,
                "usa",
                "fra",
            )
            self.assertTrue(result["ok"])
            manifest = result["manifest"]
            self.assertEqual(manifest["native_recipe"], "#201-final-layer-v1")

            roster = (gates / ROSTER_REL).read_text(encoding="utf-8")
            self.assertNotIn("inf_frg_era1960.set", roster)
            self.assertNotIn("inf_sov_era1960.set", roster)
            self.assertNotIn("units_frg_era1960.set", roster)
            for rel in PARENT_RELS:
                self.assertTrue((gates / rel).is_file(), rel)
            self.assertIn(
                "aio effective settings",
                (gates / PARENT_RELS[0]).read_text(encoding="utf-8"),
            )

            ctf = (gates / CTF_REL).read_text(encoding="utf-8")
            self.assertIn("FULL_AIO_CTF_SENTINEL", ctf)
            self.assertIn("{settings", ctf)
            self.assertIn("{presets", ctf)
            self.assertIn("{bots", ctf)

            values = (gates / VALUES_REL).read_text(encoding="utf-8")
            self.assertIn("PARENT_VALUES_SENTINEL", values)
            self.assertIn('"goc_usa goc_fra"', values)
            self.assertIn('"goc_fra goc_usa"', values)

            alliances = (gates / ALLIANCES_REL).read_text(encoding="utf-8")
            for side in ("nato", "ukr", "rusa", "prc", "goc_usa", "goc_fra"):
                self.assertIn(f'{{armies "{side}"}}', alliances)

            conquest = (
                gates / "resource/script/multiplayer/modes/conquest.lua"
            ).read_text(encoding="utf-8")
            west_body = conquest.split("local westNations = {", 1)[1].split("}", 1)[0]
            east_body = conquest.split("local eastNations = {", 1)[1].split("}", 1)[0]
            self.assertIn("goc_usa = true", west_body)
            self.assertNotIn("goc_fra = true", west_body)
            self.assertIn("goc_fra = true", east_body)

            self.assertEqual(verify_native_pair(gates), [])

            restored = restore_native_pair(gates)
            self.assertTrue(restored["ok"])
            for rel in PARENT_RELS:
                self.assertFalse((gates / rel).exists(), rel)


if __name__ == "__main__":
    unittest.main()
