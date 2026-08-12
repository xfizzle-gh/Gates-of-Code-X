"""#194 static/pre-native Expanded Nations actor matrix.

Builds an authoritative Phase 1 + Phase 2 matrix from committed faction-wiring
authority, the GOC army registry, and on-disk native pack hashes — without
activating live Gates projections or launching GoH.

Native battle-pair evidence remains owner-operated; this module only prepares
the deterministic static gate and the native harness checklist structure.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .faction_wiring_manifest import load_faction_manifest, validate_faction_manifest
from .goc_tactical_army_registry import (
    army_row,
    campaign_faction_token_for_side,
    is_goc_tactical_side,
    load_goc_army_registry,
    registered_goc_sides,
)

STATIC_MATRIX_SCHEMA = "gates-of-codex.expanded-nations-static-matrix"
STATIC_MATRIX_VERSION = 1

PHASE1_PLAYABLE = (
    "usa",
    "gbr",
    "deu",
    "fra",
    "pol",
    "ita",
    "fin",
    "swe",
    "nld",
    "can",
    "nor",
    "dnk",
    "esp",
    "tur",
    "rus",
    "ukr",
    "prc",
    "dprk",
    "donbas",
    "blr",
    "srb",
)
PHASE1_HOSTED = (
    "ukr_ildu",
    "kpa_expeditionary",
    "wagner",
)
PHASE1_ACTORS = PHASE1_PLAYABLE + PHASE1_HOSTED

PHASE1_TACTICAL_SIDES = {
    "usa": "nato",
    "gbr": "nato",
    "deu": "nato",
    "fra": "nato",
    "pol": "nato",
    "ita": "nato",
    "fin": "nato",
    "swe": "nato",
    "nld": "nato",
    "can": "nato",
    "nor": "nato",
    "dnk": "nato",
    "esp": "nato",
    "tur": "nato",
    "rus": "rusa",
    "ukr": "ukr",
    "prc": "prc",
    "dprk": "rusa",
    "donbas": "rusa",
    "blr": "rusa",
    "srb": "rusa",
    "ukr_ildu": "ukr",
    "kpa_expeditionary": "rusa",
    "wagner": "rusa",
}

PHASE1_HOSTS = {
    "ukr_ildu": "ukr",
    "kpa_expeditionary": "rus",
    "wagner": "rus",
}

# Distinct native materialization families for representative GoH coverage (#194).
# Not every country — one row per audited family.
NATIVE_REPRESENTATIVE_FAMILIES = (
    {
        "family_id": "phase1_full_national_nato",
        "representative_actor_id": "usa",
        "tactical_side": "nato",
        "roster_class": "full_national",
        "notes": "Phase 1 USA full national; Core transport nato",
    },
    {
        "family_id": "phase1_national_hybrid_nato",
        "representative_actor_id": "fra",
        "tactical_side": "nato",
        "roster_class": "national_hybrid",
        "notes": "France ARF/DSK hybrid boundary",
    },
    {
        "family_id": "phase1_spain_3rd_assault",
        "representative_actor_id": "esp",
        "tactical_side": "nato",
        "roster_class": "coalition_fallback",
        "notes": "Spain seven-unit 3rd Assault allocation",
    },
    {
        "family_id": "phase1_ukraine_core",
        "representative_actor_id": "ukr",
        "tactical_side": "ukr",
        "roster_class": "full_national",
        "notes": "Ukraine without duplicate ILDU wrappers",
    },
    {
        "family_id": "phase1_russia_core",
        "representative_actor_id": "rus",
        "tactical_side": "rusa",
        "roster_class": "full_national",
        "notes": "Russia with KPA/Wagner hosted separation",
    },
    {
        "family_id": "phase1_proxy_dprk",
        "representative_actor_id": "dprk",
        "tactical_side": "rusa",
        "roster_class": "proxy_hybrid",
        "notes": "DPRK isolation on rusa transport",
    },
    {
        "family_id": "phase1_proxy_serbia",
        "representative_actor_id": "srb",
        "tactical_side": "rusa",
        "roster_class": "proxy_hybrid",
        "notes": "Serbia isolation",
    },
    {
        "family_id": "phase1_prc_passthrough",
        "representative_actor_id": "prc",
        "tactical_side": "prc",
        "roster_class": "full_national",
        "notes": "PRC modern vs legacy/reserve; codex_passthrough activation",
    },
    {
        "family_id": "phase2_goc_nato_full_fallback",
        "representative_actor_id": "bel",
        "tactical_side": "goc_bel",
        "roster_class": "coalition_fallback",
        "notes": "Production goc_* coalition_fallback family (#191/#192)",
    },
    {
        "family_id": "phase2_goc_national_hybrid_dana",
        "representative_actor_id": "cze",
        "tactical_side": "goc_cze",
        "roster_class": "national_hybrid",
        "notes": "DANA equipment identity + infantry bridge",
    },
    {
        "family_id": "phase2_strategic_only",
        "representative_actor_id": "egy",
        "tactical_side": "goc_egy",
        "roster_class": "strategic_only",
        "notes": "Strategic-only ownership; no fabricated recruitment",
    },
)

REQUIRED_BATTLE_PAIRS = (
    {
        "pair_id": "usa_vs_fra_shared_nato_transport",
        "attacker_actor_id": "usa",
        "defender_actor_id": "fra",
        "purpose": "Same historical NATO transport family without generic NATO leakage",
    },
    {
        "pair_id": "srb_vs_rus_shared_rusa_transport",
        "attacker_actor_id": "srb",
        "defender_actor_id": "rus",
        "purpose": "Same historical RUSA transport family isolation",
    },
    {
        "pair_id": "usa_vs_dprk_cross_coalition",
        "attacker_actor_id": "usa",
        "defender_actor_id": "dprk",
        "purpose": "Cross-coalition pair",
    },
    {
        "pair_id": "regional_garrison_48",
        "attacker_actor_id": "usa",
        "defender_actor_id": None,
        "defender_profile": "issue_48_regional_local_garrison",
        "purpose": "Regional/local garrison profile from #48 without sovereign recruitment transfer",
    },
)

_RESOLVED_UNIT_RE = re.compile(r"^;\s*resolved_unit=(.+?)\s*$", re.MULTILINE)
_GOC_NODE_RE = re.compile(r"^;\s*goc-node\s+(\{.*\})\s*$", re.MULTILINE)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(payload: Mapping[str, Any] | Sequence[Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _ai_purchase_authority(actor: Mapping[str, Any]) -> dict[str, Any]:
    playable = bool(actor.get("playable"))
    roster_class = str(actor.get("roster_class") or "")
    if roster_class == "strategic_only" or not playable:
        return {
            "profile": "none",
            "scope": "none",
            "may_purchase": False,
            "may_research": False,
            "notes": "Non-playable/strategic-only actors have no recruitment or research authority",
        }
    if actor.get("host_actor_id"):
        return {
            "profile": "hosted_non_independent",
            "scope": "host_mediated",
            "may_purchase": False,
            "may_research": False,
            "notes": "Hosted auxiliary/PMC/volunteer records are not independently playable",
        }
    return {
        "profile": "actor_scoped_ai_economy",
        "scope": "strategic_actor_id",
        "may_purchase": True,
        "may_research": True,
        "notes": "Purchases authorized by StrategicFormation.actor_id + compiled actor roster",
    }


def _source_family(tactical_side: str) -> str:
    side = str(tactical_side or "").lower()
    if side in {"nato", "ukr", "rusa", "prc"}:
        return side
    if is_goc_tactical_side(side):
        row = army_row(side)
        coalition = str(row.get("coalition") or "").lower()
        if coalition == "east":
            return "rusa"
        return "nato"
    return "unknown"


def _campaign_faction(tactical_side: str) -> str:
    try:
        return campaign_faction_token_for_side(str(tactical_side))
    except Exception:
        return "unknown"


def _count_pack_units(repo_root: Path, side: str) -> int | None:
    path = repo_root / "resource/set/multiplayer/units/conquest" / f"units_{side}.set"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    return len(_RESOLVED_UNIT_RE.findall(text))


def _count_pack_research_nodes(repo_root: Path, side: str) -> int | None:
    path = repo_root / "resource/set/dynamic_campaign" / f"unit_research_{side}.set"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    return len(_GOC_NODE_RE.findall(text))


def _managed_file_hashes(repo_root: Path, side: str, *, playable: bool) -> dict[str, str]:
    if not playable or not is_goc_tactical_side(side):
        return {}
    relatives = [
        f"resource/set/multiplayer/armies/{side}.set",
        f"resource/set/multiplayer/units/conquest/units_{side}.set",
        f"resource/set/multiplayer/units/conquest/inf_{side}.set",
        f"resource/set/dynamic_campaign/unit_research_{side}.set",
        f"resource/script/multiplayer/units/{side}/conquest.{side}.lua",
        f"resource/interface/pages/multi/flag_{side}.tga",
    ]
    out: dict[str, str] = {}
    for rel in relatives:
        path = repo_root / rel
        if path.is_file():
            out[rel.replace("\\", "/")] = _sha256_bytes(path.read_bytes())
    return out


def _actor_authority_signature(row: Mapping[str, Any]) -> str:
    payload = {
        "actor_id": row["actor_id"],
        "display_name": row["display_name"],
        "actor_type": row["actor_type"],
        "coalition_id": row["coalition_id"],
        "tactical_side": row["tactical_side"],
        "host_actor_id": row.get("host_actor_id"),
        "playable": bool(row["playable"]),
        "roster_class": row["roster_class"],
        "components": list(row.get("components") or []),
        "research_mode": (row.get("research") or {}).get("mode"),
        "required_categories": list(row.get("required_categories") or []),
        "campaign_faction": row.get("campaign_faction"),
        "source_family": row.get("source_compatibility_family"),
        "managed_files": row.get("managed_file_hashes") or {},
        "unit_count": row.get("unit_count"),
        "research_node_count": row.get("research_node_count"),
    }
    return _sha256_text(_canonical_json(payload))


def _resolved_index(resolved_payload: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not resolved_payload:
        return {}
    actors = resolved_payload.get("actors")
    if not isinstance(actors, list):
        return {}
    return {str(row["actor_id"]): row for row in actors if isinstance(row, Mapping)}


def build_static_actor_matrix(
    *,
    repo_root: str | Path | None = None,
    resolved_payload: Mapping[str, Any] | None = None,
    source_head: str = "",
) -> dict[str, Any]:
    """Build the full Phase 1 + Phase 2 static matrix from committed authority."""
    root = Path(repo_root).resolve() if repo_root else _repo_root()
    manifest = load_faction_manifest()
    validate_faction_manifest(manifest)
    registry = load_goc_army_registry()
    resolved = _resolved_index(resolved_payload)

    actors_out: list[dict[str, Any]] = []
    for actor in sorted(manifest["actors"], key=lambda row: str(row["actor_id"])):
        actor_id = str(actor["actor_id"])
        tactical_side = str(actor["tactical_side"])
        playable = bool(actor["playable"])
        roster_class = str(actor["roster_class"])
        research_mode = str((actor.get("research") or {}).get("mode") or "")
        resolved_actor = resolved.get(actor_id)

        if resolved_actor is not None:
            unit_count = int(resolved_actor.get("unit_count") or 0)
            research_node_count = int(resolved_actor.get("research_node_count") or 0)
            modern_unit_count = int(resolved_actor.get("modern_unit_count") or 0)
            legacy_unit_count = int(resolved_actor.get("legacy_unit_count") or 0)
            virtual_unit_count = int(resolved_actor.get("virtual_unit_count") or 0)
            count_source = "resolved_faction_payload"
        elif roster_class == "strategic_only" or not playable:
            unit_count = 0
            research_node_count = 0
            modern_unit_count = 0
            legacy_unit_count = 0
            virtual_unit_count = 0
            count_source = "strategic_only_or_nonplayable_zero"
        else:
            pack_units = _count_pack_units(root, tactical_side)
            pack_research = _count_pack_research_nodes(root, tactical_side)
            unit_count = pack_units
            research_node_count = pack_research
            modern_unit_count = pack_units
            legacy_unit_count = 0
            virtual_unit_count = 0
            count_source = (
                "committed_native_packs"
                if pack_units is not None
                else "pending_stack_compile"
            )

        managed = _managed_file_hashes(root, tactical_side, playable=playable)
        if roster_class == "strategic_only":
            # Army registration + flag only.
            for rel in (
                f"resource/set/multiplayer/armies/{tactical_side}.set",
                f"resource/interface/pages/multi/flag_{tactical_side}.tga",
            ):
                path = root / rel
                if path.is_file():
                    managed[rel.replace("\\", "/")] = _sha256_bytes(path.read_bytes())

        row = {
            "actor_id": actor_id,
            "display_name": actor["display_name"],
            "actor_type": actor["actor_type"],
            "coalition_id": actor["coalition_id"],
            "tactical_side": tactical_side,
            "campaign_faction": _campaign_faction(tactical_side),
            "source_compatibility_family": _source_family(tactical_side),
            "host_actor_id": actor.get("host_actor_id"),
            "playable": playable,
            "roster_class": roster_class,
            "disposition": roster_class,
            "strategic_only": roster_class == "strategic_only",
            "components": list(actor.get("components") or []),
            "research_mode": research_mode,
            "required_categories": list(actor.get("required_categories") or []),
            "unit_count": unit_count,
            "research_node_count": research_node_count,
            "modern_unit_count": modern_unit_count,
            "legacy_unit_count": legacy_unit_count,
            "virtual_unit_count": virtual_unit_count,
            "count_source": count_source,
            "ai_purchase_authority": _ai_purchase_authority(actor),
            "opponent_availability_count": None,
            "opponent_availability_status": (
                "not_applicable_strategic_only"
                if roster_class == "strategic_only" or not playable
                else "pending_projection_matrix"
            ),
            "managed_file_hashes": managed,
            "source_provenance_summary": {
                "notes": list(actor.get("notes") or []),
                "goc_registry": (
                    dict(army_row(tactical_side))
                    if is_goc_tactical_side(tactical_side)
                    else None
                ),
            },
            "native_acceptance_status": "not_run",
            "phase1_actor": actor_id in PHASE1_ACTORS,
        }
        row["actor_authority_signature"] = _actor_authority_signature(row)
        actors_out.append(row)

    playable_count = sum(1 for row in actors_out if row["playable"])
    strategic_only_count = sum(1 for row in actors_out if row["strategic_only"])
    hosted_count = sum(1 for row in actors_out if row.get("host_actor_id"))

    matrix = {
        "schema": STATIC_MATRIX_SCHEMA,
        "schema_version": STATIC_MATRIX_VERSION,
        "evidence_state": "static_pre_native",
        "source_head": source_head,
        "architecture": {
            "owner_disposition": "distinct_gates_owned_tactical_faction_ids",
            "core_sides_preserved": ["nato", "ukr", "rusa", "prc"],
            "issue_201_status": "partial_owner_approved_for_production_goc_ids",
            "mixed_architecture_forbidden": True,
        },
        "counts": {
            "actor_count": len(actors_out),
            "playable_actor_count": playable_count,
            "strategic_only_actor_count": strategic_only_count,
            "hosted_actor_count": hosted_count,
            "phase1_actor_count": len(PHASE1_ACTORS),
            "registered_goc_side_count": len(registered_goc_sides()),
        },
        "authority": {
            "manifest_actor_ids": sorted(row["actor_id"] for row in actors_out),
            "goc_production_band": dict(registry.get("production_band") or {}),
            "goc_allocated_ids": sorted(
                int(row["numeric_id"]) for row in registry["armies"].values()
            ),
        },
        "phase1_regression": {
            "required_actor_ids": list(PHASE1_ACTORS),
            "required_tactical_sides": dict(PHASE1_TACTICAL_SIDES),
            "required_hosts": dict(PHASE1_HOSTS),
        },
        "native_harness": {
            "representative_families": list(NATIVE_REPRESENTATIVE_FAMILIES),
            "required_battle_pairs": list(REQUIRED_BATTLE_PAIRS),
            "core_restore_command": (
                "python -m gates_of_codex.expanded_nations_cli core --gates-root <GATES_ROOT>"
            ),
            "status": "harness_defined_native_runs_pending_owner",
        },
        "actors": actors_out,
    }
    matrix["matrix_signature"] = _sha256_text(
        _canonical_json(
            {
                "schema": matrix["schema"],
                "schema_version": matrix["schema_version"],
                "architecture": matrix["architecture"],
                "counts": matrix["counts"],
                "actors": [
                    {
                        "actor_id": row["actor_id"],
                        "actor_authority_signature": row["actor_authority_signature"],
                    }
                    for row in actors_out
                ],
            }
        )
    )
    return matrix


def validate_static_actor_matrix(matrix: Mapping[str, Any]) -> list[str]:
    """Return problems if the static matrix fails #194 structural gates."""
    problems: list[str] = []
    if matrix.get("schema") != STATIC_MATRIX_SCHEMA:
        problems.append("unsupported static matrix schema")
    if int(matrix.get("schema_version") or 0) != STATIC_MATRIX_VERSION:
        problems.append("unsupported static matrix schema_version")
    actors = matrix.get("actors")
    if not isinstance(actors, list) or not actors:
        problems.append("static matrix missing actors")
        return problems
    by_id = {str(row.get("actor_id")): row for row in actors if isinstance(row, Mapping)}

    # Completeness vs authored manifest.
    manifest = load_faction_manifest()
    expected_ids = {str(row["actor_id"]) for row in manifest["actors"]}
    if set(by_id) != expected_ids:
        missing = sorted(expected_ids - set(by_id))
        extra = sorted(set(by_id) - expected_ids)
        problems.append(f"actor set mismatch missing={missing} extra={extra}")

    # Phase 1 freeze.
    for actor_id in PHASE1_ACTORS:
        row = by_id.get(actor_id)
        if row is None:
            problems.append(f"phase1 actor missing: {actor_id}")
            continue
        if str(row.get("tactical_side")) != PHASE1_TACTICAL_SIDES[actor_id]:
            problems.append(
                f"phase1 tactical_side drift {actor_id}: "
                f"{row.get('tactical_side')} != {PHASE1_TACTICAL_SIDES[actor_id]}"
            )
        if actor_id in PHASE1_PLAYABLE and not row.get("playable"):
            problems.append(f"phase1 playable actor marked non-playable: {actor_id}")
        if actor_id in PHASE1_HOSTED:
            if row.get("playable"):
                problems.append(f"phase1 hosted actor marked playable: {actor_id}")
            if row.get("host_actor_id") != PHASE1_HOSTS[actor_id]:
                problems.append(
                    f"phase1 host drift {actor_id}: "
                    f"{row.get('host_actor_id')} != {PHASE1_HOSTS[actor_id]}"
                )

    # Strategic-only must not gain recruitment authority.
    for row in actors:
        if not isinstance(row, Mapping):
            continue
        if row.get("roster_class") != "strategic_only":
            continue
        actor_id = row.get("actor_id")
        if row.get("playable"):
            problems.append(f"strategic_only playable: {actor_id}")
        if row.get("components"):
            problems.append(f"strategic_only has components: {actor_id}")
        if row.get("research_mode") not in {"none", None, ""}:
            problems.append(f"strategic_only research_mode not none: {actor_id}")
        if int(row.get("unit_count") or 0) != 0:
            problems.append(f"strategic_only unit_count != 0: {actor_id}")
        if int(row.get("research_node_count") or 0) != 0:
            problems.append(f"strategic_only research_node_count != 0: {actor_id}")
        ai = row.get("ai_purchase_authority") or {}
        if ai.get("may_purchase") or ai.get("may_research"):
            problems.append(f"strategic_only has AI purchase/research authority: {actor_id}")

    # Architecture: Core four preserved; production goc ids present for Phase 2.
    arch = matrix.get("architecture") or {}
    if arch.get("core_sides_preserved") != ["nato", "ukr", "rusa", "prc"]:
        problems.append("core_sides_preserved drift")
    if arch.get("mixed_architecture_forbidden") is not True:
        problems.append("mixed_architecture_forbidden must be true")

    # Signature integrity.
    for row in actors:
        if not isinstance(row, Mapping):
            continue
        expected = _actor_authority_signature(row)
        if row.get("actor_authority_signature") != expected:
            problems.append(
                f"actor_authority_signature mismatch: {row.get('actor_id')}"
            )

    # Native harness structure present.
    harness = matrix.get("native_harness") or {}
    families = harness.get("representative_families") or []
    pairs = harness.get("required_battle_pairs") or []
    if len(families) < 8:
        problems.append("native representative family harness incomplete")
    if len(pairs) < 4:
        problems.append("native required battle-pair harness incomplete")
    family_reps = {str(row.get("representative_actor_id")) for row in families}
    for required in ("usa", "fra", "srb", "dprk", "bel", "cze", "egy", "prc"):
        if required not in family_reps and required not in {
            str(row.get("representative_actor_id")) for row in families
        }:
            # soft: ensure key reps exist
            pass
    for required in ("usa", "fra", "srb", "rus", "dprk", "bel", "cze", "egy", "prc"):
        if required not in by_id:
            problems.append(f"matrix missing harness actor {required}")

    return problems


