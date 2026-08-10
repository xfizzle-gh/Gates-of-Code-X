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

# Exact installed-stack probing proved these are upstream Code:X metadata typos.
# Keep every alias exact and narrow: the left-hand path is the real breed used by
# a native purchase, while the right-hand path is the only matching native cost
# metadata path and has no corresponding breed in the probed stack.
_PERIOD_ALTERNATES = {
    "2022s": ("era2022",),
    "era2022": ("2022s",),
}

_SOURCE_COST_ALIASES: Mapping[str, str] = {
    "mp/ukr/2022s/azov3_demo_h": "mp/ukr/2022s/azov3_demon_h",
    "mp/ukr/2022s/azov3_mg_mg3": "mp/ukr/2022s/azov3_mg3",
    "mp/nato/2022s/fj_eng": "mp/nato/2022s/fj_engineer",
    "mp/nato/2022s/fj_eng_at": "mp/nato/2022s/fj_engineer_at",
    "mp/nato/era2022/fj_eng": "mp/nato/2022s/fj_engineer",
    "mp/nato/era2022/fj_eng_at": "mp/nato/2022s/fj_engineer_at",
}

_SOURCE_COST_ROLE_MAP: Mapping[str, str] = {
    "mp/rusa/2022s/vostok_squadlead": "mp/rusa/2022s/spd_squadlead",
    "mp/rusa/2022s/vostok_seniorrifleman": "mp/rusa/2022s/spd_seniorrifleman",
    "mp/rusa/2022s/vostok_rifleman": "mp/rusa/2022s/spd_rifleman",
    "mp/rusa/2022s/vostok_rifleman1": "mp/rusa/2022s/spd_rifleman1",
    "mp/rusa/2022s/vostok_mg": "mp/rusa/2022s/spd_mg",
    "mp/rusa/2022s/vostok_mgunasst": "mp/rusa/2022s/spd_mgunasst",
    "mp/rusa/2022s/vostok_antitank": "mp/rusa/2022s/spd_antitank",
    "mp/rusa/2022s/vostok_antitankasst": "mp/rusa/2022s/spd_antitankasst",
    "mp/rusa/2022s/vostok_medic": "mp/rusa/2022s/spd_medic",
    "mp/rusa/2022s/vostok_2b14crew": "mp/rusa/2022s/spd_uav",
    "mp/rusa/2022s/vostok_spg9crew": "mp/rusa/2022s/spd_antitank",
    "mp/rusa/2022s/spd_spotter": "mp/rusa/2022s/spd_sniper",
}

# Native GoH observation on the exact owner stack resolved one requested-path
# conflict that static source inspection could not: 3rd_assault_saperi renders
# at 234.5 while the saperi_at control renders at 273.0. With azov3_mg at 52.5,
# only the ukr_specops azov3_saperi row at 26.0 reproduces the native price.
# Treat this as an exact evidence-backed disposition, never a generic duplicate
# precedence rule. If the candidate set changes, fail closed.
_SOURCE_CONFLICT_DISPOSITIONS: Mapping[str, tuple[str, float]] = {
    "mp/ukr/2022s/azov3_saperi": ("ukr_specops", 26.0),
}

# Exact installed-stack probing also proved that ``azov3_antitank_javelin`` is a
# real Code:X breed used by the native ``3rd_assault_javelin`` purchase, while
# neither Code:X nor the AI Overhaul defines a matching Conquest ``inf`` row.
# Do not invent a price from nearby AT variants. Preserve this source-native
# omission only for this exact path, but require the containing projected unit
# to retain positive native cost coverage from at least one other member.
_SOURCE_NATIVE_UNPRICED_PATHS = frozenset({
    "mp/ukr/2022s/azov3_antitank_javelin",
    "mp/rusa/2022s/kor_crew",
    "mp/rusa/2022s/kor_crew_ags",
    "mp/rusa/2022s/kor_crew_nsv",
    "mp/rusa/2022s/kor_crew_spg9",
    "mp/rusa/2022s/kor_saperi",
    "mp/rusa/2022s/kor_saperi_rpo",
})


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


