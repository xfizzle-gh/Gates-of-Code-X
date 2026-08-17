from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Mapping

from . import campaign_menu
from .local_discovery import LaunchPathDiscovery, detect_launch_paths as _detect_launch_paths


GATES_CODEX_LIVE_WORKSHOP_ID = "3696721120"
LIVE_DEPLOYMENT_MANIFEST = ".goc-deployment-manifest.json"
LIVE_DEPLOYMENT_SCHEMA = "gates-of-codex.live-workshop-deployment"


def _clean(value: object) -> str:
    return str(value or "").strip()


def _current_source_commit() -> str:
    try:
        from .packaging import resolve_source_commit

        return _clean(resolve_source_commit()).lower()
    except Exception:
        return ""


def _live_manifest(root: Path) -> dict[str, object] | None:
    source = root / LIVE_DEPLOYMENT_MANIFEST
    if not source.is_file():
        return None
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _is_exact_live_gates_root(value: str | Path | None, *, source_commit: str) -> bool:
    text = _clean(value)
    if not text:
        return False
    root = Path(text).expanduser()
    if not root.is_dir() or root.name != GATES_CODEX_LIVE_WORKSHOP_ID:
        return False
    mod_info = root / "mod.info"
    if not mod_info.is_file():
        return False
    try:
        identity = mod_info.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return False
    if "Gates of CodeX" not in identity and "Gates of Code:X" not in identity:
        return False
    manifest = _live_manifest(root)
    if manifest is None or manifest.get("schema") != LIVE_DEPLOYMENT_SCHEMA:
        return False
    if _clean(manifest.get("target_root")):
        try:
            if Path(_clean(manifest.get("target_root"))).expanduser().resolve() != root.resolve():
                return False
        except OSError:
            return False
    deployed_commit = _clean(manifest.get("source_commit")).lower()
    return bool(source_commit and deployed_commit == source_commit)


def _candidate_live_roots(
    discovered: LaunchPathDiscovery,
    environ: Mapping[str, str],
) -> tuple[Path, ...]:
    candidates: list[Path] = []

    configured = _clean(environ.get("GATES_CODEX_ROOT"))
    if configured:
        candidates.append(Path(configured).expanduser())

    environment = dict(discovered.environment)
    for key in ("WEST81_ROOT", "CODEX_ROOT", "CODEX_AI_OVERHAUL_ROOT"):
        raw = _clean(environment.get(key))
        if not raw:
            continue
        layer = Path(raw).expanduser()
        # .../steamapps/workshop/content/400750/<item id>
        if layer.parent.name == "400750":
            candidates.append(layer.parent / GATES_CODEX_LIVE_WORKSHOP_ID)

    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if resolved not in unique:
            unique.append(resolved)
    return tuple(unique)


def detect_launch_paths(
    scenario_id: str,
    *,
    environ: Mapping[str, str] | None = None,
    **kwargs,
) -> LaunchPathDiscovery:
    """Run normal discovery, but never replace an exact live GoH Gates layer.

    The source checkout remains the authority for the stack config and Godot
    project. The final GoH stack layer must instead be the guarded live Workshop
    deployment that GoH itself loads. P6 native acceptance proved that validating
    the checkout while GoH loads Workshop item 3696721120 is not an acceptable
    handoff boundary.
    """

    env = os.environ if environ is None else environ
    discovered = _detect_launch_paths(scenario_id, environ=env, **kwargs)
    source_commit = _current_source_commit()
    live_root = next(
        (
            candidate.resolve()
            for candidate in _candidate_live_roots(discovered, env)
            if _is_exact_live_gates_root(candidate, source_commit=source_commit)
        ),
        None,
    )
    if live_root is None:
        return discovered

    updated: list[tuple[str, str]] = []
    replaced_root = False
    for key, value in discovered.environment:
        if key == "GATES_CODEX_ROOT":
            updated.append((key, str(live_root)))
            replaced_root = True
        else:
            updated.append((key, value))
    if not replaced_root:
        updated.append(("GATES_CODEX_ROOT", str(live_root)))
    return replace(discovered, environment=tuple(updated))


def main() -> int:
    # campaign_menu imported detect_launch_paths directly, so install the native
    # runtime-aware scanner before constructing the Tk UI.
    campaign_menu.detect_launch_paths = detect_launch_paths
    return campaign_menu.main()


if __name__ == "__main__":
    raise SystemExit(main())
