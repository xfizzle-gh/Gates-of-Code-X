from __future__ import annotations

from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Runtime CLI wrapper that installs the #207 snapshot acceleration."""

    from .frontend_fastpath import install_frontend_fast_path

    install_frontend_fast_path()
    from .entrypoint import main as application_main

    return application_main(argv)
