from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.faction_wiring_compiler import FactionWiringCompiler
from gates_of_codex.faction_wiring_manifest import (
    _canonical_sha256,
    load_faction_manifest,
    validate_faction_manifest,
)


class FactionLiveStackQuarantineTests(unittest.TestCase):
    def _manifest(self):
        manifest = load_faction_manifest()
        validate_faction_manifest(manifest)
        return manifest

    def test_owner_native_invalid_breed_units_are_excluded_before_resolution(self) -> None:
        manifest = self._manifest()

        donbas = manifest["components"]["donbas_native"]["selectors"][0]
        donbas_exclude = re.compile(donbas["exclude_regex"], re.I)
        self.assertRegex("rus114_inf_rifle", donbas_exclude)
        self.assertRegex("rus114_inf_rifle(rusa)", donbas_exclude)
        self.assertNotRegex("rus114_inf_mg", donbas_exclude)

        kpa = manifest["components"]["kpa_infantry"]["selectors"][0]
        kpa_exclude = re.compile(kpa["exclude_regex"], re.I)
        for name in ("kor_inf_ags", "kor_inf_spg", "kor_inf_ags(rusa)", "kor_inf_spg(rusa)"):
            self.assertRegex(name, kpa_exclude)
        self.assertNotRegex("kor_inf_rifle", kpa_exclude)

    def test_quarantine_does_not_weaken_the_selector_include_boundary(self) -> None:
        manifest = self._manifest()
        kpa = manifest["components"]["kpa_infantry"]["selectors"][0]
        self.assertEqual("research_branch", kpa["kind"])
        self.assertEqual("rusa", kpa["source_side"])
        self.assertEqual("2022vdv106", kpa["root"])
        self.assertEqual("^kor_", kpa["include_regex"])

    def test_compiler_and_earth3_loader_share_exact_manifest_identity(self) -> None:
        expected_manifest = self._manifest()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "stack-root"
            root.mkdir()
            compiler = FactionWiringCompiler([root])
        self.assertEqual(
            _canonical_sha256(expected_manifest),
            _canonical_sha256(compiler.manifest),
        )


if __name__ == "__main__":
    unittest.main()
