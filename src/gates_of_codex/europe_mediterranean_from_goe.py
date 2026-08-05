from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .europe import build_goe_europe_campaign
from .models import CampaignState, Faction
from .strategic import ensure_strategic_layer
from .strategic_map import decode_png_rgb, import_strategic_map, write_png_rgb


MAP_ID = "europe_mediterranean_from_goe"
DEFAULT_OUTPUT_DIR = "godot/assets/maps/europe_mediterranean/from_goe"
INTERIM_DIR = Path("godot/assets/maps/europe/interim_goe")

# Playable marker-space theatre (y increases north).
# Tuned to red-box Europe–Med operational frame (not oversized regional canvas).
MARKER_THEATRE = {
    "x_min": -4.0,
    "x_max": 3.0,
    "y_min": -0.95,  # general south cutoff; FORCE_INCLUDE pulls coastal N Africa
    "y_max": 6.0,  # Scandinavia / far north
}

# Frozen red-box display frame (source pixels). Never expanded by force-includes.
FROZEN_DISPLAY_CROP = {
    "x0": 206,
    "y0": 47,
    "width": 817,
    "height": 920,
}

# Coastal Maghreb / Egypt / Levant always playable when present.
FORCE_INCLUDE_COASTAL_PROVINCE_IDS: frozenset[str] = frozenset(
    {
        "province_0101",  # Casablanca
        "province_0111",  # Spanish Africa
        "province_0114",  # Algiers
        "province_0117",  # Constantine
        "province_0112",  # Tunis
        "province_0095",  # Gabes
        "province_0097",  # Tripoli
        "province_0089",  # Tripolitania
        "province_0098",  # Benghasi
        "province_0091",  # Cyrenaica
        "province_0099",  # Derna
        "province_0094",  # Alexandria
        "province_0079",  # Cairo
        "province_0086",  # Suez
        "province_0078",  # Sinai
        "province_0090",  # Palestine
        "province_0107",  # Lebanon
        "province_0102",  # Syria
        "province_0110",  # Aleppo
        "province_0113",  # Cyprus
        "province_0085",  # Sirte (coast)
        "province_0087",  # Matrouh (coast approach)
        "province_0093",  # El Agheila (coast approach)
    }
)

# Important edge provinces restored by ID (not x/y thresholds). Geometry is
# clipped to FROZEN_DISPLAY_CROP — must not expand the canvas.
FORCE_INCLUDE_STRATEGIC_PROVINCES: dict[str, str] = {
    "province_0156": "Lisbon",
    "province_0408": "Moscow",
    "province_0384": "Tula",
    "province_0284": "Donetsk",  # historical Stalino
    "province_0327": "Luhansk",  # historical Voroshilovgrad
    "province_0126": "Malatya",
    "province_0143": "Sivas",
    "province_0502": "Salla",
    # North Scandinavia land-bridge (Sweden/Norway ↔ Finland via Lappi corridor).
    "province_0500": "Tornedalen",
    "province_0501": "Lappi",
    "province_0504": "Norrbotten",
    # Full island of Ireland (raster component; not marker-window only).
    "province_0370": "Munster",
    "province_0382": "Leinster",
    "province_0394": "Connacht",
    "province_0409": "Northern Ireland",
    "province_0417": "Ulster West",
}

FORCE_INCLUDE_PROVINCE_IDS: frozenset[str] = frozenset(
    set(FORCE_INCLUDE_COASTAL_PROVINCE_IDS) | set(FORCE_INCLUDE_STRATEGIC_PROVINCES)
)

DISPLAY_NAME_OVERRIDES: dict[str, str] = dict(FORCE_INCLUDE_STRATEGIC_PROVINCES)

# Seed province for Ireland land-component detection in the source raster.
IRELAND_COMPONENT_SEED = "province_0409"

# Explicit allowlist of intentionally isolated playable components (by label).
# Empty by default — islands must have authored crossings.
INTENTIONALLY_ISOLATED_COMPONENTS: frozenset[str] = frozenset()

# Deep interior Africa — never playable (may still be visual land).
FORCE_EXCLUDE_PROVINCE_IDS: frozenset[str] = frozenset(
    {
        "province_0066",  # Western Desert
        "province_0081",  # Fezzan
        "province_0103",  # Algerian Desert
        "province_0080",  # Marrakech
        "province_0062",
        "province_0072",
        "province_0083",  # Jordan interior
        "province_0084",
        "province_0077",
        "Aswan",
    }
)

# Display crop padding from playable land bbox only (no deep-Africa expansion).
# Matches tighter red-box theatre framing.
DISPLAY_EXPAND = {
    "north": 0.10,  # room for Scandinavia
    "south": 0.02,  # thin margin below Maghreb/Egypt coastal belt
    "west": 0.03,
    "east": 0.03,
}

MIN_PLAYABLE_PIXELS = 12
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
SEPARATOR_FILL_ITERS = 3

