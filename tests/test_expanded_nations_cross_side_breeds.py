from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.expanded_nations_breeds import project_actor_breed_files
from gates_of_codex.expanded_nations_models import (
    BREED_ROOT_RELATIVE,
    GENERATED_MARKER,
    all_managed_candidates,
)


class ExpandedNationsCrossSideBreedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.layers = [self.root / name for name in ("vanilla", "west81", "codex", "ai", "gates")]
        for layer in self.layers:
            (layer / "resource").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _actor(self, *, component: str = "spain_3rd_assault_legion") -> dict:
        return {
            "actor_id": "esp",
            "tactical_side": "nato",
            "units": [
                {
                    "unit_name": "3rd_assault_fixture(nato)",
                    "component_id": component,
                    "source_side": "ukr",
                    "tactical_side": "nato",
                    "period": "2022s",
                    "members": {"azov3_squadlead": 1},
                }
            ],
        }

    def _write_source(self) -> tuple[Path, Path]:
        source_dir = self.layers[2] / "resource/set/breed/mp/ukr/2022s"
        source_dir.mkdir(parents=True)
        breed = source_dir / "azov3_squadlead.set"
        include = source_dir / "ability.inc"
        breed.write_text(
            '{breed\n\t(include "ability.inc")\n\t{skin "fixture"}\n}\n',
            encoding="utf-8",
        )
        include.write_text('(define "fixture_ability" 1)\n', encoding="utf-8")
        return breed, include

    def test_spain_mirrors_exact_source_breed_and_local_include_closure(self) -> None:
        source_breed, source_include = self._write_source()

        outputs = project_actor_breed_files(self._actor(), self.layers)

        breed_relative = BREED_ROOT_RELATIVE / "nato/2022s/azov3_squadlead.set"
        include_relative = BREED_ROOT_RELATIVE / "nato/2022s/ability.inc"
        self.assertEqual({breed_relative, include_relative}, set(outputs))
        for relative in (breed_relative, include_relative):
            self.assertTrue(outputs[relative].decode("utf-8").startswith(GENERATED_MARKER))
        self.assertIn(source_breed.read_text(encoding="utf-8").strip(), outputs[breed_relative].decode("utf-8"))
        self.assertIn(source_include.read_text(encoding="utf-8").strip(), outputs[include_relative].decode("utf-8"))

    def test_existing_target_side_breed_is_never_overwritten(self) -> None:
        self._write_source()
        target = self.layers[3] / "resource/set/breed/mp/nato/2022s/azov3_squadlead.set"
        target.parent.mkdir(parents=True)
        target.write_text('{breed {skin "native_nato"}}\n', encoding="utf-8")

        outputs = project_actor_breed_files(self._actor(), self.layers)

        self.assertEqual({}, outputs)
        self.assertIn("native_nato", target.read_text(encoding="utf-8"))

    def test_cross_side_mirroring_is_not_global(self) -> None:
        self._write_source()
        outputs = project_actor_breed_files(
            self._actor(component="france_national"),
            self.layers,
        )
        self.assertEqual({}, outputs)

    def test_managed_candidate_scan_recovers_dynamic_breed_backup_target(self) -> None:
        target = self.layers[-1] / BREED_ROOT_RELATIVE / "nato/2022s/azov3_squadlead.set"
        target.parent.mkdir(parents=True)
        target.write_text(f"{GENERATED_MARKER}\n{{breed}}\n", encoding="utf-8")
        self.assertIn(target, all_managed_candidates(self.layers[-1]))

        backup = target.with_name(target.name + ".goc-deactivate")
        target.replace(backup)
        self.assertFalse(target.exists())
        self.assertIn(target, all_managed_candidates(self.layers[-1]))


if __name__ == "__main__":
    unittest.main()
