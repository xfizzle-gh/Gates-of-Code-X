from __future__ import annotations

from pathlib import Path
from typing import Any

from .expanded_nations_transaction import (
    deactivate_actor_projection,
    install_projection,
    recover_interrupted_deactivation,
)
from .expanded_nations_verify import (
    load_manifest,
    verify_actor_projection_files,
    verify_manifest_files,
    verify_projection_artifacts,
)

__all__ = [
    "deactivate_actor_projection",
    "install_projection",
    "load_manifest",
    "verify_actor_projection",
    "verify_manifest_files",
    "verify_projection_artifacts",
]


def verify_actor_projection(gates_root: str | Path) -> dict[str, Any]:
    root = Path(gates_root).expanduser().resolve()
    recover_interrupted_deactivation(root)
    return verify_actor_projection_files(root)