# (left, right, crossing_type) — exact type is preserved on both endpoints.
AUTHED_CROSSINGS: tuple[tuple[str, str, str], ...] = (
    # English Channel
    ("province_0365", "province_0329", "ferry_or_sea_lane"),
    ("Sussex", "province_0329", "ferry_or_sea_lane"),
    # Denmark ↔ Zealand ↔ Sweden
    ("Schleswig", "province_0419", "ferry_or_sea_lane"),
    ("Holstein", "province_0419", "ferry_or_sea_lane"),
    ("province_0419", "province_0421", "strait"),  # Oresund: Sjaelland ↔ Skane
    # Ireland ↔ Britain (no land edges)
    ("province_0409", "province_0420", "ferry_or_sea_lane"),  # NI ↔ SW Scotland
    ("province_0370", "province_0367", "ferry_or_sea_lane"),  # Munster/east IE ↔ Wales
    # Mediterranean / Black Sea straits and short ferries
    ("province_0127", "province_0139", "strait"),  # Sicily ↔ Calabria
    ("province_0179", "province_0173", "strait"),  # Bosporus
    ("province_0179", "province_0177", "strait"),
    ("province_0111", "province_0123", "strait"),  # Gibraltar: Spanish Africa ↔ Andalusia
    ("province_0127", "province_0112", "ferry_or_sea_lane"),  # Sicily ↔ Tunis
    ("province_0115", "province_0167", "ferry_or_sea_lane"),  # Crete ↔ Peloponnese
    ("province_0113", "province_0107", "ferry_or_sea_lane"),  # Cyprus ↔ Lebanon
    ("province_0151", "province_0192", "ferry_or_sea_lane"),  # Sardinia ↔ Corsica
    ("province_0192", "province_0215", "ferry_or_sea_lane"),  # Corsica ↔ Provence
    ("province_0155", "province_0141", "ferry_or_sea_lane"),  # Balearics ↔ Valencia
    ("province_0234", "province_0265", "strait"),  # Crimea ↔ Kherson
    ("province_0455", "province_0465", "ferry_or_sea_lane"),  # Saaremaa ↔ Harju
    ("province_0415", "province_0412", "ferry_or_sea_lane"),  # Danish island ↔ Jutland coast
    ("province_0441", "province_0436", "ferry_or_sea_lane"),  # Baltic island ↔ S. Sweden
)

CROSSING_META: dict[str, dict] = {
    "strait": {
        "movement_cost_multiplier": 1.25,
        "requires_port": False,
        "can_be_blockaded": True,
        "bidirectional": True,
    },
    "ferry": {
        "movement_cost_multiplier": 1.5,
        "requires_port": True,
        "can_be_blockaded": True,
        "bidirectional": True,
    },
    "ferry_or_sea_lane": {
        "movement_cost_multiplier": 1.5,
        "requires_port": True,
        "can_be_blockaded": True,
        "bidirectional": True,
    },
    "sea_lane": {
        "movement_cost_multiplier": 2.0,
        "requires_port": True,
        "can_be_blockaded": True,
        "bidirectional": True,
    },
}

# Max water gap (source pixels) when proposing nearest-coast candidates (not auto-committed).
CROSSING_CANDIDATE_MAX_GAP_PX = 48

EXCLUDES = [
    "deep Central Asia",
    "deep Sahara as playable geography",
    "far Atlantic / Americas filler",
]


def _load_interim() -> tuple[dict, object]:
    manifest_path = INTERIM_DIR / "map_manifest.json"
    texture_path = INTERIM_DIR / "province_id_map.png"
    if not manifest_path.is_file() or not texture_path.is_file():
        raise FileNotFoundError(f"Interim GoE assets missing under {INTERIM_DIR}")
    return json.loads(manifest_path.read_text(encoding="utf-8")), decode_png_rgb(texture_path)


def discover_ireland_province_ids(
    province_table: list[dict],
    image,
) -> list[str]:
    """Return every source province color on the Ireland landmass (seed = NI)."""
    by_id = {str(row["province_id"]): row for row in province_table}
    seed = by_id.get(IRELAND_COMPONENT_SEED)
    if seed is None:
        return []
    seed_rgb = tuple(int(c) for c in seed["rgb"])
    color_to_pid = {
        tuple(int(c) for c in row["rgb"]): str(row["province_id"]) for row in province_table
    }
    seeds: list[tuple[int, int]] = []
    for y in range(image.height):
        for x in range(image.width):
            if image.color_at(x, y) == seed_rgb:
                seeds.append((x, y))
    if not seeds:
        return [IRELAND_COMPONENT_SEED]
    from collections import deque

    seen: set[tuple[int, int]] = set(seeds)
    q = deque(seeds)
    colors: set[tuple[int, int, int]] = {seed_rgb}
    while q:
        x, y = q.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if nx < 0 or ny < 0 or nx >= image.width or ny >= image.height:
                continue
            if (nx, ny) in seen:
                continue
            color = image.color_at(nx, ny)
            if color == WHITE:
                continue
            seen.add((nx, ny))
            q.append((nx, ny))
            if color != BLACK:
                colors.add(color)
    ids = sorted({color_to_pid[c] for c in colors if c in color_to_pid})
    return ids


