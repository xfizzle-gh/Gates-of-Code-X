"""Apply a WarFighter scenario (data/scenario_*.json) to the campaign project.

Rewrites, in campaign/:
  Assets/MonoBehaviour/CampaignWorldRules.asset      faction slots, turn order, diplomacy
  Assets/MonoBehaviour/CampaignScriptedEvents.asset  WWII events removed
  Assets/TextAsset/province_database_*.json          unused slots' provinces become Neutral
  Assets/Resources/WfContent/Flags/flag_<tag>.png    faction flags from WF
  Assets/Scripts/WfCampaign/WfFactions.generated.cs  dropdown order and slot table for the code

    python tools/build_wf_scenario.py [data/scenario_europe.json]
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
WF = Path(json.loads((ROOT / "tools" / "paths.json").read_text(encoding="utf-8"))["WF"])
PROJECT = ROOT / "campaign"
RULES = PROJECT / "Assets" / "MonoBehaviour" / "CampaignWorldRules.asset"
EVENTS = PROJECT / "Assets" / "MonoBehaviour" / "CampaignScriptedEvents.asset"
FLAGS_SRC = WF / "resource" / "interface" / "pages" / "main" / "dynamic_campaign"
FLAGS_OUT = PROJECT / "Assets" / "Resources" / "WfContent" / "Flags"
CODE_OUT = PROJECT / "Assets" / "Scripts" / "WfCampaign"
NEUTRAL = 9


def guid_for(key: str) -> str:
    return hashlib.md5(("wfcampaign:" + key).encode("utf-8")).hexdigest()


def hex_list(slots) -> str:
    return "".join(struct.pack("<i", s).hex() for s in slots)


def set_field(block: str, name: str, value: str) -> str:
    return re.sub(rf"(?m)^(\s+){name}:.*$", lambda m: f"{m.group(1)}{name}: {value}".rstrip(), block, count=1)


def write_flag(tag: str) -> str:
    # WF has a full-brightness flag for some factions and only a dimmed tooltip version for others.
    candidates = [FLAGS_SRC / f"flag_{tag}.tga", FLAGS_SRC / f"flag_{tag}.png",
                  FLAGS_SRC / f"tooltip_flag_{tag}.tga", FLAGS_SRC / f"tooltip_flag_{tag}.png"]
    src = next((p for p in candidates if p.exists()), None)
    if src is None:
        return "{fileID: 0}"
    FLAGS_OUT.mkdir(parents=True, exist_ok=True)
    dst = FLAGS_OUT / f"flag_{tag}.png"
    im = Image.open(src).convert("RGBA")
    if src.name.startswith("tooltip_"):
        r, g, b, a = im.split()
        peak = max(max(c.getextrema()[1] for c in (r, g, b)), 1)
        gain = 255.0 / peak
        r, g, b = (c.point(lambda v: min(255, int(v * gain))) for c in (r, g, b))
        im = Image.merge("RGBA", (r, g, b, a))
    im.save(dst)
    guid = guid_for("flag/" + tag)
    dst.with_name(dst.name + ".meta").write_text(
        f"fileFormatVersion: 2\nguid: {guid}\nTextureImporter:\n  mipmaps:\n    enableMipMap: 0\n"
        "  textureType: 8\n  spriteMode: 1\n  alphaIsTransparency: 1\n  nPOTScale: 0\n", encoding="utf-8", newline="\n")
    return f"{{fileID: 21300000, guid: {guid}, type: 3}}"


def main() -> None:
    scenario_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "scenario_2032.json"
    sc = json.loads(scenario_path.read_text(encoding="utf-8"))
    factions = sc["factions"]
    by_slot = {f["slot"]: f for f in factions}
    side_id = sc["sides"]

    text = RULES.read_text(encoding="utf-8")
    head, rest = text.split("  Factions:\n", 1)
    fac_text, tail = rest.split("  TurnOrder:", 1)
    blocks = re.split(r"(?m)^(?=  - Faction: )", fac_text)
    blocks = [b for b in blocks if b.strip()]
    out_blocks, seen = [], set()
    for b in blocks:
        slot = int(re.match(r"  - Faction: (\d+)", b).group(1))
        f = by_slot.get(slot)
        if f is None:
            continue  # slot not used by this scenario: drop it from the rules
        seen.add(slot)
        b = set_field(b, "DisplayName", f["name"])
        b = set_field(b, "Side", str(side_id[f["side"]]))
        b = set_field(b, "ParticipatesInTurnOrder", "1")
        b = set_field(b, "HumanSelectable", "1")
        b = set_field(b, "AIEnabled", "1")
        b = set_field(b, "UnitFactionTag", f["tag"])
        for k in ("UnitFactionTagRequiredDlc", "BackupUnitFactionTag", "BackupUnitFactionTagRequiredDlc", "FallbackUnitFactionTag"):
            b = set_field(b, k, "")
        for k, v in sc["startingResources"].items():
            b = set_field(b, k, str(v))
        b = set_field(b, "Flag", write_flag(f["tag"]))
        out_blocks.append(b)
    missing = set(by_slot) - seen
    if missing:
        raise SystemExit(f"scenario uses slots with no faction block in the rules asset: {sorted(missing)}")

    order = [f["slot"] for f in factions]
    profiles = []
    for f in factions:
        allies = [g["slot"] for g in factions if g["side"] == f["side"] and g is not f]
        enemies = [g["slot"] for g in factions if g["side"] != f["side"]]
        profiles.append(
            f"  - Faction: {f['slot']}\n    War: {hex_list(enemies)}\n    Hostile:\n    Neutral:\n"
            f"    Friendly:\n    Allied: {hex_list(allies)}\n")
    after_profiles = tail.split("  BaseAutoResolveAttackBonus:", 1)[1]
    RULES.write_text(
        head + "  Factions:\n" + "".join(out_blocks) + f"  TurnOrder: {hex_list(order)}\n  DiplomacyProfiles:\n"
        + "".join(profiles) + "  BaseAutoResolveAttackBonus:" + after_profiles, encoding="utf-8", newline="\n")

    ev = EVENTS.read_text(encoding="utf-8")
    EVENTS.write_text(ev.split("  Events:", 1)[0] + "  Events: []\n", encoding="utf-8", newline="\n")

    db_path = next((PROJECT / "Assets" / "TextAsset").glob("province_database_*.json"))
    # Always start from the recovered original so re-running with another scenario is clean.
    original = ROOT / "recovered" / "unity" / "ExportedProject" / "Assets" / "TextAsset" / db_path.name
    db = json.loads((original if original.exists() else db_path).read_text(encoding="utf-8"))
    used = set(by_slot) | {NEUTRAL}
    slot_of_tag = {f["tag"]: f["slot"] for f in factions}
    owners = sc.get("provinces")
    counts, neutralised = {}, 0
    for p in db["Provinces"]:
        if owners is not None:
            # Explicit scenario: every province is the listed faction's, or neutral.
            p["Owner"] = slot_of_tag[owners[p["ProvinceId"]]] if p["ProvinceId"] in owners else NEUTRAL
        elif p["Owner"] not in used:
            p["Owner"] = NEUTRAL
            neutralised += 1
        spec = sc.get("specializationOverrides", {}).get(p["ProvinceId"])
        if spec:
            p["Specialization"] = spec
        yields = sc.get("yieldOverrides", {}).get(p["ProvinceId"])
        if yields:
            p["ResourceYield"].update(yields)
        counts[p["Owner"]] = counts.get(p["Owner"], 0) + 1
    db_path.write_text(json.dumps(db, indent=4), encoding="utf-8")

    CODE_OUT.mkdir(parents=True, exist_ok=True)
    rows = ",\n".join(f'\t\tnew WfFaction("{f["tag"]}", "{f["name"]}", (FactionType){f["slot"]})' for f in factions)
    (CODE_OUT / "WfFactions.generated.cs").write_text(
        "// Generated by tools/build_wf_scenario.py from " + scenario_path.name + ". Do not edit.\n"
        "public static partial class WfFactions\n{\n"
        "\tpublic static readonly WfFaction[] All = new WfFaction[]\n\t{\n" + rows + "\n\t};\n}\n",
        encoding="utf-8", newline="\n")

    print(f"scenario {sc['id']}: {len(factions)} factions")
    for f in factions:
        print(f"  {f['tag']:5} {f['name']:18} slot {f['slot']:2} ({f['slotWas']:12}) {f['side']:6} provinces: {counts.get(f['slot'], 0)}")
    print(f"  neutral provinces: {counts.get(NEUTRAL, 0)} ({neutralised} taken from unused slots)")


if __name__ == "__main__":
    main()
