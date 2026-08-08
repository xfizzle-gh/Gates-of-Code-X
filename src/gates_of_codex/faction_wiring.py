from __future__ import annotations

from .faction_wiring_compiler import FactionWiringCompiler
from .faction_wiring_manifest import load_faction_manifest, validate_faction_manifest
from .faction_wiring_models import (
    FactionWiringError, ResolutionProblem, ResolvedResearchNode,
)
from .faction_wiring_report import main, render_faction_summary

__all__ = [
    "FactionWiringCompiler",
    "FactionWiringError",
    "ResolutionProblem",
    "ResolvedResearchNode",
    "load_faction_manifest",
    "validate_faction_manifest",
    "render_faction_summary",
    "main",
]

if __name__ == "__main__":
    raise SystemExit(main())
