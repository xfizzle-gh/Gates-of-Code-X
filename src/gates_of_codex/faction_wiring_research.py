from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

from .modstack import resource_root
from .faction_wiring_types import SourceResearchNode

RESEARCH_ROW_RE = re.compile(
    r'^\s*\{\s*(?:(tech)\s+)?"([^"]+)".*?requires\s+"([^"]*)".*?costs\s+(-?\d+)',
    re.I,
)


@dataclass(slots=True)
class SourceResearchIndex:
    nodes: dict[tuple[str, str], SourceResearchNode]
    children: dict[tuple[str, str], list[str]]

    @classmethod
    def build(cls, roots: Sequence[Path]) -> "SourceResearchIndex":
        nodes: dict[tuple[str, str], SourceResearchNode] = {}
        for priority, root in enumerate(roots):
            resources = resource_root(root)
            research_root = resources / "set/dynamic_campaign"
            if not research_root.is_dir():
                continue
            for path in sorted(research_root.glob("unit_research_*.set")):
                side = path.stem.removeprefix("unit_research_").lower()
                relative = path.relative_to(resources).as_posix()
                for node in _parse_research_file(
                    path,
                    side=side,
                    source_file=f"{priority}:{root.name}/{relative}",
                    source_layer=root.name,
                    source_priority=priority,
                ):
                    nodes[(side, node.node_id)] = node
        children: dict[tuple[str, str], list[str]] = defaultdict(list)
        for (side, node_id), node in nodes.items():
            children[(side, node.prerequisite)].append(node_id)
        for key in list(children):
            children[key] = sorted(set(children[key]))
        return cls(nodes=nodes, children=dict(children))

    def get(self, side: str, node_id: str) -> SourceResearchNode | None:
        return self.nodes.get((side, node_id))

    def descendants(self, side: str, root: str) -> list[SourceResearchNode]:
        if (side, root) not in self.nodes:
            return []
        ordered: list[SourceResearchNode] = []
        queue: deque[str] = deque([root])
        seen: set[str] = set()
        while queue:
            node_id = queue.popleft()
            if node_id in seen:
                continue
            seen.add(node_id)
            node = self.nodes.get((side, node_id))
            if node is None:
                continue
            ordered.append(node)
            queue.extend(self.children.get((side, node_id), []))
        return ordered


def _parse_research_file(
    path: Path,
    *,
    side: str,
    source_file: str,
    source_layer: str,
    source_priority: int,
) -> Iterator[SourceResearchNode]:
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith(";") or stripped.startswith("//"):
            continue
        match = RESEARCH_ROW_RE.search(line)
        if not match:
            continue
        yield SourceResearchNode(
            node_id=match.group(2),
            side=side,
            kind="tech" if match.group(1) else "unit",
            prerequisite=match.group(3),
            cost=max(0, int(match.group(4))),
            source_file=source_file,
            source_layer=source_layer,
            source_priority=source_priority,
        )
