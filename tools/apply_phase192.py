from __future__ import annotations
import base64, shutil, subprocess, zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
parts = [
    (TOOLS / f".phase192_patch{i}").read_text(encoding="ascii")
    for i in range(1, 7)
]
patch = zlib.decompress(base64.b64decode("".join(parts)))
patch_path = TOOLS / ".phase192.patch"
patch_path.write_bytes(patch)
subprocess.run(
    ["git", "apply", "--whitespace=nowarn", str(patch_path)],
    cwd=ROOT,
    check=True,
)

flag = ROOT / "resource/interface/pages/multi/flag_goc_bel.tga"
for actor in ("grc", "rou", "bgr", "hrv", "svn", "bih", "mne", "alb", "mkd", "mda"):
    dest = ROOT / f"resource/interface/pages/multi/flag_goc_{actor}.tga"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(flag, dest)

final_workflow = (TOOLS / ".phase192_final_workflow.yml").read_bytes()
(ROOT / ".github/workflows/expanded-nations-projection.yml").write_bytes(final_workflow)

for path in [
    patch_path,
    *(TOOLS / f".phase192_patch{i}" for i in range(1, 7)),
    TOOLS / ".phase192_final_workflow.yml",
    Path(__file__),
]:
    path.unlink(missing_ok=True)
