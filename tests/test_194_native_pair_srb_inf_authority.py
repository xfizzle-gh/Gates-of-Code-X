"""Regression for Serbia's native Soviet-era inf define authority."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.expanded_nations_native_pair import (
    CONQUEST_LUA_REL,
    CTF_REL,
    PARENT_RELS,
    ROSTER_REL,
    VALUES_REL,
    install_native_pair,
    restore_native_pair,
    verify_native_pair,
)


class Phase194SerbiaInfAuthorityTests(unittest.TestCase):
    def test_serbia_materializes_proven_soviet_inf_define_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workshop = root / "400750"
            west = workshop / "2897299509"
            codex = workshop / "3261086933"
            aio = workshop / "3636883799"
            for layer in (west, codex, aio):
                layer.mkdir(parents=True, exist_ok=True)

            for rel in PARENT_RELS:
                path = codex / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"; baseline parent {Path(rel).name}\n", encoding="utf-8")

            sov_inf_rel = "resource/set/multiplayer/units/conquest/inf_sov_era1960.set"
            sov_inf = west / sov_inf_rel
            sov_inf.parent.mkdir(parents=True, exist_ok=True)
            sov_inf.write_text(
                "; WEST81_SOV_INF_AUTHORITY\n"
                "(define \"sov_guncrew\" {cost 5})\n"
                '{"mp/sov/era1960/sup_guncrew" ("sov_guncrew" side(sov)) {cost 5}}\n',
                encoding="utf-8",
            )

            sov_breed = west / "resource/set/breed/mp/sov/era1960"
            sov_breed.mkdir(parents=True, exist_ok=True)
            (sov_breed / "ability.inc").write_text("; sov ability\n", encoding="utf-8")
            (sov_breed / "sup_guncrew.set").write_text(
                '(include "ability.inc")\n{breed sov_guncrew}\n', encoding="utf-8"
            )

            rusa_breed = codex / "resource/set/breed/mp/rusa/2022s"
            rusa_breed.mkdir(parents=True, exist_ok=True)
            (rusa_breed / "ability.inc").write_text("; rusa ability\n", encoding="utf-8")
            (rusa_breed / "rus_rifleman.set").write_text(
                '(include "ability.inc")\n{breed rusa_rifleman}\n', encoding="utf-8"
            )

            values = codex / VALUES_REL
            values.parent.mkdir(parents=True, exist_ok=True)
            values.write_text(
                "{Regions\n"
                "\t{Europe\n\t\t{AvailableMatchups\n\t\t\t\"rusa nato\"\n\t\t}\n\t}\n"
                "}\n{GameModes\n\t\"campaign_capture_the_flag\"\n}\n",
                encoding="utf-8",
            )

            ctf = aio / CTF_REL
            ctf.parent.mkdir(parents=True, exist_ok=True)
            ctf.write_text(
                '(define "bot_state" {unitset {value "conquest"}})\n'
                "{game\n"
                "\t{settings {difficulty multiplayer}}\n"
                "\t{teamSettings {alliances (include \"presets/alliances_generic.inc\")}}\n"
                "\t{presets {\"d:campaign\" {bots {normal (\"bot_state\")}}}}\n"
                "}\n",
                encoding="utf-8",
            )

            source = root / "source"
            for side in ("goc_srb", "goc_rus"):
                files = {
                    f"resource/set/multiplayer/units/conquest/units_{side}.set":
                        f'; unit fixture {side}\n("fixture" side({side}))\n',
                    f"resource/set/dynamic_campaign/unit_research_{side}.set": "; research fixture\n",
                    f"resource/script/multiplayer/units/{side}/conquest.{side}.lua": "Purchases = {}\n",
                    f"resource/set/multiplayer/armies/{side}.set": f'{{army "{side}"}}\n',
                }
                for rel, text in files.items():
                    path = source / rel
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text, encoding="utf-8")
                flag = source / f"resource/interface/pages/multi/flag_{side}.tga"
                flag.parent.mkdir(parents=True, exist_ok=True)
                flag.write_bytes(b"fixture-tga")

            srb_inf = source / "resource/set/multiplayer/units/conquest/inf_goc_srb.set"
            srb_inf.parent.mkdir(parents=True, exist_ok=True)
            srb_inf.write_text(
                '; goc-inf-cost {"cost":5.0,"source_path":"mp/sov/era1960/sup_guncrew",'
                '"source_reference":"1:2897299509/set/multiplayer/units/conquest/inf_sov_era1960.set",'
                '"target_path":"mp/goc_srb/era1960/sup_guncrew"}\n'
                '{"mp/goc_srb/era1960/sup_guncrew" ("sov_guncrew" side(goc_srb)) {cost 5}}\n',
                encoding="utf-8",
            )
            rus_inf = source / "resource/set/multiplayer/units/conquest/inf_goc_rus.set"
            rus_inf.parent.mkdir(parents=True, exist_ok=True)
            rus_inf.write_text(
                '{"mp/goc_rus/2022s/rus_rifleman" ("rusa_banner" side(goc_rus)) {cost 10}}\n',
                encoding="utf-8",
            )

            conquest = source / CONQUEST_LUA_REL
            conquest.parent.mkdir(parents=True, exist_ok=True)
            conquest.write_text(
                "local nationMap = { rusa = 1, goc_srb = 94, goc_rus = 18 }\n"
                "local westNations = { nato = true, ukr = true }\n"
                "local eastNations = { rusa = true, prc = true, goc_srb = true, goc_rus = true }\n",
                encoding="utf-8",
            )

            resolved = {
                "error_count": 0,
                "actors": [
                    {
                        "actor_id": "srb",
                        "playable": True,
                        "tactical_side": "goc_srb",
                        "components": ["soviet_legacy_core"],
                        "units": [
                            {
                                "unit_name": "legacy_support(goc_srb)",
                                "component_id": "soviet_legacy_core",
                                "source_side": "sov",
                                "period": "era1960",
                                "members": {"sup_guncrew": 1},
                            }
                        ],
                    },
                    {
                        "actor_id": "rus",
                        "playable": True,
                        "tactical_side": "goc_rus",
                        "components": ["russia_fixture"],
                        "units": [
                            {
                                "unit_name": "rifle_fixture(goc_rus)",
                                "component_id": "russia_fixture",
                                "source_side": "rusa",
                                "period": "2022s",
                                "members": {"rus_rifleman": 1},
                            }
                        ],
                    },
                ],
            }

            gates = workshop / "3696721120"
            gates.mkdir()
            result = install_native_pair(
                source,
                gates,
                workshop,
                "srb",
                "rus",
                resolved_payload=resolved,
            )
            self.assertTrue(result["ok"])
            manifest = result["manifest"]
            self.assertEqual(manifest["supplemental_parent_inf"], ["inf_sov_era1960.set"])

            installed_sov_inf = gates / sov_inf_rel
            self.assertTrue(installed_sov_inf.is_file())
            self.assertIn("WEST81_SOV_INF_AUTHORITY", installed_sov_inf.read_text(encoding="utf-8"))

            roster = (gates / ROSTER_REL).read_text(encoding="utf-8")
            self.assertIn('(include "conquest/inf_sov_era1960.set")', roster)
            self.assertLess(
                roster.index('include "conquest/inf_sov_era1960.set"'),
                roster.index('include "conquest/inf_goc_srb.set"'),
            )
            self.assertEqual(verify_native_pair(gates), [])

            restored = restore_native_pair(gates)
            self.assertTrue(restored["ok"])
            self.assertFalse(installed_sov_inf.exists())


if __name__ == "__main__":
    unittest.main()
