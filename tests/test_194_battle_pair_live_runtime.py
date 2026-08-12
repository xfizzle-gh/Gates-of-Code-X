"""Native #194 battle-pair live-install regressions.

These tests specifically protect the owner-observed create_dynamic_campaign crash
where pair packs/overlays were present but the live roster selector and patched
conquest.lua were stale or missing from the Workshop destination.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.expanded_nations_battle_pair import (
    BATTLE_PAIR_BACKUP_DIR,
    BATTLE_PAIR_MANIFEST_RELATIVE,
    CONQUEST_LUA_REL,
    ENGINE_RUNTIME_RELS,
    ROSTER_CONQUEST_REL,
    materialize_battle_pair,
    restore_battle_pair,
    verify_battle_pair,
)

ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Phase194BattlePairLiveRuntimeTests(unittest.TestCase):
    def _install(self, dest: Path) -> dict:
        return materialize_battle_pair(
            ROOT,
            attacker_actor_id="usa",
            defender_actor_id="fra",
            output_root=dest,
            source_pack_root=ROOT,
        )

    def test_install_populates_complete_engine_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory)
            result = self._install(dest)
            self.assertTrue(result["ok"])
            self.assertEqual(result["manifest"]["schema_version"], 3)

            for rel in ENGINE_RUNTIME_RELS:
                self.assertTrue((dest / rel).is_file(), rel)
                self.assertIn(rel, result["manifest"]["installed_files"])

            roster = (dest / ROSTER_CONQUEST_REL).read_text(encoding="utf-8")
            self.assertIn("mode=native_battle_pair_dc", roster)
            self.assertIn("inf_goc_usa.set", roster)
            self.assertIn("units_goc_usa.set", roster)
            self.assertIn("inf_goc_fra.set", roster)
            self.assertIn("units_goc_fra.set", roster)
            # Pair selector must not reference a third GOC pack that the pair
            # installer did not copy into this clean destination.
            self.assertNotIn("goc_bel", roster)

            conquest = (dest / CONQUEST_LUA_REL).read_text(encoding="utf-8")
            self.assertIn("local nationMap", conquest)
            self.assertIn("goc_usa", conquest)
            self.assertIn("goc_fra", conquest)

            for side in ("goc_usa", "goc_fra"):
                self.assertTrue(
                    (dest / f"resource/set/multiplayer/units/conquest/units_{side}.set").is_file()
                )
                self.assertTrue(
                    (dest / f"resource/set/multiplayer/units/conquest/inf_{side}.set").is_file()
                )
                self.assertTrue(
                    (dest / f"resource/set/dynamic_campaign/unit_research_{side}.set").is_file()
                )
                self.assertTrue(
                    (dest / f"resource/script/multiplayer/units/{side}/conquest.{side}.lua").is_file()
                )
                self.assertTrue(
                    (dest / f"resource/interface/pages/multi/flag_{side}.tga").is_file()
                )

            self.assertEqual(verify_battle_pair(dest), [])

    def test_stale_live_roster_and_conquest_are_replaced_then_restored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory)
            prior = {
                ROSTER_CONQUEST_REL: "; stale pre-pair roster\n",
                CONQUEST_LUA_REL: "-- stale pre-pair conquest lua\n",
                "resource/set/dynamic_campaign/values.set": "; prior values\n",
            }
            for rel, text in prior.items():
                path = dest / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8", newline="\n")

            self._install(dest)
            self.assertNotEqual(
                (dest / ROSTER_CONQUEST_REL).read_text(encoding="utf-8"),
                prior[ROSTER_CONQUEST_REL],
            )
            self.assertNotEqual(
                (dest / CONQUEST_LUA_REL).read_text(encoding="utf-8"),
                prior[CONQUEST_LUA_REL],
            )
            self.assertEqual(verify_battle_pair(dest), [])

            result = restore_battle_pair(dest)
            self.assertTrue(result["ok"], result)
            for rel, text in prior.items():
                self.assertEqual((dest / rel).read_text(encoding="utf-8"), text, rel)

            # Files absent before the pair are transactional and disappear.
            for side in ("goc_usa", "goc_fra"):
                self.assertFalse(
                    (dest / f"resource/set/multiplayer/units/conquest/units_{side}.set").exists()
                )
                self.assertFalse(
                    (dest / f"resource/interface/pages/multi/flag_{side}.tga").exists()
                )
            self.assertFalse((dest / BATTLE_PAIR_MANIFEST_RELATIVE).exists())
            self.assertFalse((dest / BATTLE_PAIR_BACKUP_DIR).exists())

    def test_verifier_rejects_missing_live_selector_or_conquest_lua(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory)
            self._install(dest)
            (dest / ROSTER_CONQUEST_REL).unlink()
            problems = verify_battle_pair(dest)
            self.assertTrue(
                any("roster_conquest" in item for item in problems),
                problems,
            )

        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory)
            self._install(dest)
            (dest / CONQUEST_LUA_REL).unlink()
            problems = verify_battle_pair(dest)
            self.assertTrue(
                any("conquest.lua" in item for item in problems),
                problems,
            )

    def test_schema_v2_restore_cleans_copied_pack_and_restores_overlay(self) -> None:
        """Forward-compatible cleanup for the pair install used in the failed native run."""
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory)
            pack_rel = "resource/set/multiplayer/units/conquest/units_goc_usa.set"
            pack = dest / pack_rel
            pack.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / pack_rel, pack)

            values_rel = "resource/set/dynamic_campaign/values.set"
            values = dest / values_rel
            values.parent.mkdir(parents=True, exist_ok=True)
            values.write_text("; pair values\n", encoding="utf-8", newline="\n")

            backup = dest / BATTLE_PAIR_BACKUP_DIR / values_rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_text("; prior values\n", encoding="utf-8", newline="\n")

            manifest = {
                "schema": "gates-of-codex.expanded-nations-battle-pair",
                "schema_version": 2,
                "installed_files": {
                    pack_rel: {"sha256": _sha256(pack)},
                    values_rel: {"sha256": _sha256(values)},
                },
                "backups": [
                    {
                        "relative_path": values_rel,
                        "backup_relative": (BATTLE_PAIR_BACKUP_DIR / values_rel).as_posix(),
                    }
                ],
            }
            manifest_path = dest / BATTLE_PAIR_MANIFEST_RELATIVE
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = restore_battle_pair(dest)
            self.assertTrue(result["ok"], result)
            self.assertFalse(pack.exists())
            self.assertEqual(values.read_text(encoding="utf-8"), "; prior values\n")