def select_playable_provinces(
    province_table: list[dict],
    *,
    ireland_ids: frozenset[str] | None = None,
) -> tuple[list[dict], dict]:
    by_id = {str(row["province_id"]): row for row in province_table}
    selected: dict[str, dict] = {}
    marker_bound = 0
    for row in province_table:
        pid = str(row["province_id"])
        if pid in FORCE_EXCLUDE_PROVINCE_IDS:
            continue
        ax, ay = row.get("marker_anchor") or [0.0, 0.0]
        x, y = float(ax), float(ay)
        if (
            MARKER_THEATRE["x_min"] <= x <= MARKER_THEATRE["x_max"]
            and MARKER_THEATRE["y_min"] <= y <= MARKER_THEATRE["y_max"]
        ):
            selected[pid] = row
            marker_bound += 1

    forced_in = []
    include_ids = set(FORCE_INCLUDE_PROVINCE_IDS)
    if ireland_ids:
        include_ids |= set(ireland_ids)
    for pid in sorted(include_ids):
        row = by_id.get(pid)
        if row is None or pid in FORCE_EXCLUDE_PROVINCE_IDS:
            continue
        if pid not in selected:
            if pid in FORCE_INCLUDE_STRATEGIC_PROVINCES:
                reason = "force_include_strategic_edge"
                name = FORCE_INCLUDE_STRATEGIC_PROVINCES[pid]
            elif ireland_ids and pid in ireland_ids:
                reason = "force_include_ireland_landmass"
                name = str(
                    DISPLAY_NAME_OVERRIDES.get(pid, row.get("display_name", pid))
                )
            else:
                reason = "force_include_mediterranean_coastal"
                name = str(row.get("display_name", pid))
            forced_in.append(
                {
                    "province_id": pid,
                    "display_name": name,
                    "reason": reason,
                }
            )
        selected[pid] = row

    # Far-north playable expansion: any non-excluded province whose marker is
    # in the northern band of the expanded theatre.
    scandi_added = []
    for row in province_table:
        pid = str(row["province_id"])
        if pid in selected or pid in FORCE_EXCLUDE_PROVINCE_IDS:
            continue
        ax, ay = row.get("marker_anchor") or [0.0, 0.0]
        x, y = float(ax), float(ay)
        if not (
            MARKER_THEATRE["x_min"] <= x <= MARKER_THEATRE["x_max"]
            and 3.8 <= y <= MARKER_THEATRE["y_max"]
        ):
            continue
        selected[pid] = row
        scandi_added.append(
            {
                "province_id": pid,
                "display_name": str(row.get("display_name", pid)),
                "reason": "scandinavia_north_expansion",
                "marker_y": y,
            }
        )

    forced_out = []
    for pid in sorted(FORCE_EXCLUDE_PROVINCE_IDS):
        row = selected.pop(pid, None)
        if row is not None:
            forced_out.append(
                {
                    "province_id": pid,
                    "display_name": str(row.get("display_name", pid)),
                    "reason": "force_exclude_deep_interior",
                }
            )

    kept = list(selected.values())
    if len(kept) < 80:
        raise RuntimeError(f"Playable theatre too small: {len(kept)}")
    report = {
        "marker_bound_count": marker_bound,
        "force_included": forced_in,
        "force_excluded": forced_out,
        "scandinavia_added": scandi_added,
        "final_playable_count": len(kept),
        "force_include_ids": sorted(FORCE_INCLUDE_PROVINCE_IDS),
        "force_exclude_ids": sorted(FORCE_EXCLUDE_PROVINCE_IDS),
    }
    return kept, report


def _province_pixel_stats(image) -> dict[tuple[int, int, int], dict]:
    stats: dict[tuple[int, int, int], dict] = {}
    for y in range(image.height):
        for x in range(image.width):
            color = image.color_at(x, y)
            if color in (BLACK, WHITE):
                continue
            row = stats.get(color)
            if row is None:
                row = {
                    "count": 0,
                    "sx": 0.0,
                    "sy": 0.0,
                    "min_x": x,
                    "max_x": x,
                    "min_y": y,
                    "max_y": y,
                }
                stats[color] = row
            row["count"] += 1
            row["sx"] += x
            row["sy"] += y
            row["min_x"] = min(row["min_x"], x)
            row["max_x"] = max(row["max_x"], x)
            row["min_y"] = min(row["min_y"], y)
            row["max_y"] = max(row["max_y"], y)
    for row in stats.values():
        n = max(row["count"], 1)
        row["cx"] = row["sx"] / n
        row["cy"] = row["sy"] / n
    return stats