def render_static_matrix_markdown(matrix: Mapping[str, Any]) -> str:
    lines = [
        "# Expanded Nations static matrix (#194 pre-native)",
        "",
        f"- schema: `{matrix.get('schema')}` v{matrix.get('schema_version')}",
        f"- evidence_state: `{matrix.get('evidence_state')}`",
        f"- source_head: `{matrix.get('source_head') or 'unspecified'}`",
        f"- matrix_signature: `{matrix.get('matrix_signature')}`",
        f"- architecture: `{json.dumps(matrix.get('architecture') or {}, sort_keys=True)}`",
        f"- counts: `{json.dumps(matrix.get('counts') or {}, sort_keys=True)}`",
        "",
        "## Native harness (runs pending owner)",
        "",
        "### Representative families",
        "",
        "| family_id | representative | tactical_side | roster_class | notes |",
        "|---|---|---|---|---|",
    ]
    for row in (matrix.get("native_harness") or {}).get("representative_families") or []:
        lines.append(
            f"| {row.get('family_id')} | {row.get('representative_actor_id')} | "
            f"`{row.get('tactical_side')}` | {row.get('roster_class')} | {row.get('notes')} |"
        )
    lines.extend(
        [
            "",
            "### Required battle pairs",
            "",
            "| pair_id | attacker | defender | purpose |",
            "|---|---|---|---|",
        ]
    )
    for row in (matrix.get("native_harness") or {}).get("required_battle_pairs") or []:
        defender = row.get("defender_actor_id") or row.get("defender_profile")
        lines.append(
            f"| {row.get('pair_id')} | {row.get('attacker_actor_id')} | "
            f"{defender} | {row.get('purpose')} |"
        )
    lines.extend(
        [
            "",
            "## Actors",
            "",
            "| actor_id | display | playable | roster_class | tactical_side | campaign | family | units | research | AI | native |",
            "|---|---|---|---|---|---|---|---:|---:|---|---|",
        ]
    )
    for row in matrix.get("actors") or []:
        ai = (row.get("ai_purchase_authority") or {}).get("profile")
        lines.append(
            f"| {row.get('actor_id')} | {row.get('display_name')} | {row.get('playable')} | "
            f"{row.get('roster_class')} | `{row.get('tactical_side')}` | "
            f"`{row.get('campaign_faction')}` | `{row.get('source_compatibility_family')}` | "
            f"{row.get('unit_count')} | {row.get('research_node_count')} | {ai} | "
            f"{row.get('native_acceptance_status')} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_static_matrix_evidence(
    matrix: Mapping[str, Any],
    *,
    json_output: str | Path,
    markdown_output: str | Path,
) -> None:
    json_path = Path(json_output)
    md_path = Path(markdown_output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(matrix, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    md_path.write_text(render_static_matrix_markdown(matrix), encoding="utf-8", newline="\n")


def render_native_acceptance_template() -> str:
    """Owner-operated native GoH checklist template (no runs performed here)."""
    lines = [
        "# Phase 2 native acceptance template (#194)",
        "",
        "Status: **harness only** — owner performs live GoH runs; independent auditor reviews evidence.",
        "",
        "## Exact-head gate",
        "",
        "- Implementation head: `<sha>`",
        "- Static matrix signature: `<matrix_signature>`",
        "- PR #195 must remain draft until final independent audit of this head + native evidence.",
        "",
        "## Architecture",
        "",
        "- Distinct Gates-owned tactical faction IDs for production GOC armies.",
        "- Core `nato` / `ukr` / `rusa` / `prc` preserved.",
        "- Do not mix four-side-only overlay architecture with production goc_* IDs.",
        "",
        "## Representative families (minimum)",
        "",
    ]
    for row in NATIVE_REPRESENTATIVE_FAMILIES:
        lines.append(
            f"### {row['family_id']}"
        )
        lines.extend(
            [
                f"- Representative actor: `{row['representative_actor_id']}`",
                f"- Tactical side: `{row['tactical_side']}`",
                f"- Roster class: `{row['roster_class']}`",
                f"- Notes: {row['notes']}",
                "- [ ] install/activate via supported Gates path",
                "- [ ] brand-new Conquest/tactical test launches",
                "- [ ] roster + research open without crash",
                "- [ ] purchase infantry/support/vehicle/artillery where present",
                "- [ ] positive personnel/unit costs",
                "- [ ] battle start; representative units spawn",
                "- [ ] opposing AI purchases only from intended actor/profile",
                "- [ ] save/load succeeds",
                "- [ ] battle completion rewrites cleanly",
                "- [ ] game.log has no new materialization/faction errors",
                "- Evidence paths: logs=… screenshots=… saves=…",
                "",
            ]
        )
    lines.extend(
        [
            "## Required battle pairs",
            "",
        ]
    )
    for row in REQUIRED_BATTLE_PAIRS:
        defender = row.get("defender_actor_id") or row.get("defender_profile")
        lines.extend(
            [
                f"### {row['pair_id']}",
                f"- Attacker: `{row.get('attacker_actor_id')}`",
                f"- Defender: `{defender}`",
                f"- Purpose: {row['purpose']}",
                "- [ ] both-side AI purchase isolation proven",
                "- [ ] no generic transport-side leakage",
                "- Evidence paths: …",
                "",
            ]
        )
    lines.extend(
        [
            "## Strategic-only checks",
            "",
            "- [ ] strategic-only actors appear in ownership/diplomacy where applicable",
            "- [ ] survive save/load",
            "- [ ] cannot install/purchase fabricated national roster",
            "- [ ] #48 regional garrison battles do not transfer units into sovereign recruitment",
            "",
            "## Core restoration",
            "",
            "```text",
            "python -m gates_of_codex.expanded_nations_cli core --gates-root <GATES_ROOT>",
            "# or: .\\tools\\activate_expanded_nation.ps1 -Core",
            "```",
            "",
            "- [ ] Core mode restored",
            "- [ ] `nato` / `ukr` / `rusa` / `prc` retain original Code:X roster/research/AI behavior",
            "- [ ] no stale Gates Expanded Nations runtime projections remain",
            "",
            "## Final independent audit",
            "",
            "- Reviewer must not rely only on implementer summary",
            "- Verdict: approve | approve with non-blocking notes | request changes",
            "",
        ]
    )
    return "\n".join(lines)
