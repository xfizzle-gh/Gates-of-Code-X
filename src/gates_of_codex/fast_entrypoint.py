from __future__ import annotations

from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Runtime CLI wrapper for the post-P5 responsiveness layer (#207)."""

    from .frontend_fastpath import install_frontend_fast_path
    from .turn_cycle import install_frontend_turn_cycle_op

    install_frontend_fast_path()
    install_frontend_turn_cycle_op()
    from .entrypoint import main as application_main

    return application_main(argv)
