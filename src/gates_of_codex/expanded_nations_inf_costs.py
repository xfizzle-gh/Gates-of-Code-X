from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from .expanded_nations_breeds import (
    _CROSS_SIDE_BREED_COMPONENTS,
    _resolve_source_breed,
)
from .expanded_nations_models import ExpandedNationsError, GENERATED_MARKER, sha256_bytes
from .expanded_nations_sources import _rename_entry
from .goh_source import SourceEntry, scan_source_entries
from .modstack import resource_root

_COST_RE = re.compile(
    r"\{\s*cost\s+(-?(?:\d+(?:\.\d*)?|\.\d+))\s*\}",
    re.IGNORECASE,
)
_SIDE_RE_TEMPLATE = r"\bside\s*\(\s*%s\s*\)"
_INF_MARKER = "; goc-inf-cost "
_ROSTER_INSERT_BEFORE = '\t(include "conquest/goc_opponent_units.set")'


@dataclass(frozen=True, slots=True)
class ProjectedInfCost:
    source_path: str
    target_path: str
    source_side: str
    target_side: str
    cost: float
    source_reference: str
    source_sha256: str
    projected_sha256: str


@dataclass(frozen=True, slots=True)
class _IndexedInfRow:
    entry: SourceEntry
    source_reference: str
    priority: int


