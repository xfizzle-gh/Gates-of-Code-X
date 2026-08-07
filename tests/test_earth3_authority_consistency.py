from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "godot/assets/maps/earth3_europe_mediterranean"
AUTH = ROOT / "config/earth3/production_authority.json"
HASH = "a849b3817d98d34e1687c7f7d4899c21f54925fa458cde8b5fe425f6b05206f3"
PRE = "507b0069a9572e915059ff6d21bd9f13a68cf62a26770c94a90c0b0e6a900be7"
GAPS = {"e3_2830", "e3_2888"}


class Earth3AuthorityConsistencyTests(unittest.TestCase):
    def test_all_authority_files_agree_exactly(self) -> None:
        auth = json.loads(AUTH.read_text(encoding="utf-8"))
        meta = json.loads((PROD / "dataset_meta.json").read_text(encoding="utf-8"))
        man = json.loads((PROD / "map_manifest.json").read_text(encoding="utf-8"))
        tri = json.loads((PROD / "triangulation_audit.json").read_text(encoding="utf-8"))
        bh = json.loads((PROD / "black_hole_audit.json").read_text(encoding="utf-8"))
        body = (PROD / "polygon_dataset.json").read_text(encoding="utf-8")
        if body.endswith("\n"):
            body = body[:-1]
        ds = json.loads(body)
        ds_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
        ids = {p["id"] for p in ds["provinces"]}

        self.assertEqual(ds["province_count"], 3510)
        self.assertEqual(len(ds["provinces"]), 3510)
        self.assertEqual(ds["land_count"], 3295)
        self.assertEqual(ds["water_count"], 215)
        self.assertEqual(ds["included_source_ids_sha256"], HASH)
        self.assertEqual(ds.get("pre_sanitize_included_ids_sha256"), PRE)

        for obj, label in ((auth, "auth"), (meta, "meta"), (man, "manifest")):
            self.assertEqual(int(obj.get("province_count") or obj.get("polygon_dataset", {}).get("province_count", 0) or obj["province_count"]), 3510, label)
        self.assertEqual(auth["included_ids_sha256"], HASH)
        self.assertEqual(meta["included_source_ids_sha256"], HASH)
        self.assertEqual(man["included_source_ids_sha256"], HASH)
        self.assertEqual(auth["land_count"], 3295)
        self.assertEqual(auth["water_count"], 215)
        self.assertEqual(auth["selectable_province_count"], 3295)
        self.assertEqual(auth["dataset_sha256"], ds_sha)
        self.assertEqual(meta["dataset_sha256"], ds_sha)
        self.assertEqual(man["polygon_dataset"]["sha256"], ds_sha)

        self.assertEqual(tri["province_count_checked"], 3510)
        self.assertEqual(tri["failed_count"], 0)
        self.assertTrue(tri.get("ok"))
        self.assertEqual(tri.get("empty_mesh_count", 0), 0)
        self.assertNotIn("e3_2830", ids)
        self.assertNotIn("e3_2888", ids)
        self.assertTrue(bh.get("ok"))
        self.assertEqual(bh.get("failed_empty_meshes", 0), 0)

        # fixtures/snapshots must not reference excluded gameplay gaps as present provinces
        for path in (ROOT / "godot/fixtures").rglob("*.json"):
            text = path.read_text(encoding="utf-8")
            for gap in GAPS:
                self.assertNotIn(gap, text, f"{path} still references {gap}")

        # profiler post-topology report must claim 3510 authority
        rep = (ROOT / "docs/godot-presentation/earth3_interactive_baseline_post_topology.md").read_text(encoding="utf-8")
        self.assertIn("**3510**", rep)
        self.assertIn(HASH, rep)
        self.assertIn("Historical comparison authority", rep)
        # must not claim measured authority is 3512
        self.assertNotIn("| provinces | 3512 |", rep.split("Historical comparison")[0])


if __name__ == "__main__":
    unittest.main()
