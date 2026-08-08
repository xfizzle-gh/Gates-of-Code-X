from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from .modstack import normalize_stack, stack_signature
from .faction_wiring_actors import FactionActorMixin
from .faction_wiring_components import FactionComponentMixin
from .faction_wiring_manifest import (
    _canonical_sha256, _pretty_json, load_faction_manifest, validate_faction_manifest,
)
from .faction_wiring_models import (
    OUTPUT_SCHEMA, OUTPUT_VERSION, FactionWiringError, ResolutionProblem,
)
from .faction_wiring_report import render_faction_summary
from .faction_wiring_research import SourceResearchIndex
from .faction_wiring_scan import SourceUnitIndex


class FactionWiringCompiler(FactionComponentMixin, FactionActorMixin):
    def __init__(
        self,
        resource_stack: Iterable[str | Path],
        *,
        manifest: Mapping[str, Any] | None = None,
    ) -> None:
        self.roots = normalize_stack(resource_stack)
        if not self.roots:
            raise FactionWiringError("Faction wiring requires an ordered resource stack")
        for root in self.roots:
            if not root.is_dir():
                raise FileNotFoundError(f"Stack layer does not exist: {root}")
        self.manifest = dict(manifest or load_faction_manifest())
        validate_faction_manifest(self.manifest)
        self.unit_index = SourceUnitIndex.build(self.roots)
        self.research_index = SourceResearchIndex.build(self.roots)
        self._breed_index: dict[tuple[str, str], tuple[Path, int]] | None = None
        self._vehicle_index: set[str] | None = None

    def compile(self) -> dict[str, Any]:
        components = self.manifest["components"]
        resolved_components = {
            component_id: self._resolve_component(component_id, component)
            for component_id, component in sorted(components.items())
        }
        actors: list[dict[str, Any]] = []
        problems: list[ResolutionProblem] = []
        for actor in sorted(self.manifest["actors"], key=lambda item: item["actor_id"]):
            actor_result, actor_problems = self._resolve_actor(actor, resolved_components)
            actors.append(actor_result)
            problems.extend(actor_problems)
        problems.sort(key=lambda item: (item.severity, item.actor_id, item.component_id, item.message))
        payload: dict[str, Any] = {
            "schema": OUTPUT_SCHEMA,
            "schema_version": OUTPUT_VERSION,
            "manifest_schema_version": self.manifest["schema_version"],
            "stack_signature": stack_signature(self.roots),
            "manifest_sha256": _canonical_sha256(self.manifest),
            "source_policy": self.manifest["source_policy"],
            "source_layers": [
                {"priority": index, "name": root.name, "path": str(root)}
                for index, root in enumerate(self.roots)
            ],
            "actor_count": len(actors),
            "actors": actors,
            "problems": [item.to_dict() for item in problems],
            "error_count": sum(item.severity == "error" for item in problems),
            "warning_count": sum(item.severity == "warning" for item in problems),
        }
        payload["wiring_signature"] = _canonical_sha256(payload)
        return payload

    def write(self, output: str | Path, summary: str | Path) -> dict[str, Any]:
        payload = self.compile()
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(_pretty_json(payload), encoding="utf-8")
        summary_path = Path(summary)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(render_faction_summary(payload), encoding="utf-8")
        return payload
