from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from gates_of_codex import campaign_menu_runtime, player_shell
from gates_of_codex.local_discovery import LaunchPathDiscovery


COMMIT = "a" * 40


def _discovery(tmp_path: Path, gates_root: Path) -> LaunchPathDiscovery:
    workshop = tmp_path / "Steam" / "steamapps" / "workshop" / "content" / "400750"
    west81 = workshop / "2897299509"
    codex = workshop / "3261086933"
    ai = workshop / "3636883799"
    for path in (west81, codex, ai, gates_root):
        path.mkdir(parents=True, exist_ok=True)
    return LaunchPathDiscovery(
        campaign_file=str(tmp_path / "campaign.json"),
        continue_campaign_file="",
        stack_config=str(tmp_path / "mod-stack.windows.json"),
        game_directory=str(tmp_path / "game"),
        profile_directory=str(tmp_path / "profile"),
        godot_executable=str(tmp_path / "Godot.exe"),
        godot_project=str(tmp_path / "godot"),
        environment=(
            ("WEST81_ROOT", str(west81)),
            ("CODEX_ROOT", str(codex)),
            ("CODEX_AI_OVERHAUL_ROOT", str(ai)),
            ("GATES_CODEX_ROOT", str(gates_root)),
        ),
        missing=(),
    )


def _deploy_live(root: Path, commit: str = COMMIT) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "mod.info").write_text('{mod\n{name "Gates of CodeX"}\n}\n', encoding="utf-8")
    (root / ".goc-deployment-manifest.json").write_text(
        json.dumps(
            {
                "schema": "gates-of-codex.live-workshop-deployment",
                "schema_version": 1,
                "source_commit": commit,
                "target_root": str(root.resolve()),
            }
        ),
        encoding="utf-8",
    )


def test_menu_scanner_uses_exact_guarded_live_workshop_layer(monkeypatch, tmp_path: Path) -> None:
    source_checkout = tmp_path / "Gates-of-Code-X"
    source_checkout.mkdir()
    workshop = tmp_path / "Steam" / "steamapps" / "workshop" / "content" / "400750"
    live = workshop / "3696721120"
    discovered = _discovery(tmp_path, source_checkout)
    _deploy_live(live)

    monkeypatch.setattr(campaign_menu_runtime, "_detect_launch_paths", lambda *_a, **_k: discovered)
    monkeypatch.setattr(campaign_menu_runtime, "_current_source_commit", lambda: COMMIT)

    result = campaign_menu_runtime.detect_launch_paths("ww3_2028_expanded", environ={})

    assert dict(result.environment)["GATES_CODEX_ROOT"] == str(live.resolve())


def test_menu_scanner_refuses_stale_live_workshop_deployment(monkeypatch, tmp_path: Path) -> None:
    source_checkout = tmp_path / "Gates-of-Code-X"
    source_checkout.mkdir()
    workshop = tmp_path / "Steam" / "steamapps" / "workshop" / "content" / "400750"
    live = workshop / "3696721120"
    discovered = _discovery(tmp_path, source_checkout)
    _deploy_live(live, commit="b" * 40)

    monkeypatch.setattr(campaign_menu_runtime, "_detect_launch_paths", lambda *_a, **_k: discovered)
    monkeypatch.setattr(campaign_menu_runtime, "_current_source_commit", lambda: COMMIT)

    result = campaign_menu_runtime.detect_launch_paths("ww3_2028_expanded", environ={})

    assert dict(result.environment)["GATES_CODEX_ROOT"] == str(source_checkout)


def test_gui_prelaunch_persists_resolved_live_stack(monkeypatch, tmp_path: Path) -> None:
    stack = [
        str(tmp_path / "vanilla"),
        str(tmp_path / "west81"),
        str(tmp_path / "codex"),
        str(tmp_path / "ai"),
        str(tmp_path / "3696721120"),
    ]
    state = SimpleNamespace(
        map_metadata={"stack_config": str(tmp_path / "mod-stack.windows.json")},
        game_directory=str(tmp_path / "game"),
        profile_directory=str(tmp_path / "profile"),
        code_x_directory="stale-checkout",
    )
    calls = []

    def validate_stack(stack_config, *, game_directory, profile_directory, required):
        calls.append((stack_config, game_directory, profile_directory, required))
        return list(stack)

    monkeypatch.setattr(player_shell, "validate_stack", validate_stack)
    monkeypatch.setattr(player_shell, "_codex_layer_from_stack", lambda _layers: stack[2])

    campaign_menu_runtime._persist_resolved_stack_context(state)

    assert state.map_metadata["resource_stack"] == stack
    assert state.code_x_directory == stack[2]
    assert calls == [
        (
            str(tmp_path / "mod-stack.windows.json"),
            str(tmp_path / "game"),
            str(tmp_path / "profile"),
            True,
        )
    ]


def test_menu_entrypoint_routes_through_live_stack_runtime() -> None:
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert 'gates-of-codex-menu = "gates_of_codex.campaign_menu_runtime:main"' in pyproject
