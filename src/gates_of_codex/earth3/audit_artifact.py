"""Machine-readable local Earth3 crop audit artifact (archive stays uncommitted)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .crop import apply_crop, load_crop_candidates
from .geometry import (
    AUTHORITATIVE_GEOMETRY_ENGINE,
    STDLIB_GEOMETRY_ENGINE,
    bounds_intersect,
    overlap_ratio_stdlib,
    require_authoritative_geometry_engine,
    ring_bounds,
)
from .locations import GATING_LOCATION_KEYS, validate_required_locations
from .oracle import shapely_overlap_ratio
from .parse import load_earth3_dataset

AUDIT_SCHEMA = "gates-of-codex.earth3-local-crop-audit"
AUDIT_SCHEMA_VERSION = 1


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def included_ids_hash(ids: list[int]) -> str:
    payload = ",".join(str(i) for i in sorted(ids))
    return sha256_text(payload)


def build_local_crop_audit(
    *,
    archive_path: str | Path,
    crop_config_path: str | Path,
    candidate_id: str = "em_reference_masked",
    commit_sha: str = "",
    tool_version: str = "",
) -> dict:
    archive_path = Path(archive_path)
    crop_config_path = Path(crop_config_path)
    if not archive_path.is_file():
        raise FileNotFoundError(f"LOCAL SOURCE REQUIRED: archive not found: {archive_path}")

    engine = require_authoritative_geometry_engine()
    dataset = load_earth3_dataset(archive_path)
    candidates = load_crop_candidates(crop_config_path)
    candidate = next(c for c in candidates if c.id == candidate_id)
    result = apply_crop(dataset, candidate)

    # Oracle comparison: authoritative Shapely vs stdlib comparison tooling.
    discrepancies = 0
    flips = 0
    checked = 0
    thr = candidate.inclusion_threshold
    for pid, province in dataset.provinces.items():
        if not candidate.rect.intersects_bounds(province.bounds):
            continue
        if not any(
            bounds_intersect(province.bounds, ring_bounds(ring))
            for ring in candidate.mask_rings
        ):
            continue
        checked += 1
        auth = shapely_overlap_ratio(province.ring, candidate.mask_rings)
        std = overlap_ratio_stdlib(province.ring, candidate.mask_rings)
        if abs(auth - std) > 1e-3:
            discrepancies += 1
            if (auth >= thr) != (std >= thr):
                flips += 1

    locations = validate_required_locations(dataset, set(result.included_ids))
    decisions_file = None
    decisions_sha = None
    raw_config = json.loads(crop_config_path.read_text(encoding="utf-8"))
    for row in raw_config.get("candidates", []):
        if row.get("id") == candidate_id and row.get("threshold_decisions_file"):
            decisions_file = (crop_config_path.parent / row["threshold_decisions_file"]).resolve()
            decisions_sha = sha256_file(decisions_file)
            break

    decisions_payload = {}
    if decisions_file and decisions_file.is_file():
        decisions_payload = json.loads(decisions_file.read_text(encoding="utf-8"))

    include_ids = list(decisions_payload.get("include_ids", []))
    exclude_ids = list(decisions_payload.get("exclude_ids", []))

    return {
        "schema": AUDIT_SCHEMA,
        "schema_version": AUDIT_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "generation": {
            "commit_sha": commit_sha,
            "tool_version": tool_version,
            "authoritative_geometry_engine": engine,
            "comparison_geometry_engine": STDLIB_GEOMETRY_ENGINE,
            "note": (
                "Shapely is mandatory for authoritative crop generation. "
                "Stdlib overlap is comparison-only and never silently becomes authority."
            ),
        },
        "source": {
            "archive_path_local_only": str(archive_path),
            "archive_sha256": sha256_file(archive_path),
            "source_province_count": len(dataset.provinces),
            "archive_committed": False,
        },
        "tracked_inputs": {
            "crop_config_path": str(crop_config_path.as_posix()),
            "crop_config_sha256": sha256_file(crop_config_path),
            "threshold_decisions_path": (
                str(Path(decisions_file).as_posix()) if decisions_file else None
            ),
            "threshold_decisions_sha256": decisions_sha,
        },
        "oracle": {
            "provinces_checked": checked,
            "discrepancy_count_abs_gt_1e-3": discrepancies,
            "classification_flip_count": flips,
        },
        "crop_result": {
            "province_count": result.province_count,
            "land_province_count": result.land_count,
            "water_province_count": result.water_count,
            "vertex_count": result.vertex_count,
            "adjacency_edge_count": result.adjacency_edges,
            "disconnected_land_components": result.disconnected_land_components,
            "threshold_review_count": len(result.threshold_review_ids),
            "included_ids_sha256": included_ids_hash(result.included_ids),
            "required_include_override_count": len(candidate.required_include_ids),
            "explicit_exclude_override_count": len(candidate.explicit_exclude_ids),
        },
        "threshold_decisions": {
            "include_count": len(include_ids),
            "exclude_count": len(exclude_ids),
            "total_decisions": len(include_ids) + len(exclude_ids),
            "expected_total_decisions": 55,
            "include_ids": include_ids,
            "exclude_ids": exclude_ids,
        },
        "exact_required_locations": locations,
        "expected_gating_location_keys": list(GATING_LOCATION_KEYS),
    }


def write_local_crop_audit(path: str | Path, payload: dict) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def validate_committed_audit_artifact(
    artifact_path: str | Path,
    *,
    crop_config_path: str | Path,
    threshold_decisions_path: str | Path | None = None,
) -> dict:
    """CI-safe validation of the committed local audit artifact (no archive needed)."""
    artifact_path = Path(artifact_path)
    crop_config_path = Path(crop_config_path)
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    errors: list[str] = []

    if payload.get("schema") != AUDIT_SCHEMA:
        errors.append(f"schema mismatch: {payload.get('schema')}")
    if int(payload.get("schema_version", -1)) != AUDIT_SCHEMA_VERSION:
        errors.append(f"schema_version mismatch: {payload.get('schema_version')}")

    gen = payload.get("generation") or {}
    if gen.get("authoritative_geometry_engine") != AUTHORITATIVE_GEOMETRY_ENGINE:
        errors.append("authoritative_geometry_engine must be shapely")

    tracked = payload.get("tracked_inputs") or {}
    expected_cfg = sha256_file(crop_config_path)
    if tracked.get("crop_config_sha256") != expected_cfg:
        errors.append("crop_config_sha256 does not match tracked config file")

    if threshold_decisions_path is None:
        # Resolve from config.
        cfg = json.loads(crop_config_path.read_text(encoding="utf-8"))
        for row in cfg.get("candidates", []):
            if row.get("id") == payload.get("candidate_id") and row.get(
                "threshold_decisions_file"
            ):
                threshold_decisions_path = (
                    crop_config_path.parent / row["threshold_decisions_file"]
                )
                break
    if threshold_decisions_path is not None:
        threshold_decisions_path = Path(threshold_decisions_path)
        expected_dec = sha256_file(threshold_decisions_path)
        if tracked.get("threshold_decisions_sha256") != expected_dec:
            errors.append("threshold_decisions_sha256 does not match tracked decisions file")
        dec = json.loads(threshold_decisions_path.read_text(encoding="utf-8"))
        dec_total = len(dec.get("include_ids", [])) + len(dec.get("exclude_ids", []))
        if dec_total != 55:
            errors.append(f"threshold decisions file total {dec_total} != 55")

    crop = payload.get("crop_result") or {}
    if int(crop.get("province_count", -1)) != 3648:
        errors.append(f"province_count {crop.get('province_count')} != 3648")
    if int(crop.get("land_province_count", -1)) != 3431:
        errors.append(f"land_province_count {crop.get('land_province_count')} != 3431")
    if int(crop.get("water_province_count", -1)) != 217:
        errors.append(f"water_province_count {crop.get('water_province_count')} != 217")
    if int(crop.get("threshold_review_count", -1)) != 0:
        errors.append("threshold_review_count must be 0 after freeze")

    oracle = payload.get("oracle") or {}
    if int(oracle.get("discrepancy_count_abs_gt_1e-3", -1)) != 0:
        errors.append("oracle discrepancy_count must be 0")
    if int(oracle.get("classification_flip_count", -1)) != 0:
        errors.append("oracle classification_flip_count must be 0")

    thr = payload.get("threshold_decisions") or {}
    if int(thr.get("total_decisions", -1)) != 55:
        errors.append(f"threshold total_decisions {thr.get('total_decisions')} != 55")
    if int(thr.get("include_count", -1)) != 24:
        errors.append(f"threshold include_count {thr.get('include_count')} != 24")
    if int(thr.get("exclude_count", -1)) != 31:
        errors.append(f"threshold exclude_count {thr.get('exclude_count')} != 31")

    locs = payload.get("exact_required_locations") or {}
    if not locs.get("ok"):
        errors.append(f"exact_required_locations failed: {locs.get('failure_keys')}")
    expected_keys = set(GATING_LOCATION_KEYS)
    artifact_keys = set(locs.get("gating_keys") or [])
    if artifact_keys != expected_keys:
        errors.append(
            "gating location key set mismatch: "
            f"missing={sorted(expected_keys - artifact_keys)} "
            f"extra={sorted(artifact_keys - expected_keys)}"
        )
    # Also verify expected_gating_location_keys field if present.
    expected_field = set(payload.get("expected_gating_location_keys") or [])
    if expected_field and expected_field != expected_keys:
        errors.append("expected_gating_location_keys field mismatch")

    src = payload.get("source") or {}
    if src.get("archive_committed") is not False:
        errors.append("archive_committed must be false")
    if int(src.get("source_province_count", -1)) != 13892:
        errors.append("source_province_count must be 13892")
    if not src.get("archive_sha256"):
        errors.append("archive_sha256 missing")

    return {
        "ok": not errors,
        "errors": errors,
        "artifact_path": str(artifact_path),
    }
