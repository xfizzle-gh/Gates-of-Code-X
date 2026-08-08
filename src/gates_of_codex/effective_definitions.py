from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
import hashlib
from pathlib import Path
import re
from typing import Iterable, Mapping, Sequence
import zipfile

from .faction_wiring_scan import SourceUnitIndex
from .faction_wiring_types import ReferenceKind
from .goh_source import SourceEntry, scan_source_entries
from .modstack import normalize_stack, resource_root


class DefinitionKind(str, Enum):
    VEHICLE_ENTITY = "vehicle_entity"
    PURCHASE_UNIT_WRAPPER = "purchase_unit_wrapper"
    STRATEGIC_CALL_IN = "strategic_call_in"
    INTERACTION_OBJECT = "interaction_object"
    REGISTRY_ALIAS = "registry_alias"


REFERENCE_TERMINAL_KINDS = {
    ReferenceKind.VEHICLE_ENTITY: frozenset({DefinitionKind.VEHICLE_ENTITY}),
    ReferenceKind.PURCHASE_UNIT: frozenset({DefinitionKind.PURCHASE_UNIT_WRAPPER}),
    ReferenceKind.STRATEGIC_CALL_IN: frozenset({DefinitionKind.STRATEGIC_CALL_IN}),
    ReferenceKind.INTERACTION_OBJECT: frozenset({DefinitionKind.INTERACTION_OBJECT}),
}


@dataclass(frozen=True, slots=True)
class DefinitionCandidate:
    identifier: str
    kind: DefinitionKind
    layer: str
    priority: int
    path: str
    line: int
    column: int
    packed: bool
    parser_form: str
    source_order: int
    alias_target: str = ""


@dataclass(frozen=True, slots=True)
class AliasHop:
    identifier: str
    target: str
    candidate: DefinitionCandidate


@dataclass(frozen=True, slots=True)
class DefinitionAmbiguity:
    identifier: str
    reason: str
    candidates: tuple[DefinitionCandidate, ...]


@dataclass(frozen=True, slots=True)
class DefinitionResolution:
    identifier: str
    reference_kind: ReferenceKind
    status: str
    candidates: tuple[DefinitionCandidate, ...] = ()
    winner: DefinitionCandidate | None = None
    shadowed: tuple[DefinitionCandidate, ...] = ()
    alias_chain: tuple[AliasHop, ...] = ()
    terminal: DefinitionCandidate | None = None
    ambiguity: DefinitionAmbiguity | None = None

    @property
    def ok(self) -> bool:
        return self.status == "resolved" and self.terminal is not None


