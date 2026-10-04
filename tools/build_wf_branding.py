"""Replace the Gates of Europa start-menu artwork and version label in campaign/.

Background: WarFighter's own main-menu image (resource/interface/pages/main/video_bkg.png), darkened,
with a text title drawn on it. The texture file is replaced in place so its .meta and GUID are kept.

    python tools/build_wf_branding.py
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
WF = Path(json.loads((ROOT / "tools" / "paths.json").read_text(encoding="utf-8"))["WF"])
PROJECT = ROOT / "campaign"
TARGET = PROJECT / "Assets" / "Texture2D" / "GatesOfEuropa.png"
SCENE = PROJECT / "Assets" / "Scenes" / "StartMenu.unity"
SIZE = (1672, 941)


def font(name: str, size: int):
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default()


def main() -> None:
    src = Image.open(WF / "resource" / "interface" / "pages" / "main" / "video_bkg.png").convert("RGB")
    scale = max(SIZE[0] / src.width, SIZE[1] / src.height)
    src = src.resize((round(src.width * scale), round(src.height * scale)), Image.LANCZOS)
    left, top = (src.width - SIZE[0]) // 2, (src.height - SIZE[1]) // 2
    bg = src.crop((left, top, left + SIZE[0], top + SIZE[1])).filter(ImageFilter.GaussianBlur(2))
    bg = ImageEnhance.Brightness(ImageEnhance.Color(bg).enhance(0.55)).enhance(0.42)

    d = ImageDraw.Draw(bg)
    cx = SIZE[0] // 2
    title, sub = font("impact.ttf", 190), font("arialbd.ttf", 30)
    d.text((cx + 4, 334), "WARFIGHTER", font=title, fill=(0, 0, 0), anchor="mm")
    d.text((cx, 330), "WARFIGHTER", font=title, fill=(214, 208, 190), anchor="mm")
    d.line([(cx - 420, 452), (cx + 420, 452)], fill=(150, 120, 70), width=3)
    d.text((cx, 492), "C A M P A I G N   •   S T R A T E G Y   •   C O N Q U E S T", font=sub, fill=(200, 170, 110), anchor="mm")
    d.text((cx, SIZE[1] - 26), "Gates of Warfighter  -  based on Gates of Europa, used with its author's permission",
           font=font("arial.ttf", 18), fill=(170, 170, 170), anchor="mm")
    bg.save(TARGET)

    t = SCENE.read_text(encoding="utf-8")
    t2 = t.replace("m_text: ' v 0.2.0'", "m_text: ' dev build'").replace("m_text: ' WarFighter Campaign - dev build'", "m_text: ' dev build'")
    SCENE.write_text(t2, encoding="utf-8", newline="\n")
    print(f"menu background replaced ({TARGET.name}, {SIZE[0]}x{SIZE[1]}); version label {'updated' if t2 != t else 'unchanged'}")


if __name__ == "__main__":
    main()