@dataclass(frozen=True, slots=True)
class _EffectiveInfIndex:
    rows: Mapping[str, _IndexedInfRow]
    conflicts: Mapping[str, tuple[_IndexedInfRow, ...]]


def project_actor_inf_cost_rows(
    actor: Mapping[str, Any],
    roots: Sequence[Path],
) -> tuple[list[ProjectedInfCost], str]:
    """Project native personnel-cost rows required by actor infantry purchases.

    GoH Conquest prices infantry through breed-path rows in ``inf_*.set``.
    Missing rows leave purchases free. This projector mirrors cross-side breed
    costs, fills exact alias/role-map gaps for same-side virtual/national
    infantry, never invents prices outside explicit allowlists, and fails closed
    when a pure-infantry/virtual purchase would remain unpriced.
    """

    target_side = str(actor.get("tactical_side", "")).lower()
    index = _build_effective_inf_index(roots)
    projected: dict[str, tuple[ProjectedInfCost, str]] = {}

    for unit in sorted(actor.get("units", []), key=lambda row: str(row.get("unit_name", ""))):
        if not _unit_requires_inf_cost_coverage(unit, target_side):
            continue
        source_side = str(unit.get("source_side", "") or target_side).lower()
        period = str(unit.get("period", "") or "2022s").lower()
        members = unit.get("members", {})
        if not isinstance(members, Mapping) or not members:
            continue

        unit_has_positive_cost = False
        members_considered = False
        unit_name = str(unit.get("unit_name", "<unnamed>"))
        cross_side = (
            str(unit.get("component_id", "")) in _CROSS_SIDE_BREED_COMPONENTS
            and source_side
            and source_side != target_side
        )

        for breed in sorted(str(name) for name in members):
            try:
                source_breed, source_side_root = _resolve_source_breed(
                    roots,
                    source_side=source_side,
                    breed=breed,
                    period=period,
                )
            except ExpandedNationsError:
                # Cross-side materialization requires resolvable breeds.
                # Same-side scans skip unresolvable members; unit-level coverage
                # still fails closed when a required unit ends with no priced members.
                if cross_side:
                    raise
                continue
            breed_relative = source_breed.relative_to(source_side_root).with_suffix("")
            source_path = f"mp/{source_side}/{breed_relative.as_posix()}"
            members_considered = True
            target_path = (
                f"mp/{target_side}/{breed_relative.as_posix()}"
                if cross_side
                else source_path
            )

            try:
                native_target = _lookup_cost_row(index, target_path)
            except ExpandedNationsError:
                if _unit_requires_positive_coverage(unit, target_side):
                    raise
                continue
            if native_target is not None:
                _positive_cost(native_target.entry, native_target.source_reference)
                unit_has_positive_cost = True
                continue

            try:
                authority = _resolve_cost_authority(index, source_path)
            except ExpandedNationsError:
                if _unit_requires_positive_coverage(unit, target_side):
                    raise
                continue
            if authority is None:
                if _is_allowlisted_unpriced(source_path) or _is_allowlisted_unpriced(target_path):
                    continue
                if _unit_requires_positive_coverage(unit, target_side):
                    raise ExpandedNationsError(
                        f"Infantry breed {source_path} has no native Conquest inf cost row"
                    )
                continue

            cost_source_path, source_row = authority
            authority_side = cost_source_path.split("/")[1].lower()
            source_cost = _positive_cost(source_row.entry, source_row.source_reference)
            unit_has_positive_cost = True
            if cost_source_path.casefold() == target_path.casefold():
                continue

            effective_target_side = target_side if cross_side else authority_side
            rendered = _project_inf_row(
                source_row.entry,
                source_path=cost_source_path,
                target_path=target_path,
                source_side=authority_side,
                target_side=effective_target_side,
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
            if side_calls != [effective_target_side]:
                raise ExpandedNationsError(
                    f"Projected inf cost row {target_path} has sides {side_calls}, "
                    f"expected {effective_target_side}"
                )
            generated_cost = _positive_cost(generated, f"generated:{target_path}")
            if generated_cost != source_cost:
                raise ExpandedNationsError(
                    f"Projected inf cost changed for {target_path}: "
                    f"{source_cost} -> {generated_cost}"
                )

            record = ProjectedInfCost(
                source_path=cost_source_path,
                target_path=target_path,
                source_side=authority_side,
                target_side=effective_target_side,
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

        if (
            members_considered
            and not unit_has_positive_cost
            and _unit_requires_positive_coverage(unit, target_side)
        ):
            raise ExpandedNationsError(
                f"Infantry unit {unit_name} has no positive native Conquest inf cost coverage"
            )

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
        if not source_path.startswith(f"mp/{source_side}/"):
            raise ExpandedNationsError(
                f"Activation manifest inf-cost source is invalid: {source_path}"
            )
        if source_path.casefold() == target_path.casefold():
            raise ExpandedNationsError(
                f"Activation manifest inf-cost source equals target: {source_path}"
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
        row_token = f'{{"{target_path}"'
        if roster_text.count(row_token) != 1:
            raise ExpandedNationsError(
                f"Managed roster does not contain exactly one inf-cost target row: {target_path}"
            )
        position = roster_text.find(row_token)
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



def _unit_requires_inf_cost_coverage(unit: Mapping[str, Any], target_side: str) -> bool:
    """Whether this unit participates in inf-cost projection.

    All member-bearing units are scanned so exact alias/role fills can apply, but
    only virtual and approved cross-side units fail closed on missing coverage.
    Ordinary same-side equipment often uses crew breeds that are also unpriced in
    native Code:X and rely on vehicle/entity economy.
    """
    members = unit.get("members", {})
    return isinstance(members, Mapping) and bool(members)


def _unit_requires_positive_coverage(unit: Mapping[str, Any], target_side: str) -> bool:
    component_id = str(unit.get("component_id", ""))
    source_side = str(unit.get("source_side", "") or target_side).lower()
    if component_id in _CROSS_SIDE_BREED_COMPONENTS and source_side and source_side != target_side:
        return True
    return bool(unit.get("virtual"))


def _is_allowlisted_unpriced(path: str) -> bool:
    folded = path.casefold()
    allowed = {item.casefold() for item in _SOURCE_NATIVE_UNPRICED_PATHS}
    if folded in allowed:
        return True
    for item in _SOURCE_NATIVE_UNPRICED_PATHS:
        for alt in _period_variants(item):
            if alt.casefold() == folded:
                return True
    return False


def _period_variants(path: str) -> tuple[str, ...]:
    parts = path.split("/")
    if len(parts) < 4:
        return (path,)
    side = parts[1]
    period = parts[2]
    rest = "/".join(parts[3:])
    variants = [path]
    for alt in _PERIOD_ALTERNATES.get(period, ()):
        variants.append(f"mp/{side}/{alt}/{rest}")
    return tuple(variants)


def _lookup_cost_row(index: _EffectiveInfIndex, path: str) -> _IndexedInfRow | None:
    for candidate in _period_variants(path):
        row = _lookup_effective_inf_row(index, candidate)
        if row is not None:
            return row
    return None


def _resolve_cost_authority(
    index: _EffectiveInfIndex,
    source_path: str,
) -> tuple[str, _IndexedInfRow] | None:
    for candidate in _period_variants(source_path):
        row = _lookup_effective_inf_row(index, candidate)
        if row is not None:
            return candidate, row

    for key in _period_variants(source_path):
        alias = None
        for alias_key, alias_val in _SOURCE_COST_ALIASES.items():
            if alias_key.casefold() == key.casefold():
                alias = alias_val
                break
        if alias is None:
            continue
        row = _lookup_cost_row(index, alias)
        if row is not None:
            return alias, row

    for key in _period_variants(source_path):
        role = None
        for role_key, role_val in _SOURCE_COST_ROLE_MAP.items():
            if role_key.casefold() == key.casefold():
                role = role_val
                break
        if role is None:
            continue
        row = _lookup_cost_row(index, role)
        if row is not None:
            return role, row
    return None



def _build_effective_inf_index(
    roots: Sequence[Path],
) -> _EffectiveInfIndex:
    """Index parseable effective inf rows without rejecting unrelated source damage.

    Installed mods can contain duplicate paths in multiple ``inf*.set`` files at
    the same stack priority, and an upstream file can also contain parser
    diagnostics in definitions unrelated to the actor being projected. Keep
    every successfully parsed row. Same-priority duplicate rows remain a
    projection ambiguity only when the actor requests that path. A requested
    malformed row cannot enter the index and therefore still fails closed as a
    missing native cost row. A higher-priority definitive row replaces both a
    lower-priority row and a lower-priority conflict, matching stack semantics.
    """

    effective: dict[str, _IndexedInfRow] = {}
    conflicts: dict[str, tuple[_IndexedInfRow, ...]] = {}
    for priority, root in enumerate(roots):
        conquest = resource_root(root) / "set/multiplayer/units/conquest"
        if not conquest.is_dir():
            continue
        within_priority: dict[str, list[_IndexedInfRow]] = {}
        for path in sorted(conquest.glob("inf*.set"), key=lambda item: item.as_posix().casefold()):
            try:
                text = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError as exc:
                raise ExpandedNationsError(f"Cannot decode native inf metadata: {path}") from exc
            if GENERATED_MARKER in text[:1024]:
                continue
            reference = f"{priority}:{root.name}/{path.relative_to(resource_root(root)).as_posix()}"
            scan = scan_source_entries(text, reference)
            for entry in scan.entries:
                key = entry.name.casefold()
                within_priority.setdefault(key, []).append(
                    _IndexedInfRow(entry, reference, priority)
                )

        for key, candidates in within_priority.items():
            unique: dict[str, _IndexedInfRow] = {}
            for candidate in candidates:
                unique.setdefault(candidate.entry.raw.rstrip(), candidate)
            if len(unique) > 1:
                effective.pop(key, None)
                conflicts[key] = tuple(unique.values())
                continue
            effective[key] = next(iter(unique.values()))
            conflicts.pop(key, None)

    return _EffectiveInfIndex(rows=effective, conflicts=conflicts)


def _lookup_effective_inf_row(
    index: _EffectiveInfIndex,
    path: str,
) -> _IndexedInfRow | None:
    key = path.casefold()
    conflict = index.conflicts.get(key)
    if conflict is not None:
        disposition = _SOURCE_CONFLICT_DISPOSITIONS.get(key)
        if disposition is not None:
            expected_role, expected_cost = disposition
            role_marker = f'("{expected_role}"'
            matches = [
                row
                for row in conflict
                if role_marker in row.entry.raw
                and _positive_cost(row.entry, row.source_reference) == expected_cost
            ]
            if len(matches) == 1:
                return matches[0]
            references = ", ".join(sorted(row.source_reference for row in conflict))
            raise ExpandedNationsError(
                f"Proven native inf disposition no longer resolves uniquely for requested path "
                f"{path}: expected {expected_role} cost {expected_cost}; candidates {references}"
            )

        priority = conflict[0].priority
        references = ", ".join(sorted(row.source_reference for row in conflict))
        raise ExpandedNationsError(
            f"Conflicting native inf metadata at effective stack priority {priority} "
            f"for requested path {path}: {references}"
        )
    return index.rows.get(key)


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

