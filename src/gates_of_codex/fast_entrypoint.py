from __future__ import annotations

import sys
from collections.abc import Sequence


def _install_fast_paths() -> None:
    from .frontend_fastpath import install_frontend_fast_path
    from .turn_cycle import install_frontend_turn_cycle_op

    install_frontend_fast_path()
    install_frontend_turn_cycle_op()


def main(argv: Sequence[str] | None = None) -> int:
    """Runtime CLI wrapper for the post-P5 responsiveness layer (#207)."""
    _install_fast_paths()
    from .entrypoint import main as application_main

    return application_main(argv)


def player_main(argv: Sequence[str] | None = None) -> int:
    """Run the packaged player shell directly, preserving the #207 fast paths."""
    _install_fast_paths()
    from .frozen_runtime import configure_frozen_earth3_authority
    from .player_shell import main as player_shell_main, read_last_campaign

    configure_frozen_earth3_authority()
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        arguments = ["--continue"] if read_last_campaign() is not None else ["--new"]
    return player_shell_main(arguments)
