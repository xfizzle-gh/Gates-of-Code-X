from __future__ import annotations

import unittest

from gates_of_codex.faction_wiring_manifest import load_faction_manifest, validate_faction_manifest


class FactionAuditAdjustmentTest(unittest.TestCase):
    def test_prc_legacy_reserve_contains_exactly_the_audited_rows(self) -> None:
        expected = {
            "artillery_barrage_light_prc",
            "artillery_barrage_medium_prc",
            "artillery_barrage_rocket_prc",
            "artillery_barrage_smoke_prc",
            "mortar_barrage_light_prc",
            "mortar_barrage_medium_prc",
            "mortar_barrage_smoke_prc",
            "paradrop_supply_prc",
            "ptl-02",
            "t62_545",
            "type80",
            "ztz852",
            "ztz853",
            "ztz96a",
        }
        manifest = load_faction_manifest()
        validate_faction_manifest(manifest)
        regular = manifest["components"]["prc_regular"]
        reserve = manifest["components"]["prc_legacy_reserve"]
        actual = {
            unit
            for selector in reserve["selectors"]
            for unit in selector["units"]
        }
        self.assertEqual("modern_only", regular["provenance_policy"])
        self.assertEqual("legacy_explicit", reserve["provenance_policy"])
        self.assertEqual("PRC Legacy / Reserve Equipment", reserve["research_label"])
        self.assertEqual(expected, actual)
        prc = next(actor for actor in manifest["actors"] if actor["actor_id"] == "prc")
        self.assertEqual(["prc_regular", "prc_legacy_reserve"], prc["components"])

        rejected_unverified_west81_support = {
            "airstrike_cluster_prc",
            "airstrike_heavy_prc",
            "airstrike_light_prc",
            "airstrike_wp_prc",
            "artillery_barrage_heavy_prc",
        }
        for selector in regular["selectors"]:
            exclude_regex = selector.get("exclude_regex", "")
            for unit in rejected_unverified_west81_support:
                self.assertIn(unit, exclude_regex)
        self.assertTrue(rejected_unverified_west81_support.isdisjoint(actual))

    def test_canada_receives_directly_source_backed_leopard_2a4m(self) -> None:
        manifest = load_faction_manifest()
        validate_faction_manifest(manifest)
        component = manifest["components"]["canada_national"]
        exact_units = {
            unit
            for selector in component["selectors"]
            if selector["kind"] == "exact"
            for unit in selector["units"]
        }
        self.assertIn("leopard_c2_mexas", exact_units)
        self.assertIn("leopord_2a4m", exact_units)

    def test_finland_does_not_inherit_the_complete_soviet_legacy_pool(self) -> None:
        manifest = load_faction_manifest()
        validate_faction_manifest(manifest)
        finland = next(actor for actor in manifest["actors"] if actor["actor_id"] == "fin")
        self.assertNotIn("soviet_legacy_core", finland["components"])
        self.assertIn("finland_national", finland["components"])
        self.assertIn("nato_common_infantry", finland["components"])
        self.assertIn("nato_common_support", finland["components"])
        self.assertTrue(any("broad Soviet legacy pool" in note for note in finland["notes"]))

    def test_soviet_legacy_core_is_heavy_equipment_only(self) -> None:
        manifest = load_faction_manifest()
        validate_faction_manifest(manifest)
        component = manifest["components"]["soviet_legacy_core"]
        actual = {
            unit
            for selector in component["selectors"]
            if selector["kind"] == "exact"
            for unit in selector["units"]
        }
        self.assertEqual(
            {
                "btr-60pb",
                "btr-80",
                "bmp-1",
                "bmp1p",
                "bmp2",
                "mtlb",
                "t55a",
                "t55am",
                "t72a",
                "t72b",
                "122mm_d-30",
                "bm-21_grad",
                "zsu-23-4m",
                "ural375",
                "ural375_ammo",
            },
            actual,
        )
        self.assertTrue(
            {
                "squad_rifle_con",
                "squad_rifle_moto2_con(sov)",
                "squad_rifle_mech2_con(sov)",
                "squad_guards_con",
                "squad_engineer_moto_con(sov)",
                "squad_medic_moto_con(sov)",
            }.isdisjoint(actual)
        )
        actors = {actor["actor_id"]: actor for actor in manifest["actors"]}
        self.assertIn("serbia_infantry", actors["srb"]["components"])
        self.assertIn("kpa_infantry", actors["dprk"]["components"])
        self.assertIn("donbas_native", actors["donbas"]["components"])
        self.assertIn("belarus_modern_support", actors["blr"]["components"])

    def test_spain_uses_only_the_approved_3rd_assault_legion_infantry_subset(self) -> None:
        manifest = load_faction_manifest()
        validate_faction_manifest(manifest)
        actors = {actor["actor_id"]: actor for actor in manifest["actors"]}
        spain = actors["esp"]
        self.assertEqual(
            ["spain_3rd_assault_legion", "nato_fallback_heavy", "nato_common_support"],
            spain["components"],
        )
        self.assertNotIn("nato_full_fallback", spain["components"])
        component = manifest["components"]["spain_3rd_assault_legion"]
        selector = component["selectors"][0]
        self.assertEqual("exact", selector["kind"])
        self.assertEqual("ukr", selector["source_side"])
        self.assertEqual(
            {
                "3rd_assault_mg3",
                "3rd_assault_at",
                "3rd_assault_javelin",
                "3rd_assault_saperi",
                "3rd_assault_saperi_at",
                "3rd_assault_decepticons",
                "squad_3rd_rozv_hatred(ukr)",
            },
            set(selector["units"]),
        )
        self.assertEqual(
            {"2022nrft", "2022nrfa"},
            {
                selector["root"]
                for selector in manifest["components"]["nato_fallback_heavy"]["selectors"]
            },
        )

    def test_ukraine_uses_native_codex_branches_without_duplicate_ildu_component(self) -> None:
        manifest = load_faction_manifest()
        validate_faction_manifest(manifest)
        actors = {actor["actor_id"]: actor for actor in manifest["actors"]}
        ukraine = actors["ukr"]
        self.assertEqual(["ukraine_regular"], ukraine["components"])
        self.assertEqual("native", ukraine["research"]["mode"])
        self.assertNotIn("ukraine_ildu", ukraine["components"])
        roots = {
            selector["root"]
            for selector in manifest["components"]["ukraine_regular"]["selectors"]
            if selector["kind"] == "research_branch"
        }
        self.assertIn("azov32022", roots)
        compatibility_pool = manifest["components"]["ukraine_ildu"]
        self.assertIn("Compatibility-only", compatibility_pool["description"])
        self.assertNotIn("ukraine_ildu", actors["esp"]["components"])

    def test_audit_notes_are_applied_without_duplicates(self) -> None:
        first = load_faction_manifest()
        second = load_faction_manifest()
        self.assertEqual(first, second)
        for actor_id in ("fin", "can"):
            actor = next(actor for actor in first["actors"] if actor["actor_id"] == actor_id)
            self.assertEqual(len(actor["notes"]), len(set(actor["notes"])))


if __name__ == "__main__":
    unittest.main()
