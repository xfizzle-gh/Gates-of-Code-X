from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPIKE = ROOT / "spikes" / "201-custom-tactical-factions"
RESOURCE = SPIKE / "resource"

PROTOTYPES = {
    "goc_usa": {"army_id": 90, "nation_map": 9, "coalition": "west"},
    "goc_fra": {"army_id": 91, "nation_map": 10, "coalition": "east"},
    "goc_srb": {"army_id": 92, "nation_map": 11, "coalition": "east"},
    "goc_rus": {"army_id": 93, "nation_map": 12, "coalition": "east"},
    "goc_dprk": {"army_id": 94, "nation_map": 13, "coalition": "east"},
}

REQUIRED_MATCHUPS = {
    ("goc_usa", "goc_fra"),
    ("goc_fra", "goc_usa"),
    ("goc_srb", "goc_rus"),
    ("goc_rus", "goc_srb"),
    ("goc_usa", "goc_dprk"),
    ("goc_dprk", "goc_usa"),
}

FORBIDDEN_RESEARCH_SIDES = ("nato", "rusa", "prc", "ukr", "sov", "csa")
PARENT_CONQUEST = (
    "settings.set",
    "inf_ukr.set",
    "inf_rusa.set",
    "inf_nato.set",
    "inf_prc_era1960.set",
    "inf_csa_era1960.set",
    "units_ukr.set",
    "units_rusa.set",
    "units_nato.set",
    "units_sov_era1960.set",
    "units_csa_era1960.set",
    "units_prc_era1960.set",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _unit_ids_for(faction: str) -> set[str]:
    text = _read(RESOURCE / "set" / "multiplayer" / "units" / "conquest" / f"units_{faction}.set")
    return set(re.findall(rf'\{{\s*"({re.escape(faction)}_test_[^"]+\({re.escape(faction)}\))"', text))


class CustomTacticalFactionSpikeTests(unittest.TestCase):
    def test_army_ids_in_range_and_unique(self) -> None:
        seen: dict[int, str] = {}
        for faction, meta in PROTOTYPES.items():
            army_path = RESOURCE / "set" / "multiplayer" / "armies" / f"{faction}.set"
            self.assertTrue(army_path.is_file(), faction)
            text = _read(army_path)
            match = re.search(r"\{id\s+(\d+)\}", text)
            self.assertIsNotNone(match, faction)
            army_id = int(match.group(1))
            self.assertEqual(meta["army_id"], army_id)
            self.assertGreaterEqual(army_id, 0)
            self.assertLessEqual(army_id, 99)
            self.assertNotIn(army_id, seen)
            seen[army_id] = faction

    def test_effective_stack_collision_audit_logic_exists(self) -> None:
        deploy = _read(SPIKE / "deploy.ps1")
        self.assertIn("Get-ArmyIdMap", deploy)
        self.assertIn("PrototypeArmyIds", deploy)
        self.assertIn("idCollisions", deploy)
        self.assertIn("ParentConquestFiles", deploy)
        self.assertIn("sha256", deploy.lower())
        self.assertIn("roster_conquest.set", deploy)
        self.assertIn("Restore", deploy)

    def test_alliances_list_prototypes(self) -> None:
        for name in (
            "alliances_generic.inc",
            "alliances_goc_201.inc",
            "alliances_modern_conquest.inc",
        ):
            text = _read(RESOURCE / "set" / "multiplayer" / "games" / "presets" / name)
            for faction, meta in PROTOTYPES.items():
                self.assertIn(f'{{armies "{faction}"}}', text)
                if meta["coalition"] == "west":
                    west = text.split('{"East"', 1)[0]
                    self.assertIn(f'{{armies "{faction}"}}', west)
                else:
                    east = text.split('{"East"', 1)[1]
                    self.assertIn(f'{{armies "{faction}"}}', east)

    def test_required_matchups_present(self) -> None:
        text = _read(RESOURCE / "set" / "dynamic_campaign" / "values.set")
        pairs = set(re.findall(r'"(\S+)\s+(\S+)"', text))
        for pair in REQUIRED_MATCHUPS:
            self.assertIn(pair, pairs)

    def test_roster_includes_resolve_in_prepared_tree(self) -> None:
        roster = _read(RESOURCE / "set" / "multiplayer" / "units" / "roster_conquest.set")
        includes = re.findall(r'\(include\s+"([^"]+)"\)', roster)
        self.assertTrue(includes)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conquest = root / "conquest"
            conquest.mkdir(parents=True)
            # Parent placeholders for includes the spike does not vendor.
            for name in PARENT_CONQUEST:
                (conquest / name).write_text(f"; parent placeholder {name}\n", encoding="utf-8")
            # Copy GOC files from spike.
            src = RESOURCE / "set" / "multiplayer" / "units" / "conquest"
            for path in src.glob("*.set"):
                (conquest / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            for inc in includes:
                target = root / Path(inc)
                self.assertTrue(target.is_file(), f"unresolved include: {inc}")

    def test_research_trees_isolated_and_resolvable(self) -> None:
        for faction in PROTOTYPES:
            research = _read(
                RESOURCE / "set" / "dynamic_campaign" / f"unit_research_{faction}.set"
            )
            for side in FORBIDDEN_RESEARCH_SIDES:
                self.assertNotRegex(
                    research,
                    rf'\([^\n"]*{re.escape(side)}\)',
                    msg=f"{faction} research leaks side {side}",
                )
            unit_ids = _unit_ids_for(faction)
            self.assertGreaterEqual(len(unit_ids), 3, faction)
            unlocked = set(re.findall(r'\{"([^"]+)"\s+requires', research))
            self.assertTrue(unlocked, faction)
            for unit in unlocked:
                self.assertIn(unit, unit_ids)
                self.assertTrue(unit.endswith(f"({faction})"))
            # requires targets must resolve to tech or unit in same file
            defined = set(
                re.findall(r'\{\s*(?:tech\s+)?"([^"]+)"\s+requires', research)
            ) | set(re.findall(r'tech\s+"([^"]+)"', research))
            for req in re.findall(r'requires\s+"([^"]*)"', research):
                if not req:
                    continue
                self.assertIn(req, defined, msg=f"{faction} missing requires target {req}")

    def test_purchase_lua_schema_and_faction_isolation(self) -> None:
        for faction in PROTOTYPES:
            path = (
                RESOURCE
                / "script"
                / "multiplayer"
                / "units"
                / faction
                / f"conquest.{faction}.lua"
            )
            text = _read(path)
            self.assertIn("Repeat", text)
            self.assertIn("Units", text)
            self.assertIn("priority", text)
            self.assertIn("type", text)
            self.assertIn("unit", text)
            self.assertIn(f'Purchases["conquest.{faction}"]', text)
            units = re.findall(r'unit\s*=\s*"([^"]+)"', text)
            self.assertTrue(units, faction)
            allowed = _unit_ids_for(faction)
            for unit in units:
                self.assertIn(unit, allowed)
                self.assertTrue(unit.endswith(f"({faction})"))
                for other in PROTOTYPES:
                    if other == faction:
                        continue
                    self.assertNotIn(f"({other})", unit)
            # No generic core side purchases.
            for side in FORBIDDEN_RESEARCH_SIDES:
                self.assertNotRegex(text, rf'\({side}\)')

    def test_conquest_lua_nation_and_coalition_maps(self) -> None:
        text = _read(RESOURCE / "script" / "multiplayer" / "modes" / "conquest.lua")
        for faction, meta in PROTOTYPES.items():
            self.assertRegex(text, rf"\b{re.escape(faction)}\s*=\s*{meta['nation_map']}\b")
        west = re.search(r"local westNations\s*=\s*\{([^}]*)\}", text)
        east = re.search(r"local eastNations\s*=\s*\{([^}]*)\}", text)
        self.assertIsNotNone(west)
        self.assertIsNotNone(east)
        assert west is not None and east is not None
        for faction, meta in PROTOTYPES.items():
            blob = west.group(1) if meta["coalition"] == "west" else east.group(1)
            self.assertRegex(blob, rf"\b{re.escape(faction)}\s*=\s*true")
        self.assertNotRegex(west.group(1), r"\bgoc_fra\s*=\s*true")

    def test_deploy_standalone_is_idempotent_validator(self) -> None:
        script = _read(SPIKE / "deploy_standalone.ps1")
        self.assertIn("Source conquest.lua is authoritative", script)
        self.assertNotIn("-replace 'local eastNations", script)
        self.assertIn("do not mutate", script.lower() + " " + script)
        # Functional: dry-run validation path by invoking script against temp game root.
        with tempfile.TemporaryDirectory() as tmp:
            game_root = Path(tmp) / "game"
            (game_root / "mods").mkdir(parents=True)
            # PowerShell 5.1
            cmd = [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SPIKE / "deploy_standalone.ps1"),
                "-GameRoot",
                str(game_root),
            ]
            first = subprocess.run(cmd, capture_output=True, text=True, check=False)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            second = subprocess.run(cmd, capture_output=True, text=True, check=False)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            deployed_lua = (
                game_root
                / "mods"
                / "goc_201_faction_spike"
                / "resource"
                / "script"
                / "multiplayer"
                / "modes"
                / "conquest.lua"
            )
            source_lua = (
                RESOURCE / "script" / "multiplayer" / "modes" / "conquest.lua"
            )
            self.assertEqual(
                hashlib.sha256(deployed_lua.read_bytes()).hexdigest(),
                hashlib.sha256(source_lua.read_bytes()).hexdigest(),
            )

    def test_test_a_files_still_present(self) -> None:
        for faction in ("goc_usa", "goc_fra"):
            self.assertTrue(
                (RESOURCE / "set" / "multiplayer" / "armies" / f"{faction}.set").is_file()
            )
            self.assertTrue(
                (
                    RESOURCE
                    / "set"
                    / "multiplayer"
                    / "units"
                    / "conquest"
                    / f"units_{faction}.set"
                ).is_file()
            )
            self.assertTrue(
                (
                    RESOURCE
                    / "script"
                    / "multiplayer"
                    / "units"
                    / faction
                    / f"conquest.{faction}.lua"
                ).is_file()
            )


if __name__ == "__main__":
    unittest.main()
