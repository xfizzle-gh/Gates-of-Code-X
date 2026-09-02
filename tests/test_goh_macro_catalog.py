from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.codex.catalog import CodeXCatalogScanner


class GoHMacroCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "codex"
        self.lua_root = self.root / "resource/script/multiplayer/units/nato"
        self.source_root = self.root / "resource/set/multiplayer/units/conquest"
        self.lua_root.mkdir(parents=True)
        self.source_root.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_merges_macro_composition_into_faction_suffixed_lua_rows(self) -> None:
        (self.lua_root / "2022s.lua").write_text(
            """
            return {
              { unit = "squad_test(nato)", type = {"Infantry"}, cost = 10 },
              { unit = "m1097_avenger(nato)", type = {"AA"}, cost = 20 },
              { unit = "m1a2_test(nato)", type = {"Tank"}, cost = 30 },
              { unit = "metadata_only(nato)", type = {"Recon"}, cost = 5 },
            }
            """,
            encoding="utf-8",
        )
        (self.source_root / "units_nato.goh").write_text(
            """
            ("squad_with3types_conquest" side(nato) period(2022s) name(squad_test) c1(rifleman:6) c2(medic:1))
            ("vehicle_conquest" side(nato) period(2022s) name(m1097_avenger)
                crew1(driver:1) crew2(gunner:1))
            ("tank_conquest" side(nato) period(2022s) name(m1a2_test) crew1(tankman:2))
            """,
            encoding="utf-8",
        )

        catalog = CodeXCatalogScanner().scan(self.root)

        self.assertEqual({"rifleman": 6, "medic": 1}, catalog.units["squad_test(nato)"].members)
        self.assertEqual(["m1097_avenger"], catalog.units["m1097_avenger(nato)"].vehicles)
        self.assertEqual({"driver": 1, "gunner": 1}, catalog.units["m1097_avenger(nato)"].members)
        self.assertEqual("air_defense", catalog.units["m1097_avenger(nato)"].category)
        self.assertEqual(["m1a2_test"], catalog.units["m1a2_test(nato)"].vehicles)
        self.assertEqual("tank", catalog.units["m1a2_test(nato)"].category)
        self.assertFalse(catalog.units["metadata_only(nato)"].materializable)
        self.assertEqual(3, len(catalog.by_faction("nato")))
        self.assertEqual({"raw": 4, "materializable": 3}, catalog.diagnostic_counts()["nato"])

    def test_filename_side_and_brace_entries_remain_supported(self) -> None:
        (self.source_root / "inf_nato.set").write_text(
            """
            ("squad_with2types_conquest" period(2022s) name(filename_side_squad)
                c1(rifleman:4) c2(grenadier:2))
            {"brace_squad(nato)"
                {member "scout" 3}
            }
            """,
            encoding="utf-8",
        )

        catalog = CodeXCatalogScanner().scan(self.root)

        self.assertEqual({"rifleman": 4, "grenadier": 2}, catalog.units["filename_side_squad"].members)
        self.assertEqual("nato", catalog.units["filename_side_squad"].side)
        self.assertEqual({"scout": 3}, catalog.units["brace_squad(nato)"].members)
        self.assertEqual(2, len(catalog.by_faction("nato")))

    def test_multiline_squad_withNtypes_merges_members(self) -> None:
        (self.lua_root.parent / "rusa").mkdir(parents=True, exist_ok=True)
        (self.lua_root.parent / "rusa" / "conquest.rusa.lua").write_text(
            '{ unit = "rus90_inf_rifle(rusa)", type = {"Infantry","Squad"} },\n',
            encoding="utf-8",
        )
        (self.source_root / "units_rusa.set").write_text(
            """
("squad_with7types_conquest" side(rusa) period(2022s)
min_stage(1) max_stage(99) name(rus90_inf_rifle)
 c1(rus90_squadlead:1) c2(rus90_seniorrifleman:1) c3(rus90_rifleman:1) c4(rus90_mg:1) c5(rus90_antitank:1) c6(rus90_marksman:1) c7(rus90_medic:1))
            """,
            encoding="utf-8",
        )
        catalog = CodeXCatalogScanner().scan(self.root)
        unit = catalog.units["rus90_inf_rifle(rusa)"]
        self.assertTrue(unit.materializable)
        self.assertEqual(
            {
                "rus90_squadlead": 1,
                "rus90_seniorrifleman": 1,
                "rus90_rifleman": 1,
                "rus90_mg": 1,
                "rus90_antitank": 1,
                "rus90_marksman": 1,
                "rus90_medic": 1,
            },
            unit.members,
        )


if __name__ == "__main__":
    unittest.main()
