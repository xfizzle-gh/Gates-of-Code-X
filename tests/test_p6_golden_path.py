"""P6 production golden path through stack, Earth3, Godot, and GoH seams."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


class ProductionStackFixture:
    """Small but complete filesystem stack consumed by production scanners."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.game = root / "Call to Arms - Gates of Hell"
        self.west = root / "2897299509"
        self.codex = root / "3261086933"
        self.ai = root / "3636883799"
        self.gates = root / "3696721120"
        self.profile = root / "profile"
        self.install = self.profile / "campaign"
        self.stack_config = root / "portable-stack.json"
        self._unit_lines: dict[tuple[Path, str], list[str]] = {}
        self._registry_lines: dict[Path, set[str]] = {}
        self._research_lines: dict[str, list[str]] = {}
        self._defined: set[tuple[Path, str, str]] = set()

    @property
    def layers(self) -> list[Path]:
        return [self.game, self.west, self.codex, self.ai, self.gates]

    def write(self) -> None:
        from gates_of_codex.bridge.archive import CampaignSaveArchive
        from gates_of_codex.faction_wiring_manifest import load_faction_manifest

        for path in (*self.layers, self.install):
            path.mkdir(parents=True, exist_ok=True)
        for path, name in (
            (self.west, "West81"),
            (self.codex, "Code:X"),
            (self.ai, "CodeX Conquest AI Overhaul"),
            (self.gates, "Gates of Code:X"),
        ):
            self._write(path / "mod.info", f'{{mod {{name "{name}"}}}}\n')
            (path / "resource").mkdir(exist_ok=True)

        self._write(self.game / "resource/gamelogic.pak", "fixture\n")
        (self.game / "resource/entity").mkdir(parents=True)
        self._write(self.game / "binaries/x64/gates_of_hell.exe", "fixture\n")
        self._write(
            self.game / "resource/map/multi/2x2/stack_test/map", "{map}\n"
        )
        self._write(
            self.ai / "resource/script/ai-overhaul.lua",
            "return { recognizeTime = 0.05 }\n",
        )

        manifest = load_faction_manifest()
        for component in manifest["components"].values():
            for selector in component["selectors"]:
                kind = selector["kind"]
                if kind == "research_branch":
                    self._add_branch(selector)
                elif kind == "exact":
                    layer = (
                        self.west
                        if component.get("provenance_policy") == "legacy_explicit"
                        or selector.get("source_side") in {"sov", "frg", "gdr", "csa"}
                        else self.codex
                    )
                    for name in selector["units"]:
                        self._add_vehicle_unit(
                            layer,
                            str(selector.get("source_side") or self._side(name)),
                            str(name),
                        )
                elif kind == "virtual":
                    for unit in selector["units"]:
                        side = str(unit["source_side"])
                        for breed in unit.get("members", {}):
                            self._write_breed(side, str(breed))
                        for vehicle in unit.get("vehicles", []):
                            self._registry_lines.setdefault(self.gates, set()).add(
                                str(vehicle)
                            )
                else:
                    raise AssertionError(f"unsupported bundled selector in fixture: {kind}")

        # The stack validator consumes the same Code:X source files through its
        # Lua catalog surface. These four entries prove all tactical sides have
        # materializable content before Earth3 compilation starts.
        lua: list[str] = []
        for side in ("nato", "ukr", "rusa", "prc"):
            name = f"stack_rifle({side})"
            breed = f"stack_rifleman_{side}"
            self._unit_lines.setdefault((self.codex, side), []).append(
                f'{{"{name}" {{member "{breed}" 4}}}}\n'
            )
            self._write_breed(side, breed)
            lua.append(
                f'{{priority=1, type={{"Infantry","Squad"}}, unit="{name}"}},\n'
            )
        self._write(
            self.codex / "resource/script/multiplayer/units/nato/2022s.nato.lua",
            "".join(lua),
        )

        for (layer, side), lines in self._unit_lines.items():
            self._write(
                layer
                / f"resource/set/multiplayer/units/conquest/2022s/units_{side}.set",
                "".join(lines),
            )
        for layer, entity_ids in self._registry_lines.items():
            self._write(
                layer / "resource/set/registry/unit.reg",
                "".join(f'{{"{value}"}}\n' for value in sorted(entity_ids)),
            )
        for side, lines in self._research_lines.items():
            self._write(
                self.codex / f"resource/set/dynamic_campaign/unit_research_{side}.set",
                "".join(lines),
            )

        CampaignSaveArchive().write(
            self.install / "conquest template.sav",
            status=(
                "{saveinfo\n"
                "\t{version 7}\n"
                '\t{gameVersion "1.065.0"}\n'
                "\t{timestamp 1}\n"
                "\t{mp 1000}\n\t{sp 100}\n\t{ap 100}\n\t{rp 100}\n"
                "\t{seed 123}\n"
                '\t{name "P6 Fixture Conquest"}\n'
                "\t{army nato}\n\t{enemyArmy rusa}\n"
                "\t{difficulty normal}\n\t{duration 4}\n\t{resources 0}\n"
                "\t{playedGames 0}\n\t{wonGames 0}\n"
                "\t{unlockedResearch\n\t}\n"
                "}\n"
            ),
            campaign_scn="{campaign}\n",
        )
        self.stack_config.write_text(
            json.dumps(
                {
                    "layers": [
                        {
                            "role": "vanilla",
                            "name": "Vanilla",
                            "path": str(self.game),
                            "sentinels": ["resource/entity", "resource/gamelogic.pak"],
                        },
                        {
                            "role": "west81",
                            "name": "West81",
                            "path": str(self.west),
                            "accepted_mod_names": ["West81", "West-81"],
                        },
                        {
                            "role": "codex",
                            "name": "Code:X",
                            "path": str(self.codex),
                            "accepted_mod_names": ["Code:X", "Code-X"],
                        },
                        {
                            "role": "codex_ai_overhaul",
                            "name": "Code:X AI Overhaul",
                            "path": str(self.ai),
                            "accepted_mod_names": ["CodeX Conquest AI Overhaul"],
                        },
                        {
                            "role": "gates_codex",
                            "name": "Gates of Code:X",
                            "path": str(self.gates),
                            "accepted_mod_names": ["Gates of Code:X", "Gates of CodeX"],
                        },
                    ]
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def _add_branch(self, selector: dict) -> None:
        side = str(selector["source_side"])
        root = str(selector["root"])
        lines = self._research_lines.setdefault(side, [])
        lines.append(f'{{ tech "{root}" requires "" costs 1 position 0 0}}\n')
        names = [
            (f"{root}_inf_rifle", f"{root}_inf_rifle"),
            (f"{root}_tank", f"{root}_tank"),
            (f"{root}_arty", f"{root}_arty"),
        ]
        include = str(selector.get("include_regex") or "")
        if root == "2022arf":
            names = [("squad_arf_rifle", "squad_arf_rifle(nato)")]
        elif include.startswith("^kor_"):
            names = [("kor_100_rifle", "kor_100_rifle")]
        elif include and "wgn" in include:
            names = [("wgn_100_rifle", "wgn_100_rifle")]
        for index, (research_name, unit_name) in enumerate(names, start=1):
            self._add_vehicle_unit(self.codex, side, unit_name)
            lines.append(
                f'{{"{research_name}" requires "{root}" costs 1 position {index} 0}}\n'
            )

    def _add_vehicle_unit(self, layer: Path, side: str, name: str) -> None:
        key = (layer, side, name)
        if key in self._defined:
            return
        self._defined.add(key)
        # Keep the entity identifier category-neutral. Category inference also
        # examines referenced entity text, so random hash fragments such as
        # ``a10`` can otherwise turn a tank fixture into aviation content.
        entity = f"fixture_entity_{len(self._defined):04d}"
        self._unit_lines.setdefault((layer, side), []).append(
            f'{{"{name}" {{vehicle "{entity}"}}}}\n'
        )
        self._registry_lines.setdefault(layer, set()).add(entity)

    def _write_breed(self, side: str, breed: str) -> None:
        self._write(
            self.codex / f"resource/set/breed/mp/{side}/2022s/{breed}.set",
            "{breed}\n",
        )

    @staticmethod
    def _side(name: str) -> str:
        match = re.search(r"\(([^()]+)\)$", name)
        return match.group(1) if match else "nato"

    @staticmethod
    def _write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _godot_executable() -> Path | None:
    explicit = str(os.environ.get("GODOT_BIN", "")).strip()
    if not explicit:
        return None
    candidate = Path(explicit)
    if not candidate.is_file():
        raise AssertionError(f"GODOT_BIN is not a file: {candidate}")
    return candidate.resolve()


def _consume_snapshot_in_godot(test: unittest.TestCase, snapshot: Path) -> bool:
    executable = _godot_executable()
    if executable is None:
        return False
    completed = subprocess.run(
        [
            str(executable),
            "--headless",
            "--path",
            str(ROOT / "godot"),
            "--audio-driver",
            "Dummy",
            "-s",
            "res://scripts/tools/player_shell_test.gd",
            "--",
            f"--snapshot={snapshot}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = completed.stdout + completed.stderr
    test.assertEqual(0, completed.returncode, output)
    test.assertIn("player_shell_test: PASS", output)
    return True


def _synthesize_completed_tactical_result(save_path: Path) -> None:
    """Simulate only GoH's post-handoff archive rewrite."""
    from gates_of_codex.bridge.archive import CampaignSaveArchive
    from gates_of_codex.bridge.status import StatusBuilder

    archive = CampaignSaveArchive()
    contents = archive.read(save_path)
    baseline = StatusBuilder().parse_result(contents.status)
    status = re.sub(
        r"(\{\s*playedGames\s+)\d+",
        rf"\g<1>{baseline.played_games + 1}",
        contents.status,
        count=1,
    )
    status = re.sub(
        r"(\{\s*wonGames\s+)\d+",
        rf"\g<1>{baseline.won_games + 1}",
        status,
        count=1,
    )
    archive.write(save_path, status=status, campaign_scn=contents.campaign_scn)


class P6GoldenPathTests(unittest.TestCase):
    def test_godot_ci_executes_this_proof_with_an_explicit_binary(self) -> None:
        workflow = (ROOT / ".github/workflows/gates-of-codex.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'GODOT_BIN="$HOME/godot" python -m unittest tests.test_p6_golden_path -v',
            workflow,
        )

    def test_production_earth3_handoff_import_and_continuation(self) -> None:
        from gates_of_codex.acceptance import fingerprint_save
        from gates_of_codex.faction_wiring_compiler import FactionWiringCompiler
        from gates_of_codex.frontend_commands import apply_frontend_commands
        from gates_of_codex.operational_order_options import (
            list_operational_move_options,
        )
        from gates_of_codex.player_shell import build_play_parser, run_play
        from gates_of_codex.service import GatesOfCodeXService
        from gates_of_codex.state_io import load_campaign
        from gates_of_codex.turn_cycle import PLAYER_ROUND_OP, install_frontend_turn_cycle_op

        install_frontend_turn_cycle_op()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = ProductionStackFixture(root / "stack")
            fixture.write()
            compiled = FactionWiringCompiler(fixture.layers).compile()
            self.assertEqual(
                (0, 0),
                (compiled["error_count"], compiled["warning_count"]),
                compiled["problems"],
            )
            campaign_root = root / "managed-home/campaigns/earth3_v1"
            environ = dict(os.environ)
            environ["GATES_OF_CODEX_HOME"] = str(root / "managed-home")
            args = build_play_parser().parse_args(
                [
                    "--new",
                    "--campaign",
                    str(campaign_root),
                    "--stack-config",
                    str(fixture.stack_config),
                    "--game",
                    str(fixture.game),
                    "--profile",
                    str(fixture.profile),
                    "--tactical-map",
                    "multi/2x2/stack_test",
                    "--no-launch",
                ]
            )
            # Production receives this value as a process environment variable.
            # Keep run_play's explicit mapping and ambient safety classifier on
            # the same managed-home authority while the snapshot is published.
            with mock.patch.dict(os.environ, environ, clear=False):
                play = run_play(args, environ=environ)
            campaign = Path(play.campaign_path)
            snapshot = Path(play.snapshot_path)
            self.assertEqual("earth3_europe_mediterranean", play.map_id)
            self.assertEqual(5, len(play.stack_layers))
            self.assertTrue(campaign.is_file())
            self.assertTrue(snapshot.is_file())
            snapshot_payload = json.loads(snapshot.read_text(encoding="utf-8"))
            maintenance = snapshot_payload["control"]["maintenance"]
            self.assertTrue(maintenance["destructive_controls_allowed"], maintenance)
            self.assertIn(
                "reset_test_campaign", snapshot_payload["control"]["supported_ops"]
            )
            _consume_snapshot_in_godot(self, snapshot)

            state = load_campaign(campaign)
            option = next(
                row
                for row in list_operational_move_options(
                    state, state.selected_faction
                )
                if row["formation_id"] == "sf_pol_vilnius"
                and row["target_node_id"] == "op-node-e3_3380-anchor"
            )
            issued = apply_frontend_commands(
                campaign,
                commands=[
                    {
                        "op": "issue_move_order",
                        "command_id": "p6-issue-contact-route",
                        "formation": option["formation_id"],
                        "path_node_ids": option["path_node_ids"],
                        "path_edge_ids": option["path_edge_ids"],
                    }
                ],
                snapshot_path=None,
            )
            self.assertTrue(issued["ok"], issued)
            committed = apply_frontend_commands(
                campaign,
                commands=[
                    {
                        "op": "commit_move_orders",
                        "command_id": "p6-commit-contact-route",
                        "faction": state.selected_faction.value,
                        "locked_stance": option["locked_stance"],
                    }
                ],
                snapshot_path=None,
            )
            self.assertTrue(committed["ok"], committed)

            first_round = apply_frontend_commands(
                campaign,
                commands=[
                    {"op": PLAYER_ROUND_OP, "command_id": "p6-player-round-1"}
                ],
                snapshot_path=None,
            )
            self.assertTrue(first_round["ok"], first_round)
            self.assertEqual(
                ["ukr", "rusa"], first_round["results"][0]["data"]["ai_factions"]
            )
            self.assertIsNone(load_campaign(campaign).pending_battle)
            second_round = apply_frontend_commands(
                campaign,
                commands=[
                    {"op": PLAYER_ROUND_OP, "command_id": "p6-player-round-2"}
                ],
                snapshot_path=None,
            )
            self.assertTrue(second_round["ok"], second_round)
            self.assertEqual(
                ["ukr", "rusa"], second_round["results"][0]["data"]["ai_factions"]
            )
            pending = load_campaign(campaign).pending_battle
            self.assertIsNotNone(pending)
            self.assertEqual("node_contact", pending.encounter_kind)
            self.assertEqual("sf_pol_vilnius", pending.attacker_formation_id)
            self.assertEqual("sf_rus_donetsk", pending.defender_formation_id)

            handoff = apply_frontend_commands(
                campaign,
                commands=[
                    {
                        "op": "handoff",
                        "command_id": "p6-production-handoff",
                        "map": "multi/2x2/stack_test",
                        "work_root": str(root / "live"),
                        "backup_root": str(root / "backups"),
                    }
                ],
                snapshot_path=None,
            )
            self.assertTrue(handoff["ok"], handoff)
            save_path = Path(handoff["results"][0]["data"]["installed_save_path"])
            self.assertTrue(save_path.is_file())
            service = GatesOfCodeXService()
            manifest = service.load_manifest(service.manifest_path(save_path))
            self.assertEqual(pending.battle_id, manifest.battle_id)
            self.assertEqual(campaign.resolve(), Path(manifest.campaign_path).resolve())
            self.assertEqual(save_path.resolve(), Path(manifest.save_path).resolve())
            original = fingerprint_save(save_path)
            self.assertEqual(original.sha256, manifest.installed_sha256)
            self.assertEqual(original.size, manifest.installed_size)

            untouched = apply_frontend_commands(
                campaign,
                commands=[
                    {
                        "op": "verify_result",
                        "command_id": "p6-verify-untouched-handoff",
                        "save_path": str(save_path),
                    }
                ],
                snapshot_path=None,
            )
            self.assertTrue(untouched["ok"], untouched)
            self.assertFalse(untouched["results"][0]["data"]["verified"], untouched)

            _synthesize_completed_tactical_result(save_path)
            verified = apply_frontend_commands(
                campaign,
                commands=[
                    {
                        "op": "verify_result",
                        "command_id": "p6-verify-completed-result",
                        "save_path": str(save_path),
                    }
                ],
                snapshot_path=None,
            )
            self.assertTrue(verified["ok"], verified)
            self.assertTrue(verified["results"][0]["data"]["verified"], verified)

            imported = apply_frontend_commands(
                campaign,
                commands=[
                    {
                        "op": "import_battle",
                        "command_id": "p6-import-result",
                        "save_path": str(save_path),
                    }
                ],
                snapshot_path=None,
            )
            self.assertTrue(imported["ok"], imported)
            self.assertIsNone(load_campaign(campaign).pending_battle)
            replay = apply_frontend_commands(
                campaign,
                commands=[
                    {
                        "op": "import_battle",
                        "command_id": "p6-import-result",
                        "save_path": str(save_path),
                    }
                ],
                snapshot_path=None,
            )
            self.assertTrue(replay["ok"], replay)
            self.assertTrue(replay["results"][0]["data"]["duplicate"], replay)

            reloaded = load_campaign(campaign)
            next_option = list_operational_move_options(
                reloaded, reloaded.selected_faction
            )[0]
            next_action = apply_frontend_commands(
                campaign,
                commands=[
                    {
                        "op": "issue_move_order",
                        "command_id": "p6-next-strategic-action",
                        "formation": next_option["formation_id"],
                        "path_node_ids": next_option["path_node_ids"],
                        "path_edge_ids": next_option["path_edge_ids"],
                    }
                ],
                snapshot_path=None,
            )
            self.assertTrue(next_action["ok"], next_action)
            continued = load_campaign(campaign)
            self.assertIsNotNone(
                continued.strategic_formations[next_option["formation_id"]].move_order
            )


if __name__ == "__main__":
    unittest.main()
