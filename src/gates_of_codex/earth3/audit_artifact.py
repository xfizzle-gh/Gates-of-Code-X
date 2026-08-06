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
from .model import Earth3Dataset
from .parse import load_earth3_dataset

AUDIT_SCHEMA = "gates-of-codex.earth3-local-crop-audit"
AUDIT_SCHEMA_VERSION = 2


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    """SHA-256 of raw file bytes (for binary sources such as the local archive)."""
    return sha256_bytes(Path(path).read_bytes())


def sha256_text_file(path: str | Path) -> str:
    """SHA-256 of a tracked text file with newlines normalized to LF.

    Git may check out tracked text as CRLF on Windows. Normalize before
    hashing so CI validation is platform-stable. Never use this for binary
    archives.
    """
    data = Path(path).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return sha256_bytes(data)


def sha256_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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
            decisions_sha = sha256_text_file(decisions_file)
            break

    decisions_payload = {}
    if decisions_file and decisions_file.is_file():
        decisions_payload = json.loads(decisions_file.read_text(encoding="utf-8"))

    include_ids = list(decisions_payload.get("include_ids", []))
    exclude_ids = list(decisions_payload.get("exclude_ids", []))

    # Repository-relative tracked paths only (no absolute machine paths).
    try:
        cfg_rel = crop_config_path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except Exception:
        cfg_rel = "config/earth3/crop_candidates_v1.json"
    decisions_rel = None
    if decisions_file:
        try:
            decisions_rel = Path(decisions_file).resolve().relative_to(Path.cwd().resolve()).as_posix()
        except Exception:
            decisions_rel = "config/earth3/threshold_decisions_em_reference_masked_v1.json"

    return {
        "schema": AUDIT_SCHEMA,
        "schema_version": AUDIT_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "generation": {
            "source": "tools/earth3/generate_local_audit.py",
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
            "archive_label": "LOCAL_UNCOMMITTED_EARTH3_ARCHIVE",
            "archive_sha256": sha256_file(archive_path),
            "source_province_count": len(dataset.provinces),
            "archive_committed": False,
        },
        "tracked_inputs": {
            "crop_config_path": cfg_rel.replace("\\", "/"),
            "crop_config_sha256": sha256_text_file(crop_config_path),
            "threshold_decisions_path": decisions_rel,
            "threshold_decisions_sha256": decisions_sha,
            "hash_normalization": "tracked_text_lf_only_archive_raw_bytes",
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
            "include_ids": include_ids,
            "exclude_ids": exclude_ids,
        },
        "exclusion_anchor_status": _exclusion_anchor_status(
            dataset, set(result.included_ids), raw_config
        ),
        "iceland_land_province_count": _iceland_land_count(dataset, set(result.included_ids)),
        "exact_required_locations": locations,
        "expected_gating_location_keys": list(GATING_LOCATION_KEYS),
    }


def _exclusion_anchor_status(
    dataset: Earth3Dataset, included: set[int], raw_config: dict
) -> list[dict]:
    rows = []
    for anchor in raw_config.get("exclusion_city_anchors", []):
        pid = int(anchor["source_province_id"])
        rows.append(
            {
                "name": anchor["name"],
                "source_province_id": pid,
                "included": pid in included,
                "ok_excluded": pid not in included,
                "x": anchor.get("x"),
                "y": anchor.get("y"),
            }
        )
    return rows


def _iceland_land_count(dataset: Earth3Dataset, included: set[int]) -> int:
    count = 0
    for pid in included:
        province = dataset.provinces[pid]
        if province.is_water:
            continue
        cx, cy = province.centroid
        if 7000 < cx < 7900 and 650 < cy < 1200:
            count += 1
    return count


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
    expected_cfg = sha256_text_file(crop_config_path)
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
        expected_dec = sha256_text_file(threshold_decisions_path)
        if tracked.get("threshold_decisions_sha256") != expected_dec:
            errors.append("threshold_decisions_sha256 does not match tracked decisions file")
    crop = payload.get("crop_result") or {}
    for key in (
        "province_count",
        "land_province_count",
        "water_province_count",
        "included_ids_sha256",
    ):
        if key not in crop:
            errors.append(f"crop_result missing {key}")
    if int(crop.get("threshold_review_count", -1)) != 0:
        errors.append("threshold_review_count must be 0 after freeze")
    if int(crop.get("province_count", 0)) < 2500:
        errors.append("province_count unexpectedly small for EM theatre")

    oracle = payload.get("oracle") or {}
    if int(oracle.get("discrepancy_count_abs_gt_1e-3", -1)) != 0:
        errors.append("oracle discrepancy_count must be 0")
    if int(oracle.get("classification_flip_count", -1)) != 0:
        errors.append("oracle classification_flip_count must be 0")

    thr = payload.get("threshold_decisions") or {}
    total = int(thr.get("total_decisions", -1))
    if total < 0:
        errors.append("threshold total_decisions missing")
    if total != int(thr.get("include_count", -1)) + int(thr.get("exclude_count", -1)):
        errors.append("threshold include/exclude counts do not sum to total_decisions")
    # decisions file total must match artifact
    if threshold_decisions_path is not None:
        dec = json.loads(Path(threshold_decisions_path).read_text(encoding="utf-8"))
        dec_total = len(dec.get("include_ids", [])) + len(dec.get("exclude_ids", []))
        if dec_total != total:
            errors.append(
                f"threshold decisions file total {dec_total} != artifact {total}"
            )

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
    expected_field = set(payload.get("expected_gating_location_keys") or [])
    if expected_field and expected_field != expected_keys:
        errors.append("expected_gating_location_keys field mismatch")

    anchors = payload.get("exclusion_anchor_status") or []
    for row in anchors:
        if not row.get("ok_excluded", False):
            errors.append(
                f"exclusion anchor still included: {row.get('name')} p={row.get('source_province_id')}"
            )

    iceland_n = int(payload.get("iceland_land_province_count", -1))
    if iceland_n < 18:
        errors.append(f"iceland_land_province_count {iceland_n} < 18")

    src = payload.get("source") or {}
    if src.get("archive_committed") is not False:
        errors.append("archive_committed must be false")
    if src.get("archive_label") != "LOCAL_UNCOMMITTED_EARTH3_ARCHIVE":
        errors.append("archive_label must be LOCAL_UNCOMMITTED_EARTH3_ARCHIVE")
    if int(src.get("source_province_count", -1)) != 13892:
        errors.append("source_province_count must be 13892")
    if not src.get("archive_sha256"):
        errors.append("archive_sha256 missing")
    # No absolute machine paths in committed artifact.
    blob = json.dumps(payload)
    if ":\\" in blob or "/Users/" in blob or "E:/" in blob or "C:/" in blob:
        errors.append("artifact contains absolute machine path")

    tracked = payload.get("tracked_inputs") or {}
    for key in ("crop_config_path", "threshold_decisions_path"):
        val = str(tracked.get(key) or "")
        if val.startswith("/") or ":\\" in val or val.startswith("E:") or val.startswith("C:"):
            errors.append(f"{key} must be repository-relative, got {val!r}")

    return {
        "ok": not errors,
        "errors": errors,
        "artifact_path": str(artifact_path),
    }
