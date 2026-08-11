"""P4 adversarial regressions for the player launch and continuation shell.

These cover the authority boundaries introduced by P4:

* one player action creates/continues the authoritative Earth3 campaign;
* the Godot snapshot is derived presentation state, never campaign authority;
* accepted mutations apply exactly once, and rejected/replayed/interrupted ones
  leave both the campaign and the published snapshot at the accepted state;
* production never silently resolves a GoE-derived map or substitutes paths.

Building and exporting the production Earth3 campaign is expensive, so the
Earth3 flow is executed exactly once per run and shared by the tests that must
observe real production authority. Map-independent mutation semantics are proved
against the fast legacy scenario through the same player entry point.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from gates_of_codex.earth3_campaign import EARTH3_MAP_ID, Earth3AuthorityError
from gates_of_codex.earth3_operational import P3_AUTHORITY_METADATA_KEY
from gates_of_codex.frontend import LEGACY_GOE_MAP_ID
from gates_of_codex.frontend_commands import (
    COMMAND_LEDGER_KEY,
    apply_frontend_commands,
    read_command_ledger,
)
from gates_of_codex.player_shell import (
    PLAYER_LAUNCH_KEY,
    PlayerShellError,
    build_play_parser,
    clear_last_campaign_if_matches,
    create_new_campaign,
    find_godot_executable,
    last_campaign_path,
    launch_strategic_application,
    player_home,
    read_last_campaign,
    resolve_campaign_paths,
    run_play,
    write_last_campaign,
)
from gates_of_codex.state_io import load_campaign

from test_p2_earth3_campaign_bootstrap import _resolved_catalog


LEGACY_SCENARIO = "legacy_goe_europe"


def _play_args(*values: str):
    return build_play_parser().parse_args(list(values))


def _environ(home: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["GATES_OF_CODEX_HOME"] = str(home)
    return env


def _read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _new_legacy_campaign(root: Path, *extra: str):
    """Create a campaign through the real player entry point, cheaply."""
    args = _play_args(
        "--new",
        "--campaign",
        str(root / "campaign"),
        "--no-launch",
        "--scenario",
        LEGACY_SCENARIO,
        *extra,
    )
    return run_play(args, environ=_environ(root / "home"))


class Earth3ProductionLaunchTests(unittest.TestCase):
    """One real production launch, continued once, shared by every assertion."""

    temporary: tempfile.TemporaryDirectory
    root: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        environ = _environ(cls.root / "home")
        # ``build_earth3_v1_campaign`` already accepts resolved catalog authority
        # instead of a live stack; production ``play`` always resolves it from
        # the validated stack config instead.
        cls.created = run_play(
            _play_args(
                "--new", "--campaign", str(cls.root / "campaign"), "--no-launch"
            ),
            environ=environ,
            resolved_catalog=_resolved_catalog(),
        )
        cls.created_campaign = load_campaign(cls.created.campaign_path)
        cls.created_snapshot = _read_json(cls.created.snapshot_path)

        # Advance the campaign through the authoritative mutation path. The
        # snapshot is deliberately not republished here; continuation must
        # regenerate it from campaign state alone.
        cls.applied = apply_frontend_commands(
            cls.created.campaign_path,
            commands=[{"op": "end_turn", "command_id": "p4-earth3-turn"}],
            snapshot_path=None,
        )
        cls.mutated_campaign = load_campaign(cls.created.campaign_path)

        cls.resumed = run_play(
            _play_args(
                "--continue", "--campaign", str(cls.root / "campaign"), "--no-launch"
            ),
            environ=environ,
        )
        cls.resumed_campaign = load_campaign(cls.resumed.campaign_path)
        cls.resumed_snapshot = _read_json(cls.resumed.snapshot_path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_one_player_command_creates_earth3_campaign_and_snapshot(self) -> None:
        self.assertEqual("new", self.created.mode)
        self.assertTrue(Path(self.created.campaign_path).is_file())
        self.assertTrue(Path(self.created.snapshot_path).is_file())
        self.assertEqual(EARTH3_MAP_ID, self.created.map_id)
        self.assertEqual("earth3_v1", self.created.scenario_id)
        self.assertFalse(self.created.launched)

    def test_campaign_directory_holds_exactly_one_authoritative_campaign(self) -> None:
        names = sorted(
            path.name for path in Path(self.created.campaign_path).parent.glob("*.json")
        )
        self.assertEqual(
            ["campaign.json", "campaign_snapshot.json", "frontend_commands.json"], names
        )

    def test_generated_snapshot_identifies_earth3(self) -> None:
        snapshot = self.created_snapshot
        self.assertEqual(EARTH3_MAP_ID, snapshot["campaign"]["map_id"])
        self.assertEqual(EARTH3_MAP_ID, snapshot["application"]["map_id"])
        self.assertEqual("earth3_v1", snapshot["application"]["scenario_id"])
        self.assertEqual("production", snapshot["application"]["scenario_status"])
        self.assertEqual(
            EARTH3_MAP_ID, snapshot["campaign"]["map_metadata"]["strategic_map_id"]
        )

    def test_godot_map_metadata_resolves_earth3_directly(self) -> None:
        strategic_map = self.created_snapshot["strategic_map"]
        self.assertEqual(EARTH3_MAP_ID, strategic_map["map_id"])
        self.assertEqual([EARTH3_MAP_ID], strategic_map["available_map_ids"])
        self.assertEqual([EARTH3_MAP_ID], strategic_map["production_map_ids"])
        self.assertEqual("none", strategic_map["fallback"])
        self.assertIn(
            "earth3_europe_mediterranean", json.dumps(strategic_map, sort_keys=True)
        )

    def test_production_flow_contains_no_goe_fallback(self) -> None:
        # Production selection is Earth3 without any explicit scenario request.
        self.assertEqual("earth3_v1", _play_args("--new").scenario)
        self.assertEqual(EARTH3_MAP_ID, self.created_campaign.map_id)
        strategic_map = self.created_snapshot["strategic_map"]
        for legacy in (
            LEGACY_GOE_MAP_ID,
            "goe_europe",
            "interim_goe_europe",
            "europe_mediterranean_from_goe",
        ):
            self.assertNotIn(legacy, strategic_map["available_map_ids"])
            self.assertNotEqual(legacy, strategic_map["map_id"])
            self.assertNotEqual(legacy, self.created_snapshot["application"]["map_id"])

    def test_initial_playable_campaign_defaults_to_fog_off(self) -> None:
        self.assertEqual("off", self.created.fog_of_war)
        self.assertFalse(self.created_campaign.fog_of_war_enabled)

    def test_snapshot_exposes_player_launch_actions_from_persisted_settings(self) -> None:
        play = self.created_snapshot["control"]["play"]
        self.assertTrue(play["enabled"])
        self.assertEqual("play", play["new_args"][0])
        for expected in ("--new", "--force-new", "--no-launch", "earth3_v1", "nato", "off"):
            self.assertIn(expected, play["new_args"])
        self.assertEqual(
            [
                "play",
                "--continue",
                "--campaign",
                self.created.campaign_path,
                "--no-launch",
                "--scenario",
                "earth3_v1",
            ],
            play["continue_args"],
        )

    def test_application_block_reports_player_facing_identity(self) -> None:
        application = self.created_snapshot["application"]
        self.assertEqual("Gates of CodeX", application["name"])
        self.assertTrue(str(application["version"]).strip())
        self.assertEqual(self.created.campaign_path, application["campaign_path"])
        self.assertEqual("nato", application["selected_faction"])
        self.assertEqual(
            self.created_campaign.turn_number, application["turn_number"]
        )

    def test_continue_reopens_the_same_campaign_identity_and_path(self) -> None:
        self.assertEqual("continue", self.resumed.mode)
        self.assertEqual(self.created.campaign_path, self.resumed.campaign_path)
        self.assertEqual(
            self.created_campaign.campaign_name, self.resumed_campaign.campaign_name
        )
        self.assertEqual(EARTH3_MAP_ID, self.resumed_campaign.map_id)
        self.assertEqual(
            EARTH3_MAP_ID, self.resumed_snapshot["campaign"]["map_id"]
        )

    def test_continue_remembers_the_campaign_without_manual_paths(self) -> None:
        self.assertEqual(
            Path(self.created.campaign_path),
            read_last_campaign(_environ(self.root / "home")),
        )

    def test_close_reopen_preserves_p3_operational_state(self) -> None:
        before = self.mutated_campaign
        after = self.resumed_campaign
        self.assertTrue(self.applied["ok"], self.applied)
        self.assertEqual(
            self.created_campaign.map_metadata[P3_AUTHORITY_METADATA_KEY],
            after.map_metadata[P3_AUTHORITY_METADATA_KEY],
        )
        self.assertEqual(before.turn_number, after.turn_number)
        self.assertEqual(before.current_faction, after.current_faction)
        self.assertEqual(before.selected_faction, after.selected_faction)
        self.assertEqual(
            sorted(before.strategic_formations), sorted(after.strategic_formations)
        )
        for formation_id, force in before.strategic_formations.items():
            resumed = after.strategic_formations[formation_id]
            self.assertEqual(force.position, resumed.position)
            self.assertEqual(force.move_order, resumed.move_order)
            self.assertEqual(force.faction, resumed.faction)
        self.assertEqual(
            {key: value.supply for key, value in before.battalions.items()},
            {key: value.supply for key, value in after.battalions.items()},
        )
        self.assertEqual(
            before.map_metadata.get("operational_site_control"),
            after.map_metadata.get("operational_site_control"),
        )
        self.assertEqual(before.pending_battle, after.pending_battle)
        self.assertEqual(
            {key: value.owner for key, value in before.provinces.items()},
            {key: value.owner for key, value in after.provinces.items()},
        )

    def test_continuation_snapshot_is_regenerated_from_campaign_state(self) -> None:
        self.assertEqual(
            self.resumed_campaign.turn_number,
            self.resumed_snapshot["campaign"]["turn_number"],
        )
        self.assertEqual(
            self.resumed_campaign.current_faction.value,
            self.resumed_snapshot["campaign"]["current_faction"],
        )

    def test_persisted_launch_settings_survive_continuation(self) -> None:
        launch = self.resumed_campaign.map_metadata[PLAYER_LAUNCH_KEY]
        self.assertEqual(self.created.campaign_path, launch["campaign_path"])
        self.assertEqual(self.created.snapshot_path, launch["snapshot_path"])
        self.assertEqual(self.created.commands_path, launch["commands_path"])

    def test_headless_godot_imports_generated_production_snapshot(self) -> None:
        godot = (
            os.environ.get("GODOT_BIN")
            or shutil.which("godot")
            or shutil.which("godot4")
        )
        if not godot:
            self.skipTest(
                "Godot 4 executable not available; proved by the godot-map CI job"
            )
        completed = subprocess.run(
            [
                godot,
                "--headless",
                "--path",
                str(ROOT / "godot"),
                "--audio-driver",
                "Dummy",
                "-s",
                "res://scripts/tools/player_shell_test.gd",
                "--",
                f"--snapshot={self.created.snapshot_path}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)


class PlayerCommandAuthorityTests(unittest.TestCase):
    """Mutation semantics proved through the real player flow, map-independent."""

    def test_legal_command_mutates_the_campaign_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = _new_legacy_campaign(root)
            before = load_campaign(created.campaign_path)
            result = apply_frontend_commands(
                created.campaign_path,
                commands=[{"op": "end_turn", "command_id": "cmd-a"}],
                snapshot_path=created.snapshot_path,
            )
            after = load_campaign(created.campaign_path)
            ledger = read_command_ledger(after)

        self.assertTrue(result["ok"], result)
        self.assertEqual(1, result["commands_applied"])
        self.assertNotEqual(before.current_faction, after.current_faction)
        self.assertEqual(["cmd-a"], [row["command_id"] for row in ledger["entries"]])

    def test_replayed_command_id_cannot_apply_twice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = _new_legacy_campaign(root)
            command = {"op": "end_turn", "command_id": "cmd-replay"}
            first = apply_frontend_commands(
                created.campaign_path,
                commands=[dict(command)],
                snapshot_path=created.snapshot_path,
            )
            after_first = load_campaign(created.campaign_path)
            second = apply_frontend_commands(
                created.campaign_path,
                commands=[dict(command)],
                snapshot_path=created.snapshot_path,
            )
            after_second = load_campaign(created.campaign_path)

        self.assertTrue(first["ok"], first)
        self.assertTrue(second["ok"], second)
        self.assertEqual(1, first["commands_applied"])
        self.assertEqual(0, second["commands_applied"])
        self.assertTrue(second["results"][0]["data"]["duplicate"])
        self.assertEqual(after_first.turn_number, after_second.turn_number)
        self.assertEqual(after_first.current_faction, after_second.current_faction)

    def test_distinct_ids_still_apply_each_deliberate_press(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = _new_legacy_campaign(root)
            start = load_campaign(created.campaign_path).turn_number
            for index in range(4):
                result = apply_frontend_commands(
                    created.campaign_path,
                    commands=[{"op": "end_turn", "command_id": f"turn-{index}"}],
                    snapshot_path=created.snapshot_path,
                )
                self.assertTrue(result["ok"], result)
            after = load_campaign(created.campaign_path)

        self.assertEqual(start + 1, after.turn_number)
        self.assertEqual(4, len(read_command_ledger(after)["entries"]))

    def test_duplicate_ids_inside_one_batch_are_rejected_whole(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = _new_legacy_campaign(root)
            before = Path(created.campaign_path).read_bytes()
            result = apply_frontend_commands(
                created.campaign_path,
                commands=[
                    {"op": "end_turn", "command_id": "same"},
                    {"op": "end_turn", "command_id": "same"},
                ],
                snapshot_path=created.snapshot_path,
            )

            self.assertFalse(result["ok"], result)
            self.assertEqual(0, result["commands_applied"])
            self.assertEqual(before, Path(created.campaign_path).read_bytes())

    def test_self_committing_ops_may_not_share_a_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = _new_legacy_campaign(root)
            before = Path(created.campaign_path).read_bytes()
            result = apply_frontend_commands(
                created.campaign_path,
                commands=[
                    {"op": "end_turn", "command_id": "a"},
                    {"op": "import_battle", "command_id": "b"},
                ],
                snapshot_path=created.snapshot_path,
            )

            self.assertFalse(result["ok"], result)
            self.assertIn("submitted alone", result["results"][0]["detail"])
            self.assertEqual(before, Path(created.campaign_path).read_bytes())

    def test_rejected_command_preserves_campaign_and_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = _new_legacy_campaign(root)
            campaign_before = Path(created.campaign_path).read_bytes()
            snapshot_before = Path(created.snapshot_path).read_bytes()
            result = apply_frontend_commands(
                created.campaign_path,
                commands=[{"op": "not_a_real_op", "command_id": "bad"}],
                snapshot_path=created.snapshot_path,
            )

            self.assertFalse(result["ok"], result)
            self.assertEqual(0, result["commands_applied"])
            self.assertEqual(campaign_before, Path(created.campaign_path).read_bytes())
            self.assertEqual(snapshot_before, Path(created.snapshot_path).read_bytes())

    def test_earlier_success_is_discarded_when_a_later_command_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = _new_legacy_campaign(root)
            campaign_before = Path(created.campaign_path).read_bytes()
            snapshot_before = Path(created.snapshot_path).read_bytes()
            result = apply_frontend_commands(
                created.campaign_path,
                commands=[
                    {"op": "end_turn", "command_id": "ok-1"},
                    {"op": "not_a_real_op", "command_id": "bad-1"},
                ],
                snapshot_path=created.snapshot_path,
            )
            after = load_campaign(created.campaign_path)

            self.assertFalse(result["ok"], result)
            self.assertEqual(campaign_before, Path(created.campaign_path).read_bytes())
            self.assertEqual(snapshot_before, Path(created.snapshot_path).read_bytes())
            self.assertNotIn(COMMAND_LEDGER_KEY, after.map_metadata)

    def test_interrupted_publish_never_publishes_partial_state_or_double_applies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = _new_legacy_campaign(root)
            before = load_campaign(created.campaign_path)
            snapshot_before = Path(created.snapshot_path).read_bytes()

            with patch(
                "gates_of_codex.frontend.write_frontend_snapshot",
                side_effect=OSError("device full"),
            ):
                interrupted = apply_frontend_commands(
                    created.campaign_path,
                    commands=[{"op": "end_turn", "command_id": "cmd-interrupt"}],
                    snapshot_path=created.snapshot_path,
                )
            after_interrupt = load_campaign(created.campaign_path)

            # The published snapshot still shows the last accepted state.
            self.assertEqual(snapshot_before, Path(created.snapshot_path).read_bytes())

            # Recovery replays the same identity; it must not apply twice.
            replay = apply_frontend_commands(
                created.campaign_path,
                commands=[{"op": "end_turn", "command_id": "cmd-interrupt"}],
                snapshot_path=created.snapshot_path,
            )
            after_replay = load_campaign(created.campaign_path)
            snapshot_after = _read_json(created.snapshot_path)

        self.assertFalse(interrupted["ok"], interrupted)
        self.assertIn("snapshot_publish_failed", interrupted)
        self.assertNotEqual(before.current_faction, after_interrupt.current_faction)
        self.assertTrue(replay["ok"], replay)
        self.assertEqual(0, replay["commands_applied"])
        self.assertEqual(after_interrupt.turn_number, after_replay.turn_number)
        self.assertEqual(after_interrupt.current_faction, after_replay.current_faction)
        # The recovered snapshot is regenerated from accepted campaign state only.
        self.assertEqual(
            after_replay.current_faction.value,
            snapshot_after["campaign"]["current_faction"],
        )

    def test_accepted_mutation_refreshes_the_snapshot_from_campaign_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = _new_legacy_campaign(root)
            apply_frontend_commands(
                created.campaign_path,
                commands=[{"op": "end_turn", "command_id": "cmd-turn"}],
                snapshot_path=created.snapshot_path,
            )
            state = load_campaign(created.campaign_path)
            snapshot = _read_json(created.snapshot_path)

        self.assertEqual(state.turn_number, snapshot["campaign"]["turn_number"])
        self.assertEqual(
            state.current_faction.value, snapshot["campaign"]["current_faction"]
        )
        self.assertEqual(
            str(Path(created.campaign_path)), snapshot["control"]["campaign_path"]
        )

    def test_launch_clears_a_stale_command_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = _new_legacy_campaign(root)
            Path(created.commands_path).write_text(
                json.dumps({"commands": [{"op": "end_turn", "command_id": "stale"}]}),
                encoding="utf-8",
            )
            resumed = run_play(
                _play_args(
                    "--continue", "--campaign", str(root / "campaign"), "--no-launch"
                ),
                environ=_environ(root / "home"),
            )
            queued = _read_json(resumed.commands_path)

        self.assertEqual([], queued["commands"])


class ContinuationFailClosedTests(unittest.TestCase):
    def test_continue_without_a_campaign_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = _play_args(
                "--continue", "--campaign", str(root / "missing"), "--no-launch"
            )
            with self.assertRaises(PlayerShellError) as raised:
                run_play(args, environ=_environ(root / "home"))
        self.assertIn("No campaign to continue", str(raised.exception))
        self.assertFalse((root / "missing").exists())

    def test_continue_with_no_remembered_campaign_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(PlayerShellError) as raised:
                run_play(
                    _play_args("--continue", "--no-launch"),
                    environ=_environ(root / "home"),
                )
        self.assertIn("No campaign to continue", str(raised.exception))

    def test_new_campaign_refuses_to_replace_an_existing_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = _new_legacy_campaign(root)
            original = Path(created.campaign_path).read_bytes()
            with self.assertRaises(PlayerShellError) as raised:
                _new_legacy_campaign(root)
            self.assertEqual(original, Path(created.campaign_path).read_bytes())
        self.assertIn("--continue", str(raised.exception))

    def test_continue_never_derives_a_campaign_from_the_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = _new_legacy_campaign(root)
            Path(created.snapshot_path).write_text("{}\n", encoding="utf-8")
            resumed = run_play(
                _play_args(
                    "--continue", "--campaign", str(root / "campaign"), "--no-launch"
                ),
                environ=_environ(root / "home"),
            )
            snapshot = _read_json(resumed.snapshot_path)
            state = load_campaign(resumed.campaign_path)

        self.assertEqual(LEGACY_GOE_MAP_ID, snapshot["campaign"]["map_id"])
        self.assertEqual(LEGACY_GOE_MAP_ID, state.map_id)


class FailClosedTests(unittest.TestCase):
    def test_missing_earth3_assets_fail_closed_without_map_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = resolve_campaign_paths(root / "campaign")
            with patch(
                "gates_of_codex.player_shell.build_scenario",
                side_effect=Earth3AuthorityError("polygon_dataset.json missing"),
            ):
                with self.assertRaises(Earth3AuthorityError):
                    create_new_campaign(paths=paths, resolved_catalog={})
            self.assertFalse(paths.campaign.exists())
            self.assertFalse(paths.snapshot.exists())

    def test_earth3_player_seat_is_fixed_to_nato(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = resolve_campaign_paths(root / "campaign")
            with self.assertRaises(PlayerShellError) as raised:
                create_new_campaign(paths=paths, faction="rusa", resolved_catalog={})
            self.assertFalse(paths.campaign.exists())
        self.assertIn("NATO", str(raised.exception))

    def test_missing_stack_config_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = _play_args(
                "--new", "--campaign", str(root / "campaign"), "--no-launch"
            )
            with self.assertRaises(PlayerShellError) as raised:
                run_play(args, environ=_environ(root / "home"))
            self.assertFalse((root / "campaign").exists())
        self.assertIn("--stack-config is required", str(raised.exception))

    def test_unreadable_stack_config_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = _play_args(
                "--new",
                "--campaign",
                str(root / "campaign"),
                "--no-launch",
                "--stack-config",
                str(root / "absent-stack.json"),
            )
            with self.assertRaises(PlayerShellError) as raised:
                run_play(args, environ=_environ(root / "home"))
            self.assertFalse((root / "campaign").exists())
        self.assertIn("Stack config not found", str(raised.exception))

    def test_invalid_stack_config_contents_fail_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "stack.json"
            config.write_text(json.dumps({"layers": []}), encoding="utf-8")
            args = _play_args(
                "--new",
                "--campaign",
                str(root / "campaign"),
                "--no-launch",
                "--stack-config",
                str(config),
            )
            with self.assertRaises(PlayerShellError) as raised:
                run_play(args, environ=_environ(root / "home"))
            self.assertIn("Invalid stack config", str(raised.exception))
            self.assertFalse((root / "campaign").exists())

    def test_stack_config_with_wrong_layer_roles_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "stack.json"
            config.write_text(
                json.dumps({"layers": [{"role": "codex", "path": str(root)}]}),
                encoding="utf-8",
            )
            args = _play_args(
                "--new",
                "--campaign",
                str(root / "campaign"),
                "--no-launch",
                "--stack-config",
                str(config),
            )
            with self.assertRaises(PlayerShellError) as raised:
                run_play(args, environ=_environ(root / "home"))
            self.assertIn("Invalid stack config", str(raised.exception))
            self.assertFalse((root / "campaign").exists())

    def test_invalid_game_and_profile_paths_are_not_silently_substituted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for flag, value in (
                ("--game", root / "no such game"),
                ("--profile", root / "no such profile"),
            ):
                args = _play_args(
                    "--new",
                    "--campaign",
                    str(root / "campaign"),
                    "--no-launch",
                    "--scenario",
                    LEGACY_SCENARIO,
                    flag,
                    str(value),
                )
                with self.assertRaises(PlayerShellError) as raised:
                    run_play(args, environ=_environ(root / "home"))
                self.assertIn(flag, str(raised.exception))
                self.assertIn("not an existing directory", str(raised.exception))
                self.assertFalse((root / "campaign").exists())

    def test_missing_godot_executable_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(PlayerShellError) as raised:
                find_godot_executable(root / "Godot Engine" / "godot.exe")
        self.assertIn("Godot executable not found", str(raised.exception))

    def test_unknown_scenario_fails_before_touching_the_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = _play_args(
                "--new",
                "--campaign",
                str(root / "campaign"),
                "--no-launch",
                "--scenario",
                "earth4_v9",
            )
            with self.assertRaises(ValueError):
                run_play(args, environ=_environ(root / "home"))
            self.assertFalse((root / "campaign").exists())


class LegacyCompatibilityTests(unittest.TestCase):
    def test_legacy_scenario_runs_only_when_explicitly_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = _new_legacy_campaign(root)
            state = load_campaign(created.campaign_path)
            snapshot = _read_json(created.snapshot_path)

        self.assertEqual(LEGACY_SCENARIO, created.scenario_id)
        self.assertEqual(LEGACY_GOE_MAP_ID, state.map_id)
        self.assertEqual("legacy", state.map_metadata["scenario_status"])
        self.assertEqual("legacy", snapshot["application"]["scenario_status"])

    def test_legacy_selection_does_not_change_the_production_default(self) -> None:
        self.assertEqual("earth3_v1", _play_args("--new").scenario)
        self.assertEqual("earth3_v1", _play_args("--continue").scenario)

    def test_fog_of_war_on_is_supported_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = _new_legacy_campaign(root, "--fog-of-war", "on")
            state = load_campaign(created.campaign_path)
            resumed = run_play(
                _play_args(
                    "--continue", "--campaign", str(root / "campaign"), "--no-launch"
                ),
                environ=_environ(root / "home"),
            )
            resumed_state = load_campaign(resumed.campaign_path)

            self.assertEqual("on", created.fog_of_war)
            self.assertTrue(state.fog_of_war_enabled)
            self.assertEqual("on", resumed.fog_of_war)
            self.assertTrue(resumed_state.fog_of_war_enabled)
            self.assertTrue(Path(resumed.snapshot_path).is_file())

    def test_legacy_continuation_keeps_the_legacy_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _new_legacy_campaign(root)
            resumed = run_play(
                _play_args(
                    "--continue", "--campaign", str(root / "campaign"), "--no-launch"
                ),
                environ=_environ(root / "home"),
            )
            state = load_campaign(resumed.campaign_path)

        self.assertEqual(LEGACY_GOE_MAP_ID, state.map_id)
        self.assertEqual(LEGACY_SCENARIO, state.map_metadata["scenario_id"])


class DeterminismAndPathTests(unittest.TestCase):
    def test_clear_last_campaign_removes_only_matching_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            environ = _environ(home)
            campaign = home / "campaigns" / "earth3_v1" / "campaign.json"
            write_last_campaign(campaign, environ=environ)

            self.assertTrue(
                clear_last_campaign_if_matches(campaign, environ=environ)
            )
            self.assertFalse(last_campaign_path(environ).exists())

    def test_clear_last_campaign_preserves_nonmatching_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            environ = _environ(home)
            remembered = home / "campaigns" / "other" / "campaign.json"
            target = home / "campaigns" / "earth3_v1" / "campaign.json"
            pointer = write_last_campaign(remembered, environ=environ)
            before = pointer.read_bytes()

            self.assertFalse(
                clear_last_campaign_if_matches(target, environ=environ)
            )
            self.assertEqual(before, pointer.read_bytes())

    def test_campaign_and_snapshot_writes_are_deterministic_and_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = _new_legacy_campaign(root)
            first_campaign = Path(first.campaign_path).read_bytes()
            first_snapshot = Path(first.snapshot_path).read_bytes()
            second = _new_legacy_campaign(root, "--force-new")
            second_campaign = Path(second.campaign_path).read_bytes()
            second_snapshot = Path(second.snapshot_path).read_bytes()
            leftovers = sorted(
                path.name
                for path in Path(second.campaign_path).parent.iterdir()
                if path.name.endswith(".tmp") or path.name.startswith(".")
            )

        self.assertEqual(first_campaign, second_campaign)
        self.assertEqual(first_snapshot, second_snapshot)
        self.assertEqual([], leftovers)

    def test_persisted_launch_settings_are_recorded_on_the_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "Gates of Hell"
            profile = root / "profile dir"
            game.mkdir()
            profile.mkdir()
            created = _new_legacy_campaign(
                root,
                "--game",
                str(game),
                "--profile",
                str(profile),
                "--tactical-map",
                "moscow_outskirts",
                "--difficulty",
                "hard",
                "--faction",
                "ukr",
            )
            state = load_campaign(created.campaign_path)

        self.assertEqual(str(game.resolve()), state.game_directory)
        self.assertEqual(str(profile.resolve()), state.profile_directory)
        self.assertEqual("moscow_outskirts", state.map_metadata["preferred_map"])
        self.assertEqual("hard", state.difficulty)
        self.assertEqual("ukr", state.selected_faction.value)
        launch = state.map_metadata[PLAYER_LAUNCH_KEY]
        self.assertEqual(created.campaign_path, launch["campaign_path"])
        self.assertEqual(created.snapshot_path, launch["snapshot_path"])

    def test_campaign_path_resolution_accepts_directories_and_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            as_directory = resolve_campaign_paths(root / "camp")
            as_file = resolve_campaign_paths(root / "camp" / "campaign.json")
            named_file = resolve_campaign_paths(root / "camp" / "my save.json")

        self.assertEqual(as_directory.campaign, as_file.campaign)
        self.assertEqual(as_directory.snapshot, as_file.snapshot)
        self.assertEqual(as_directory.commands, as_file.commands)
        self.assertEqual("my save.json", named_file.campaign.name)
        self.assertEqual("campaign_snapshot.json", named_file.snapshot.name)
        self.assertEqual(named_file.campaign.parent, named_file.snapshot.parent)

    def test_windows_style_campaign_paths_resolve_without_substitution(self) -> None:
        raw = r"C:\Users\Player\Saved Games\Gates of CodeX\campaign.json"
        paths = resolve_campaign_paths(raw)
        text = str(paths.campaign)

        self.assertTrue(text.endswith("campaign.json"), text)
        self.assertIn("Saved Games", text)
        self.assertEqual(paths.campaign.parent, paths.root)
        self.assertEqual(paths.root / "campaign_snapshot.json", paths.snapshot)
        self.assertEqual(paths.root / "frontend_commands.json", paths.commands)

    def test_campaign_directory_with_trailing_separator_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plain = resolve_campaign_paths(str(root / "camp"))
            trailing = resolve_campaign_paths(str(root / "camp") + os.sep)

        self.assertEqual(plain.campaign, trailing.campaign)
        self.assertEqual(plain.root, trailing.root)

    def test_campaign_directory_with_spaces_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "My Saved Games" / "Gates of CodeX"
            created = _new_legacy_campaign(root)
            resumed = run_play(
                _play_args(
                    "--continue", "--campaign", str(root / "campaign"), "--no-launch"
                ),
                environ=_environ(root / "home"),
            )

        self.assertEqual(created.campaign_path, resumed.campaign_path)
        self.assertIn("My Saved Games", created.campaign_path)

    def test_default_campaign_directory_is_predictable_per_user(self) -> None:
        # Both sides are canonicalized: the player home and everything derived
        # from it share one spelling, so an aliased home cannot split state.
        with tempfile.TemporaryDirectory() as temporary:
            home = (Path(temporary) / "home dir").resolve(strict=False)
            environ = _environ(home)
            resolved = resolve_campaign_paths(None, environ=environ)

            self.assertEqual(home, player_home(environ))
            self.assertEqual(
                home / "campaigns" / "earth3_v1" / "campaign.json", resolved.campaign
            )

    def test_aliased_player_home_resolves_to_one_pointer_location(self) -> None:
        """Two spellings of one home must not yield two remembered-campaign files."""
        if os.name == "nt":
            self.skipTest("Windows 8.3 canonicalization is exercised by native CI")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_home = root / "real home"
            real_home.mkdir()
            alias = root / "alias home"
            try:
                alias.symlink_to(real_home, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            self.assertEqual(
                player_home(_environ(real_home)), player_home(_environ(alias))
            )
            self.assertEqual(
                last_campaign_path(_environ(real_home)),
                last_campaign_path(_environ(alias)),
            )

    def test_default_home_follows_platform_convention(self) -> None:
        if os.name == "nt":
            home = player_home({"LOCALAPPDATA": r"C:\Users\Player\AppData\Local"})
            self.assertEqual("GatesOfCodeX", home.name)
            self.assertIn("AppData", str(home))
        else:
            home = player_home({"XDG_DATA_HOME": "/var/tmp/xdg"})
            self.assertEqual(Path("/var/tmp/xdg/gates-of-codex").resolve(strict=False), home)

    def test_strategic_application_launch_uses_argv_not_a_shell_string(self) -> None:
        recorded: dict[str, object] = {}

        class _FakePopen:
            def __init__(self, arguments, cwd=None):
                recorded["arguments"] = list(arguments)
                recorded["cwd"] = cwd

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "Godot Project"
            project.mkdir()
            snapshot = root / "camp dir" / "campaign_snapshot.json"
            snapshot.parent.mkdir()
            snapshot.write_text("{}", encoding="utf-8")
            executable = root / "Godot Engine" / "godot.exe"
            executable.parent.mkdir()
            executable.write_text("", encoding="utf-8")
            with patch("gates_of_codex.player_shell.subprocess.Popen", _FakePopen):
                launch_strategic_application(
                    snapshot=snapshot,
                    godot_executable=executable,
                    project_directory=project,
                )

        arguments = recorded["arguments"]
        self.assertEqual(str(executable), arguments[0])
        self.assertEqual(["--path", str(project), "--"], arguments[1:4])
        self.assertEqual(f"--snapshot={snapshot}", arguments[4])
        self.assertEqual(str(project), recorded["cwd"])


class CliWiringTests(unittest.TestCase):
    def test_play_is_reachable_from_the_packaged_entry_point(self) -> None:
        from gates_of_codex.entrypoint import main as entrypoint_main

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            created = _new_legacy_campaign(root)
            code = entrypoint_main(
                [
                    "play",
                    "--continue",
                    "--campaign",
                    created.campaign_path,
                    "--no-launch",
                    "--json",
                ]
            )

        self.assertEqual(0, code)

    def test_play_reports_errors_without_a_traceback(self) -> None:
        from gates_of_codex.player_shell import main as play_main

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code = play_main(
                ["--continue", "--campaign", str(root / "missing"), "--no-launch"]
            )

        self.assertEqual(1, code)

    def test_play_requires_exactly_one_mode(self) -> None:
        with self.assertRaises(SystemExit):
            _play_args("--new", "--continue")
        with self.assertRaises(SystemExit):
            _play_args("--no-launch")


if __name__ == "__main__":
    unittest.main()
