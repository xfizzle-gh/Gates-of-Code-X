"""Regression: #194 native staging preserves #201 and materializes personnel breeds."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.expanded_nations_native_pair import (
    ALLIANCES_REL,
    CONQUEST_LUA_REL,
    CTF_REL,
    PARENT_NAMES,
    PARENT_RELS,
    ROSTER_REL,
    VALUES_REL,
    install_native_pair,
    restore_native_pair,
    verify_native_pair,
)


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

        breed_root = codex / "resource/set/breed/mp/nato/2022s"
        breed_root.mkdir(parents=True, exist_ok=True)
        (breed_root / "shared.inc").write_text("; shared breed include\n", encoding="utf-8")
        (breed_root / "nato_rifleman.set").write_text(
            '(include "shared.inc")\n{breed rifleman}\n', encoding="utf-8"
        )
        (breed_root / "nato_medic.set").write_text(
            '(include "shared.inc")\n{breed medic}\n', encoding="utf-8"
        )

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

    def _fake_source(self, root: Path) -> Path:
        for side, breed in (("goc_usa", "nato_rifleman"), ("goc_fra", "nato_medic")):
            files = {
                f"resource/set/multiplayer/units/conquest/units_{side}.set":
                    f'; resolved_unit=squad_fixture({side})\n("fixture" side({side}) period(2022s) c1({breed}:1))\n',
                f"resource/set/multiplayer/units/conquest/inf_{side}.set":
                    f'{{"mp/{side}/2022s/{breed}" ("nato_basic" side({side})) {{cost 10}}}}\n',
                f"resource/set/dynamic_campaign/unit_research_{side}.set": "; research fixture\n",
                f"resource/script/multiplayer/units/{side}/conquest.{side}.lua": "Purchases = {}\n",
                f"resource/set/multiplayer/armies/{side}.set": f'{{army "{side}"}}\n',
            }
            for rel, text in files.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            flag = root / f"resource/interface/pages/multi/flag_{side}.tga"
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_bytes(b"fixture-tga")

        conquest = root / CONQUEST_LUA_REL
        conquest.parent.mkdir(parents=True, exist_ok=True)
        conquest.write_text(
            "local nationMap = { nato = 3, rusa = 1, goc_usa = 14, goc_fra = 17 }\n"
            "local westNations = { nato = true, ukr = true, goc_usa = true, goc_fra = true }\n"
            "local eastNations = { rusa = true, prc = true }\n",
            encoding="utf-8",
        )
        return root

    @staticmethod
    def _resolved_payload() -> dict[str, object]:
        return {
            "error_count": 0,
            "actors": [
                {
                    "actor_id": "usa",
                    "playable": True,
                    "tactical_side": "goc_usa",
                    "components": ["nato_us_forces"],
                    "units": [
                        {
                            "unit_name": "squad_fixture(goc_usa)",
                            "component_id": "nato_us_forces",
                            "source_side": "nato",
                            "period": "2022s",
                            "members": {"nato_rifleman": 1},
                        }
                    ],
                },
                {
                    "actor_id": "fra",
                    "playable": True,
                    "tactical_side": "goc_fra",
                    "components": ["nato_common_infantry"],
                    "units": [
                        {
                            "unit_name": "squad_fixture(goc_fra)",
                            "component_id": "nato_common_infantry",
                            "source_side": "nato",
                            "period": "2022s",
                            "members": {"nato_medic": 1},
                        }
                    ],
                },
            ],
        }

    def test_real_stack_projection_matches_201_native_contract_and_breed_closure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workshop = self._fake_workshop(root / "400750")
            source = self._fake_source(root / "source")
            gates = workshop / "3696721120"
            gates.mkdir()

            result = install_native_pair(
                source,
                gates,
                workshop,
                "usa",
                "fra",
                resolved_payload=self._resolved_payload(),
            )
            self.assertTrue(result["ok"])
            manifest = result["manifest"]
            self.assertEqual(manifest["native_recipe"], "#201-final-layer-v1")
            self.assertEqual(manifest["schema_version"], 2)
            self.assertGreater(manifest["breed_counts"]["goc_usa"], 0)
            self.assertGreater(manifest["breed_counts"]["goc_fra"], 0)

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

            usa_breed = gates / "resource/set/breed/mp/goc_usa/2022s/nato_rifleman.set"
            fra_breed = gates / "resource/set/breed/mp/goc_fra/2022s/nato_medic.set"
            for breed in (usa_breed, fra_breed):
                self.assertTrue(breed.is_file())
                self.assertIn("cross-side-breed-source=nato/2022s/", breed.read_text(encoding="utf-8"))
                self.assertTrue((breed.parent / "shared.inc").is_file())

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

            conquest = (gates / CONQUEST_LUA_REL).read_text(encoding="utf-8")
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
            self.assertFalse(usa_breed.exists())
            self.assertFalse(fra_breed.exists())


if __name__ == "__main__":
    unittest.main()
