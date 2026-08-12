from __future__ import annotations

import sys

from gates_of_codex.frozen_runtime import configure_frozen_earth3_authority


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


def main(argv: list[str] | None = None) -> int:
    """Serve both live-acceptance commands and the packaged write-back backend.

    Godot needs a console-subsystem process for `apply-frontend` so the JSON
    result remains capturable for handoff/verify/import state.  The player GUI is
    windowed and is therefore not the authoritative write-back transport.
    """
    _authenticate_frozen_earth3()
    arguments = _normalize_arguments(list(sys.argv[1:] if argv is None else argv))

    if not arguments or arguments[0] in _ACCEPTANCE_COMMANDS or arguments[0] in {
        "-h",
        "--help",
    }:
        from gates_of_codex.acceptance_cli import main as acceptance_main

        return acceptance_main(arguments)

    from gates_of_codex.fast_entrypoint import main as application_main

    return application_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
