from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGIONS = ROOT / "tools/opengs_eval/gate1_regions.py"
PIPELINE = ROOT / "tools/opengs_eval/gate1_pipeline.py"
DOC = ROOT / "docs/research/opengs-evaluation/gate_1_implementation.md"
PROVENANCE = ROOT / "tools/opengs_eval/gate1_upstream_modules.json"

regions = REGIONS.read_text(encoding="utf-8")
start = regions.index("def largest_remainder(")
end = regions.index("def terrain_name(", start)
replacement = '''def largest_remainder(
    items: Sequence[Mapping[str, Any]],
    total: int,
    weights: Sequence[float],
    *,
    minimums: Sequence[int] | None = None,
) -> list[int]:
    n = len(items)
    if n == 0:
        if total != 0:
            raise Gate1Error(f"cannot allocate {total} regions across zero territories")
        return []
    if len(weights) != n:
        raise Gate1Error("allocation weights do not match territory count")
    lower_bounds = [1] * n if minimums is None else [int(value) for value in minimums]
    if len(lower_bounds) != n or any(value < 1 for value in lower_bounds):
        raise Gate1Error("allocation minimums must provide one positive integer per territory")
    minimum_total = sum(lower_bounds)
    if total < minimum_total:
        raise Gate1Error(
            f"cannot allocate {total} regions across component minimum {minimum_total}"
        )
    total_weight = float(sum(weights))
    if total_weight <= 0:
        weights, total_weight = [1.0] * n, float(n)
    exact = [float(w) / total_weight * total for w in weights]
    allocation = [max(lower_bounds[i], int(math.floor(exact[i]))) for i in range(n)]
    current = sum(allocation)
    if current < total:
        order = sorted(
            range(n),
            key=lambda i: (
                -(exact[i] - math.floor(exact[i])),
                int(items[i]["_pmap_index"]),
            ),
        )
        while current < total:
            for i in order:
                allocation[i] += 1
                current += 1
                if current == total:
                    break
    elif current > total:
        order = sorted(
            range(n),
            key=lambda i: (
                exact[i] - math.floor(exact[i]),
                -allocation[i],
                int(items[i]["_pmap_index"]),
            ),
        )
        while current > total:
            changed = False
            for i in order:
                if allocation[i] > lower_bounds[i]:
                    allocation[i] -= 1
                    current -= 1
                    changed = True
                    if current == total:
                        break
            if not changed:
                raise Gate1Error("allocation could not satisfy component minimums and total")
    return allocation


'''
regions = regions[:start] + replacement + regions[end:]
REGIONS.write_text(regions, encoding="utf-8", newline="\n")

pipeline = PIPELINE.read_text(encoding="utf-8")
old = '''    land_alloc = largest_remainder(land_territories, counts["land_provinces"], land_weights)
    ocean_alloc = largest_remainder(ocean_territories, counts["ocean_provinces"], ocean_weights)
'''
new = '''    def province_component_minimum(territory: dict[str, Any]) -> int:
        territory_index = int(territory["_pmap_index"])
        eligible_mask = (territory_pmap == territory_index) & ~masks["lake_mask"]
        _labels, component_count = ndlabel(eligible_mask)
        component_count = int(component_count)
        if component_count <= 0:
            raise Gate1Error(
                f"territory {territory['territory_id']} has no non-lake province components"
            )
        return component_count

    land_minimums = [province_component_minimum(item) for item in land_territories]
    ocean_minimums = [province_component_minimum(item) for item in ocean_territories]
    land_alloc = largest_remainder(
        land_territories,
        counts["land_provinces"],
        land_weights,
        minimums=land_minimums,
    )
    ocean_alloc = largest_remainder(
        ocean_territories,
        counts["ocean_provinces"],
        ocean_weights,
        minimums=ocean_minimums,
    )
'''
if pipeline.count(old) != 1:
    raise RuntimeError(f"allocation block expected once, found {pipeline.count(old)}")
pipeline = pipeline.replace(old, new, 1)
PIPELINE.write_text(pipeline, encoding="utf-8", newline="\n")

doc = DOC.read_text(encoding="utf-8")
old_doc = "- Allocation uses deterministic largest-remainder logic and must exactly satisfy requested land/ocean territory and province counts.\n"
new_doc = "- Allocation uses deterministic largest-remainder logic with independently measured connected-component lower bounds and must exactly satisfy requested land/ocean territory and province counts.\n"
if doc.count(old_doc) != 1:
    raise RuntimeError(f"documentation allocation line expected once, found {doc.count(old_doc)}")
doc = doc.replace(old_doc, new_doc, 1)
DOC.write_text(doc, encoding="utf-8", newline="\n")

provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))
for relative in sorted(provenance["destination_canonical_utf8_lf_sha256"]):
    path = ROOT / relative
    normalized = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    provenance["destination_canonical_utf8_lf_sha256"][relative] = hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()
PROVENANCE.write_text(
    json.dumps(provenance, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
    newline="\n",
)

print("Applied Gate 1 component-aware exact province allocation correction")
