from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.map_discovery import discover_maps
from gates_of_codex.profiles import discover_profile_locations


class MapAndProfileDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_discovers_only_map_roots_and_uses_later_overlay(self) -> None:
        base = self.root / "base"
        codex = self.root / "codex"
        overhaul = self.root / "overhaul"

        base_map = base / "resource/map/multi/test_map"
        base_map.mkdir(parents=True)
        (base_map / "map").write_text("base", encoding="utf-8")
        (base_map / "campaign_capture_the_flag.mi").write_text("mode", encoding="utf-8")

        codex_map = codex / "resource/map/multi/codex_map"
        codex_map.mkdir(parents=True)
        (codex_map / "map.mi").write_text("codex", encoding="utf-8")
        (codex_map / "ammunition.mi").write_text("ammo", encoding="utf-8")

        override = overhaul / "resource/map/multi/test_map"
        override.mkdir(parents=True)
        (override / "map").write_text("override", encoding="utf-8")
        (overhaul / "resource/map/random_weather_switch.mi").parent.mkdir(parents=True, exist_ok=True)
        (overhaul / "resource/map/random_weather_switch.mi").write_text("script", encoding="utf-8")

        maps = discover_maps(base, codex, overhaul)
        self.assertEqual(["multi/codex_map", "multi/test_map"], [value.identifier for value in maps])
        selected = next(value for value in maps if value.identifier == "multi/test_map")
        self.assertEqual(str(overhaul.resolve()), selected.source)
        self.assertTrue(selected.path.endswith("multi/test_map/map"))

    def test_discovers_nonstandard_profile_and_likely_save_directory(self) -> None:
        search = self.root / "Users/Tester/AppData/Roaming"
        profile = search / "Call to Arms - Gates of Hell/profiles/123456789"
        save = profile / "campaigns"
        save.mkdir(parents=True)

        values = discover_profile_locations([search], max_depth=8)
        self.assertEqual(1, len(values))
        self.assertEqual(str((search / "Call to Arms - Gates of Hell/profiles").resolve()), values[0].path)
        self.assertIn(str(save.resolve()), values[0].save_directories)


if __name__ == "__main__":
    unittest.main()
