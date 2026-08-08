from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / "tools/opengs_eval/gate1_pipeline.py"

text = PIPELINE.read_text(encoding="utf-8")
start = text.index("    labeled_lakes, lake_count = ndlabel(lake_mask)\n")
end = text.index("    jobs: list[tuple[dict[str, Any], int]] = []\n", start)
replacement = '''    labeled_lakes, lake_count = ndlabel(lake_mask)
    for component in range(1, lake_count + 1):
        component_mask = labeled_lakes == component
        parent_indices = sorted(
            int(value)
            for value in np.unique(territory_pmap[component_mask])
            if int(value) >= 0
        )
        if not parent_indices:
            raise Gate1Error(f"lake component {component} has no containing territory pixels")
        for territory_index in parent_indices:
            parent = territory_by_index.get(territory_index)
            if parent is None or parent["territory_type"] != "land":
                raise Gate1Error(
                    f"lake component {component} intersects invalid parent territory index {territory_index}"
                )
            partition_mask = component_mask & (territory_pmap == territory_index)
            ys, xs = np.where(partition_mask)
            if len(xs) == 0:
                raise Gate1Error(
                    f"lake component {component} has an empty territory partition {territory_index}"
                )
            center_x, center_y = float(xs.mean()), float(ys.mean())
            r, g, b = stable_color(province_index, "lake", used_colors)
            item = {
                "province_id": province_series.get_id(), "province_type": "lake",
                "R": r, "G": g, "B": b, "x": center_x, "y": center_y,
                "territory_id": parent["territory_id"],
                "_pmap_index": province_index, "province_terrain": "lakes",
            }
            province_map[partition_mask] = province_index
            provinces.append(item)
            parent.setdefault("province_ids", []).append(item["province_id"])
            province_index += 1

'''
text = text[:start] + replacement + text[end:]
PIPELINE.write_text(text, encoding="utf-8", newline="\n")
print("Applied Gate 1 lake-to-territory spatial parent authority correction")
