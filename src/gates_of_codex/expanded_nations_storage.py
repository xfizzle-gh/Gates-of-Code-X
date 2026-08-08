from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from .expanded_nations_compile import recover_interrupted_compile
from .expanded_nations_transaction import (
    deactivate_actor_projection as _deactivate_actor_projection,
    install_projection as _install_projection,
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


def install_projection(
    root: Path,
    outputs: Mapping[Path, bytes],
    manifest_bytes: bytes,
    *,
    post_commit_verify: Callable[[], Any] | None = None,
) -> None:
    recover_interrupted_compile(root)
    _install_projection(
        root,
        outputs,
        manifest_bytes,
        post_commit_verify=post_commit_verify,
    )


def deactivate_actor_projection(gates_root: str | Path) -> bool:
    root = Path(gates_root).expanduser().resolve()
    recover_interrupted_compile(root)
    return _deactivate_actor_projection(root)


def verify_actor_projection(gates_root: str | Path) -> dict[str, Any]:
    root = Path(gates_root).expanduser().resolve()
    recover_interrupted_compile(root)
    recover_interrupted_deactivation(root)
    return verify_actor_projection_files(root)
