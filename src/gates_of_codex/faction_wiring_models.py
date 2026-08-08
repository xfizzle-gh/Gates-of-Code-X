from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

MANIFEST_SCHEMA = "gates-of-codex.faction-wiring"
MANIFEST_VERSION = 1
OUTPUT_SCHEMA = "gates-of-codex.resolved-factions"
OUTPUT_VERSION = 1
SUPPORTED_TACTICAL_SIDES = frozenset({"nato", "ukr", "rusa", "prc"})
ACTOR_TYPES = frozenset({"sovereign", "separatist", "expeditionary", "auxiliary", "pmc", "volunteer"})
ROSTER_CLASSES = frozenset({"full_national", "national_hybrid", "coalition_fallback", "proxy_hybrid", "nonstate"})
RESEARCH_MODES = frozenset({"native", "hybrid", "generated"})
SELECTOR_KINDS = frozenset({"research_branch", "exact", "prefix", "regex", "virtual"})
PROVENANCE_POLICIES = frozenset({"modern_only", "legacy_explicit", "mixed"})


class FactionWiringError(ValueError):
    pass


@dataclass(slots=True)
class ResolvedResearchNode:
    key: str
    actor_id: str
    node_type: str
    display_name: str
    cost: int
    prerequisites: list[str] = field(default_factory=list)
    unlock_units: list[str] = field(default_factory=list)
    source_node: str = ""
    source_file: str = ""
    component_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ResolutionProblem:
    severity: str
    actor_id: str
    component_id: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(slots=True)
class _ResolvedComponent:
    component_id: str
    provenance_policy: str = "mixed"
    research_label: str = ""
    units: dict[str, SourceUnit] = field(default_factory=dict)
    research_nodes: dict[str, SourceResearchNode] = field(default_factory=dict)
    branch_roots: list[str] = field(default_factory=list)
    problems: list[ResolutionProblem] = field(default_factory=list)
