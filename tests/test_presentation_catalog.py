from __future__ import annotations

import unittest
from types import SimpleNamespace

from gates_of_codex.europe import build_goe_europe_campaign
from gates_of_codex.presentation_catalog import register_materialized_presentations


class _Units:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def raw_values(self) -> list[object]:
        return list(self._values)


class PresentationCatalogTests(unittest.TestCase):
    def test_group_source_is_copied_to_members_and_vehicles(self) -> None:
        state = build_goe_europe_campaign()
        definition = SimpleNamespace(
            name="west81_motor_rifle(rusa)",
            members={"nva_rifleman": 6, "nva_machinegunner": 1},
            vehicles=("btr60",),
            source_files=(
                "0:West81/resource/set/multiplayer/units/conquest/1980s/units.set",
            ),
            category="infantry",
            side="rusa",
            period="1980s",
        )
        catalog = SimpleNamespace(units=_Units([definition]))

        register_materialized_presentations(state, catalog)
        values = state.map_metadata["unit_presentations"]

        for object_name in (
            "west81_motor_rifle(rusa)",
            "nva_rifleman",
            "nva_machinegunner",
            "btr60",
        ):
            self.assertIn(object_name, values)
            self.assertEqual("West81", values[object_name]["source"]["label"])
            self.assertEqual("W81", values[object_name]["source"]["marker"])
            self.assertEqual("legacy_reserve", values[object_name]["source"]["role"])
        self.assertEqual("Nva Rifleman", values["nva_rifleman"]["display_name"])
        self.assertEqual("nva_rifleman", values["nva_rifleman"]["portrait_key"])
        self.assertEqual("west81_motor_rifle(rusa)", values["btr60"]["catalog_unit"])

    def test_overlay_source_remains_distinct_from_modern_and_legacy(self) -> None:
        state = build_goe_europe_campaign()
        definition = SimpleNamespace(
            name="overlay_unit(nato)",
            members={"overlay_rifleman": 1},
            vehicles=(),
            source_files=(
                "2:Gates-of-Code-X/resource/set/multiplayer/units/overlay.set",
            ),
            category="infantry",
            side="nato",
            period="2022s",
        )
        catalog = SimpleNamespace(units=_Units([definition]))

        register_materialized_presentations(state, catalog)
        source = state.map_metadata["unit_presentations"]["overlay_rifleman"]["source"]

        self.assertEqual("Gates overlay", source["label"])
        self.assertEqual("OVR", source["marker"])
        self.assertEqual("overlay", source["role"])
        self.assertEqual(2, source["priority"])


if __name__ == "__main__":
    unittest.main()
