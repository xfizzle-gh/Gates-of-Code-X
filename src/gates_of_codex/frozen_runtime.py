from __future__ import annotations

import functools
import sys
from pathlib import Path
from typing import Any


_CONFIGURED_ROOT: Path | None = None


def frozen_bundle_root() -> Path | None:
    """Return PyInstaller's extraction root, or ``None`` outside a frozen build."""
    if not bool(getattr(sys, "frozen", False)):
        return None
    value = getattr(sys, "_MEIPASS", None)
    if not value:
        raise RuntimeError("Frozen Gates of CodeX runtime is missing sys._MEIPASS")
    root = Path(value).resolve(strict=True)
    if not root.is_dir():
        raise RuntimeError(f"Frozen Gates of CodeX bundle root is not a directory: {root}")
    return root


def configure_frozen_earth3_authority() -> Path | None:
    """Bind existing P1/P3 exact-byte loaders to the PyInstaller bundle root.

    Source and installed layouts keep their existing authority-root behavior.
    Frozen one-file applications place repository-shaped data at ``sys._MEIPASS``;
    this packaging seam changes only the default root passed to the already
    authenticated loaders. It does not alter any authority document or hash.
    """
    global _CONFIGURED_ROOT

    root = frozen_bundle_root()
    if root is None:
        return None
    if _CONFIGURED_ROOT == root:
        return root

    from . import earth3_campaign, earth3_operational

    def bundled_p1_root() -> Path:
        return root

    earth3_campaign._default_authority_root = bundled_p1_root

    current_loader = earth3_operational.load_authenticated_p3_graph
    if not bool(getattr(current_loader, "_goc_frozen_authority_wrapper", False)):
        original_loader = current_loader

        @functools.wraps(original_loader)
        def bundled_p3_loader(*, repository_root: Path | None = None) -> dict[str, Any]:
            return original_loader(
                repository_root=root if repository_root is None else repository_root
            )

        bundled_p3_loader._goc_frozen_authority_wrapper = True  # type: ignore[attr-defined]
        bundled_p3_loader._goc_frozen_authority_root = root  # type: ignore[attr-defined]
        earth3_operational.load_authenticated_p3_graph = bundled_p3_loader

    _CONFIGURED_ROOT = root
    return root
