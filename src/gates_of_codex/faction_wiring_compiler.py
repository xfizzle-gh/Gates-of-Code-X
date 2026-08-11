from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
import re
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
from .effective_definitions import EffectiveDefinitionIndex


_MOD_INFO_NAME_RE = re.compile(r'\{name\s+"([^"]+)"\}', re.I)
_QUARANTINE_SCHEMA = "gates-of-codex.faction-live-stack-quarantine"
_QUARANTINE_VERSION = 1


def _is_west81_layer(root: Path) -> bool:
    if root.name.casefold() in {"2897299509", "west81", "west-81"}:
        return True
    mod_info = root / "mod.info"
    if not mod_info.is_file():
        return False
    match = _MOD_INFO_NAME_RE.search(
        mod_info.read_text(encoding="utf-8-sig", errors="replace")
    )
    return bool(match and match.group(1) in {"West-81", "West81"})


def _apply_live_stack_quarantine(manifest: dict[str, Any]) -> None:
    """Exclude narrowly documented unusable live-stack purchase units.

    The compiler still fails closed for every other missing or invalid asset. This
    only changes selector input for exact units proven unusable by owner-native
    testing, before normal breed/definition validation runs.
    """
    source = files("gates_of_codex").joinpath("data", "faction_live_stack_quarantine.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if set(payload) != {"schema", "schema_version", "exclusions"}:
        raise FactionWiringError("Live-stack quarantine has invalid top-level fields")
    if payload["schema"] != _QUARANTINE_SCHEMA or payload["schema_version"] != _QUARANTINE_VERSION:
        raise FactionWiringError("Unsupported live-stack quarantine schema")
    exclusions = payload["exclusions"]
    if not isinstance(exclusions, list):
        raise FactionWiringError("Live-stack quarantine exclusions must be an array")

    components = manifest.get("components")
    if not isinstance(components, dict):
        raise FactionWiringError("Faction manifest components are unavailable for live-stack quarantine")
    for entry in exclusions:
        required = {"component_id", "selector_index", "exclude_regex", "reason"}
        if not isinstance(entry, dict) or set(entry) != required:
            raise FactionWiringError("Live-stack quarantine entry has invalid fields")
        component_id = entry["component_id"]
        component = components.get(component_id)
        if not isinstance(component, dict):
            raise FactionWiringError(
                f"Live-stack quarantine references unknown component {component_id}"
            )
        selector_index = entry["selector_index"]
        if isinstance(selector_index, bool) or not isinstance(selector_index, int):
            raise FactionWiringError(
                f"Live-stack quarantine selector index is invalid for {component_id}"
            )
        selectors = component.get("selectors")
        if not isinstance(selectors, list) or selector_index < 0 or selector_index >= len(selectors):
            raise FactionWiringError(
                f"Live-stack quarantine selector index is out of range for {component_id}: {selector_index}"
            )
        selector = selectors[selector_index]
        if selector.get("kind") not in {"research_branch", "prefix"}:
            raise FactionWiringError(
                f"Live-stack quarantine for {component_id} must target a selector supporting exclude_regex"
            )
        pattern = entry["exclude_regex"]
        reason = entry["reason"]
        if not isinstance(pattern, str) or not pattern or not isinstance(reason, str) or not reason:
            raise FactionWiringError(
                f"Live-stack quarantine entry is incomplete for {component_id}"
            )
        try:
            re.compile(pattern, re.I)
        except re.error as exc:
            raise FactionWiringError(
                f"Live-stack quarantine regex is invalid for {component_id}: {exc}"
            ) from exc
        existing = str(selector.get("exclude_regex", "") or "")
        selector["exclude_regex"] = (
            f"(?:{existing})|(?:{pattern})" if existing else pattern
        )


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
        if manifest is None:
            _apply_live_stack_quarantine(self.manifest)
        validate_faction_manifest(self.manifest)
        self.unit_index = SourceUnitIndex.build(self.roots)
        self.definition_index = EffectiveDefinitionIndex.build(
            self.roots,
            unit_index=self.unit_index,
        )
        self.research_index = SourceResearchIndex.build(self.roots)
        self._legacy_layer_priorities = {
            priority
            for priority, root in enumerate(self.roots)
            if _is_west81_layer(root)
        }
        self._breed_index: dict[tuple[str, str], tuple[Path, int]] | None = None

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