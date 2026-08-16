from __future__ import annotations

import sys

from gates_of_codex.frozen_runtime import configure_frozen_earth3_authority
from gates_of_codex.issue212_economy_profile import install_issue212_economy_profiler
from gates_of_codex.packaging import PackagingError, enforce_packaged_backend_identity
from gates_of_codex.startup_rebaseline import install_startup_rebaseline_contracts


_ACCEPTANCE_COMMANDS = {
    "maps",
    "profiles",
    "validate",
    "first-test",
    "backup",
    "restore",
    "cleanup-save",
    "handoff",
    "verify",
}


def _authenticate_frozen_earth3() -> None:
    root = configure_frozen_earth3_authority()
    if root is None:
        return

    from gates_of_codex.earth3_campaign import load_earth3_authority
    from gates_of_codex.earth3_operational import load_authenticated_p3_graph

    p1 = load_earth3_authority()
    p3 = load_authenticated_p3_graph()
    if p1.production_asset_version != "earth3_production_v1":
        raise RuntimeError("Frozen Earth3 P1 production authority version mismatch")
    if len(p3.get("nodes", [])) != 64 or len(p3.get("edges", [])) != 65:
        raise RuntimeError("Frozen Earth3 P3 operational authority count mismatch")


def _normalize_arguments(argv: list[str]) -> list[str]:
    arguments = list(argv)
    if len(arguments) >= 2 and arguments[:2] == ["-m", "gates_of_codex"]:
        arguments = arguments[2:]
    return arguments


def _try_persistent_forward(arguments: list[str]) -> int | None:
    if arguments[:1] != ["apply-frontend"]:
        return None
    from gates_of_codex.persistent_backend import try_forward_apply_frontend

    forwarded = try_forward_apply_frontend(arguments)
    if forwarded is None:
        return None
    exit_code, output = forwarded
    if output:
        sys.stdout.write(output)
        if not output.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
    return int(exit_code)


def main(argv: list[str] | None = None) -> int:
    """Serve both live-acceptance commands and the packaged write-back backend.

    Godot needs a console-subsystem process for `apply-frontend` so the JSON
    result remains capturable for handoff/verify/import state. The player GUI is
    windowed and is therefore not the authoritative write-back transport.
    """
    arguments = _normalize_arguments(list(sys.argv[1:] if argv is None else argv))
    try:
        invocation = enforce_packaged_backend_identity(arguments)
    except PackagingError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    arguments = list(invocation.arguments)
    install_startup_rebaseline_contracts()
    install_issue212_economy_profiler()

    # The persistent #207 backend authenticates once when the session starts.
    # Fast command clients forward before repeating the expensive frozen P1/P3
    # startup checks. If no healthy session exists, preserve the original
    # fail-closed one-shot path below.
    forwarded = _try_persistent_forward(arguments)
    if forwarded is not None:
        return forwarded

    _authenticate_frozen_earth3()

    if not arguments or arguments[0] in _ACCEPTANCE_COMMANDS or arguments[0] in {
        "-h",
        "--help",
    }:
        from gates_of_codex.acceptance_cli import main as acceptance_main

        return acceptance_main(arguments)

    from gates_of_codex.fast_entrypoint import (
        dispatch_authenticated_packaged_invocation,
    )

    return dispatch_authenticated_packaged_invocation(
        invocation, process_argv=arguments
    )


if __name__ == "__main__":
    raise SystemExit(main())
