from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from test_p2_earth3_campaign_bootstrap import _resolved_catalog

from gates_of_codex import earth3_campaign, frozen_runtime
from gates_of_codex.earth3_campaign import Earth3AuthorityError
from gates_of_codex.earth3_fixture_authority import (
    FIXTURE_AUTHORITY_KEY,
    Earth3FixtureAuthorityError,
    authored_fixture_authority_marker,
)
from gates_of_codex.earth3_operational import (
    P3_AUTHORITY_METADATA_KEY,
    Earth3OperationalAuthorityError,
)
from gates_of_codex.fast_entrypoint import _require_frozen_console_backend
from gates_of_codex.frontend import FRONTEND_SCHEMA_VERSION, write_frontend_snapshot
from gates_of_codex.packaging import (
    PackagingError,
    enforce_packaged_backend_identity,
    resolve_source_commit,
)
from gates_of_codex.frontend_commands import apply_frontend_commands
from gates_of_codex.models import Faction
from gates_of_codex.operational_order_options import list_operational_move_options
from gates_of_codex.scenario import build_scenario
from gates_of_codex.state_io import load_campaign, save_campaign


WRITEBACK = ROOT / "godot/scripts/main_writeback.gd"
WORKFLOW = ROOT / ".github/workflows/gates-of-codex.yml"
PLAYER_FORMATION = "sf_deu_berlin"


def _live_executable() -> Path | None:
    explicit = str(os.environ.get("GATES_OF_CODEX_LIVE_EXE", "")).strip()
    if explicit:
        candidate = Path(explicit)
        if not candidate.is_file():
            raise AssertionError(f"GATES_OF_CODEX_LIVE_EXE is not a file: {candidate}")
        return candidate.resolve()
    fallback = ROOT / "dist" / "GatesOfCodeXLive.exe"
    if fallback.is_file():
        return fallback.resolve()
    return None


def _first_nato_route(state):
    row = next(
        option
        for option in list_operational_move_options(state, Faction.NATO)
        if option["formation_id"] == PLAYER_FORMATION
    )
    return {
        "formation_id": str(row["formation_id"]),
        "faction": str(row["faction"]),
        "locked_stance": str(row["locked_stance"]),
        "path_node_ids": list(row["path_node_ids"]),
        "path_edge_ids": list(row["path_edge_ids"]),
    }


