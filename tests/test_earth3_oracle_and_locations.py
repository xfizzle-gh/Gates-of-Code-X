from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from gates_of_codex.earth3.audit_artifact import (
    AUDIT_SCHEMA,
    validate_committed_audit_artifact,
)
from gates_of_codex.earth3.crop import apply_crop, load_crop_candidates
from gates_of_codex.earth3.geometry import (
    AUTHORITATIVE_GEOMETRY_ENGINE,
    GeometryAuthorityError,
    overlap_ratio,
    overlap_ratio_stdlib,
    require_authoritative_geometry_engine,
)
from gates_of_codex.earth3.locations import (
    GATING_LOCATION_KEYS,
    REQUIRED_LOCATIONS,
    validate_required_locations,
)
from gates_of_codex.earth3.model import Earth3City, Earth3Dataset, Earth3Province

try:
    from gates_of_codex.earth3.oracle import SHAPELY_AVAILABLE, shapely_overlap_ratio
except ImportError:  # pragma: no cover
    SHAPELY_AVAILABLE = False


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = Path(r"C:\Users\paulf\Downloads\AOH3_Earth3_map_provinces.zip")
LOCAL_AUDIT = ROOT / "docs/earth3-crop/local_crop_audit.json"
BOUNDARY_JSON = ROOT / "docs/earth3-crop/boundary_review_em_reference_masked.json"


class GeometryAuthorityTests(unittest.TestCase):
    def test_authoritative_engine_is_shapely(self) -> None:
        self.assertEqual(AUTHORITATIVE_GEOMETRY_ENGINE, "shapely")

    def test_require_authoritative_fails_without_shapely(self) -> None:
        with mock.patch("gates_of_codex.earth3.oracle.SHAPELY_AVAILABLE", False):
            with self.assertRaises(GeometryAuthorityError) as ctx:
                require_authoritative_geometry_engine()
            self.assertIn("Shapely is required", str(ctx.exception))
            self.assertIn("will not silently", str(ctx.exception))

    def test_overlap_ratio_does_not_silently_fallback(self) -> None:
        subject = ((0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0))
        mask = (((0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)),)
        with mock.patch("gates_of_codex.earth3.oracle.SHAPELY_AVAILABLE", False):
            with self.assertRaises(GeometryAuthorityError):
                overlap_ratio(subject, mask)


class OracleGeometryTests(unittest.TestCase):
    def test_stdlib_and_shapely_agree_on_synthetic(self) -> None:
        if not SHAPELY_AVAILABLE:
            self.skipTest("LOCAL SOURCE REQUIRED: shapely not installed")
        subject = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
        mask = (((5.0, -1.0), (11.0, -1.0), (11.0, 11.0), (5.0, 11.0)),)
        std = overlap_ratio_stdlib(subject, mask)
        sh = shapely_overlap_ratio(subject, mask)
        self.assertAlmostEqual(std, 0.5, places=5)
        self.assertAlmostEqual(sh, 0.5, places=5)


class ThresholdDecisionConfigTests(unittest.TestCase):
    def test_threshold_decisions_cover_exactly_55(self) -> None:
        path = ROOT / "config/earth3/threshold_decisions_em_reference_masked_v1.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        include = data["include_ids"]
        exclude = data["exclude_ids"]
        total = len(include) + len(exclude)
        self.assertGreaterEqual(total, 1)
        self.assertEqual(len(set(include) & set(exclude)), 0)
        self.assertEqual(len(data["decisions"]), total)

    def test_masked_candidate_loads_frozen_overrides(self) -> None:
        candidates = load_crop_candidates(ROOT / "config/earth3/crop_candidates_v1.json")
        masked = next(c for c in candidates if c.id == "em_reference_masked")
        self.assertGreaterEqual(len(masked.explicit_exclude_ids), 33)
        self.assertGreaterEqual(len(masked.required_include_ids), 40)
        self.assertIn(11370, masked.explicit_exclude_ids)
        self.assertIn(11764, masked.explicit_exclude_ids)

    def test_permission_wording_is_owner_asserted(self) -> None:
        data = json.loads(
            (ROOT / "config/earth3/crop_candidates_v1.json").read_text(encoding="utf-8")
        )
        perm = data["permission"]
        self.assertEqual(perm["status"], "OWNER_ASSERTED_GRANT")
        self.assertIn("signed license instrument", perm["not_present_in_repo"])