def _fit_marker_to_pixel(
    province_table: list[dict],
    color_stats: dict[tuple[int, int, int], dict],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    pairs: list[tuple[float, float, float, float]] = []
    for row in province_table:
        color = tuple(int(c) for c in row.get("rgb", []))
        stat = color_stats.get(color)
        if stat is None or stat["count"] < 8:
            continue
        ax, ay = row.get("marker_anchor") or [0.0, 0.0]
        pairs.append((float(ax), float(ay), float(stat["cx"]), float(stat["cy"])))
    if len(pairs) < 8:
        raise RuntimeError("Not enough provinces to fit marker→pixel map")

    def fit_axis(sa: list[float], sb: list[float], dst: list[float]) -> tuple[float, float, float]:
        n = float(len(dst))
        a = sum(sa)
        b = sum(sb)
        d = sum(dst)
        aa = sum(x * x for x in sa)
        bb = sum(x * x for x in sb)
        ab = sum(x * y for x, y in zip(sa, sb))
        ad = sum(x * y for x, y in zip(sa, dst))
        bd = sum(x * y for x, y in zip(sb, dst))
        m = [[aa, ab, a, ad], [ab, bb, b, bd], [a, b, n, d]]
        for col in range(3):
            pivot = max(range(col, 3), key=lambda r: abs(m[r][col]))
            m[col], m[pivot] = m[pivot], m[col]
            div = m[col][col] or 1e-12
            for j in range(col, 4):
                m[col][j] /= div
            for ri in range(3):
                if ri == col:
                    continue
                factor = m[ri][col]
                for j in range(col, 4):
                    m[ri][j] -= factor * m[col][j]
        return m[0][3], m[1][3], m[2][3]

    return (
        fit_axis([p[0] for p in pairs], [p[1] for p in pairs], [p[2] for p in pairs]),
        fit_axis([p[0] for p in pairs], [p[1] for p in pairs], [p[3] for p in pairs]),
    )


def _m2p(mx: float, my: float, xm, ym) -> tuple[float, float]:
    p, q, r = xm
    s, t, u = ym
    return p * mx + q * my + r, s * mx + t * my + u


def _land_connected_components(land_neighbors: dict[str, list[str]], active_ids: set[str]) -> list[list[str]]:
    seen: set[str] = set()
    comps: list[list[str]] = []
    for pid in sorted(active_ids):
        if pid in seen:
            continue
        stack = [pid]
        seen.add(pid)
        comp: list[str] = []
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for nxt in land_neighbors.get(cur, []):
                if nxt in active_ids and nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        comps.append(sorted(comp))
    comps.sort(key=len, reverse=True)
    return comps


def _component_label(comp: list[str], by_name: dict[str, str]) -> str:
    names = " ".join(by_name.get(pid, pid) for pid in comp).lower()
    ids = set(comp)
    if IRELAND_COMPONENT_SEED in ids or "northern ireland" in names:
        return "ireland"
    if any(k in names for k in ("london", "wales", "scotland", "midlands", "yorkshire", "sussex")):
        return "great_britain"
    if any(k in names for k in ("sjaelland", "zealand")) and len(comp) <= 4:
        return "zealand"
    if any(k in names for k in ("oslo", "sodermalm", "stockholm")) and len(comp) < 80:
        return "scandinavia_west"
    if "sicillia" in names or "sicily" in names:
        return "sicily"
    if "sardegna" in names or "sardinia" in names:
        return "sardinia"
    if "corsica" in names:
        return "corsica"
    if "crete" in names:
        return "crete"
    if "cyprus" in names:
        return "cyprus"
    if "baleares" in names or "balear" in names:
        return "balearics"
    if "crimea" in names:
        return "crimea"
    if "saaremaa" in names:
        return "saaremaa"
    if "cairo" in names or "algiers" in names or "casablanca" in names:
        return "north_africa_near_east"
    if len(comp) >= 80:
        return "mainland_europe"
    if len(comp) == 1:
        return f"singleton:{by_name.get(comp[0], comp[0])}"
    return f"component:{by_name.get(comp[0], comp[0])}"


def propose_nearest_coast_crossings(
    *,
    owners: list[int],
    index_pid: dict[int, str],
    crop_w: int,
    crop_h: int,
    components: list[list[str]],
    max_gap_px: int = CROSSING_CANDIDATE_MAX_GAP_PX,
) -> list[dict]:
    """Deterministic candidate proposer. Never auto-commits gameplay edges."""
    pid_comp: dict[str, int] = {}
    for i, comp in enumerate(components):
        for pid in comp:
            pid_comp[pid] = i
    # Shoreline pixels: playable land with a water (owner < 0) 4-neighbor.
    shores: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for y in range(crop_h):
        for x in range(crop_w):
            a = owners[y * crop_w + x]
            if a < 0:
                continue
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if nx < 0 or ny < 0 or nx >= crop_w or ny >= crop_h:
                    continue
                if owners[ny * crop_w + nx] < 0:
                    shores[a].append((x, y))
                    break
    # Downsample shores for speed.
    sample: dict[int, list[tuple[int, int]]] = {}
    for idx, pts in shores.items():
        step = max(1, len(pts) // 80)
        sample[idx] = pts[::step][:80]
    candidates: list[dict] = []
    idxs = sorted(sample)
    for i, ai in enumerate(idxs):
        for bi in idxs[i + 1 :]:
            ca = pid_comp.get(index_pid[ai], -1)
            cb = pid_comp.get(index_pid[bi], -1)
            if ca < 0 or cb < 0 or ca == cb:
                continue
            best = None
            for ax, ay in sample[ai]:
                for bx, by in sample[bi]:
                    dist = abs(ax - bx) + abs(ay - by)
                    if dist <= 1 or dist > max_gap_px:
                        continue
                    # segment must be mostly water
                    steps = max(dist, 1)
                    water = 0
                    total = 0
                    for s in range(1, steps):
                        t = s / steps
                        x = int(round(ax + (bx - ax) * t))
                        y = int(round(ay + (by - ay) * t))
                        if x < 0 or y < 0 or x >= crop_w or y >= crop_h:
                            continue
                        total += 1
                        if owners[y * crop_w + x] < 0:
                            water += 1
                    if total == 0 or water / total < 0.75:
                        continue
                    if best is None or dist < best[0]:
                        best = (dist, ax, ay, bx, by, water, total)
            if best is None:
                continue
            dist, ax, ay, bx, by, water, total = best
            candidates.append(
                {
                    "a": index_pid[ai],
                    "b": index_pid[bi],
                    "gap_px": int(dist),
                    "water_fraction": round(water / max(total, 1), 3),
                    "shore_a": [ax, ay],
                    "shore_b": [bx, by],
                    "status": "candidate_only_not_committed",
                    "components": [ca, cb],
                }
            )
    candidates.sort(key=lambda row: (row["gap_px"], row["a"], row["b"]))
    return candidates[:80]


def _close_visual_land_mask(mask: list[bool], w: int, h: int) -> list[bool]:
    """Remove internal province-separator cracks without flooding open ocean.

    1) Morphological close (dilate then erode) seals thin black separators.
    2) Flood-fill from border through non-land; remaining non-land pockets are
       interior holes and become land (continuous silhouette).
    """

    def dilate(src: list[bool]) -> list[bool]:
        out = list(src)
        for y in range(h):
            for x in range(w):
                if src[y * w + x]:
                    continue
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if 0 <= nx < w and 0 <= ny < h and src[ny * w + nx]:
                        out[y * w + x] = True
                        break
        return out

    def erode(src: list[bool]) -> list[bool]:
        out = list(src)
        for y in range(h):
            for x in range(w):
                if not src[y * w + x]:
                    continue
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if nx < 0 or ny < 0 or nx >= w or ny >= h or not src[ny * w + nx]:
                        out[y * w + x] = False
                        break
        return out

    closed = mask
    for _ in range(3):
        closed = dilate(closed)
    for _ in range(3):
        closed = erode(closed)

    # Exterior = non-land reachable from image border.
    exterior = [False] * (w * h)
    stack: list[int] = []
    for x in range(w):
        for y in (0, h - 1):
            idx = y * w + x
            if not closed[idx] and not exterior[idx]:
                exterior[idx] = True
                stack.append(idx)
    for y in range(h):
        for x in (0, w - 1):
            idx = y * w + x
            if not closed[idx] and not exterior[idx]:
                exterior[idx] = True
                stack.append(idx)
    while stack:
        idx = stack.pop()
        x = idx % w
        y = idx // w
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if nx < 0 or ny < 0 or nx >= w or ny >= h:
                continue
            nidx = ny * w + nx
            if closed[nidx] or exterior[nidx]:
                continue
            exterior[nidx] = True
            stack.append(nidx)

    out = list(closed)
    for i, is_land in enumerate(closed):
        if not is_land and not exterior[i]:
            out[i] = True  # interior hole → continuous land
    return out


def generate_europe_mediterranean_from_goe(
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    pad_px: int = 8,
) -> dict:
    """Build expanded theatre with separate visual land vs playable color-ID."""

    manifest, image = _load_interim()
    source_table = list(manifest.get("province_table", []))
    color_stats = _province_pixel_stats(image)
    xm, ym = _fit_marker_to_pixel(source_table, color_stats)
    color_to_row = {tuple(int(c) for c in row["rgb"]): row for row in source_table}
    all_land_colors = set(color_stats)

    ireland_ids = frozenset(discover_ireland_province_ids(source_table, image))
    playable_rows, selection_report = select_playable_provinces(
        source_table, ireland_ids=ireland_ids
    )
    selection_report["ireland_landmass_province_ids"] = sorted(ireland_ids)
    playable_ids = {str(r["province_id"]) for r in playable_rows}
    playable_colors = {tuple(int(c) for c in r["rgb"]) for r in playable_rows}

    # Locked red-box frame — force-includes clip into this, never expand it.
    min_x = int(FROZEN_DISPLAY_CROP["x0"])
    min_y = int(FROZEN_DISPLAY_CROP["y0"])
    crop_w = int(FROZEN_DISPLAY_CROP["width"])
    crop_h = int(FROZEN_DISPLAY_CROP["height"])
    max_x = min_x + crop_w - 1
    max_y = min_y + crop_h - 1
    if max_x >= image.width or max_y >= image.height or min_x < 0 or min_y < 0:
        raise RuntimeError(
            f"Frozen crop {FROZEN_DISPLAY_CROP} outside source {image.width}x{image.height}"
        )
    _ = pad_px  # retained for API compat; crop is frozen

    # Visual land = any source land color inside frozen frame (map-art silhouette).
    visual_mask = [False] * (crop_w * crop_h)
    cosmetic_ids: list[dict] = []
    cosmetic_seen: set[str] = set()
    for y in range(crop_h):
        for x in range(crop_w):
            color = image.color_at(min_x + x, min_y + y)
            if color == WHITE or color == BLACK or color not in all_land_colors:
                continue
            visual_mask[y * crop_w + x] = True
            row = color_to_row.get(color)
            if row is None:
                continue
            pid = str(row["province_id"])
            if pid not in playable_ids and pid not in cosmetic_seen:
                cosmetic_seen.add(pid)
                cosmetic_ids.append(
                    {
                        "province_id": pid,
                        "display_name": str(
                            DISPLAY_NAME_OVERRIDES.get(pid, row.get("display_name", pid))
                        ),
                        "role": "visual_background_only",
                    }
                )

    # Close internal separator cracks: morph-close + fill holes not connected to border.
    before_close = sum(1 for v in visual_mask if v)
    visual_mask = _close_visual_land_mask(visual_mask, crop_w, crop_h)
    visual_separators_closed = sum(1 for v in visual_mask if v) - before_close

    # --- playable ID grid ---
    playable_grid: list[tuple[int, int, int]] = [BLACK] * (crop_w * crop_h)
    pixel_counts: dict[str, int] = defaultdict(int)
    full_counts = {
        str(color_to_row[c]["province_id"]): int(color_stats[c]["count"])
        for c in playable_colors
        if c in color_stats
    }
    playable_by_color = {tuple(int(c) for c in r["rgb"]): r for r in playable_rows}
    for y in range(crop_h):
        for x in range(crop_w):
            color = image.color_at(min_x + x, min_y + y)
            if color in playable_colors:
                playable_grid[y * crop_w + x] = color
                pixel_counts[str(playable_by_color[color]["province_id"])] += 1

    # Dilate playable provinces into black separators only (not into white exterior).
    separators_filled = 0
    for _ in range(SEPARATOR_FILL_ITERS):
        claims: list[tuple[int, int, tuple[int, int, int]]] = []
        for y in range(crop_h):
            for x in range(crop_w):
                idx = y * crop_w + x
                if playable_grid[idx] != BLACK:
                    continue
                # Only dilate over original black separator, not open water outside land mask
                # unless it's between playable provinces (visual land can guide).
                src = image.color_at(min_x + x, min_y + y)
                if src == WHITE:
                    continue
                cands: list[tuple[str, tuple[int, int, int]]] = []
                seen: set[str] = set()
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if nx < 0 or ny < 0 or nx >= crop_w or ny >= crop_h:
                        continue
                    cand = playable_grid[ny * crop_w + nx]
                    if cand == BLACK or cand not in playable_colors:
                        continue
                    pid = str(playable_by_color[cand]["province_id"])
                    if pid in seen:
                        continue
                    seen.add(pid)
                    cands.append((pid, cand))
                if not cands:
                    continue
                cands.sort(key=lambda item: item[0])
                claims.append((x, y, cands[0][1]))
        if not claims:
            break
        for x, y, color in claims:
            idx = y * crop_w + x
            if playable_grid[idx] != BLACK:
                continue
            playable_grid[idx] = color
            pixel_counts[str(playable_by_color[color]["province_id"])] += 1
            separators_filled += 1

    # Drop tiny playable remnants.
    active_rows: list[dict] = []
    dropped_tiny: list[dict] = []
    scandi_report = []
    for row in playable_rows:
        pid = str(row["province_id"])
        kept = pixel_counts.get(pid, 0)
        full = max(full_counts.get(pid, 0), 1)
        if kept < MIN_PLAYABLE_PIXELS:
            dropped_tiny.append(
                {
                    "province_id": pid,
                    "display_name": str(row.get("display_name", pid)),
                    "pixels_kept": kept,
                }
            )
            continue
        entry = dict(row)
        active_rows.append(entry)
        if any(s["province_id"] == pid for s in selection_report.get("scandinavia_added", [])):
            scandi_report.append(
                {
                    "province_id": pid,
                    "display_name": str(row.get("display_name", pid)),
                    "pixel_area": kept,
                }
            )

    active_ids = {str(r["province_id"]) for r in active_rows}
    active_colors = {tuple(int(c) for c in r["rgb"]) for r in active_rows}
    # Erase dropped playable colors.
    drop_colors = {
        tuple(int(c) for c in r["rgb"])
        for r in playable_rows
        if str(r["province_id"]) not in active_ids
    }
    for idx, color in enumerate(playable_grid):
        if color in drop_colors:
            playable_grid[idx] = BLACK

    # Pack playable ID texture + rebuild stats.
    id_bytes = bytearray(crop_w * crop_h * 3)
    owners = [-1] * (crop_w * crop_h)
    pid_index = {pid: i for i, pid in enumerate(sorted(active_ids))}
    index_pid = {i: pid for pid, i in pid_index.items()}
    color_to_pid = {tuple(int(c) for c in r["rgb"]): str(r["province_id"]) for r in active_rows}
    sums: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    pixels_by_pid: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for y in range(crop_h):
        for x in range(crop_w):
            idx = y * crop_w + x
            color = playable_grid[idx]
            base = idx * 3
            id_bytes[base : base + 3] = bytes(color)
            pid = color_to_pid.get(color)
            if pid is None:
                continue
            owners[idx] = pid_index[pid]
            sums[pid][0] += x
            sums[pid][1] += y
            sums[pid][2] += 1
            pixels_by_pid[pid].append((x, y))

    # Direct-contact land adjacency.
    land_edges: set[tuple[str, str]] = set()
    for y in range(crop_h):
        for x in range(crop_w):
            a = owners[y * crop_w + x]
            if a < 0:
                continue
            for nx, ny in ((x + 1, y), (x, y + 1)):
                if nx >= crop_w or ny >= crop_h:
                    continue
                b = owners[ny * crop_w + nx]
                if b >= 0 and b != a:
                    land_edges.add(tuple(sorted((index_pid[a], index_pid[b]))))
    land_neighbors: dict[str, list[str]] = defaultdict(list)
    for a, b in sorted(land_edges):
        land_neighbors[a].append(b)
        land_neighbors[b].append(a)

    # Preserve exact authored crossing types per directed endpoint pair.
    authored_edge_types: dict[str, dict[str, str]] = defaultdict(dict)
    authored_edges: list[dict] = []
    for left, right, etype in AUTHED_CROSSINGS:
        if left not in active_ids or right not in active_ids:
            continue
        key = tuple(sorted((left, right)))
        if key in land_edges:
            continue
        meta = dict(CROSSING_META.get(etype, CROSSING_META["ferry_or_sea_lane"]))
        authored_edges.append(
            {
                "a": key[0],
                "b": key[1],
                "type": etype,
                "crossing_type": etype,
                **meta,
            }
        )
        authored_edge_types[left][right] = etype
        authored_edge_types[right][left] = etype

    # Land-only connected components + nearest-coast candidates (review only).
    components = _land_connected_components(land_neighbors, active_ids)
    by_display = {
        str(r["province_id"]): str(
            DISPLAY_NAME_OVERRIDES.get(str(r["province_id"]), r.get("display_name", r["province_id"]))
        )
        for r in active_rows
    }
    component_report = []
    for comp in components:
        label = _component_label(comp, by_display)
        component_report.append(
            {
                "label": label,
                "size": len(comp),
                "province_ids": comp,
                "display_names": [by_display[p] for p in comp],
            }
        )
    crossing_candidates = propose_nearest_coast_crossings(
        owners=owners,
        index_pid=index_pid,
        crop_w=crop_w,
        crop_h=crop_h,
        components=components,
    )

    def snap(pid: str, cx: float, cy: float) -> tuple[float, float, bool]:
        ix, iy = int(round(cx)), int(round(cy))
        if 0 <= ix < crop_w and 0 <= iy < crop_h and owners[iy * crop_w + ix] == pid_index[pid]:
            return float(ix), float(iy), False
        best = min(
            pixels_by_pid[pid],
            key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2,
        )
        return float(best[0]), float(best[1]), True

    table = []
    snapped = 0
    for row in sorted(active_rows, key=lambda r: str(r["province_id"])):
        pid = str(row["province_id"])
        n = max(int(sums[pid][2]), 1)
        cx, cy = sums[pid][0] / n, sums[pid][1] / n
        ax, ay, did = snap(pid, cx, cy)
        if did:
            snapped += 1
        land = sorted(set(land_neighbors.get(pid, [])))
        auth_types = dict(authored_edge_types.get(pid, {}))
        auth = sorted(auth_types)
        display_name = DISPLAY_NAME_OVERRIDES.get(pid, row.get("display_name", pid))
        human = bool(row.get("name_is_human_readable", True)) or pid in DISPLAY_NAME_OVERRIDES
        edge_types = {n: "land" for n in land}
        edge_meta: dict[str, dict] = {}
        for n, etype in auth_types.items():
            edge_types[n] = etype
            edge_meta[n] = {
                "crossing_type": etype,
                **dict(CROSSING_META.get(etype, CROSSING_META["ferry_or_sea_lane"])),
            }
        table.append(
            {
                "province_id": pid,
                "display_name": display_name,
                "name_is_human_readable": human,
                "rgb": list(row["rgb"]),
                "marker_anchor": [float(ax), float(crop_h - 1 - ay)],
                "source_neighbors": sorted(set(land) | set(auth)),
                "land_neighbors": land,
                "edge_types": edge_types,
                "edge_meta": edge_meta,
                "source_province_id": row.get("source_province_id", pid),
                "mapping_method": "goe_theatre_playable",
                "provenance": {
                    "generator": "europe_mediterranean_from_goe_v7_topology",
                    "pixels": int(sums[pid][2]),
                    "anchor_snapped": did,
                    "clipped_to_frozen_frame": pid in FORCE_INCLUDE_STRATEGIC_PROVINCES
                    or pid in ireland_ids,
                },
            }
        )

    for row in table:
        ax = int(round(row["marker_anchor"][0]))
        ay = crop_h - 1 - int(round(row["marker_anchor"][1]))
        color = (
            id_bytes[(ay * crop_w + ax) * 3],
            id_bytes[(ay * crop_w + ax) * 3 + 1],
            id_bytes[(ay * crop_w + ax) * 3 + 2],
        )
        if color_to_pid.get(color) != row["province_id"]:
            raise RuntimeError(f"Anchor outside province {row['province_id']}")

    # Continuous map-art underlay: ONE soft parchment for all visual land
    # (playable + surrounding). No grey "disabled province" treatment.
    # Water is a distinct cool tone. Internal structure comes only from the
    # playable color-ID / ownership / border layers on top.
    LAND_RGB = (232, 226, 212)
    WATER_RGB = (214, 224, 234)
    bg = bytearray(crop_w * crop_h * 3)
    for y in range(crop_h):
        for x in range(crop_w):
            idx = y * crop_w + x
            base = idx * 3
            if visual_mask[idx]:
                bg[base : base + 3] = bytes(LAND_RGB)
            else:
                bg[base : base + 3] = bytes(WATER_RGB)

    # visual_land_mask.png: white=land any, black=water
    mask_bytes = bytearray(crop_w * crop_h * 3)
    for idx, is_land in enumerate(visual_mask):
        tone = 255 if is_land else 0
        base = idx * 3
        mask_bytes[base : base + 3] = bytes((tone, tone, tone))

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    id_png = out / "province_id_map.png"
    write_png_rgb(id_png, crop_w, crop_h, bytes(id_bytes))
    write_png_rgb(out / "visual_land_mask.png", crop_w, crop_h, bytes(mask_bytes))
    write_png_rgb(out / "background_procedural.png", crop_w, crop_h, bytes(bg))

    # Attach neighbor lists for scandi report
    by_table = {r["province_id"]: r for r in table}
    for item in scandi_report:
        item["neighbors"] = list(by_table.get(item["province_id"], {}).get("source_neighbors", []))
        item["pixel_area"] = int(by_table.get(item["province_id"], {}).get("provenance", {}).get("pixels", 0))

    selection_report["final_playable_count"] = len(table)
    selection_report["scandinavia_playable"] = scandi_report
    selection_report["cosmetic_visual_land_provinces"] = cosmetic_ids[:80]
    selection_report["cosmetic_visual_land_count"] = len(cosmetic_ids)
    selection_report["land_adjacency_edges"] = len(land_edges)
    selection_report["authored_edges"] = authored_edges
    selection_report["authored_non_land_edges"] = len(authored_edges)
    selection_report["anchors_snapped"] = snapped
    selection_report["black_separators_filled"] = separators_filled
    selection_report["visual_separators_closed"] = visual_separators_closed
    selection_report["land_adjacency_mode"] = "direct_4_neighbor_playable_only"
    selection_report["cosmetic_interaction"] = {
        "hover": False,
        "selection": False,
        "labels": False,
        "counters": False,
        "facilities": False,
        "objectives": False,
        "adjacency": False,
        "note": "outside-theatre land is continuous background art only; not in ID map or graph",
    }
    selection_report["dropped_tiny"] = dropped_tiny
    selection_report["display_expand"] = dict(DISPLAY_EXPAND)
    selection_report["display_crop_px"] = {
        "x0": min_x,
        "y0": min_y,
        "x1": max_x,
        "y1": max_y,
        "width": crop_w,
        "height": crop_h,
        "frozen": True,
    }
    selection_report["force_include_strategic"] = [
        {"province_id": pid, "display_name": name}
        for pid, name in sorted(FORCE_INCLUDE_STRATEGIC_PROVINCES.items())
    ]
    selection_report["underlay_style"] = "continuous_parchment_no_province_subdivision"
    selection_report["land_components"] = component_report
    selection_report["land_component_count"] = len(component_report)
    selection_report["crossing_candidates"] = crossing_candidates
    selection_report["crossing_candidates_note"] = (
        "Deterministic nearest-coast proposals only; not gameplay edges unless allowlisted"
    )
    # Connectivity policy: every non-mainland component needs an authored crossing
    # unless explicitly allowlisted as intentionally isolated.
    mainland_ids = set()
    for item in component_report:
        if item["label"] == "mainland_europe":
            mainland_ids = set(item["province_ids"])
            break
    if not mainland_ids and component_report:
        mainland_ids = set(component_report[0]["province_ids"])
    authored_pairs = {tuple(sorted((e["a"], e["b"]))) for e in authored_edges}
    component_connectivity = []
    for item in component_report:
        label = item["label"]
        ids = set(item["province_ids"])
        if label == "mainland_europe" or ids == mainland_ids:
            status = "mainland"
        elif label in INTENTIONALLY_ISOLATED_COMPONENTS:
            status = "intentionally_isolated"
        else:
            linked = False
            for a, b in authored_pairs:
                if (a in ids) != (b in ids):
                    linked = True
                    break
            status = "connected_by_authored_crossing" if linked else "incorrectly_disconnected"
        component_connectivity.append(
            {
                "label": label,
                "size": item["size"],
                "status": status,
                "province_ids": item["province_ids"],
            }
        )
    selection_report["component_connectivity"] = component_connectivity
    bad = [c for c in component_connectivity if c["status"] == "incorrectly_disconnected"]
    selection_report["disconnected_components_unresolved"] = bad
    # Ireland report rows
    ireland_report = []
    by_table = {r["province_id"]: r for r in table}
    for pid in sorted(ireland_ids):
        row = by_table.get(pid)
        if row is None:
            continue
        ireland_report.append(
            {
                "province_id": pid,
                "display_name": row["display_name"],
                "pixel_area": int(row.get("provenance", {}).get("pixels", 0)),
                "land_neighbors": list(row.get("land_neighbors") or []),
                "authored_sea_connections": {
                    n: t
                    for n, t in (row.get("edge_types") or {}).items()
                    if t != "land"
                },
            }
        )
    selection_report["ireland_playable"] = ireland_report

    result = import_strategic_map(
        id_png,
        table,
        out / "map_manifest.json",
        map_id=MAP_ID,
        provenance="derived_from_interim_goe_europe_theatre_crop",
        ignored_colors=(BLACK, WHITE),
        texture_output=id_png,
    )
    result["asset_status"] = "derived_project_theatre"
    result["theatre"] = {
        "name": "Europe-Mediterranean from GoE",
        "marker_bounds": dict(MARKER_THEATRE),
        "source_province_count": len(source_table),
        "theatre_province_count": len(table),
        "playable_province_count": len(table),
        "selection": selection_report,
        "excludes": EXCLUDES,
        "layers": {
            "visual_land_mask": "visual_land_mask.png",
            "playable_id_map": "province_id_map.png",
            "background_procedural": "background_procedural.png",
        },
    }
    result["visual_background"] = {
        "path": "background_procedural.png",
        "width": crop_w,
        "height": crop_h,
        "asset_status": "project_procedural",
        "layer_role": "presentation_underlay_from_visual_land_mask",
        "visual_land_mask": "visual_land_mask.png",
    }
    result["visual_background_policy"] = {
        "repo_stores_pack_artwork": False,
        "gameplay_authority": "color_id_province_map",
        "status_label": "project_procedural",
        "nonplayable_land": "continuous_parchment_background_art_only",
    }
    result["provenance_table"] = {
        "visible_geography": "continuous_land_silhouette_in_frozen_frame",
        "playable_geography": "selected_goe_provinces_clipped_to_frozen_frame",
        "adjacency": "direct_4_neighbor_playable_plus_authored_crossings",
        "north_africa": "continuous_visual_land_coastal_playable_belt",
        "scandinavia": "expanded_playable_north",
        "display_frame": "frozen_817x920",
    }
    (out / "map_manifest.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out / "README.md").write_text(
        "\n".join(
            [
                "# Europe–Mediterranean theatre (from GoE)",
                "",
                f"- playable provinces: {len(table)}",
                f"- frozen display: {crop_w}×{crop_h}",
                "- `province_id_map.png` — playable only (selection/ownership/borders)",
                "- `visual_land_mask.png` — continuous land silhouette (no province cracks)",
                "- `background_procedural.png` — parchment land / cool water underlay",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return result


def build_europe_mediterranean_from_goe_campaign(
    *,
    manifest_path: str | Path | None = None,
    selected_faction: Faction = Faction.NATO,
) -> CampaignState:
    path = Path(manifest_path) if manifest_path else Path(DEFAULT_OUTPUT_DIR) / "map_manifest.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"Theatre manifest missing: {path}. Run generate-europe-mediterranean-from-goe first."
        )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if str(manifest.get("map_id")) != MAP_ID:
        raise ValueError(f"Expected map_id {MAP_ID}, got {manifest.get('map_id')}")

    state = build_goe_europe_campaign()
    rows = list(manifest.get("province_table", []))
    kept_ids = {str(row["province_id"]) for row in rows}
    anchors = {
        str(row["province_id"]): row.get("marker_anchor") or [0.0, 0.0] for row in rows
    }
    neighbors_map = {
        str(row["province_id"]): [str(n) for n in row.get("source_neighbors", [])]
        for row in rows
    }
    display_names = {
        str(row["province_id"]): str(row.get("display_name") or row["province_id"])
        for row in rows
    }

    state.provinces = {pid: p for pid, p in state.provinces.items() if pid in kept_ids}
    for pid, province in state.provinces.items():
        anchor = anchors.get(pid, [province.x, province.y])
        province.x = float(anchor[0])
        province.y = float(anchor[1])
        province.neighbors = neighbors_map.get(pid, [])
        if pid in display_names:
            province.display_name = display_names[pid]
            province.metadata["display_name_locked"] = True
            province.metadata["name_source"] = "em_theatre_manifest"
        province.map_region = "europe_mediterranean"
        province.metadata["europe_mediterranean_from_goe"] = True
        province.metadata["playable"] = True
        province.metadata["name_is_human_readable"] = not str(
            display_names.get(pid, pid)
        ).lower().startswith("province")

    state.battalions = {
        bid: b for bid, b in state.battalions.items() if b.province_id in state.provinces
    }
    live_fids = {b.formation_id for b in state.battalions.values() if b.formation_id}
    state.formations = {
        fid: f for fid, f in state.formations.items() if fid in live_fids or not live_fids
    }

    state.campaign_name = "Gates of CodeX: Europe-Mediterranean (GoE theatre)"
    state.selected_faction = selected_faction
    state.current_faction = selected_faction
    state.map_id = MAP_ID
    state.map_metadata = {
        **dict(state.map_metadata),
        "strategic_map_id": MAP_ID,
        "strategic_map_manifest": "assets/maps/europe_mediterranean/from_goe/map_manifest.json",
        "strategic_map_provenance": "derived_from_interim_goe_europe_theatre_crop",
        "europe_mediterranean_from_goe": True,
        "canonical": False,
        "note": "Playable provinces subset; visual land may include unselectable Africa.",
        "theatre_marker_bounds": dict(MARKER_THEATRE),
        "excludes": EXCLUDES,
    }
    for fs in state.factions.values():
        fs.is_human_controlled = fs.faction == selected_faction
    state.pending_battle = None
    state.schema_version = max(state.schema_version, 5)
    ensure_strategic_layer(state)
    state.validate()
    return state
