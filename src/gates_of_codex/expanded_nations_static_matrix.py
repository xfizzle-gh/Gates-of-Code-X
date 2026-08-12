"""#194 static/pre-native Expanded Nations actor matrix.

Expanded-mode production uses distinct Gates-owned ``goc_*`` tactical IDs while
preserving Core ``nato/ukr/rusa/prc`` transport/source-family boundaries.

This module builds deterministic static evidence without launching GoH. Native
battle runs remain owner-operated after independent pre-native audit.
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
STATIC_MATRIX_VERSION = 2

PHASE1_PLAYABLE = (
    "usa", "gbr", "deu", "fra", "pol", "ita", "fin", "swe", "nld", "can",
    "nor", "dnk", "esp", "tur", "rus", "ukr", "prc", "dprk", "donbas", "blr", "srb",
)
PHASE1_HOSTED = ("ukr_ildu", "kpa_expeditionary", "wagner")
PHASE1_ACTORS = PHASE1_PLAYABLE + PHASE1_HOSTED

# Frozen Phase 1 source/core transport families (roster boundaries), NOT Expanded tactical IDs.
PHASE1_SOURCE_FAMILY = {
    "usa": "nato", "gbr": "nato", "deu": "nato", "fra": "nato", "pol": "nato",
    "ita": "nato", "fin": "nato", "swe": "nato", "nld": "nato", "can": "nato",
    "nor": "nato", "dnk": "nato", "esp": "nato", "tur": "nato",
    "rus": "rusa", "ukr": "ukr", "prc": "prc", "dprk": "rusa", "donbas": "rusa",
    "blr": "rusa", "srb": "rusa",
    "ukr_ildu": "ukr", "kpa_expeditionary": "rusa", "wagner": "rusa",
}

PHASE1_HOSTS = {
    "ukr_ildu": "ukr",
    "kpa_expeditionary": "rus",
    "wagner": "rus",
}

PHASE1_EXPANDED_TACTICAL_SIDE = {
    "usa": "goc_usa", "gbr": "goc_gbr", "deu": "goc_deu", "fra": "goc_fra",
    "pol": "goc_pol", "ita": "goc_ita", "fin": "goc_fin", "swe": "goc_swe",
    "nld": "goc_nld", "can": "goc_can", "nor": "goc_nor", "dnk": "goc_dnk",
    "esp": "goc_esp", "tur": "goc_tur", "rus": "goc_rus", "ukr": "goc_ukr",
    "prc": "prc",  # Code:X passthrough retains native prc side
    "dprk": "goc_dprk", "donbas": "goc_donbas", "blr": "goc_blr", "srb": "goc_srb",
    "ukr_ildu": "goc_ukr", "kpa_expeditionary": "goc_rus", "wagner": "goc_rus",
}

NATIVE_REPRESENTATIVE_FAMILIES = (
    {
        "family_id": "phase1_full_national_west",
        "representative_actor_id": "usa",
        "expanded_tactical_side": "goc_usa",
        "source_compatibility_family": "nato",
        "roster_class": "full_national",
        "checklist": "playable",
        "notes": "Phase 1 USA full national on Gates ID; source family nato",
    },
    {
        "family_id": "phase1_national_hybrid_west",
        "representative_actor_id": "fra",
        "expanded_tactical_side": "goc_fra",
        "source_compatibility_family": "nato",
        "roster_class": "national_hybrid",
        "checklist": "playable",
        "notes": "France ARF/DSK hybrid on Gates ID for same-family USA-vs-France proof",
    },
    {
        "family_id": "phase1_spain_3rd_assault",
        "representative_actor_id": "esp",
        "expanded_tactical_side": "goc_esp",
        "source_compatibility_family": "nato",
        "roster_class": "coalition_fallback",
        "checklist": "playable",
        "notes": "Spain seven-unit 3rd Assault allocation",
    },
    {
        "family_id": "phase1_ukraine_core",
        "representative_actor_id": "ukr",
        "expanded_tactical_side": "goc_ukr",
        "source_compatibility_family": "ukr",
        "roster_class": "full_national",
        "checklist": "playable",
        "notes": "Ukraine without duplicate ILDU wrappers",
    },
    {
        "family_id": "phase1_russia_core",
        "representative_actor_id": "rus",
        "expanded_tactical_side": "goc_rus",
        "source_compatibility_family": "rusa",
        "roster_class": "full_national",
        "checklist": "playable",
        "notes": "Russia with KPA/Wagner hosted separation",
    },
    {
        "family_id": "phase1_proxy_dprk",
        "representative_actor_id": "dprk",
        "expanded_tactical_side": "goc_dprk",
        "source_compatibility_family": "rusa",
        "roster_class": "proxy_hybrid",
        "checklist": "playable",
        "notes": "DPRK isolation on Gates ID; source family rusa",
    },
    {
        "family_id": "phase1_proxy_serbia",
        "representative_actor_id": "srb",
        "expanded_tactical_side": "goc_srb",
        "source_compatibility_family": "rusa",
        "roster_class": "proxy_hybrid",
        "checklist": "playable",
        "notes": "Serbia isolation for srb-vs-rus same-family proof",
    },
    {
        "family_id": "phase1_prc_passthrough",
        "representative_actor_id": "prc",
        "expanded_tactical_side": "prc",
        "source_compatibility_family": "prc",
        "roster_class": "full_national",
        "checklist": "playable",
        "notes": "PRC Code:X passthrough retains native prc side",
    },
    {
        "family_id": "phase2_goc_nato_full_fallback",
        "representative_actor_id": "bel",
        "expanded_tactical_side": "goc_bel",
        "source_compatibility_family": "nato",
        "roster_class": "coalition_fallback",
        "checklist": "playable",
        "notes": "Production goc_* coalition_fallback family",
    },
    {
        "family_id": "phase2_goc_national_hybrid_dana",
        "representative_actor_id": "cze",
        "expanded_tactical_side": "goc_cze",
        "source_compatibility_family": "nato",
        "roster_class": "national_hybrid",
        "checklist": "playable",
        "notes": "DANA equipment identity + infantry bridge",
    },
    {
        "family_id": "phase2_strategic_only",
        "representative_actor_id": "egy",
        "expanded_tactical_side": "goc_egy",
        "source_compatibility_family": "nato",
        "roster_class": "strategic_only",
        "checklist": "strategic_only",
        "notes": "Strategic-only ownership; fabricated national recruitment must remain impossible",
    },
)

REQUIRED_BATTLE_PAIRS = (
    {
        "pair_id": "usa_vs_fra_gates_ids_shared_nato_source_family",
        "attacker_actor_id": "usa",
        "attacker_expanded_tactical_side": "goc_usa",
        "defender_actor_id": "fra",
        "defender_expanded_tactical_side": "goc_fra",
        "source_family": "nato",
        "purpose": "Same source family without generic Core nato side leakage",
    },
    {
        "pair_id": "srb_vs_rus_gates_ids_shared_rusa_source_family",
        "attacker_actor_id": "srb",
        "attacker_expanded_tactical_side": "goc_srb",
        "defender_actor_id": "rus",
        "defender_expanded_tactical_side": "goc_rus",
        "source_family": "rusa",
        "purpose": "Same source family without generic Core rusa side leakage",
    },
    {
        "pair_id": "usa_vs_dprk_cross_coalition",
        "attacker_actor_id": "usa",
        "attacker_expanded_tactical_side": "goc_usa",
        "defender_actor_id": "dprk",
        "defender_expanded_tactical_side": "goc_dprk",
        "source_family": "cross",
        "purpose": "Cross-coalition pair on distinct Gates IDs",
    },
    {
        "pair_id": "regional_garrison_48",
        "attacker_actor_id": "usa",
        "attacker_expanded_tactical_side": "goc_usa",
        "defender_actor_id": None,
        "defender_profile": "issue_48_regional_local_garrison",
        "purpose": "Regional/local garrison without sovereign recruitment transfer",
    },
)

PLAYABLE_CHECKLIST = (
    "install_or_activate_via_supported_gates_path",
    "launch_brand_new_conquest_or_tactical_test",
    "roster_and_research_open_without_crash",
    "purchase_representative_infantry_support_vehicle_artillery_where_present",
    "prove_positive_personnel_and_unit_costs",
    "start_battle_and_prove_representative_units_spawn",
    "prove_opposing_ai_purchases_only_from_intended_actor_profile",
    "save_load_succeeds",
    "battle_completion_rewrites_cleanly",
    "game_log_has_no_new_materialization_or_faction_errors",
)

STRATEGIC_ONLY_CHECKLIST = (
    "actor_appears_in_strategic_ownership_or_diplomacy_where_applicable",
    "actor_survives_save_load",
    "actor_cannot_be_selected_as_independent_playable",
    "actor_cannot_install_or_purchase_fabricated_national_roster",
    "local_neutral_battles_may_use_issue_48_garrisons_without_recruitment_transfer",
    "no_research_nodes_or_ai_purchase_authority",
)

_RESOLVED_UNIT_RE = re.compile(r"^;\s*resolved_unit=(.+?)\s*$", re.MULTILINE)
_GOC_NODE_RE = re.compile(r"^;\s*goc-node\s+(\{.*\})\s*$", re.MULTILINE)
_TEXT_SUFFIXES = {".set", ".inc", ".lua", ".pot", ".txt", ".md", ".json", ".yml", ".yaml"}


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical_json(payload: Mapping[str, Any] | Sequence[Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _canonical_file_digest(path: Path) -> str:
    """Cross-platform stable digest for managed evidence files."""
    data = path.read_bytes()
    if path.suffix.lower() in _TEXT_SUFFIXES or b"\x00" not in data[:1024]:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return hashlib.sha256(data).hexdigest()
        # Normalize newlines and strip UTF-8 BOM for Git checkout stability.
        if text.startswith("\ufeff"):
            text = text.lstrip("\ufeff")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return _sha256_text(text)
    return hashlib.sha256(data).hexdigest()


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


def _source_family(actor_id: str, tactical_side: str) -> str:
    if actor_id in PHASE1_SOURCE_FAMILY:
        return PHASE1_SOURCE_FAMILY[actor_id]
    side = str(tactical_side or "").lower()
    if side in {"nato", "ukr", "rusa", "prc"}:
        return side
    if is_goc_tactical_side(side):
        row = army_row(side)
        if row.get("core_transport_side"):
            return str(row["core_transport_side"])
        coalition = str(row.get("coalition") or "").lower()
        return "rusa" if coalition == "east" else "nato"
    return "unknown"


def _campaign_faction(tactical_side: str) -> str:
    try:
        return campaign_faction_token_for_side(str(tactical_side))
    except Exception:
        side = str(tactical_side or "").lower()
        if side in {"nato", "ukr", "rusa", "prc", "neutral"}:
            return side
        return "unknown"


def _count_pack_units(repo_root: Path, side: str) -> int | None:
    path = repo_root / "resource/set/multiplayer/units/conquest" / f"units_{side}.set"
    if not path.is_file():
        return None
    return len(_RESOLVED_UNIT_RE.findall(path.read_text(encoding="utf-8", errors="ignore")))


def _count_pack_research_nodes(repo_root: Path, side: str) -> int | None:
    path = repo_root / "resource/set/dynamic_campaign" / f"unit_research_{side}.set"
    if not path.is_file():
        return None
    return len(_GOC_NODE_RE.findall(path.read_text(encoding="utf-8", errors="ignore")))


def _managed_file_hashes(repo_root: Path, side: str, *, playable: bool, strategic_only: bool) -> dict[str, str]:
    relatives: list[str] = []
    if is_goc_tactical_side(side):
        relatives.append(f"resource/set/multiplayer/armies/{side}.set")
        relatives.append(f"resource/interface/pages/multi/flag_{side}.tga")
        if playable and not strategic_only:
            relatives.extend(
                [
                    f"resource/set/multiplayer/units/conquest/units_{side}.set",
                    f"resource/set/multiplayer/units/conquest/inf_{side}.set",
                    f"resource/set/dynamic_campaign/unit_research_{side}.set",
                    f"resource/script/multiplayer/units/{side}/conquest.{side}.lua",
                ]
            )
    out: dict[str, str] = {}
    for rel in relatives:
        path = repo_root / rel
        if path.is_file():
            out[rel.replace("\\", "/")] = _canonical_file_digest(path)
    return out


def _actor_authority_signature(row: Mapping[str, Any]) -> str:
    payload = {
        "actor_id": row["actor_id"],
        "display_name": row["display_name"],
        "actor_type": row["actor_type"],
        "coalition_id": row["coalition_id"],
        "expanded_tactical_side": row["expanded_tactical_side"],
        "source_compatibility_family": row["source_compatibility_family"],
        "campaign_faction": row["campaign_faction"],
        "host_actor_id": row.get("host_actor_id"),
        "playable": bool(row["playable"]),
        "roster_class": row["roster_class"],
        "components": list(row.get("components") or []),
        "research_mode": row.get("research_mode"),
        "required_categories": list(row.get("required_categories") or []),
        "unit_count": row.get("unit_count"),
        "research_node_count": row.get("research_node_count"),
        "modern_unit_count": row.get("modern_unit_count"),
        "legacy_unit_count": row.get("legacy_unit_count"),
        "virtual_unit_count": row.get("virtual_unit_count"),
        "opponent_availability_count": row.get("opponent_availability_count"),
        "managed_files": row.get("managed_file_hashes") or {},
        "ai_profile": (row.get("ai_purchase_authority") or {}).get("profile"),
    }
    return _sha256_text(_canonical_json(payload))


def _resolved_index(resolved_payload: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not resolved_payload:
        return {}
    actors = resolved_payload.get("actors")
    if not isinstance(actors, list):
        return {}
    return {str(row["actor_id"]): row for row in actors if isinstance(row, Mapping)}


def _opponent_availability_count(
    actor: Mapping[str, Any],
    all_actors: Sequence[Mapping[str, Any]],
) -> int | None:
    if not actor.get("playable") or actor.get("roster_class") == "strategic_only":
        return 0
    side = str(actor.get("tactical_side") or "")
    # Opponents = other playable actors with a different expanded tactical side.
    return sum(
        1
        for other in all_actors
        if other.get("playable")
        and other.get("roster_class") != "strategic_only"
        and str(other.get("actor_id")) != str(actor.get("actor_id"))
        and str(other.get("tactical_side") or "") != side
    )


def manifest_authority_fingerprint(repo_root: str | Path | None = None) -> str:
    """Fingerprint full expanded authored authority for snapshot binding.

    Includes complete load_faction_manifest() payload (schema, source_policy,
    fully audit-adjusted components, actors) plus the tactical army registry.
    """
    root = Path(repo_root).resolve() if repo_root else _repo_root()
    manifest = load_faction_manifest()
    validate_faction_manifest(manifest)
    registry = load_goc_army_registry()
    payload = {
        "manifest": {
            "schema": manifest.get("schema"),
            "schema_version": manifest.get("schema_version"),
            "source_policy": manifest.get("source_policy"),
            "components": manifest.get("components"),
            "actors": sorted(
                list(manifest.get("actors") or []),
                key=lambda item: str(item.get("actor_id") or ""),
            ),
        },
        "goc_army_registry": registry,
    }
    return _sha256_text(_canonical_json(payload))


def pack_count_authority_fingerprint(repo_root: str | Path | None = None) -> str:
    """Fingerprint committed playable GOC pack counts and canonical content hashes."""
    root = Path(repo_root).resolve() if repo_root else _repo_root()
    packs: dict[str, dict[str, Any]] = {}
    for side in sorted(registered_goc_sides()):
        row = army_row(side)
        if not bool(row.get("playable")):
            continue
        if str(row.get("roster_class") or "") == "strategic_only":
            continue
        unit_rel = f"resource/set/multiplayer/units/conquest/units_{side}.set"
        research_rel = f"resource/set/dynamic_campaign/unit_research_{side}.set"
        inf_rel = f"resource/set/multiplayer/units/conquest/inf_{side}.set"
        lua_rel = f"resource/script/multiplayer/units/{side}/conquest.{side}.lua"
        unit_path = root / unit_rel
        research_path = root / research_rel
        packs[side] = {
            "unit_count": _count_pack_units(root, side),
            "research_node_count": _count_pack_research_nodes(root, side),
            "files": {
                rel: (_canonical_file_digest(root / rel) if (root / rel).is_file() else None)
                for rel in (unit_rel, research_rel, inf_rel, lua_rel)
            },
            "unit_pack_present": unit_path.is_file(),
            "research_pack_present": research_path.is_file(),
        }
    return _sha256_text(_canonical_json(packs))


def load_resolved_static_snapshot(repo_root: str | Path | None = None) -> dict[str, Any] | None:
    """Load committed resolved count snapshot for stack-free CI/static evidence.

    Fail-closed: snapshot must match current full manifest/registry fingerprint and
    committed playable pack count/hash authority.
    """
    root = Path(repo_root).resolve() if repo_root else _repo_root()
    path = root / "docs/audits/expanded-nations-resolved-static-snapshot.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("actors"), list):
        raise ValueError("resolved static snapshot is malformed")
    expected_fp = manifest_authority_fingerprint(root)
    actual_fp = str(payload.get("manifest_authority_fingerprint") or "")
    if actual_fp != expected_fp:
        raise ValueError(
            "resolved static snapshot is stale relative to current manifest/registry "
            f"authority (snapshot={actual_fp[:12] or 'missing'} "
            f"current={expected_fp[:12]})"
        )
    expected_pack_fp = pack_count_authority_fingerprint(root)
    actual_pack_fp = str(payload.get("pack_count_authority_fingerprint") or "")
    if actual_pack_fp != expected_pack_fp:
        raise ValueError(
            "resolved static snapshot is stale relative to committed pack count "
            f"authority (snapshot={actual_pack_fp[:12] or 'missing'} "
            f"current={expected_pack_fp[:12]})"
        )
    # Actor tactical sides must still match current manifest exactly.
    manifest = load_faction_manifest()
    expected_sides = {
        str(row["actor_id"]): str(row["tactical_side"]) for row in manifest["actors"]
    }
    snapshot_sides = {
        str(row.get("actor_id")): str(row.get("tactical_side"))
        for row in payload["actors"]
        if isinstance(row, Mapping)
    }
    if snapshot_sides != expected_sides:
        raise ValueError("resolved static snapshot actor/side map does not match manifest")
    # Playable GOC pack unit counts must match snapshot unit_count when packs exist.
    # Research node counts may legitimately differ between full resolved compile
    # authority and committed pack goc-node markers; pack hashes bind the pack bytes.
    by_id = {
        str(row.get("actor_id")): row
        for row in payload["actors"]
        if isinstance(row, Mapping)
    }
    for actor in manifest["actors"]:
        if not actor.get("playable") or actor.get("roster_class") == "strategic_only":
            continue
        side = str(actor.get("tactical_side") or "")
        if not is_goc_tactical_side(side):
            continue
        pack_units = _count_pack_units(root, side)
        if pack_units is None:
            continue
        snap = by_id.get(str(actor["actor_id"])) or {}
        if int(snap.get("unit_count") or -1) != pack_units:
            raise ValueError(
                f"resolved static snapshot unit_count mismatch for {actor['actor_id']}: "
                f"snapshot={snap.get('unit_count')} pack={pack_units}"
            )
    return payload


def build_static_actor_matrix(
    *,
    repo_root: str | Path | None = None,
    resolved_payload: Mapping[str, Any] | None = None,
    source_head: str = "",
    require_resolved_counts: bool = False,
    use_committed_resolved_snapshot: bool = True,
) -> dict[str, Any]:
    root = Path(repo_root).resolve() if repo_root else _repo_root()
    manifest = load_faction_manifest()
    validate_faction_manifest(manifest)
    registry = load_goc_army_registry()
    if resolved_payload is None and use_committed_resolved_snapshot:
        resolved_payload = load_resolved_static_snapshot(root)
    resolved = _resolved_index(resolved_payload)
    authored_actors = list(manifest["actors"])

    actors_out: list[dict[str, Any]] = []
    for actor in sorted(authored_actors, key=lambda row: str(row["actor_id"])):
        actor_id = str(actor["actor_id"])
        expanded_side = str(actor["tactical_side"])
        playable = bool(actor["playable"])
        roster_class = str(actor["roster_class"])
        research_mode = str((actor.get("research") or {}).get("mode") or "")
        strategic_only = roster_class == "strategic_only"
        source_family = _source_family(actor_id, expanded_side)
        resolved_actor = resolved.get(actor_id)

        if resolved_actor is not None:
            unit_count = int(resolved_actor.get("unit_count") or 0)
            research_node_count = int(resolved_actor.get("research_node_count") or 0)
            modern_unit_count = int(resolved_actor.get("modern_unit_count") or 0)
            legacy_unit_count = int(resolved_actor.get("legacy_unit_count") or 0)
            virtual_unit_count = int(resolved_actor.get("virtual_unit_count") or 0)
            count_source = "resolved_faction_payload"
        elif strategic_only or not playable:
            unit_count = 0
            research_node_count = 0
            modern_unit_count = 0
            legacy_unit_count = 0
            virtual_unit_count = 0
            count_source = "strategic_only_or_nonplayable_zero"
        else:
            pack_units = _count_pack_units(root, expanded_side)
            pack_research = _count_pack_research_nodes(root, expanded_side)
            if pack_units is None or pack_research is None:
                if require_resolved_counts:
                    raise ValueError(
                        f"Playable actor {actor_id} missing resolved/pack counts; "
                        "supply resolved_payload/stack compile"
                    )
                unit_count = None
                research_node_count = None
                modern_unit_count = None
                legacy_unit_count = None
                virtual_unit_count = None
                count_source = "missing_resolved_or_pack_authority"
            else:
                unit_count = pack_units
                research_node_count = pack_research
                modern_unit_count = pack_units
                legacy_unit_count = 0
                virtual_unit_count = 0
                count_source = "committed_native_packs"

        managed = _managed_file_hashes(
            root,
            expanded_side,
            playable=playable,
            strategic_only=strategic_only,
        )
        opponent_count = _opponent_availability_count(actor, authored_actors)

        row = {
            "actor_id": actor_id,
            "display_name": actor["display_name"],
            "actor_type": actor["actor_type"],
            "coalition_id": actor["coalition_id"],
            "expanded_tactical_side": expanded_side,
            "tactical_side": expanded_side,  # Expanded-mode production identity
            "source_compatibility_family": source_family,
            "core_transport_side": source_family if source_family in {"nato", "ukr", "rusa", "prc"} else None,
            "campaign_faction": _campaign_faction(expanded_side),
            "host_actor_id": actor.get("host_actor_id"),
            "playable": playable,
            "roster_class": roster_class,
            "disposition": roster_class,
            "strategic_only": strategic_only,
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
            "opponent_availability_count": opponent_count,
            "opponent_availability_status": (
                "not_applicable_strategic_only"
                if strategic_only or not playable
                else "playable_actors_with_distinct_expanded_tactical_side"
            ),
            "managed_file_hashes": managed,
            "source_provenance_summary": {
                "notes": list(actor.get("notes") or []),
                "goc_registry": (
                    dict(army_row(expanded_side))
                    if is_goc_tactical_side(expanded_side)
                    else None
                ),
            },
            "native_acceptance_status": "not_run",
            "native_checklist": (
                list(STRATEGIC_ONLY_CHECKLIST)
                if strategic_only
                else (list(PLAYABLE_CHECKLIST) if playable else ["hosted_non_independent"])
            ),
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
            "expanded_mode_uses_gates_ids": True,
            "phase1_source_families_frozen": True,
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
            "resolved_payload_present": bool(resolved),
        },
        "phase1_regression": {
            "required_actor_ids": list(PHASE1_ACTORS),
            "required_source_families": dict(PHASE1_SOURCE_FAMILY),
            "required_expanded_tactical_sides": dict(PHASE1_EXPANDED_TACTICAL_SIDE),
            "required_hosts": dict(PHASE1_HOSTS),
        },
        "native_harness": {
            "representative_families": list(NATIVE_REPRESENTATIVE_FAMILIES),
            "required_battle_pairs": list(REQUIRED_BATTLE_PAIRS),
            "playable_checklist": list(PLAYABLE_CHECKLIST),
            "strategic_only_checklist": list(STRATEGIC_ONLY_CHECKLIST),
            "core_restore_command": (
                "python -m gates_of_codex.expanded_nations_cli core --gates-root <GATES_ROOT>"
            ),
            "battle_pair_install_command": (
                "python -m gates_of_codex.expanded_nations_cli battle-pair "
                "--attacker <ATTACKER_ACTOR_ID> --defender <DEFENDER_ACTOR_ID> "
                "--gates-root <GATES_ROOT> --source-repo <SOURCE_REPO>"
            ),
            "battle_pair_verify_command": (
                "python -m gates_of_codex.expanded_nations_cli battle-pair-verify "
                "--gates-root <GATES_ROOT>"
            ),
            "battle_pair_restore_command": (
                "python -m gates_of_codex.expanded_nations_cli battle-pair-restore "
                "--gates-root <GATES_ROOT>"
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
                "phase1_regression": matrix["phase1_regression"],
                "native_harness": {
                    "representative_families": matrix["native_harness"]["representative_families"],
                    "required_battle_pairs": matrix["native_harness"]["required_battle_pairs"],
                    "playable_checklist": matrix["native_harness"]["playable_checklist"],
                    "strategic_only_checklist": matrix["native_harness"]["strategic_only_checklist"],
                },
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

    manifest = load_faction_manifest()
    expected_ids = {str(row["actor_id"]) for row in manifest["actors"]}
    if set(by_id) != expected_ids:
        problems.append(
            f"actor set mismatch missing={sorted(expected_ids - set(by_id))} "
            f"extra={sorted(set(by_id) - expected_ids)}"
        )

    arch = matrix.get("architecture") or {}
    if arch.get("expanded_mode_uses_gates_ids") is not True:
        problems.append("expanded_mode_uses_gates_ids must be true")
    if arch.get("core_sides_preserved") != ["nato", "ukr", "rusa", "prc"]:
        problems.append("core_sides_preserved drift")

    for actor_id in PHASE1_ACTORS:
        row = by_id.get(actor_id)
        if row is None:
            problems.append(f"phase1 actor missing: {actor_id}")
            continue
        if row.get("source_compatibility_family") != PHASE1_SOURCE_FAMILY[actor_id]:
            problems.append(f"phase1 source family drift: {actor_id}")
        expected_side = PHASE1_EXPANDED_TACTICAL_SIDE[actor_id]
        if row.get("expanded_tactical_side") != expected_side:
            problems.append(
                f"phase1 expanded tactical side drift {actor_id}: "
                f"{row.get('expanded_tactical_side')} != {expected_side}"
            )
        if actor_id != "prc" and expected_side != "prc":
            if not str(expected_side).startswith("goc_"):
                problems.append(f"phase1 expanded side is not gates id: {actor_id}")
        if actor_id in PHASE1_PLAYABLE and not row.get("playable"):
            problems.append(f"phase1 playable marked non-playable: {actor_id}")
        if actor_id in PHASE1_HOSTS:
            if row.get("playable"):
                problems.append(f"phase1 hosted marked playable: {actor_id}")
            if row.get("host_actor_id") != PHASE1_HOSTS[actor_id]:
                problems.append(f"phase1 host drift: {actor_id}")

    for row in actors:
        actor_id = row.get("actor_id")
        if row.get("roster_class") == "strategic_only":
            if row.get("playable") or row.get("components") or int(row.get("unit_count") or 0):
                problems.append(f"strategic_only recruitment leak: {actor_id}")
            if row.get("research_mode") not in {"none", None, ""}:
                problems.append(f"strategic_only research leak: {actor_id}")
            ai = row.get("ai_purchase_authority") or {}
            if ai.get("may_purchase") or ai.get("may_research"):
                problems.append(f"strategic_only AI authority leak: {actor_id}")
            if row.get("native_checklist") != list(STRATEGIC_ONLY_CHECKLIST):
                problems.append(f"strategic_only checklist incorrect: {actor_id}")
        elif row.get("playable"):
            if row.get("unit_count") is None or row.get("research_node_count") is None:
                problems.append(f"playable actor missing authoritative counts: {actor_id}")
            if row.get("modern_unit_count") is None or row.get("legacy_unit_count") is None:
                problems.append(f"playable actor missing modern/legacy counts: {actor_id}")
            if row.get("opponent_availability_count") is None:
                problems.append(f"playable actor missing opponent availability: {actor_id}")
            if row.get("native_checklist") != list(PLAYABLE_CHECKLIST):
                problems.append(f"playable checklist incorrect: {actor_id}")
            # Same-family battle architecture: non-PRC playable expanded sides should be goc_* 
            # or explicit passthrough prc.
            side = str(row.get("expanded_tactical_side") or "")
            if row.get("actor_id") != "prc" and not side.startswith("goc_") and side != "prc":
                problems.append(
                    f"playable expanded tactical side is not Gates-owned id: {actor_id}={side}"
                )

        expected_sig = _actor_authority_signature(row)
        if row.get("actor_authority_signature") != expected_sig:
            problems.append(f"actor_authority_signature mismatch: {actor_id}")

    harness = matrix.get("native_harness") or {}
    if harness.get("strategic_only_checklist") != list(STRATEGIC_ONLY_CHECKLIST):
        problems.append("native harness missing strategic_only_checklist")
    if harness.get("playable_checklist") != list(PLAYABLE_CHECKLIST):
        problems.append("native harness missing playable_checklist")
    pairs = {row.get("pair_id") for row in harness.get("required_battle_pairs") or []}
    for required in (
        "usa_vs_fra_gates_ids_shared_nato_source_family",
        "srb_vs_rus_gates_ids_shared_rusa_source_family",
        "usa_vs_dprk_cross_coalition",
        "regional_garrison_48",
    ):
        if required not in pairs:
            problems.append(f"missing required battle pair {required}")
    # Battle pairs must reference Gates IDs for USA/FRA/SRB/RUS/DPRK.
    for row in harness.get("required_battle_pairs") or []:
        if row.get("pair_id", "").startswith("usa_vs_fra"):
            if row.get("attacker_expanded_tactical_side") != "goc_usa":
                problems.append("usa_vs_fra attacker side not goc_usa")
            if row.get("defender_expanded_tactical_side") != "goc_fra":
                problems.append("usa_vs_fra defender side not goc_fra")
        if row.get("pair_id", "").startswith("srb_vs_rus"):
            if row.get("attacker_expanded_tactical_side") != "goc_srb":
                problems.append("srb_vs_rus attacker side not goc_srb")
            if row.get("defender_expanded_tactical_side") != "goc_rus":
                problems.append("srb_vs_rus defender side not goc_rus")

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
        "## Native harness",
        "",
        "### Representative families",
        "",
        "| family_id | actor | expanded_side | source_family | checklist | notes |",
        "|---|---|---|---|---|---|",
    ]
    for row in (matrix.get("native_harness") or {}).get("representative_families") or []:
        lines.append(
            f"| {row.get('family_id')} | {row.get('representative_actor_id')} | "
            f"`{row.get('expanded_tactical_side')}` | `{row.get('source_compatibility_family')}` | "
            f"{row.get('checklist')} | {row.get('notes')} |"
        )
    lines.extend(
        [
            "",
            "### Required battle pairs",
            "",
            "| pair_id | attacker | attacker_side | defender | defender_side | purpose |",
            "|---|---|---|---|---|---|",
        ]
    )
    for row in (matrix.get("native_harness") or {}).get("required_battle_pairs") or []:
        defender = row.get("defender_actor_id") or row.get("defender_profile")
        lines.append(
            f"| {row.get('pair_id')} | {row.get('attacker_actor_id')} | "
            f"`{row.get('attacker_expanded_tactical_side')}` | {defender} | "
            f"`{row.get('defender_expanded_tactical_side') or row.get('defender_profile')}` | "
            f"{row.get('purpose')} |"
        )
    lines.extend(
        [
            "",
            "### Checklists",
            "",
            "Playable:",
            "",
        ]
    )
    for item in (matrix.get("native_harness") or {}).get("playable_checklist") or []:
        lines.append(f"- {item}")
    lines.extend(["", "Strategic-only:", ""])
    for item in (matrix.get("native_harness") or {}).get("strategic_only_checklist") or []:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Actors",
            "",
            "| actor_id | playable | roster | expanded_side | source_family | units | research | modern | legacy | opponents | AI | native |",
            "|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for row in matrix.get("actors") or []:
        ai = (row.get("ai_purchase_authority") or {}).get("profile")
        lines.append(
            f"| {row.get('actor_id')} | {row.get('playable')} | {row.get('roster_class')} | "
            f"`{row.get('expanded_tactical_side')}` | `{row.get('source_compatibility_family')}` | "
            f"{row.get('unit_count')} | {row.get('research_node_count')} | "
            f"{row.get('modern_unit_count')} | {row.get('legacy_unit_count')} | "
            f"{row.get('opponent_availability_count')} | {ai} | {row.get('native_acceptance_status')} |"
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
    lines = [
        "# Phase 2 native acceptance template (#194)",
        "",
        "Status: **harness only** — owner performs live GoH runs; independent auditor reviews evidence.",
        "",
        "## Architecture",
        "",
        "- Expanded-mode production uses distinct Gates-owned `goc_*` tactical IDs.",
        "- Phase 1 source/core transport families (`nato`/`ukr`/`rusa`/`prc`) remain the frozen roster boundary labels.",
        "- Core Code:X sides remain available via Core restore; do not mix architectures.",
        "",
        "## Playable family checklist",
        "",
    ]
    for item in PLAYABLE_CHECKLIST:
        lines.append(f"- [ ] {item}")
    lines.extend(["", "## Strategic-only checklist", ""])
    for item in STRATEGIC_ONLY_CHECKLIST:
        lines.append(f"- [ ] {item}")
    lines.extend(["", "## Representative families", ""])
    for row in NATIVE_REPRESENTATIVE_FAMILIES:
        lines.extend(
            [
                f"### {row['family_id']} (`{row['checklist']}`)",
                f"- Actor: `{row['representative_actor_id']}`",
                f"- Expanded tactical side: `{row['expanded_tactical_side']}`",
                f"- Source family: `{row['source_compatibility_family']}`",
                f"- Notes: {row['notes']}",
                "- Evidence paths: logs=… screenshots=… saves=…",
                "",
            ]
        )
    lines.extend(["## Required battle pairs", ""])
    for row in REQUIRED_BATTLE_PAIRS:
        defender = row.get("defender_actor_id") or row.get("defender_profile")
        lines.extend(
            [
                f"### {row['pair_id']}",
                f"- Attacker: `{row.get('attacker_actor_id')}` / `{row.get('attacker_expanded_tactical_side')}`",
                f"- Defender: `{defender}` / `{row.get('defender_expanded_tactical_side') or row.get('defender_profile')}`",
                f"- Purpose: {row['purpose']}",
                "- Evidence paths: …",
                "",
            ]
        )
    lines.extend(
        [
            "## Core restoration",
            "",
            "```text",
            "python -m gates_of_codex.expanded_nations_cli core --gates-root <GATES_ROOT>",
            "```",
            "",
            "- [ ] Core restored; `nato`/`ukr`/`rusa`/`prc` retain original Code:X behavior",
            "- [ ] no stale Gates Expanded Nations projections remain",
            "",
        ]
    )
    return "\n".join(lines)