class EffectiveDefinitionIndex:
    """Typed definition lookup over an explicitly ordered resource stack."""

    MAX_ALIAS_DEPTH = 32

    def __init__(
        self,
        candidates: Iterable[DefinitionCandidate] = (),
        *,
        semantic_signatures: Mapping[DefinitionCandidate, str] | None = None,
    ) -> None:
        grouped: dict[str, list[DefinitionCandidate]] = defaultdict(list)
        for candidate in candidates:
            grouped[candidate.identifier].append(candidate)
        self._candidates: Mapping[str, tuple[DefinitionCandidate, ...]] = {
            identifier: tuple(sorted(values, key=_report_key))
            for identifier, values in grouped.items()
        }
        self._semantic_signatures = dict(semantic_signatures or {})

    @classmethod
    def build(
        cls,
        roots: Sequence[str | Path],
        *,
        unit_index: SourceUnitIndex | None = None,
    ) -> "EffectiveDefinitionIndex":
        normalized_roots = normalize_stack(roots)
        source_units = unit_index or SourceUnitIndex.build(normalized_roots)
        candidates: list[DefinitionCandidate] = []
        signatures: dict[DefinitionCandidate, str] = {}
        for priority, root in enumerate(normalized_roots):
            resources = resource_root(root)
            for archive_path in sorted(
                path for path in resources.rglob("*")
                if path.is_file() and path.suffix.lower() == ".pak"
            ):
                if not zipfile.is_zipfile(archive_path):
                    continue
                with zipfile.ZipFile(archive_path, "r") as archive:
                    members = sorted(
                        (
                            info for info in archive.infolist()
                            if not info.is_dir() and _is_entity_definition_path(info.filename)
                        ),
                        key=lambda info: info.filename,
                    )
                    for source_order, member in enumerate(members):
                        content = archive.read(member)
                        candidate = DefinitionCandidate(
                            identifier=Path(member.filename).stem,
                            kind=DefinitionKind.VEHICLE_ENTITY,
                            layer=root.name,
                            priority=priority,
                            path=(
                                f"{archive_path.relative_to(resources).as_posix()}"
                                f"!/{member.filename.replace(chr(92), '/')}"
                            ),
                            line=1,
                            column=1,
                            packed=True,
                            parser_form="def_file",
                            source_order=source_order,
                        )
                        candidates.append(candidate)
                        signatures[candidate] = _content_signature(content)

            entity_root = resources / "entity"
            if entity_root.is_dir():
                for source_order, path in enumerate(sorted(
                    candidate for candidate in entity_root.rglob("*")
                    if candidate.is_file() and candidate.suffix.lower() == ".def"
                )):
                    candidate = DefinitionCandidate(
                        identifier=path.stem,
                        kind=DefinitionKind.VEHICLE_ENTITY,
                        layer=root.name,
                        priority=priority,
                        path=path.relative_to(resources).as_posix(),
                        line=1,
                        column=1,
                        packed=False,
                        parser_form="def_file",
                        source_order=source_order,
                    )
                    candidates.append(candidate)
                    signatures[candidate] = _content_signature(path.read_bytes())

            registry_root = resources / "set/registry"
            if registry_root.is_dir():
                for path in sorted(registry_root.rglob("*.reg")):
                    _append_source_candidates(
                        candidates,
                        signatures,
                        path=path,
                        resources=resources,
                        layer=root.name,
                        priority=priority,
                        mode="registry",
                        source_units=source_units,
                    )

            set_root = resources / "set"
            if set_root.is_dir():
                for path in sorted(
                    candidate for candidate in set_root.rglob("*")
                    if candidate.is_file() and candidate.suffix.lower() in {".set", ".goh"}
                ):
                    _append_source_candidates(
                        candidates,
                        signatures,
                        path=path,
                        resources=resources,
                        layer=root.name,
                        priority=priority,
                        mode="set",
                        source_units=source_units,
                    )

            interaction_root = resources / "set/interaction_entity"
            if not interaction_root.is_dir():
                continue
            for path in sorted(interaction_root.rglob("*.inc")):
                source = path.relative_to(resources).as_posix()
                text = path.read_text(encoding="utf-8-sig", errors="replace")
                for source_order, entry in enumerate(scan_source_entries(text, source).entries):
                    if not entry.name:
                        continue
                    candidate = DefinitionCandidate(
                        identifier=entry.name,
                        kind=DefinitionKind.INTERACTION_OBJECT,
                        layer=root.name,
                        priority=priority,
                        path=source,
                        line=entry.location.line,
                        column=entry.location.column,
                        packed=False,
                        parser_form=entry.form,
                        source_order=source_order,
                    )
                    candidates.append(candidate)
                    signatures[candidate] = _entry_signature(entry)
        _append_case_aliases(
            candidates,
            signatures,
            source_units=source_units,
            roots=normalized_roots,
        )
        return cls(candidates, semantic_signatures=signatures)

    def candidates_for(self, identifier: str) -> tuple[DefinitionCandidate, ...]:
        return self._candidates.get(identifier, ())

    def resolve(self, identifier: str, reference_kind: ReferenceKind) -> DefinitionResolution:
        return self._resolve(
            requested=identifier,
            current=identifier,
            reference_kind=reference_kind,
            visited=(),
            alias_chain=(),
            collected=(),
        )

    def _resolve(
        self,
        *,
        requested: str,
        current: str,
        reference_kind: ReferenceKind,
        visited: tuple[str, ...],
        alias_chain: tuple[AliasHop, ...],
        collected: tuple[DefinitionCandidate, ...],
    ) -> DefinitionResolution:
        if current in visited:
            return DefinitionResolution(
                identifier=requested,
                reference_kind=reference_kind,
                status="alias_cycle",
                candidates=collected,
                alias_chain=alias_chain,
            )
        candidates = self.candidates_for(current)
        combined = (*collected, *candidates)
        allowed = REFERENCE_TERMINAL_KINDS[reference_kind]
        terminals = tuple(candidate for candidate in candidates if candidate.kind in allowed)
        if terminals:
            winner, ambiguity = self._winner(current, terminals)
            if ambiguity is not None:
                return DefinitionResolution(
                    identifier=requested,
                    reference_kind=reference_kind,
                    status="ambiguous",
                    candidates=combined,
                    alias_chain=alias_chain,
                    ambiguity=ambiguity,
                )
            assert winner is not None
            selected = {hop.candidate for hop in alias_chain}
            selected.add(winner)
            return DefinitionResolution(
                identifier=requested,
                reference_kind=reference_kind,
                status="resolved",
                candidates=combined,
                winner=alias_chain[0].candidate if alias_chain else winner,
                shadowed=tuple(candidate for candidate in combined if candidate not in selected),
                alias_chain=alias_chain,
                terminal=winner,
            )

        aliases = tuple(
            candidate for candidate in candidates
            if candidate.kind == DefinitionKind.REGISTRY_ALIAS
        )
        if aliases:
            winner, ambiguity = self._winner(current, aliases)
            if ambiguity is not None:
                return DefinitionResolution(
                    identifier=requested,
                    reference_kind=reference_kind,
                    status="ambiguous",
                    candidates=combined,
                    alias_chain=alias_chain,
                    ambiguity=ambiguity,
                )
            assert winner is not None
            if len(alias_chain) >= self.MAX_ALIAS_DEPTH:
                return DefinitionResolution(
                    identifier=requested,
                    reference_kind=reference_kind,
                    status="alias_depth_exceeded",
                    candidates=combined,
                    winner=alias_chain[0].candidate if alias_chain else winner,
                    alias_chain=alias_chain,
                )
            hop = AliasHop(identifier=current, target=winner.alias_target, candidate=winner)
            resolution = self._resolve(
                requested=requested,
                current=winner.alias_target,
                reference_kind=reference_kind,
                visited=(*visited, current),
                alias_chain=(*alias_chain, hop),
                collected=combined,
            )
            if resolution.status == "missing":
                return DefinitionResolution(
                    identifier=requested,
                    reference_kind=reference_kind,
                    status="alias_dangling",
                    candidates=resolution.candidates,
                    winner=alias_chain[0].candidate if alias_chain else winner,
                    alias_chain=resolution.alias_chain,
                )
            return resolution

        return DefinitionResolution(
            identifier=requested,
            reference_kind=reference_kind,
            status="kind_mismatch" if candidates else "missing",
            candidates=combined,
            alias_chain=alias_chain,
        )

    def _winner(
        self,
        identifier: str,
        candidates: tuple[DefinitionCandidate, ...],
    ) -> tuple[DefinitionCandidate | None, DefinitionAmbiguity | None]:
        top_priority = max(map(_effective_priority, candidates))
        top = tuple(
            candidate for candidate in candidates
            if _effective_priority(candidate) == top_priority
        )
        semantic_values = {
            self._semantic_signatures.get(candidate, _default_semantic_signature(candidate))
            for candidate in top
        }
        if len(semantic_values) > 1:
            return None, DefinitionAmbiguity(
                identifier=identifier,
                reason="conflicting candidates at the same effective priority",
                candidates=top,
            )
        return top[0], None