class ExactLocationUnitTests(unittest.TestCase):
    def test_gating_key_set_complete(self) -> None:
        expected = {
            "Reykjavik",
            "London",
            "Dublin",
            "Madrid",
            "Lisbon",
            "Paris",
            "Berlin",
            "Rome",
            "Athens",
            "Kyiv",
            "Odesa",
            "Kherson",
            "Zaporizhzhia",
            "Donetsk",
            "Luhansk",
            "Sevastopol",
            "Simferopol",
            "Rostov_on_Don",
            "Istanbul",
            "Ankara",
            "Tbilisi",
            "Yerevan",
            "Baku",
            "Tunis",
            "Algiers",
            "Tripoli",
            "Cairo",
            "Stockholm",
            "Helsinki",
            "Tallinn",
            "Riga",
            "Vilnius",
            "Murmansk",
            "Arkhangelsk",
        }
        self.assertEqual(set(GATING_LOCATION_KEYS), expected)
        self.assertEqual(len(GATING_LOCATION_KEYS), 34)
        # Oslo is informational only.
        oslo = next(loc for loc in REQUIRED_LOCATIONS if loc.key == "Oslo")
        self.assertFalse(oslo.gating)

    def test_validate_rejects_substring_city_match(self) -> None:
        # City named "New London" must not satisfy exact "London".
        loc = next(l for l in REQUIRED_LOCATIONS if l.key == "London")
        ring = (
            (loc.x - 1, loc.y - 1),
            (loc.x + 1, loc.y - 1),
            (loc.x + 1, loc.y + 1),
            (loc.x - 1, loc.y + 1),
        )
        ds = Earth3Dataset(
            provinces={
                loc.source_province_id: Earth3Province(
                    source_id=loc.source_province_id,
                    ring=ring,
                    label_x=loc.x,
                    label_y=loc.y,
                    continent_id=2,
                    terrain_id=1,
                    region_id=0,
                    growth=1.0,
                    base_development=1,
                )
            },
            cities=(
                Earth3City("New London", loc.x, loc.y, loc.source_province_id, 0),
            ),
        )
        report = validate_required_locations(ds, {loc.source_province_id})
        by_key = {row["key"]: row for row in report["locations"]}
        self.assertFalse(by_key["London"]["city_row_found_exact"])
        self.assertFalse(by_key["London"]["ok"])


class CommittedAuditArtifactTests(unittest.TestCase):
    def test_local_audit_artifact_present_and_valid(self) -> None:
        self.assertTrue(
            LOCAL_AUDIT.is_file(),
            "docs/earth3-crop/local_crop_audit.json must be committed",
        )
        report = validate_committed_audit_artifact(
            LOCAL_AUDIT,
            crop_config_path=ROOT / "config/earth3/crop_candidates_v1.json",
            threshold_decisions_path=ROOT
            / "config/earth3/threshold_decisions_em_reference_masked_v1.json",
        )
        if not report["ok"]:
            self.fail(f"audit artifact invalid: {report['errors']}")

    def test_boundary_review_covers_55(self) -> None:
        self.assertTrue(BOUNDARY_JSON.is_file())
        data = json.loads(BOUNDARY_JSON.read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], "gates-of-codex.earth3-boundary-review")
        self.assertGreaterEqual(data["decision_count"], 1)
        self.assertEqual(data["decision_count"], len(data["provinces"]))
        self.assertEqual(data["status"], "pending_owner_visual_approval")
        for row in data["provinces"]:
            self.assertIn("owner_decision", row)
            self.assertEqual(row["owner_review_status"], "pending_owner_visual_approval")
            self.assertIn("boundary_group", row)
            self.assertIn("closeup_image", row)
            self.assertIn("geographic_reason", row)
            self.assertTrue(str(row.get("owner_reason") or row.get("geographic_reason")))
            self.assertNotIn("Owner-approved", str(row.get("owner_reason") or ""))
        by_pid = {int(r["source_province_id"]): r for r in data["provinces"]}
        if 1227 in by_pid:
            self.assertNotEqual(by_pid[1227].get("boundary_group"), "North_African_coast")


