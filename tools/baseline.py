"""M0 baseline capture: manifests, safe GOE extraction, archive indexes.

Read-only against GOE, WF and GAME. Writes only under this workspace.

    python tools/baseline.py manifest   # evidence/{source,target}-manifest.json + baseline.json
    python tools/baseline.py extract    # upstream/goe-portable (path-validated)
    python tools/baseline.py index      # evidence/archive-index/*.json
    python tools/baseline.py all
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATHS = json.loads((ROOT / "tools" / "paths.json").read_text(encoding="utf-8"))
EVIDENCE = ROOT / "evidence"

# Code/config files are hashed in full; large packed assets get size+mtime only.
HASHED_SUFFIXES = {".lua", ".set", ".inc", ".info", ".pot", ".po", ".txt", ".pat", ".mi", ".def", ".json", ".version"}
HASH_SIZE_LIMIT = 64 * 1024 * 1024


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def manifest(root: Path, hash_all: bool) -> dict:
    files = []
    total = 0
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        st = p.stat()
        total += st.st_size
        entry = {"path": p.relative_to(root).as_posix(), "size": st.st_size, "mtime": utc(st.st_mtime)}
        if hash_all or (p.suffix.lower() in HASHED_SUFFIXES and st.st_size <= HASH_SIZE_LIMIT):
            entry["sha256"] = sha256(p)
        files.append(entry)
    return {"root": str(root), "fileCount": len(files), "totalBytes": total, "files": files}


def cmd_manifest() -> None:
    goe, wf, game = (Path(PATHS[k]) for k in ("GOE", "WF", "GAME"))
    src = manifest(goe, hash_all=True)
    write_json(EVIDENCE / "source-manifest.json", src)
    tgt = manifest(wf, hash_all=False)
    write_json(EVIDENCE / "target-manifest.json", tgt)

    acf = Path(PATHS["STEAM_MANIFEST"]).read_text(encoding="utf-8", errors="replace")
    buildid = re.search(r'"buildid"\s+"(\d+)"', acf)
    zip_hash = next(f["sha256"] for f in src["files"] if f["path"].endswith("-win-Portable.zip"))
    exp = PATHS["expected"]
    baseline = {
        "capturedUtc": utc(datetime.now(timezone.utc).timestamp()),
        "goe": {"fileCount": src["fileCount"], "totalBytes": src["totalBytes"], "zipSha256": zip_hash,
                "zipMatchesPlan": zip_hash == exp["goe_zip_sha256"],
                "modInfo": (goe / "mod.info").read_text(encoding="utf-8", errors="replace")},
        "wf": {"fileCount": tgt["fileCount"], "totalBytes": tgt["totalBytes"],
               "modInfo": (wf / "mod.info").read_text(encoding="utf-8", errors="replace")},
        "game": {"steamBuildId": buildid.group(1) if buildid else None,
                 "buildMatchesPlan": bool(buildid) and buildid.group(1) == exp["game_buildid"],
                 "paks": sorted(p.relative_to(game).as_posix() for p in (game / "resource").glob("*.pak"))},
    }
    write_json(EVIDENCE / "baseline.json", baseline)
    print(json.dumps({k: v for k, v in baseline.items() if k != "game"}, indent=1)[:1500])
    print("game build:", baseline["game"]["steamBuildId"], "paks:", len(baseline["game"]["paks"]))


def cmd_extract() -> None:
    src = next(Path(PATHS["GOE"]).glob("*-win-Portable.zip"))
    dest = (ROOT / "upstream" / "goe-portable").resolve()
    with zipfile.ZipFile(src) as z:
        infos = z.infolist()
        # Refuse the whole archive if any entry would land outside dest.
        for i in infos:
            target = (dest / i.filename).resolve()
            if dest != target and dest not in target.parents:
                raise SystemExit(f"unsafe entry path: {i.filename!r}")
        dest.mkdir(parents=True, exist_ok=True)
        z.extractall(dest)
    asm = dest / "current" / "GatesofEuropa_Data" / "Managed" / "Assembly-CSharp.dll"
    got = sha256(asm) if asm.exists() else None
    print(f"extracted {len(infos)} entries -> {dest}")
    print("Assembly-CSharp.dll sha256:", got, "matchesPlan:", got == PATHS["expected"]["goe_assembly_sha256"])


def index_pak(pak: Path) -> dict:
    with zipfile.ZipFile(pak) as z:
        entries = [{"name": i.filename, "size": i.file_size, "csize": i.compress_size, "crc": f"{i.CRC:08X}"}
                   for i in z.infolist()]
    st = pak.stat()
    return {"archive": str(pak), "size": st.st_size, "mtime": utc(st.st_mtime), "entryCount": len(entries), "entries": entries}


def cmd_index() -> None:
    out = EVIDENCE / "archive-index"
    jobs = [("goe", next(Path(PATHS["GOE"]).glob("*-win-Portable.zip")))]
    jobs += [("wf", p) for p in sorted(Path(PATHS["WF"]).rglob("*.pak"))]
    jobs += [("game", p) for p in sorted((Path(PATHS["GAME"]) / "resource").glob("*.pak"))]
    summary = []
    for label, pak in jobs:
        try:
            idx = index_pak(pak)
        except (zipfile.BadZipFile, OSError) as e:
            summary.append({"source": label, "archive": str(pak), "error": str(e)})
            print(f"  FAILED {pak.name}: {e}")
            continue
        write_json(out / f"{label}__{pak.stem}.json", idx)
        summary.append({"source": label, "archive": str(pak), "size": idx["size"], "entryCount": idx["entryCount"]})
        print(f"  {label}:{pak.name}: {idx['entryCount']} entries")
    write_json(EVIDENCE / "archive-index-summary.json", summary)


COMMANDS = {"manifest": cmd_manifest, "extract": cmd_extract, "index": cmd_index}

if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "all":
        for fn in COMMANDS.values():
            fn()
    elif arg in COMMANDS:
        COMMANDS[arg]()
    else:
        raise SystemExit(__doc__)