def _write_move_batch(path: Path, route: dict[str, object]) -> None:
    path.write_text(
        json.dumps(
            {
                "commands": [
                    {
                        "op": "issue_move_order",
                        "formation": route["formation_id"],
                        "path_node_ids": route["path_node_ids"],
                        "path_edge_ids": route["path_edge_ids"],
                    },
                    {
                        "op": "commit_move_orders",
                        "faction": route["faction"],
                        "locked_stance": route["locked_stance"],
                    },
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


class PackagedCommandAuthorityContractTests(unittest.TestCase):
    def test_frozen_console_writeback_never_appends_ambient_backends(self) -> None:
        source = WRITEBACK.read_text(encoding="utf-8")
        func = source[source.index("func _backend_launch_candidates") :]
        frozen = func.index('backend_kind == "frozen_console"')
        frozen_return = func.index("return [", frozen)
        self.assertLess(
            frozen_return, func.index('{"executable": "gates-of-codex"', frozen_return)
        )
        self.assertLess(
            frozen_return, func.index('{"executable": "python"', frozen_return)
        )
        self.assertIn("Never ambient", func)
        self.assertIn("--expected-source-commit", func)
        self.assertIn("backend_source_commit", func)

    def test_windows_executable_runs_real_order_smoke(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("Packaged Earth3 real-order smoke", workflow)
        self.assertIn("GATES_OF_CODEX_LIVE_EXE", workflow)
        self.assertIn("tests.test_packaged_earth3_command_authority", workflow)

    def test_default_authority_root_uses_frozen_bundle_without_configure(self) -> None:
        original_root = earth3_campaign._default_authority_root
        original_configured = frozen_runtime._CONFIGURED_ROOT
        try:
            frozen_runtime._CONFIGURED_ROOT = None
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                with (
                    patch.object(sys, "frozen", True, create=True),
                    patch.object(sys, "_MEIPASS", str(root), create=True),
                ):
                    self.assertEqual(root, earth3_campaign._default_authority_root())
        finally:
            earth3_campaign._default_authority_root = original_root
            frozen_runtime._CONFIGURED_ROOT = original_configured

    def test_missing_sibling_live_backend_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fake_player = Path(temporary) / "GatesOfCodeX.exe"
            fake_player.write_bytes(b"not-an-exe")
            with patch.object(sys, "executable", str(fake_player)):
                with self.assertRaisesRegex(RuntimeError, "GatesOfCodeXLive.exe"):
                    _require_frozen_console_backend()

    def test_apply_frontend_fails_closed_when_authority_root_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            commands = root / "frontend_commands.json"
            environ = {**os.environ, "GATES_OF_CODEX_HOME": str(home)}
            with patch.dict(os.environ, environ, clear=False):
                state = build_scenario("earth3_v1", resolved_catalog=_resolved_catalog())
                save_campaign(state, campaign)
                write_frontend_snapshot(state, snapshot, campaign_path=campaign)
                route = _first_nato_route(state)
                _write_move_batch(commands, route)
                missing = root / "missing-authority"
                missing.mkdir()
                with patch.object(
                    earth3_campaign,
                    "_default_authority_root",
                    lambda: missing,
                ):
                    with self.assertRaises(Earth3AuthorityError):
                        apply_frontend_commands(
                            campaign,
                            commands_path=commands,
                            snapshot_path=snapshot,
                        )

    def test_apply_frontend_fails_closed_when_p3_marker_is_tampered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            commands = root / "frontend_commands.json"
            environ = {**os.environ, "GATES_OF_CODEX_HOME": str(root / "home")}
            with patch.dict(os.environ, environ, clear=False):
                state = build_scenario("earth3_v1", resolved_catalog=_resolved_catalog())
                save_campaign(state, campaign)
                write_frontend_snapshot(state, snapshot, campaign_path=campaign)
                _write_move_batch(commands, _first_nato_route(state))
                payload = json.loads(campaign.read_text(encoding="utf-8"))
                marker = payload["map_metadata"][P3_AUTHORITY_METADATA_KEY]
                marker["schema_version"] = int(marker["schema_version"]) + 1
                campaign.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
                    + "\n",
                    encoding="utf-8",
                )
                with self.assertRaises(Earth3OperationalAuthorityError):
                    apply_frontend_commands(
                        campaign,
                        commands_path=commands,
                        snapshot_path=snapshot,
                    )

    def test_mismatched_expected_commit_fails_before_apply(self) -> None:
        actual = "a" * 40
        expected = "b" * 40
        with patch(
            "gates_of_codex.packaging.resolve_source_commit", return_value=actual
        ):
            with self.assertRaisesRegex(PackagingError, "source commit mismatch"):
                enforce_packaged_backend_identity(
                    [
                        "apply-frontend",
                        "campaign.json",
                        "--expected-source-commit",
                        expected,
                    ],
                    frozen=True,
                )

    def test_frozen_apply_frontend_requires_expected_commit(self) -> None:
        with self.assertRaisesRegex(PackagingError, "--expected-source-commit"):
            enforce_packaged_backend_identity(
                ["apply-frontend", "campaign.json"],
                frozen=True,
            )

    def test_matching_expected_commit_is_stripped_from_argv(self) -> None:
        actual = "c" * 40
        with patch(
            "gates_of_codex.packaging.resolve_source_commit", return_value=actual
        ):
            remaining = enforce_packaged_backend_identity(
                [
                    "session-backend",
                    "campaign.json",
                    "--snapshot",
                    "snapshot.json",
                    "--expected-source-commit",
                    actual,
                ],
                frozen=True,
            )
        self.assertEqual(
            ["session-backend", "campaign.json", "--snapshot", "snapshot.json"],
            remaining,
        )

    def test_live_entry_rejects_mismatch_before_forward_or_auth(self) -> None:
        import run_gates_of_codex_live as live

        with (
            patch(
                "gates_of_codex.packaging.resolve_source_commit",
                return_value="d" * 40,
            ),
            patch.object(live, "_try_persistent_forward") as forward,
            patch.object(live, "_authenticate_frozen_earth3") as auth,
        ):
            code = live.main(
                [
                    "apply-frontend",
                    "campaign.json",
                    "--expected-source-commit",
                    "e" * 40,
                ]
            )
        self.assertEqual(2, code)
        forward.assert_not_called()
        auth.assert_not_called()

    def test_session_backend_launch_carries_windowed_package_commit(self) -> None:
        source = (ROOT / "src/gates_of_codex/persistent_backend.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"--expected-source-commit"', source)
        self.assertIn("source_commit", source)
        frozen = source.index("if getattr(sys, \"frozen\", False):")
        self.assertLess(
            frozen,
            source.index('"--expected-source-commit"', frozen),
        )

    def test_production_campaign_rejects_fixture_authority_marker(self) -> None:
        state = build_scenario("earth3_v1", resolved_catalog=_resolved_catalog())
        state.map_metadata[FIXTURE_AUTHORITY_KEY] = authored_fixture_authority_marker()
        with self.assertRaisesRegex(
            Earth3FixtureAuthorityError,
            "earth3_v1 cannot carry native-acceptance fixture authority",
        ):
            state.validate()


class PackagedEarth3RealOrderTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "packaged Live.exe is Windows-only")
    def test_frozen_live_apply_frontend_commits_authoritative_route(self) -> None:
        live = _live_executable()
        if live is None:
            raise unittest.SkipTest(
                "GATES_OF_CODEX_LIVE_EXE is unset; windows-executable builds it"
            )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            commands = root / "frontend_commands.json"
            environ = {**os.environ, "GATES_OF_CODEX_HOME": str(home)}
            with patch.dict(os.environ, environ, clear=False):
                state = build_scenario(
                    "earth3_v1", resolved_catalog=_resolved_catalog()
                )
                save_campaign(state, campaign)
                write_frontend_snapshot(state, snapshot, campaign_path=campaign)
                route = _first_nato_route(state)
                _write_move_batch(commands, route)
                control = json.loads(snapshot.read_text(encoding="utf-8"))["control"]
                control["python_executable"] = str(live)
                control["python_module"] = "gates_of_codex"
                control["backend_executable"] = str(live)
                control["backend_kind"] = "frozen_console"
                control["backend_source_commit"] = resolve_source_commit()
                payload = json.loads(snapshot.read_text(encoding="utf-8"))
                payload["control"] = control
                snapshot.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                completed = subprocess.run(
                    [
                        str(live),
                        "-m",
                        "gates_of_codex",
                        "apply-frontend",
                        str(campaign),
                        "--snapshot",
                        str(snapshot),
                        "--commands",
                        str(commands),
                        "--expected-source-commit",
                        control["backend_source_commit"],
                    ],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    timeout=300,
                    check=False,
                    env=environ,
                )
            output = completed.stdout + completed.stderr
            self.assertEqual(0, completed.returncode, output)
            report = json.loads(completed.stdout)
            self.assertTrue(report.get("ok"), report)
            reloaded = load_campaign(campaign)
            order = reloaded.strategic_formations[PLAYER_FORMATION].move_order
            self.assertIsNotNone(order)
            self.assertEqual(route["path_node_ids"], list(order.path_node_ids))
            self.assertEqual(route["path_edge_ids"], list(order.path_edge_ids))
            replacement = json.loads(snapshot.read_text(encoding="utf-8"))
            self.assertEqual(
                FRONTEND_SCHEMA_VERSION, int(replacement["schema_version"])
            )
            self.assertEqual(
                "gates-of-codex.frontend", str(replacement.get("schema", ""))
            )
            presented = next(
                row
                for row in replacement["strategic_formations"]
                if row["id"] == PLAYER_FORMATION
            )
            queued = presented["move_order"]
            self.assertEqual(route["path_node_ids"], queued["path_node_ids"])
            self.assertEqual(route["path_edge_ids"], queued["path_edge_ids"])

    @unittest.skipUnless(sys.platform == "win32", "packaged Live.exe is Windows-only")
    def test_frozen_live_rejects_tampered_p3_marker(self) -> None:
        live = _live_executable()
        if live is None:
            raise unittest.SkipTest(
                "GATES_OF_CODEX_LIVE_EXE is unset; windows-executable builds it"
            )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            commands = root / "frontend_commands.json"
            environ = {**os.environ, "GATES_OF_CODEX_HOME": str(root / "home")}
            with patch.dict(os.environ, environ, clear=False):
                state = build_scenario(
                    "earth3_v1", resolved_catalog=_resolved_catalog()
                )
                route = _first_nato_route(state)
                save_campaign(state, campaign)
                write_frontend_snapshot(state, snapshot, campaign_path=campaign)
                _write_move_batch(commands, route)
                payload = json.loads(campaign.read_text(encoding="utf-8"))
                marker = payload["map_metadata"][P3_AUTHORITY_METADATA_KEY]
                marker["schema_version"] = int(marker["schema_version"]) + 1
                campaign.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False)
                    + "\n",
                    encoding="utf-8",
                )
            completed = subprocess.run(
                [
                    str(live),
                    "-m",
                    "gates_of_codex",
                    "apply-frontend",
                    str(campaign),
                    "--snapshot",
                    str(snapshot),
                    "--commands",
                    str(commands),
                    "--expected-source-commit",
                    resolve_source_commit(),
                ],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
                env=environ,
            )
            output = completed.stdout + completed.stderr
            self.assertNotEqual(0, completed.returncode, output)
            self.assertNotIn("Earth3 manifest missing", output)

    @unittest.skipUnless(sys.platform == "win32", "packaged Live.exe is Windows-only")
    def test_frozen_live_rejects_wrong_windowed_package_commit(self) -> None:
        live = _live_executable()
        if live is None:
            raise unittest.SkipTest(
                "GATES_OF_CODEX_LIVE_EXE is unset; windows-executable builds it"
            )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            commands = root / "frontend_commands.json"
            environ = {**os.environ, "GATES_OF_CODEX_HOME": str(root / "home")}
            with patch.dict(os.environ, environ, clear=False):
                state = build_scenario(
                    "earth3_v1", resolved_catalog=_resolved_catalog()
                )
                save_campaign(state, campaign)
                write_frontend_snapshot(state, snapshot, campaign_path=campaign)
                _write_move_batch(commands, _first_nato_route(state))
            before = campaign.read_bytes()
            wrong = "0" * 40
            if wrong == resolve_source_commit():
                wrong = "1" * 40
            completed = subprocess.run(
                [
                    str(live),
                    "-m",
                    "gates_of_codex",
                    "apply-frontend",
                    str(campaign),
                    "--snapshot",
                    str(snapshot),
                    "--commands",
                    str(commands),
                    "--expected-source-commit",
                    wrong,
                ],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
                env=environ,
            )
            output = completed.stdout + completed.stderr
            self.assertNotEqual(0, completed.returncode, output)
            self.assertIn("source commit mismatch", output)
            self.assertEqual(before, campaign.read_bytes())