def _effective_priority(candidate: DefinitionCandidate) -> tuple[int, int]:
    return candidate.priority, 0 if candidate.packed else 1


def _report_key(candidate: DefinitionCandidate) -> tuple[object, ...]:
    return (
        -candidate.priority,
        candidate.packed,
        candidate.layer,
        candidate.path,
        candidate.line,
        candidate.column,
        candidate.source_order,
        candidate.kind.value,
        candidate.alias_target,
        candidate.identifier,
    )


def _is_entity_definition_path(value: str) -> bool:
    normalized = value.replace("\\", "/").lstrip("/")
    if normalized.lower().startswith("resource/"):
        normalized = normalized[len("resource/"):]
    lowered = normalized.lower()
    return lowered.startswith("entity/") and lowered.endswith(".def")


def _content_signature(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _default_semantic_signature(candidate: DefinitionCandidate) -> str:
    return f"{candidate.kind.value}\0{candidate.alias_target}\0{candidate.parser_form}"


def _append_source_candidates(
    candidates: list[DefinitionCandidate],
    signatures: dict[DefinitionCandidate, str],
    *,
    path: Path,
    resources: Path,
    layer: str,
    priority: int,
    mode: str,
    source_units: SourceUnitIndex,
) -> None:
    relative = path.relative_to(resources).as_posix()
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    for source_order, entry in enumerate(scan_source_entries(text, relative).entries):
        if not entry.name:
            continue
        declarations: list[tuple[DefinitionKind, str, str]] = []
        alias_target = _alias_target(entry)
        if alias_target:
            declarations.append((DefinitionKind.REGISTRY_ALIAS, alias_target, "source_alias"))
        elif mode == "registry":
            declarations.append((DefinitionKind.VEHICLE_ENTITY, "", "registry_row"))

        if mode == "set":
            if _is_strategic_declaration(entry):
                declarations.append((DefinitionKind.STRATEGIC_CALL_IN, "", entry.form))
            if _is_purchase_wrapper(relative, entry, source_units):
                declarations.append((DefinitionKind.PURCHASE_UNIT_WRAPPER, "", entry.form))
            if _is_implicit_vehicle_wrapper(entry):
                declarations.append((DefinitionKind.VEHICLE_ENTITY, "", "implicit_vehicle_wrapper"))

        for kind, target, parser_form in declarations:
            candidate = DefinitionCandidate(
                identifier=entry.name,
                kind=kind,
                layer=layer,
                priority=priority,
                path=relative,
                line=entry.location.line,
                column=entry.location.column,
                packed=False,
                parser_form=parser_form,
                source_order=source_order,
                alias_target=target,
            )
            candidates.append(candidate)
            signatures[candidate] = (
                f"alias\0{target}"
                if kind == DefinitionKind.REGISTRY_ALIAS
                else _entry_signature(entry)
            )


def _entry_signature(entry: SourceEntry) -> str:
    return _content_signature(entry.raw.encode("utf-8"))


def _alias_target(entry: SourceEntry) -> str:
    value = ""
    for call in entry.calls:
        if call.family in {"alias", "control"} and call.value:
            value = call.value
            break
        if (
            call.family == "inherit"
            and call.value
            and re.match(r"^(?:vehicle|entity)(?:[/\\\s]+)", call.value, flags=re.I)
        ):
            value = call.value
            break
    if not value:
        return ""
    value = re.sub(r"^(?:vehicle|entity)(?:[/\\\s]+)", "", value, flags=re.I)
    value = value.replace("\\", "/").rstrip("/")
    name = value.rsplit("/", 1)[-1]
    return Path(name).stem if name.lower().endswith(".def") else name


def _is_strategic_declaration(entry: SourceEntry) -> bool:
    shape = entry.macro_kind.lower()
    if shape not in {"offmap_support", "strategic_doctrine"}:
        return False
    return any(
        call.family == "action"
        and call.value.lower() in {"callin", "call_in", "strategic", "offmap"}
        for call in entry.calls
    )


def _is_purchase_wrapper(
    relative: str,
    entry: SourceEntry,
    source_units: SourceUnitIndex,
) -> bool:
    normalized = relative.lower()
    if not normalized.startswith("set/multiplayer/units/"):
        return False
    unit = source_units.units.get(entry.name)
    return unit is not None and unit.materializable


def _is_implicit_vehicle_wrapper(entry: SourceEntry) -> bool:
    if any(call.family in {"vehicle", "entity"} for call in entry.calls):
        return False
    shape = entry.macro_kind.lower()
    return bool(shape) and (
        any(token in shape for token in ("vehicle", "tank", "cannon", "artillery", "mortar"))
        or any(call.family == "crew" for call in entry.calls)
    )


def _append_case_aliases(
    candidates: list[DefinitionCandidate],
    signatures: dict[DefinitionCandidate, str],
    *,
    source_units: SourceUnitIndex,
    roots: Sequence[Path],
) -> None:
    definition_spellings: dict[str, set[str]] = defaultdict(set)
    for candidate in candidates:
        if candidate.kind == DefinitionKind.VEHICLE_ENTITY and candidate.parser_form == "def_file":
            definition_spellings[candidate.identifier.casefold()].add(candidate.identifier)

    references = sorted(
        (
            reference
            for unit in source_units.units.values()
            for reference in unit.definition_references
            if reference.kind == ReferenceKind.VEHICLE_ENTITY
        ),
        key=lambda reference: (
            reference.source,
            reference.line,
            reference.column,
            reference.identifier,
        ),
    )
    source_orders: dict[str, int] = defaultdict(int)
    for reference in references:
        targets = sorted(definition_spellings.get(reference.identifier.casefold(), ()))
        if reference.identifier in targets:
            continue
        provenance = _reference_provenance(reference.source, roots)
        if provenance is None:
            continue
        priority, layer, path = provenance
        source_order = source_orders[reference.source]
        source_orders[reference.source] += 1
        for target in targets:
            candidate = DefinitionCandidate(
                identifier=reference.identifier,
                kind=DefinitionKind.REGISTRY_ALIAS,
                layer=layer,
                priority=priority,
                path=path,
                line=reference.line,
                column=reference.column,
                packed=False,
                parser_form="case_alias:def_stem",
                source_order=source_order,
                alias_target=target,
            )
            candidates.append(candidate)
            signatures[candidate] = f"alias\0{target}"


def _reference_provenance(
    source: str,
    roots: Sequence[Path],
) -> tuple[int, str, str] | None:
    match = re.match(r"^(\d+):([^/]+)/(.*)$", source)
    if match is None:
        return None
    priority = int(match.group(1))
    layer = roots[priority].name if 0 <= priority < len(roots) else match.group(2)
    return priority, layer, match.group(3)
