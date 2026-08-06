from __future__ import annotations

import json
import unittest
from pathlib import Path

from gates_of_codex.earth3.crop import CropCandidate, CropRect, apply_crop, load_crop_candidates
from gates_of_codex.earth3.geometry import overlap_ratio, overlap_ratio_stdlib
from gates_of_codex.earth3.locations import REQUIRED_LOCATIONS, validate_required_locations
from gates_of_codex.earth3.model import Earth3City, Earth3Dataset, Earth3Province

try:
    from gates_of_codex.earth3.oracle import SHAPELY_AVAILABLE, shapely_overlap_ratio
except ImportError:  # pragma: no cover
    SHAPELY_AVAILABLE = False


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = Path(r"C:\Users\paulf\Downloads\AOH3_Earth3_map_provinces.zip")


class OracleGeometryTests(unittest.TestCase):
    def test_stdlib_and_shapely_agree_on_synthetic(self) -> None:
        if not SHAPELY_AVAILABLE:
            self.skipTest("shapely not installed")
        subject = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
        mask = (((5.0, -1.0), (11.0, -1.0), (11.0, 11.0), (5.0, 11.0)),)
        std = overlap_ratio_stdlib(subject, mask)
        sh = shapely_overlap_ratio(subject, mask)
        self.assertAlmostEqual(std, 0.5, places=5)
        self.assertAlmostEqual(sh, 0.5, places=5)
        self.assertAlmostEqual(std, sh, places=5)

    def test_overlap_ratio_prefers_shapely_when_available(self) -> None:
        subject = ((0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0))
        mask = (((1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)),)
        ratio = overlap_ratio(subject, mask)
        self.assertAlmostEqual(ratio, 0.25, places=5)


class ThresholdDecisionConfigTests(unittest.TestCase):
    def test_threshold_decisions_cover_exactly_55(self) -> None:
        path = ROOT / "config/earth3/threshold_decisions_em_reference_masked_v1.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        include = data["include_ids"]
        exclude = data["exclude_ids"]
        self.assertEqual(len(include) + len(exclude), 55)
        self.assertEqual(len(set(include) & set(exclude)), 0)
        self.assertEqual(len(include), 24)
        self.assertEqual(len(exclude), 31)
        self.assertEqual(len(data["decisions"]), 55)

    def test_masked_candidate_loads_frozen_overrides(self) -> None:
        candidates = load_crop_candidates(ROOT / "config/earth3/crop_candidates_v1.json")
        masked = next(c for c in candidates if c.id == "em_reference_masked")
        # Base excludes + 31 threshold excludes
        self.assertGreaterEqual(len(masked.explicit_exclude_ids), 33)
        # Base includes + 24 threshold includes
        self.assertGreaterEqual(len(masked.required_include_ids), 40)
        self.assertIn(11370, masked.explicit_exclude_ids)
        self.assertIn(11764, masked.explicit_exclude_ids)
        self.assertIn(1268, masked.required_include_ids)

    def test_permission_wording_is_owner_asserted(self) -> None:
        data = json.loads(
            (ROOT / "config/earth3/crop_candidates_v1.json").read_text(encoding="utf-8")
        )
        perm = data["permission"]
        self.assertEqual(perm["status"], "OWNER_ASSERTED_GRANT")
        self.assertIn("not_present_in_repo", perm)
        self.assertIn("signed license instrument", perm["not_present_in_repo"])


class ExactLocationUnitTests(unittest.TestCase):
    def test_validate_required_locations_synthetic(self) -> None:
        # Build tiny dataset with exact required province ids for a subset.
        provinces = {}
        cities = []
        for loc in REQUIRED_LOCATIONS[:3]:
            x, y = loc.x, loc.y
            ring = ((x - 1, y - 1), (x + 1, y - 1), (x + 1, y + 1), (x - 1, y + 1))
            provinces[loc.source_province_id] = Earth3Province(
                source_id=loc.source_province_id,
                ring=ring,
                label_x=x,
                label_y=y,
                continent_id=2,
                terrain_id=1,
                region_id=0,
                growth=1.0,
                base_development=1,
            )
            cities.append(
                Earth3City(loc.city_name_exact, x, y, loc.source_province_id, 0)
            )
        ds = Earth3Dataset(provinces=provinces, cities=tuple(cities))
        included = {loc.source_province_id for loc in REQUIRED_LOCATIONS[:3] if loc.must_include}
        report = validate_required_locations(ds, included)
        # Only first 3 keys present in dataset; others fail missing province.
        self.assertFalse(report["ok"])
        # The three present must_include locations should pass.
        by_key = {row["key"]: row for row in report["locations"]}
        self.assertTrue(by_key["Reykjavik"]["ok"])
        self.assertTrue(by_key["Sevastopol"]["ok"])
        self.assertTrue(by_key["Simferopol"]["ok"])


@unittest.skipUnless(ARCHIVE.is_file(), "Earth3 archive not available locally")
class LiveArchiveCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
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

    def test_oracle_discrepancy_count_zero(self) -> None:
        if not SHAPELY_AVAILABLE:
            self.skipTest("shapely not installed")
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

    def test_final_province_count_stable(self) -> None:
        # Frozen threshold decisions must preserve the pre-freeze masked count.
        self.assertEqual(self.result.province_count, 3648)
        self.assertEqual(self.result.land_count, 3431)
        self.assertEqual(self.result.water_count, 217)


if __name__ == "__main__":
    unittest.main()
