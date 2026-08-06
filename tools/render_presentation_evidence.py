"""Offline presentation composites from Godot map assets (evidence only)."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
GODOT = ROOT / "godot"
OUT = ROOT / "docs/godot-presentation/screenshots"


def main() -> None:
    manifest = json.loads(
        (GODOT / "assets/maps/europe_mediterranean/from_goe/map_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    snapshot = json.loads((GODOT / "campaign_snapshot.json").read_text(encoding="utf-8"))
    routes = json.loads(
        (GODOT / "fixtures/presentation/routes_and_battles.json").read_text(encoding="utf-8")
    )
    sites = json.loads(
        (GODOT / "fixtures/presentation/control_sites.json").read_text(encoding="utf-8")
    )
    OUT.mkdir(parents=True, exist_ok=True)

    id_img = Image.open(
        GODOT
        / "assets/maps/europe_mediterranean/from_goe"
        / manifest["id_texture"]["path"]
    ).convert("RGB")
    bg = Image.open(
        GODOT / "assets/maps/europe_mediterranean/from_goe/background_procedural.png"
    ).convert("RGBA")
    width, height = id_img.size

    rgb_to_pid: dict[tuple[int, int, int], str] = {}
    anchors: dict[str, list[float]] = {}
    for row in manifest["province_table"]:
        rgb = tuple(int(v) for v in row["rgb"])
        pid = str(row["province_id"])
        rgb_to_pid[rgb] = pid
        anchors[pid] = [float(v) for v in row.get("marker_anchor", [0, 0])]

    ownership = {
        str(p["id"]): str(p.get("owner", "neutral")) for p in snapshot.get("provinces", [])
    }
    colors = {
        "nato": (79, 143, 216, 90),
        "ukr": (226, 200, 74, 90),
        "rusa": (201, 91, 91, 90),
        "prc": (208, 138, 63, 90),
        "neutral": (112, 119, 128, 90),
    }

    owner = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pix_id = id_img.load()
    pix_o = owner.load()
    for y in range(height):
        for x in range(width):
            pid = rgb_to_pid.get(pix_id[x, y])
            if not pid:
                continue
            pix_o[x, y] = colors.get(ownership.get(pid, "neutral"), colors["neutral"])

    border = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pix_b = border.load()
    for y in range(height):
        for x in range(width):
            pid = rgb_to_pid.get(pix_id[x, y])
            if not pid:
                continue
            edge = False
            if x + 1 < width:
                right = rgb_to_pid.get(pix_id[x + 1, y])
                if right and right != pid:
                    edge = True
            if not edge and y + 1 < height:
                down = rgb_to_pid.get(pix_id[x, y + 1])
                if down and down != pid:
                    edge = True
            if edge:
                pix_b[x, y] = (102, 110, 118, 160)

    base = Image.alpha_composite(bg, owner)
    base = Image.alpha_composite(base, border)

    def anchor_to_topleft(pid: str) -> tuple[float, float]:
        anchor = anchors.get(pid, [width / 2, height / 2])
        ax, ay_bottom = float(anchor[0]), float(anchor[1])
        return ax, float(height - 1) - ay_bottom

    def compose(
        target_w: int,
        target_h: int,
        label: str,
        extras: str | None = None,
        selected: str | None = None,
        debug: bool = False,
    ) -> Image.Image:
        scale = min(target_w / width, target_h / height) * 0.92
        rw, rh = int(width * scale), int(height * scale)
        canvas = Image.new("RGBA", (target_w, target_h), (6, 9, 12, 255))
        # Identity layers use nearest to avoid ownership bleed; matches Godot draw path.
        layer = base.resize((rw, rh), Image.Resampling.NEAREST)
        ox = (target_w - rw) // 2
        oy = (target_h - rh) // 2 + 10
        canvas.alpha_composite(layer, (ox, oy))
        draw = ImageDraw.Draw(canvas)

        def map_to_screen(px: float, py: float) -> tuple[float, float]:
            return ox + px * scale, oy + py * scale

        for battalion in snapshot.get("battalions", []):
            pid = str(battalion.get("province_id", ""))
            display_pixel = battalion.get("display_pixel")
            if isinstance(display_pixel, list) and len(display_pixel) >= 2:
                sx, sy = map_to_screen(float(display_pixel[0]), float(display_pixel[1]))
            else:
                sx, sy = map_to_screen(*anchor_to_topleft(pid))
            col = colors.get(str(battalion.get("faction", "neutral")), colors["neutral"])[:3]
            draw.rectangle(
                [sx - 17, sy - 11, sx + 17, sy + 11],
                fill=col + (220,),
                outline=(255, 255, 255, 255),
            )
            draw.text(
                (sx - 12, sy - 6),
                f"I {battalion.get('unit_count', 0)}",
                fill=(255, 255, 255, 255),
            )

        if selected:
            sx, sy = map_to_screen(*anchor_to_topleft(selected))
            draw.ellipse([sx - 20, sy - 20, sx + 20, sy + 20], outline=(127, 231, 255, 255), width=3)

        if extras == "routes":
            for route in routes.get("routes", []):
                pts = [
                    map_to_screen(float(p[0]), float(p[1]))
                    for p in route.get("pixels", [])
                    if isinstance(p, list) and len(p) >= 2
                ]
                if len(pts) >= 2:
                    draw.line(pts, fill=(127, 231, 255, 255), width=3)
            for battle in routes.get("battles", []):
                if battle.get("kind") == "node":
                    pixel = battle["pixel"]
                    sx, sy = map_to_screen(float(pixel[0]), float(pixel[1]))
                else:
                    a = battle["presentation_edge_a_pixel"]
                    b = battle["presentation_edge_b_pixel"]
                    t = int(battle["presentation_progress_fp"]) / 1000.0
                    sx, sy = map_to_screen(
                        float(a[0]) + (float(b[0]) - float(a[0])) * t,
                        float(a[1]) + (float(b[1]) - float(a[1])) * t,
                    )
                draw.line([(sx - 10, sy - 10), (sx + 10, sy + 10)], fill=(255, 159, 67, 255), width=3)
                draw.line([(sx - 10, sy + 10), (sx + 10, sy - 10)], fill=(255, 159, 67, 255), width=3)
            for contact in routes.get("contacts", []):
                if contact.get("kind") == "node":
                    pixel = contact["pixel"]
                    sx, sy = map_to_screen(float(pixel[0]), float(pixel[1]))
                    draw.ellipse([sx - 7, sy - 7, sx + 7, sy + 7], outline=(255, 140, 50, 255), width=2)
                else:
                    a = contact["presentation_edge_a_pixel"]
                    b = contact["presentation_edge_b_pixel"]
                    t = int(contact.get("presentation_progress_fp", 500)) / 1000.0
                    sx, sy = map_to_screen(
                        float(a[0]) + (float(b[0]) - float(a[0])) * t,
                        float(a[1]) + (float(b[1]) - float(a[1])) * t,
                    )
                    draw.line([(sx - 8, sy - 5), (sx + 8, sy + 5)], fill=(255, 100, 50, 255), width=2)

        if extras == "sites":
            for site in sites.get("control_sites", []):
                pixel = site["pixel"]
                sx, sy = map_to_screen(float(pixel[0]), float(pixel[1]))
                col = (99, 214, 159, 255) if site.get("owned") else (184, 192, 200, 255)
                draw.polygon([(sx, sy - 8), (sx + 8, sy), (sx, sy + 8), (sx - 8, sy)], fill=col)
                progress = int(site.get("presentation_capture_progress_fp", 0))
                draw.arc(
                    [sx + 10, sy - 12, sx + 34, sy + 12],
                    start=-90,
                    end=-90 + int(360 * progress / 1000),
                    fill=(255, 177, 78, 255),
                    width=3,
                )

        if debug:
            draw.rectangle([ox, oy, ox + rw, oy + rh], outline=(80, 200, 255, 180), width=2)
            for index, pid in enumerate(anchors):
                if index % 17 != 0:
                    continue
                sx, sy = map_to_screen(*anchor_to_topleft(pid))
                draw.ellipse([sx - 1, sy - 1, sx + 1, sy + 1], fill=(200, 230, 255, 180))
            draw.text((16, 16), "DEBUG anchors/bounds", fill=(200, 255, 180, 255))
            draw.text(
                (16, 34),
                f"provinces={manifest.get('province_count')} image={width}x{height}",
                fill=(200, 255, 180, 255),
            )

        draw.text((16, target_h - 28), label, fill=(200, 210, 220, 255))
        title_y = 52 if debug else 16
        draw.text(
            (16, title_y),
            f"Gates of CodeX presentation composite | {target_w}x{target_h}",
            fill=(255, 255, 255, 230),
        )
        return canvas.convert("RGB")

    before = Image.alpha_composite(
        bg.resize((width * 2, height * 2), Image.Resampling.BILINEAR),
        owner.resize((width * 2, height * 2), Image.Resampling.BILINEAR),
    )

    def save_before(target_w: int, target_h: int, path: Path, note: str) -> None:
        src = before.convert("RGBA")
        sw, sh = src.size
        scale = min(target_w / sw, target_h / sh) * 0.92
        rw, rh = int(sw * scale), int(sh * scale)
        canvas = Image.new("RGB", (target_w, target_h), (6, 9, 12))
        resized = src.resize((rw, rh), Image.Resampling.BILINEAR).convert("RGB")
        canvas.paste(resized, ((target_w - rw) // 2, (target_h - rh) // 2))
        draw = ImageDraw.Draw(canvas)
        draw.text((16, 16), note, fill=(255, 220, 180))
        draw.text((16, target_h - 28), path.name, fill=(180, 180, 180))
        canvas.save(path, optimize=True)
        print(f"wrote {path} ({path.stat().st_size} bytes)")

    save_before(
        1920,
        1080,
        OUT / "before_full_map_1080p.png",
        "BEFORE: soft bilinear upscale of low-res theatre (illustrative baseline)",
    )
    save_before(
        2560,
        1440,
        OUT / "before_full_map_1440p.png",
        "BEFORE: soft bilinear upscale @1440p",
    )

    selected = next(iter(ownership), None)
    jobs = [
        (1920, 1080, "full_map_1080p.png", None, None, False, "AFTER: nearest identity + underlay"),
        (2560, 1440, "full_map_1440p.png", None, None, False, "AFTER: 1440p fit"),
        (1920, 1080, "selected_province.png", None, selected, False, "AFTER: selected province"),
        (1920, 1080, "formation_stack.png", None, None, False, "AFTER: formation counters"),
        (1920, 1080, "route_line.png", "routes", None, False, "AFTER: route line"),
        (1920, 1080, "node_battle_marker.png", "routes", None, False, "AFTER: node battle marker"),
        (
            1920,
            1080,
            "mock_edge_battle_marker.png",
            "routes",
            None,
            False,
            "AFTER: mock edge battle (fixed-point)",
        ),
        (1920, 1080, "debug_overlay.png", "sites", None, True, "AFTER: debug + control sites"),
    ]
    for target_w, target_h, name, extras, selected_id, debug, label in jobs:
        image = compose(target_w, target_h, label, extras=extras, selected=selected_id, debug=debug)
        path = OUT / name
        image.save(path, optimize=True)
        print(f"wrote {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