@unittest.skipUnless(
    ARCHIVE.is_file(),
    "LOCAL SOURCE REQUIRED: Earth3 archive not available (CI does not ship the archive)",
)
class LiveArchiveCorrectnessTests(unittest.TestCase):
    """These tests require the local uncommitted archive. They do NOT run in CI."""

    @classmethod
    def setUpClass(cls) -> None:
        if not SHAPELY_AVAILABLE:
            raise unittest.SkipTest(
                "LOCAL SOURCE REQUIRED: shapely not installed for authoritative crop"
            )
        from gates_of_codex.earth3.parse import load_earth3_dataset

        cls.dataset = load_earth3_dataset(ARCHIVE)
        cls.candidates = load_crop_candidates(
            ROOT / "config/earth3/crop_candidates_v1.json"
        )
        cls.masked = next(c for c in cls.candidates if c.id == "em_reference_masked")
        cls.result = apply_crop(cls.dataset, cls.masked)

    def test_threshold_review_empty_after_freeze(self) -> None:
        self.assertEqual(self.result.threshold_review_ids, [])

    def test_exact_required_locations(self) -> None:
        report = validate_required_locations(
            self.dataset, set(self.result.included_ids)
        )
        if not report["ok"]:
            self.fail(f"required location failures: {report['failure_keys']}")
        self.assertEqual(report["gating_key_count"], 34)

    def test_oracle_discrepancy_count_zero(self) -> None:
        from gates_of_codex.earth3.geometry import bounds_intersect, ring_bounds

        discrepancies = 0
        flips = 0
        thr = self.masked.inclusion_threshold
        checked = 0
        for pid, province in self.dataset.provinces.items():
            if not self.masked.rect.intersects_bounds(province.bounds):
                continue
            if not any(
                bounds_intersect(province.bounds, ring_bounds(ring))
                for ring in self.masked.mask_rings
            ):
                continue
            checked += 1
            std = overlap_ratio_stdlib(province.ring, self.masked.mask_rings)
            sh = shapely_overlap_ratio(province.ring, self.masked.mask_rings)
            if abs(std - sh) > 1e-3:
                discrepancies += 1
                if (std >= thr) != (sh >= thr):
                    flips += 1
        self.assertGreater(checked, 1000)
        self.assertEqual(discrepancies, 0)
        self.assertEqual(flips, 0)

    def test_final_province_count_matches_audit(self) -> None:
        artifact = json.loads(LOCAL_AUDIT.read_text(encoding="utf-8"))
        self.assertEqual(
            self.result.province_count, artifact["crop_result"]["province_count"]
        )
        self.assertEqual(
            self.result.land_count, artifact["crop_result"]["land_province_count"]
        )
        self.assertEqual(
            self.result.water_count, artifact["crop_result"]["water_province_count"]
        )
        iceland = artifact.get("iceland") or {}
        self.assertTrue(iceland.get("ok"), msg=iceland)
        self.assertEqual(iceland.get("expected_count"), 20)
        self.assertTrue(iceland.get("hofn_included"))
        self.assertTrue(iceland.get("bakkafjordur_included"))
        geom = artifact.get("exclusion_anchor_geometry") or {}
        self.assertTrue(geom.get("ok"), msg=geom.get("failure_names"))
        for row in geom.get("anchors") or []:
            self.assertTrue(row.get("geometry_ok_raw_below_threshold"), msg=row)
            self.assertFalse(row.get("final_included_after_overrides"), msg=row)

    def test_audit_artifact_matches_live_run(self) -> None:
        artifact = json.loads(LOCAL_AUDIT.read_text(encoding="utf-8"))
        self.assertEqual(artifact["schema"], AUDIT_SCHEMA)
        self.assertEqual(artifact["crop_result"]["province_count"], self.result.province_count)
        from gates_of_codex.earth3.audit_artifact import included_ids_hash

        self.assertEqual(
            artifact["crop_result"]["included_ids_sha256"],
            included_ids_hash(self.result.included_ids),
        )
        self.assertEqual(
            artifact["source"]["archive_label"], "LOCAL_UNCOMMITTED_EARTH3_ARCHIVE"
        )


if __name__ == "__main__":
    unittest.main()
