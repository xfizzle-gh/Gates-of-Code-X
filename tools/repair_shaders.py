"""Replace AssetRipper's stub shaders in campaign/ with the real sources shipped in the Unity editor.

AssetRipper cannot decompile shaders and writes property-only stubs. The package code itself is present
as DLLs under Assets/Plugins, so the real packages cannot simply be added (duplicate assemblies).
Instead this script:
  1. creates script-free embedded packages under campaign/Packages holding only shader sources, so
     "Packages/com.unity.render-pipelines.*/..." includes resolve;
  2. unpacks the TextMesh Pro shaders from the editor's TMP Essential Resources;
  3. deletes each stub that has a real shader of the same name and re-points every reference at it;
  4. restores the URP entry in GraphicsSettings.m_RenderPipelineGlobalSettingsMap.

    python tools/repair_shaders.py "<editor>\\Editor\\Data"
"""
from __future__ import annotations

import io
import json
import re
import shutil
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = ROOT / "campaign"
SHADER_PACKAGES = [
    "com.unity.render-pipelines.core",
    "com.unity.render-pipelines.universal",
    "com.unity.render-pipelines.universal-config",
    "com.unity.shadergraph",
]
# Unused by this 2D application. Without the URP editor assembly nothing strips their variants
# (276,480 for one pass), so the real sources would add hours to every clean build.
KEEP_STUB_PREFIXES = ("Hidden/TerrainEngine/",)
SOURCE_EXT ={".shader", ".hlsl", ".cginc", ".glslinc"}
SKIP_DIRS = {"Tests", "Samples~", "Documentation~", "ApiUpdater~", "GraphTemplates"}
TEXT_ASSET_EXT = {".mat", ".asset", ".unity", ".prefab", ".controller", ".anim"}
SHADER_NAME = re.compile(r'^\s*Shader\s+"([^"]+)"', re.M)
GUID = re.compile(r"^guid:\s*([0-9a-f]{32})", re.M)


def shader_name(path: Path) -> str | None:
    m = SHADER_NAME.search(path.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else None


def copy_shader_packages(builtin: Path) -> list[Path]:
    copied = []
    for name in SHADER_PACKAGES:
        src, dst = builtin / name, PROJECT / "Packages" / name
        if dst.exists():
            shutil.rmtree(dst)
        version = json.loads((src / "package.json").read_text(encoding="utf-8"))["version"]
        for f in src.rglob("*"):
            rel = f.relative_to(src)
            if not f.is_file() or f.suffix.lower() not in SOURCE_EXT or SKIP_DIRS & set(rel.parts):
                continue
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, dst / rel)
            meta = f.with_name(f.name + ".meta")
            if meta.exists():
                shutil.copyfile(meta, dst / rel.parent / meta.name)
            copied.append(dst / rel)
        # No dependencies and no scripts: the code stays in Assets/Plugins.
        (dst / "package.json").write_text(json.dumps(
            {"name": name, "version": version, "displayName": name + " (shader sources only)"}, indent=2) + "\n")
    return copied


def extract_tmp_shaders(builtin: Path) -> list[Path]:
    pkg = builtin / "com.unity.ugui" / "Package Resources" / "TMP Essential Resources.unitypackage"
    dst = PROJECT / "Assets" / "TextMesh Pro" / "Shaders"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    entries: dict[str, dict[str, bytes]] = {}
    with tarfile.open(pkg, "r:gz") as tar:
        for m in tar.getmembers():
            if not m.isfile():
                continue
            parts = m.name.lstrip("./").split("/")
            if len(parts) == 2:
                entries.setdefault(parts[0], {})[parts[1]] = tar.extractfile(m).read()
    out = []
    for files in entries.values():
        pathname = files.get("pathname", b"").decode("utf-8").splitlines()[0].strip() if "pathname" in files else ""
        if "/Shaders/" not in pathname or "asset" not in files:
            continue
        target = dst / Path(pathname).name
        if target.suffix.lower() not in SOURCE_EXT:
            continue
        target.write_bytes(files["asset"])
        target.with_name(target.name + ".meta").write_bytes(files["asset.meta"])
        out.append(target)
    return out


def meta_guid(path: Path) -> str | None:
    meta = path.with_name(path.name + ".meta")
    if not meta.exists():
        return None
    m = GUID.search(meta.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else None


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    builtin = Path(sys.argv[1]) / "Resources" / "PackageManager" / "BuiltInPackages"
    real_files = copy_shader_packages(builtin) + extract_tmp_shaders(builtin)

    real_by_name: dict[str, str] = {}
    for f in real_files:
        if f.suffix.lower() != ".shader":
            continue
        name, guid = shader_name(f), meta_guid(f)
        if name and guid:
            real_by_name.setdefault(name, guid)

    remap: dict[str, str] = {}
    unmatched = []
    for stub in sorted((PROJECT / "Assets" / "Shader").glob("*.shader")):
        name, guid = shader_name(stub), meta_guid(stub)
        if name and name.startswith(KEEP_STUB_PREFIXES):
            unmatched.append(name + "  (kept as stub on purpose)")
        elif name in real_by_name and guid:
            remap[guid] = real_by_name[name]
            stub.unlink()
            stub.with_name(stub.name + ".meta").unlink()
        else:
            unmatched.append(name)

    pattern = re.compile("|".join(remap)) if remap else None
    touched = 0
    for base in (PROJECT / "Assets", PROJECT / "ProjectSettings"):
        for f in base.rglob("*"):
            if not f.is_file() or f.suffix.lower() not in TEXT_ASSET_EXT:
                continue
            raw = f.read_bytes()
            if not raw.startswith(b"%YAML") or pattern is None:
                continue
            text = raw.decode("utf-8", errors="surrogateescape")
            new = pattern.sub(lambda m: remap[m.group(0)], text)
            if new != text:
                f.write_bytes(new.encode("utf-8", errors="surrogateescape"))
                touched += 1

    gs = PROJECT / "ProjectSettings" / "GraphicsSettings.asset"
    settings_guid = meta_guid(PROJECT / "Assets" / "MonoBehaviour" / "UniversalRenderPipelineGlobalSettings.asset")
    text = gs.read_text(encoding="utf-8")
    entry = ("m_RenderPipelineGlobalSettingsMap:\n"
             f"    UnityEngine.Rendering.Universal.UniversalRenderPipeline: {{fileID: 11400000, guid: {settings_guid}, type: 2}}")
    patched = text.replace("m_RenderPipelineGlobalSettingsMap: {}", entry)
    gs.write_text(patched, encoding="utf-8")

    print(f"real shader sources copied: {len(real_files)}")
    print(f"stubs replaced: {len(remap)}; files re-pointed: {touched}")
    print(f"stubs left (no real source found): {len(unmatched)}")
    for n in unmatched:
        print("   ", n)
    print("GraphicsSettings URP global settings map:", "patched" if patched != text else "unchanged")


if __name__ == "__main__":
    main()