def project_actor_inf_cost_rows(
    actor: Mapping[str, Any],
    roots: Sequence[Path],
) -> tuple[list[ProjectedInfCost], str]:
    """Project native personnel-cost rows required by approved cross-side breeds.

    GoH Conquest prices infantry through breed-path rows in ``inf_*.set`` such
    as ``mp/ukr/2022s/foo``.  Mirroring a breed from one tactical side to
    another without mirroring that row leaves the new target-side breed with a
    native purchase cost of zero.  Preserve the effective installed source row
    and change only its breed path and explicit side declaration.
    """

    target_side = str(actor.get("tactical_side", "")).lower()
    index = _build_effective_inf_index(roots)
    projected: dict[str, tuple[ProjectedInfCost, str]] = {}

    for unit in sorted(actor.get("units", []), key=lambda row: str(row.get("unit_name", ""))):
        component_id = str(unit.get("component_id", ""))
        if component_id not in _CROSS_SIDE_BREED_COMPONENTS:
            continue
        source_side = str(unit.get("source_side", "")).lower()
        if not source_side or source_side == target_side:
            continue
        period = str(unit.get("period", "")).lower()
        members = unit.get("members", {})
        if not isinstance(members, Mapping) or not members:
            continue

        for breed in sorted(str(name) for name in members):
            source_breed, source_side_root = _resolve_source_breed(
                roots,
                source_side=source_side,
                breed=breed,
                period=period,
            )
            breed_relative = source_breed.relative_to(source_side_root).with_suffix("")
            source_path = f"mp/{source_side}/{breed_relative.as_posix()}"
            target_path = f"mp/{target_side}/{breed_relative.as_posix()}"

            native_target = index.get(target_path.casefold())
            if native_target is not None:
                _positive_cost(native_target.entry, native_target.source_reference)
                continue

            source_row = index.get(source_path.casefold())
            if source_row is None:
                raise ExpandedNationsError(
                    f"Cross-side breed {source_path} has no native Conquest inf cost row"
                )
            source_cost = _positive_cost(source_row.entry, source_row.source_reference)
            rendered = _project_inf_row(
                source_row.entry,
                source_path=source_path,
                target_path=target_path,
                source_side=source_side,
                target_side=target_side,
            )
            projected_scan = scan_source_entries(rendered, f"generated:{target_path}")
            if projected_scan.diagnostics or len(projected_scan.entries) != 1:
                raise ExpandedNationsError(
                    f"Projected inf cost row is malformed: {target_path}"
                )
            generated = projected_scan.entries[0]
            if generated.name != target_path:
                raise ExpandedNationsError(
                    f"Projected inf cost row has wrong target path: {generated.name}"
                )
            side_calls = [
                call.value.lower() for call in generated.calls if call.family == "side"
            ]
            if side_calls != [target_side]:
                raise ExpandedNationsError(
                    f"Projected inf cost row {target_path} has sides {side_calls}, expected {target_side}"
                )
            generated_cost = _positive_cost(generated, f"generated:{target_path}")
            if generated_cost != source_cost:
                raise ExpandedNationsError(
                    f"Projected inf cost changed for {target_path}: {source_cost} -> {generated_cost}"
                )

            record = ProjectedInfCost(
                source_path=source_path,
                target_path=target_path,
                source_side=source_side,
                target_side=target_side,
                cost=source_cost,
                source_reference=source_row.source_reference,
                source_sha256=sha256_bytes(source_row.entry.raw.encode("utf-8")),
                projected_sha256=sha256_bytes(rendered.encode("utf-8")),
            )
            previous = projected.get(target_path.casefold())
            if previous is not None:
                if previous[0] != record or previous[1] != rendered:
                    raise ExpandedNationsError(
                        f"Conflicting projected inf cost rows for {target_path}"
                    )
                continue
            projected[target_path.casefold()] = (record, rendered)

    ordered = [projected[key] for key in sorted(projected)]
    records = [row[0] for row in ordered]
    body_parts: list[str] = []
    for record, rendered in ordered:
        metadata = json.dumps(
            {
                "source_path": record.source_path,
                "target_path": record.target_path,
                "cost": record.cost,
                "source_reference": record.source_reference,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        body_parts.extend((_INF_MARKER + metadata, rendered))
    body = "\n".join(body_parts)
    if body:
        body += "\n"
    return records, body


def inject_actor_inf_cost_rows(roster_text: str, body: str) -> str:
    """Insert generated actor-specific personnel metadata into the managed roster."""

    if not body:
        return roster_text
    if _INF_MARKER in roster_text:
        raise ExpandedNationsError("Managed roster already contains actor inf-cost rows")
    if roster_text.count(_ROSTER_INSERT_BEFORE) != 1:
        raise ExpandedNationsError(
            "Managed roster has no unique opponent include insertion point"
        )
    indented = "\n".join(
        ("\t" + line if line else "")
        for line in body.rstrip("\n").splitlines()
    )
    insertion = (
        "\t; Actor-specific native personnel prices for cross-side breed materialization.\n"
        + indented
        + "\n\n"
        + _ROSTER_INSERT_BEFORE
    )
    return roster_text.replace(_ROSTER_INSERT_BEFORE, insertion, 1)


def verify_actor_inf_cost_rows(
    roster_text: str,
    manifest: Mapping[str, Any],
) -> None:
    """Verify manifest-declared generated inf prices in an installed roster."""

    raw_rows = manifest.get("inf_cost_rows", [])
    if not isinstance(raw_rows, list):
        raise ExpandedNationsError("Activation manifest inf_cost_rows must be a list")
    side = str(manifest.get("tactical_side", "")).lower()
    seen: set[str] = set()
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            raise ExpandedNationsError("Activation manifest contains an invalid inf-cost row")
        target_path = str(raw.get("target_path", ""))
        source_path = str(raw.get("source_path", ""))
        target_side = str(raw.get("target_side", "")).lower()
        source_side = str(raw.get("source_side", "")).lower()
        try:
            cost = float(raw.get("cost", 0.0))
        except (TypeError, ValueError) as exc:
            raise ExpandedNationsError(
                f"Activation manifest has invalid inf cost for {target_path}"
            ) from exc
        if not target_path.startswith(f"mp/{side}/") or target_side != side:
            raise ExpandedNationsError(
                f"Activation manifest inf-cost row escapes actor side: {target_path}"
            )
        if not source_path.startswith(f"mp/{source_side}/") or source_side == target_side:
            raise ExpandedNationsError(
                f"Activation manifest inf-cost source is invalid: {source_path}"
            )
        if cost <= 0:
            raise ExpandedNationsError(
                f"Activation manifest contains zero/negative native inf cost: {target_path}={cost}"
            )
        folded = target_path.casefold()
        if folded in seen:
            raise ExpandedNationsError(
                f"Activation manifest contains duplicate inf-cost target: {target_path}"
            )
        seen.add(folded)
        if roster_text.count(f'"{target_path}"') != 1:
            raise ExpandedNationsError(
                f"Managed roster does not contain exactly one inf-cost target row: {target_path}"
            )
        position = roster_text.find(f'"{target_path}"')
        window = roster_text[position : position + 1024]
        if re.search(
            _SIDE_RE_TEMPLATE % re.escape(target_side),
            window,
            flags=re.IGNORECASE,
        ) is None:
            raise ExpandedNationsError(
                f"Managed roster inf-cost row has wrong/missing side: {target_path}"
            )
        costs = _COST_RE.findall(window)
        if not costs or float(costs[0]) != cost:
            raise ExpandedNationsError(
                f"Managed roster inf-cost row has wrong/missing cost: {target_path}"
            )

    marker_count = roster_text.count(_INF_MARKER)
    if marker_count != len(raw_rows):
        raise ExpandedNationsError(
            f"Managed roster inf-cost marker count mismatch: {marker_count} != {len(raw_rows)}"
        )


def _build_effective_inf_index(
    roots: Sequence[Path],
) -> dict[str, _IndexedInfRow]:
    effective: dict[str, _IndexedInfRow] = {}
    for priority, root in enumerate(roots):
        conquest = resource_root(root) / "set/multiplayer/units/conquest"
        if not conquest.is_dir():
            continue
        within_priority: dict[str, _IndexedInfRow] = {}
        for path in sorted(conquest.glob("inf*.set"), key=lambda item: item.as_posix().casefold()):
            try:
                text = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError as exc:
                raise ExpandedNationsError(f"Cannot decode native inf metadata: {path}") from exc
            if GENERATED_MARKER in text[:1024]:
                continue
            reference = f"{priority}:{root.name}/{path.relative_to(resource_root(root)).as_posix()}"
            scan = scan_source_entries(text, reference)
            if scan.diagnostics:
                raise ExpandedNationsError(f"Native inf metadata is malformed: {reference}")
            for entry in scan.entries:
                key = entry.name.casefold()
                previous = within_priority.get(key)
                current = _IndexedInfRow(entry, reference, priority)
                if previous is not None and previous.entry.raw.rstrip() != entry.raw.rstrip():
                    raise ExpandedNationsError(
                        f"Conflicting native inf metadata at stack priority {priority}: {entry.name}"
                    )
                within_priority[key] = current
        effective.update(within_priority)
    return effective


def _project_inf_row(
    entry: SourceEntry,
    *,
    source_path: str,
    target_path: str,
    source_side: str,
    target_side: str,
) -> str:
    renamed = _rename_entry(entry.raw.rstrip(), entry, target_path)
    pattern = re.compile(
        _SIDE_RE_TEMPLATE % re.escape(source_side),
        re.IGNORECASE,
    )
    projected, count = pattern.subn(f"side({target_side})", renamed)
    if count != 1:
        raise ExpandedNationsError(
            f"Native inf row {source_path} has {count} source-side declarations; expected one"
        )
    return projected


def _positive_cost(entry: SourceEntry, source_reference: str) -> float:
    values = _COST_RE.findall(entry.raw)
    if len(values) != 1:
        raise ExpandedNationsError(
            f"Native inf row {entry.name} has {len(values)} cost declarations in {source_reference}"
        )
    cost = float(values[0])
    if cost <= 0:
        raise ExpandedNationsError(
            f"Native inf row {entry.name} has non-positive cost {cost} in {source_reference}"
        )
    return cost
