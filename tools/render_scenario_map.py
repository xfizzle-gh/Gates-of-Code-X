"""Render a preview of province ownership from the province ID texture.

    python tools/render_scenario_map.py                      # current owners in campaign/
    python tools/render_scenario_map.py data/scenario_x.json out.png   # a scenario's province list
    python tools/render_scenario_map.py --ids out.png        # grey map with province numbers, for authoring
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
PROJECT = ROOT / "campaign"
COLORS = {
    "usa": (70, 110, 200), "usmc": (30, 60, 130), "uaf": (60, 170, 160), "ger": (110, 110, 110),
    "fra": (120, 170, 255), "idf": (240, 240, 255), "grm": (60, 140, 60), "reb": (200, 120, 40),
    "rus": (180, 50, 50), "pla": (220, 200, 40), "neutral": (205, 205, 200),
}


def load():
    db = json.load(open(glob.glob(str(PROJECT / "Assets" / "TextAsset" / "province_database_*.json"))[0], encoding="utf-8"))["Provinces"]
    img = np.array(Image.open(PROJECT / "Assets" / "Texture2D" / "province_idnew_map.png").convert("RGB"))
    key = (img[:, :, 0].astype(np.int32) << 16) | (img[:, :, 1].astype(np.int32) << 8) | img[:, :, 2]
    return db, img, key


def main() -> None:
    args = sys.argv[1:]
    ids_mode = "--ids" in args
    args = [a for a in args if a != "--ids"]
    db, img, key = load()
    out = Path(args[-1]) if args and args[-1].endswith(".png") else ROOT / "build" / "scenario-map.png"
    owner_by_id = None
    if args and args[0].endswith(".json"):
        sc = json.load(open(args[0], encoding="utf-8"))
        owner_by_id = sc["provinces"]
        slot_tag = {}
    else:
        sc = json.load(open(ROOT / "data" / "scenario_europe.json", encoding="utf-8"))
        slot_tag = {f["slot"]: f["tag"] for f in sc["factions"]}

    h, w = key.shape
    canvas = np.full((h, w, 3), 255, dtype=np.uint8)
    labels = []
    for p in db:
        c = p["IdColor"]
        mask = key == ((c["r"] << 16) | (c["g"] << 8) | c["b"])
        if not mask.any():
            continue
        if ids_mode:
            color = (225, 225, 220)
        elif owner_by_id is not None:
            color = COLORS.get(owner_by_id.get(p["ProvinceId"], "neutral"), COLORS["neutral"])
        else:
            color = COLORS.get(slot_tag.get(p["Owner"], "neutral"), COLORS["neutral"])
        canvas[mask] = color
        ys, xs = np.nonzero(mask)
        labels.append((int(xs.mean()), int(ys.mean()), p))
    # province borders: pixels whose right or lower neighbour differs
    edge = np.zeros((h, w), dtype=bool)
    edge[:, :-1] |= key[:, :-1] != key[:, 1:]
    edge[:-1, :] |= key[:-1, :] != key[1:, :]
    canvas[edge] = (60, 60, 60)
    im = Image.fromarray(canvas)
    scale = 2 if ids_mode else 1
    im = im.resize((w * scale, h * scale), Image.NEAREST)
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("arial.ttf", 11 if ids_mode else 9)
    except OSError:
        font = ImageFont.load_default()
    if ids_mode:
        for x, y, p in labels:
            d.text((x * scale, y * scale), p["ProvinceId"].replace("province_", "").lstrip("0") or "0", font=font, fill=(0, 0, 0), anchor="mm")
    out.parent.mkdir(exist_ok=True)
    im.save(out)
    print(f"{out} ({im.width}x{im.height}), provinces drawn: {len(labels)} of {len(db)}")


if __name__ == "__main__":
    main()
