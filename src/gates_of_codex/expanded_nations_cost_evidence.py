from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
import statistics
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .expanded_nations import (
    activate_actor_projection,
    compile_resolved_factions,
    deactivate_actor_projection,
    verify_actor_projection,
)
from .expanded_nations_breeds import _resolve_source_breed
from .expanded_nations_inf_costs import (
    _COST_RE,
    _build_effective_inf_index,
    _is_allowlisted_unpriced,
    _lookup_effective_inf_row,
    _resolve_cost_authority,
    _SOURCE_NATIVE_UNPRICED_PATHS,
)
from .expanded_nations_models import (
    MANIFEST_RELATIVE,
    UNITS_RELATIVE,
    ExpandedNationsError,
    all_managed_candidates,
    pretty_json,
    validate_payload,
)
from .goh_source import scan_source_entries
from .modstack import normalize_stack, resource_root

COST_EVIDENCE_SCHEMA = "gates-of-codex.expanded-nations-cost-evidence"
COST_EVIDENCE_VERSION = 1

_MEMBER_RE = re.compile(
    r"\bc\d+\s*\(\s*([A-Za-z0-9_./+-]+)\s*:\s*(\d+)\s*\)",
    re.IGNORECASE,
)
_BLOCK_COST_RE = re.compile(r"\{\s*cost\s+(-?(?:\d+(?:\.\d*)?|\.\d+))\s*\}", re.IGNORECASE)
_CP_RE = re.compile(r"\bcp\s*\(\s*(\d+(?:\.\d*)?)\s*\)", re.IGNORECASE)
_VEHICLE_COST_RE = re.compile(
    r'\{\s*"([^"]+)"\s*[\s\S]{0,400}?\{\s*cost\s+(-?(?:\d+(?:\.\d*)?|\.\d+))\s*\}',
    re.IGNORECASE,
)
_VEHICLE_CALL_RE = re.compile(r"\bvehicle\s*\(\s*([^)\s]+)\s*\)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class UnitCostEvidence:
    unit_name: str
    economy_class: str
    native_recruitment_cost: float | None
    personnel_cost: float | None
    entity_cost: float | None
    cp: float | None
    virtual: bool
    zero_cost: bool
    intentional_zero: bool
    rationale: str
    member_gaps: tuple[str, ...]


def build_cost_evidence_matrix(
    payload: Mapping[str, Any],
    resource_stack: Iterable[str | Path],
    *,
    gates_root: str | Path | None = None,
    source_head: str = "",
) -> dict[str, Any]:
    """Build exact-stack native recruitment-cost evidence for every playable actor."""

    validate_payload(payload)
    roots = normalize_stack(resource_stack)
    if not roots:
        raise ExpandedNationsError("Cost evidence requires an ordered mod stack")
    final_root = Path(gates_root).expanduser().resolve() if gates_root else roots[-1]
    if final_root != roots[-1]:
        raise ExpandedNationsError(
            f"Gates root must be the final stack layer: expected {roots[-1]}, got {final_root}"
        )
    if not final_root.is_dir():
        raise FileNotFoundError(f"Gates root does not exist: {final_root}")

    manifest_path = final_root / MANIFEST_RELATIVE
    if manifest_path.exists():
        verify_actor_projection(final_root)
        raise ExpandedNationsError(
            "Cost evidence generation requires Core mode; restore Core first"
        )
    occupied = [path for path in all_managed_candidates(final_root) if path.exists()]
    if occupied:
        raise ExpandedNationsError(
            "Cost evidence refuses unmanaged generated-path occupants: "
            + ", ".join(str(path) for path in occupied)
        )

    source_index = _build_effective_inf_index(roots)
    vehicle_costs = _build_vehicle_cost_index(roots)
    playable = sorted(
        (row for row in payload["actors"] if bool(row.get("playable"))),
        key=lambda row: str(row["actor_id"]),
    )
    actors: dict[str, dict[str, Any]] = {}
    global_unintended_zeros: list[dict[str, str]] = []

    try:
        for actor in playable:
            actor_id = str(actor["actor_id"])
            result = activate_actor_projection(
                payload, roots, actor_id, gates_root=final_root
            )
            manifest = verify_actor_projection(final_root)
            units_text = (final_root / UNITS_RELATIVE).read_text(encoding="utf-8")
            roster_text = (
                final_root / "resource/set/multiplayer/units/roster_conquest.set"
            ).read_text(encoding="utf-8")
            effective_index = _index_with_projected_rows(source_index, roster_text)

            unit_meta = {
                str(u.get("unit_name")): u for u in actor.get("units", [])
            }
            unit_rows: list[UnitCostEvidence] = []
            costs: list[float] = []

            scan = scan_source_entries(units_text, f"active:{actor_id}")
            if scan.diagnostics:
                raise ExpandedNationsError(
                    f"Active units parse diagnostics for {actor_id}: {scan.diagnostics[:3]}"
                )

            for entry in scan.entries:
                meta = unit_meta.get(entry.name) or unit_meta.get(
                    f"{entry.name}({result.tactical_side})"
                )
                evidence = _evaluate_unit_cost(
                    entry_name=entry.name,
                    entry_raw=entry.raw,
                    entry_form=entry.form,
                    entry_calls=entry.calls,
                    unit_meta=meta,
                    tactical_side=str(result.tactical_side),
                    roots=roots,
                    index=effective_index,
                    vehicle_costs=vehicle_costs,
                )
                unit_rows.append(evidence)
                if evidence.native_recruitment_cost is not None:
                    costs.append(float(evidence.native_recruitment_cost))
                if evidence.zero_cost and not evidence.intentional_zero:
                    global_unintended_zeros.append(
                        {
                            "actor_id": actor_id,
                            "unit_name": evidence.unit_name,
                            "economy_class": evidence.economy_class,
                            "rationale": evidence.rationale,
                        }
                    )

            projected_rows = list(manifest.get("inf_cost_rows") or [])
            projected_costs = [float(r.get("cost") or 0.0) for r in projected_rows]
            intentional_zeros = [u for u in unit_rows if u.intentional_zero]
            unintended_zeros = [
                u for u in unit_rows if u.zero_cost and not u.intentional_zero
            ]

            actors[actor_id] = {
                "actor_id": actor_id,
                "display_name": result.display_name,
                "tactical_side": result.tactical_side,
                "unit_count": result.unit_count,
                "research_node_count": result.research_node_count,
                "projection_signature": result.projection_signature,
                "stack_signature": str(manifest.get("stack_signature") or ""),
                "projected_inf_cost_row_count": len(projected_rows),
                "projected_inf_cost_min": min(projected_costs) if projected_costs else None,
                "projected_inf_cost_max": max(projected_costs) if projected_costs else None,
                "native_recruitment_cost_min": min(costs) if costs else None,
                "native_recruitment_cost_median": (
                    float(statistics.median(costs)) if costs else None
                ),
                "native_recruitment_cost_max": max(costs) if costs else None,
                "unintended_zero_count": len(unintended_zeros),
                "intentional_zero_count": len(intentional_zeros),
                "intentional_zero_units": [
                    {"unit_name": u.unit_name, "rationale": u.rationale}
                    for u in intentional_zeros
                ],
                "unintended_zero_units": [
                    {
                        "unit_name": u.unit_name,
                        "economy_class": u.economy_class,
                        "rationale": u.rationale,
                        "member_gaps": list(u.member_gaps),
                    }
                    for u in unintended_zeros
                ],
                "economy_class_counts": _count_classes(unit_rows),
                "units": [asdict(u) for u in unit_rows],
            }

            if not deactivate_actor_projection(final_root):
                raise ExpandedNationsError(
                    f"Cost evidence failed to restore Core after actor {actor_id}"
                )
    finally:
        if manifest_path.exists():
            deactivate_actor_projection(final_root)

    leftovers = [path for path in all_managed_candidates(final_root) if path.exists()]
    if leftovers:
        raise ExpandedNationsError(
            "Cost evidence left generated artifacts after Core restoration: "
            + ", ".join(str(path) for path in leftovers)
        )

    return {
        "schema": COST_EVIDENCE_SCHEMA,
        "schema_version": COST_EVIDENCE_VERSION,
        "evidence_state": "complete" if not global_unintended_zeros else "blocked",
        "source_head": source_head,
        "playable_actor_count": len(playable),
        "wiring_signature": str(payload["wiring_signature"]),
        "unintended_zero_total": len(global_unintended_zeros),
        "unintended_zeros": global_unintended_zeros,
        "actors": actors,
    }


def render_cost_evidence_markdown(matrix: Mapping[str, Any]) -> str:
    lines = [
        "# Expanded Nations native recruitment-cost evidence",
        "",
        f"- schema: `{matrix.get('schema')}` v{matrix.get('schema_version')}",
        f"- evidence_state: `{matrix.get('evidence_state')}`",
        f"- source_head: `{matrix.get('source_head')}`",
        f"- playable_actors: {matrix.get('playable_actor_count')}",
        f"- unintended_zero_total: {matrix.get('unintended_zero_total')}",
        "",
        "| actor | side | units | proj_rows | min | median | max | unintended_zero | intentional_zero |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for actor_id, row in sorted((matrix.get("actors") or {}).items()):
        lines.append(
            "| {actor} | {side} | {units} | {proj} | {mn} | {med} | {mx} | {uz} | {iz} |".format(
                actor=actor_id,
                side=row.get("tactical_side"),
                units=row.get("unit_count"),
                proj=row.get("projected_inf_cost_row_count"),
                mn=_fmt(row.get("native_recruitment_cost_min")),
                med=_fmt(row.get("native_recruitment_cost_median")),
                mx=_fmt(row.get("native_recruitment_cost_max")),
                uz=row.get("unintended_zero_count"),
                iz=row.get("intentional_zero_count"),
            )
        )
    lines.extend(["", "## Unintended zeros", ""])
    zeros = list(matrix.get("unintended_zeros") or [])
    if not zeros:
        lines.append("None.")
    else:
        for item in zeros:
            lines.append(
                f"- `{item.get('actor_id')}` / `{item.get('unit_name')}` "
                f"({item.get('economy_class')}): {item.get('rationale')}"
            )
    lines.append("")
    return "\n".join(lines)


def write_cost_evidence(
    matrix: Mapping[str, Any],
    *,
    json_output: str | Path,
    markdown_output: str | Path,
) -> None:
    json_path = Path(json_output)
    md_path = Path(markdown_output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(pretty_json(matrix) + "\n", encoding="utf-8")
    md_path.write_text(render_cost_evidence_markdown(matrix), encoding="utf-8")


def generate_cost_evidence_from_stack_config(
    stack_config: str | Path,
    *,
    gates_root: str | Path | None = None,
    source_head: str = "",
) -> dict[str, Any]:
    roots, payload = compile_resolved_factions(stack_config)
    return build_cost_evidence_matrix(
        payload,
        roots,
        gates_root=gates_root or roots[-1],
        source_head=source_head,
    )


def _evaluate_unit_cost(
    *,
    entry_name: str,
    entry_raw: str,
    entry_form: str,
    entry_calls: Sequence[Any],
    unit_meta: Mapping[str, Any] | None,
    tactical_side: str,
    roots: Sequence[Path],
    index: Any,
    vehicle_costs: Mapping[str, float],
) -> UnitCostEvidence:
    virtual = bool(unit_meta.get("virtual")) if unit_meta else entry_name.startswith("goc_")
    call_map: dict[str, list[str]] = {}
    for call in entry_calls:
        call_map.setdefault(str(getattr(call, "family", "")).lower(), []).append(str(call.value))

    entity_cost = _first_block_cost(entry_raw)
    if entity_cost is None and call_map.get("cost"):
        try:
            entity_cost = float(call_map["cost"][0])
        except ValueError:
            entity_cost = None
    cost_sp = None
    if call_map.get("cost_sp"):
        try:
            cost_sp = float(call_map["cost_sp"][0])
        except ValueError:
            cost_sp = None
    cp_vals = call_map.get("cp") or []
    cp = float(cp_vals[0]) if cp_vals else None

    members = _extract_members(entry_raw, unit_meta)
    # Ignore zero-count placeholder crew slots (common on UGV / offmap macros).
    members = {k: v for k, v in members.items() if int(v) > 0}
    personnel, gaps, allowlisted = _personnel_cost(
        members=members,
        unit_meta=unit_meta,
        tactical_side=tactical_side,
        roots=roots,
        index=index,
    )

    vehicle_names = _VEHICLE_CALL_RE.findall(entry_raw)
    vehicle_entity_cost = None
    for name in vehicle_names:
        key = name.casefold()
        if key in vehicle_costs:
            vehicle_entity_cost = float(vehicle_costs[key])
            break

    has_vehicles = bool(vehicle_names) or (
        bool(unit_meta.get("vehicles")) if unit_meta else False
    )
    is_offmap = any(
        token in entry_raw.lower()
        for token in ("strategic_doctrine", "offmap_support", "airstrike:", "universal_strat")
    )

    if entity_cost is not None and entity_cost > 0:
        economy = "entity_purchase_cost"
        native = entity_cost
        rationale = "native purchase exposes positive cost authority"
        zero = False
        intentional = False
    elif cost_sp is not None and cost_sp > 0:
        economy = "special_points_cost"
        native = cost_sp
        rationale = "native offmap/support purchase uses positive cost_sp authority"
        zero = False
        intentional = False
    elif vehicle_entity_cost is not None and vehicle_entity_cost > 0:
        economy = "vehicle_entity_cost"
        native = vehicle_entity_cost
        rationale = f"vehicle entity cost authority for {vehicle_names[0]}"
        zero = False
        intentional = False
    elif personnel is not None and personnel > 0:
        economy = "personnel_inf_sum"
        native = personnel
        rationale = "positive summed breed inf costs"
        zero = False
        intentional = False
    elif has_vehicles and cp is not None and cp > 0:
        economy = "vehicle_cp_only"
        native = cp
        rationale = "vehicle/support purchase exposes positive cp() authority"
        zero = False
        intentional = False
    elif is_offmap and (entity_cost == 0 or cp == 0 or cost_sp == 0):
        economy = "offmap_support"
        native = float(entity_cost or cost_sp or 0.0)
        rationale = (
            "native offmap/strategic support purchase; zero/low special-cost authority "
            "matches source doctrine rows"
        )
        zero = native <= 0
        intentional = zero
    elif allowlisted and (personnel is None or personnel == 0) and not gaps:
        economy = "allowlisted_unpriced_incomplete"
        native = 0.0
        rationale = "only allowlisted unpriced members; companion coverage missing"
        zero = True
        intentional = False
    elif members and (personnel is None or personnel <= 0):
        economy = "personnel_unpriced"
        native = 0.0
        rationale = "infantry/squad members lack positive inf cost coverage"
        zero = True
        intentional = False
    elif has_vehicles:
        economy = "vehicle_unpriced"
        native = 0.0
        rationale = "vehicle/support purchase lacks positive cost/cp/entity authority"
        zero = True
        intentional = False
    else:
        economy = "unknown"
        native = 0.0
        rationale = "unable to classify native recruitment authority"
        zero = True
        intentional = False

    return UnitCostEvidence(
        unit_name=entry_name,
        economy_class=economy,
        native_recruitment_cost=native,
        personnel_cost=personnel,
        entity_cost=entity_cost if entity_cost is not None else vehicle_entity_cost,
        cp=cp,
        virtual=virtual,
        zero_cost=bool(zero),
        intentional_zero=bool(intentional),
        rationale=rationale,
        member_gaps=tuple(gaps),
    )



def _extract_members(
    entry_raw: str,
    unit_meta: Mapping[str, Any] | None,
) -> dict[str, int]:
    found = {m.group(1): int(m.group(2)) for m in _MEMBER_RE.finditer(entry_raw)}
    if found:
        return found
    if unit_meta and isinstance(unit_meta.get("members"), Mapping):
        out: dict[str, int] = {}
        for key, value in unit_meta["members"].items():
            try:
                out[str(key)] = int(value)
            except (TypeError, ValueError):
                out[str(key)] = 1
        return out
    # crew(breed:n) form
    crew = re.findall(r"crew\s*\(\s*([A-Za-z0-9_./+-]+)\s*:\s*(\d+)\s*\)", entry_raw, re.I)
    return {name: int(qty) for name, qty in crew}


def _personnel_cost(
    *,
    members: Mapping[str, int],
    unit_meta: Mapping[str, Any] | None,
    tactical_side: str,
    roots: Sequence[Path],
    index: Any,
) -> tuple[float | None, list[str], bool]:
    if not members:
        return None, [], False
    source_side = str(
        (unit_meta or {}).get("source_side") or tactical_side
    ).lower()
    period = str((unit_meta or {}).get("period") or "2022s").lower()
    total = 0.0
    priced = 0
    gaps: list[str] = []
    allowlisted = False
    for breed, qty in sorted(members.items()):
        try:
            source_breed, source_side_root = _resolve_source_breed(
                roots, source_side=source_side, breed=breed, period=period
            )
            rel = source_breed.relative_to(source_side_root).with_suffix("").as_posix()
            # Prefer tactical-side path first (post-projection), then source path.
            candidates = [
                f"mp/{tactical_side}/{rel}",
                f"mp/{source_side}/{rel}",
            ]
        except ExpandedNationsError as exc:
            gaps.append(f"{breed}:resolve:{exc}")
            continue

        row = None
        used = None
        for path in candidates:
            try:
                row = _lookup_effective_inf_row(index, path)
            except ExpandedNationsError as exc:
                gaps.append(f"{breed}:conflict:{exc}")
                row = None
                continue
            if row is not None:
                used = path
                break
            try:
                auth = _resolve_cost_authority(index, path)
            except ExpandedNationsError as exc:
                gaps.append(f"{breed}:authority_conflict:{exc}")
                continue
            if auth is not None:
                used, row = auth
                break
            if _is_allowlisted_unpriced(path):
                allowlisted = True
                used = path
                row = None
                break
        if row is None:
            if allowlisted and used:
                continue
            gaps.append(f"{breed}:missing_inf")
            continue
        match = _COST_RE.search(row.entry.raw)
        if not match:
            gaps.append(f"{breed}:no_cost_token:{used}")
            continue
        cost = float(match.group(1))
        if cost <= 0:
            gaps.append(f"{breed}:nonpositive:{used}:{cost}")
            continue
        total += cost * int(qty)
        priced += 1
    if priced == 0:
        return 0.0 if members else None, gaps, allowlisted
    return total, gaps, allowlisted


def _index_with_projected_rows(base_index: Any, roster_text: str) -> Any:
    """Overlay generated roster inf rows onto the source index for evaluation."""
    from .expanded_nations_inf_costs import _EffectiveInfIndex, _IndexedInfRow
    from .goh_source import scan_source_entries

    rows = dict(base_index.rows)
    conflicts = dict(base_index.conflicts)
    scan = scan_source_entries(roster_text, "generated-roster")
    for entry in scan.entries:
        if not entry.name.lower().startswith("mp/"):
            continue
        key = entry.name.casefold()
        rows[key] = _IndexedInfRow(entry, "generated-roster", 10_000)
        conflicts.pop(key, None)
    return _EffectiveInfIndex(rows=rows, conflicts=conflicts)


def _first_block_cost(raw: str) -> float | None:
    match = _BLOCK_COST_RE.search(raw)
    if not match:
        return None
    return float(match.group(1))


def _count_classes(units: Sequence[UnitCostEvidence]) -> dict[str, int]:
    out: dict[str, int] = {}
    for unit in units:
        out[unit.economy_class] = out.get(unit.economy_class, 0) + 1
    return dict(sorted(out.items()))


def _build_vehicle_cost_index(roots: Sequence[Path]) -> dict[str, float]:
    """Index native vehicle entity {cost} rows from conquest unit files."""
    found: dict[str, tuple[int, float]] = {}
    for priority, root in enumerate(roots):
        conquest = resource_root(root) / "set/multiplayer/units/conquest"
        if not conquest.is_dir():
            continue
        for path in sorted(conquest.glob("units_*.set"), key=lambda item: item.as_posix().casefold()):
            try:
                text = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                continue
            for match in _VEHICLE_COST_RE.finditer(text):
                name = match.group(1).casefold()
                cost = float(match.group(2))
                if cost <= 0:
                    continue
                previous = found.get(name)
                if previous is None or priority >= previous[0]:
                    found[name] = (priority, cost)
    return {name: cost for name, (_priority, cost) in sorted(found.items())}


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)
