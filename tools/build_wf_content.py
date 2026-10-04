"""Generate WarFighter unit catalogs, research trees and portraits for the campaign application.

Reads the installed WF mod (read-only):
  resource/set/dynamic_campaign/unit_research_<tag>.set   research nodes, costs, prerequisites, grid
  resource/set/multiplayer/units/wf_roster_conquest.inc    expanded conquest roster (units, crews, costs)
  localizations/default.pak + loose .pot                   display names
  resource/interface/scene/portrait_squad/<id>_02|_03.png  portraits (normal / locked)

Writes into campaign/Assets/Resources:
  WfContent/GohUnitCatalog_<tag>.asset, WfContent/GohResearchTree_<tag>.asset
  GohPortraits/<id>_02.png, <id>_03.png
and a coverage report to build/wf-content-report.json.

    python tools/build_wf_content.py
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WF = Path(json.loads((ROOT / "tools" / "paths.json").read_text(encoding="utf-8"))["WF"])
PROJECT = ROOT / "campaign"
OUT = PROJECT / "Assets" / "Resources" / "WfContent"
PORTRAITS_OUT = PROJECT / "Assets" / "Resources" / "GohPortraits"
PORTRAITS_SRC = WF / "resource" / "interface" / "scene" / "portrait_squad"

TAGS = ["usa", "usmc", "uaf", "ger", "fra", "idf", "grm", "reb", "rus", "pla"]
CATALOG_SCRIPT_GUID = "eb94a793f01c4149d20650421c323aa7"
TREE_SCRIPT_GUID = "0c43762076243dd4e842bd69ed531ff3"

# roster {button} -> (GohUnitSection, GohUnitCategory, research tree section label)
BUTTONS = {
    "inf1": (1, 1, "Infantry"),
    "inf2": (2, 1, "Support Infantry"),
    "empl": (3, 2, "Emplacements"),
    "vehicles": (4, 3, "Vehicles"),
    "tanks": (5, 4, "Armor"),
}


def guid_for(key: str) -> str:
    return hashlib.md5(("wfcampaign:" + key).encode("utf-8")).hexdigest()


def yaml_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


# ---------------------------------------------------------------- roster

FIELD = {
    "content": re.compile(r'\{content "([^"]*)"\}'),
    "tags": re.compile(r'\{tags "([^"]*)"\}'),
    "button": re.compile(r'\{button "([^"]*)"\}'),
    "cost": re.compile(r"\{cost ([-\d.]+)\}"),
    "factor": re.compile(r"\{squad_cost_factor ([-\d.]+)\}"),
    "cp": re.compile(r"\{cp ([-\d.]+)\}"),
    "stage": re.compile(r"\{research_stage (\d+)\}"),
}


def parse_roster():
    path = WF / "resource" / "set" / "multiplayer" / "units" / "wf_roster_conquest.inc"
    breeds, units = {}, {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r'^\{"([^"]+)"', line)
        if not m:
            continue
        uid = m.group(1)
        f = {k: (rx.search(line).group(1) if rx.search(line) else None) for k, rx in FIELD.items()}
        if uid.startswith("mp/"):
            breeds[uid] = float(f["cost"] or 0)
        elif f["content"] is not None:
            units[uid] = f
    return breeds, units


def unit_cost(f, breeds, missing):
    members = re.findall(r"(mp/[^\s:()]+):(\d+)", f["content"])
    crew = 0.0
    for breed, n in members:
        if breed not in breeds:
            missing.add(breed)
        crew += breeds.get(breed, 0.0) * int(n)
    cost = float(f["cost"] or 0) + crew * float(f["factor"] or 1)
    return max(0, round(cost)), sum(int(n) for _, n in members)


# ---------------------------------------------------------------- names

def parse_names():
    names = {}
    ctx = re.compile(r'msgctxt "desc/(?:squad|entity)/([^"]+)"\s*\r?\n\s*msgid "([^"]*)"')
    texts = []
    with zipfile.ZipFile(WF / "localizations" / "default.pak") as z:
        for n in z.namelist():
            if n.endswith(".pot") and "/mission/" not in n:
                texts.append(z.read(n).decode("utf-8", errors="replace"))
    for p in (WF / "localizations" / "default").rglob("*.pot"):
        texts.append(p.read_text(encoding="utf-8", errors="replace"))
    for t in texts:
        for uid, name in ctx.findall(t):
            name = re.sub(r"</?c[^>]*>", "", name).strip()
            if name:
                names.setdefault(uid.lower(), name)
    return names


# ---------------------------------------------------------------- research

NODE = re.compile(r'^\{(tech )?"([^"]+)" requires "([^"]*)" costs (\d+) position (-?\d+) (-?\d+)\}')


def parse_research(tag):
    path = WF / "resource" / "set" / "dynamic_campaign" / f"unit_research_{tag}.set"
    nodes = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        m = NODE.match(line)
        if m:
            nodes.append({"id": m.group(2), "tech": bool(m.group(1)), "requires": m.group(3).split(),
                          "cost": int(m.group(4)), "pos": (int(m.group(5)), int(m.group(6)))})
        elif line.startswith("{positions"):
            # Units placed on the grid with no research requirement.
            for uid, x, y in re.findall(r'\{"([^"]+)" (-?\d+) (-?\d+)\}', line):
                nodes.append({"id": uid, "tech": False, "requires": [], "cost": 0, "pos": (int(x), int(y)), "free": True})
    return nodes


# ---------------------------------------------------------------- full templates (battle export)

def yaml_dq(s: str) -> str:
    out = s.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
    return '"' + out + '"'


def extract_block(text: str, opener: str) -> str:
    """Return the brace-balanced block starting at `opener` (e.g. '{inventory'), or ''."""
    m = re.search(re.escape(opener) + r"(?=[\s}])", text, re.I)
    if not m:
        return ""
    depth, i = 0, m.start()
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[m.start():i + 1]
        i += 1
    return ""


class Templates:
    def __init__(self):
        self.breed_cache = {}
        self.pak = zipfile.ZipFile(WF / "resource" / "entity.pak")
        self.defs = {}
        for n in self.pak.namelist():
            if n.lower().endswith(".def"):
                self.defs.setdefault(Path(n).stem.lower(), n)

    def human(self, breed: str, count: int, tag: str, warnings: list) -> str | None:
        if breed not in self.breed_cache:
            p = WF / "resource" / "set" / "breed" / (breed + ".set")
            self.breed_cache[breed] = p.read_text(encoding="utf-8", errors="replace") if p.exists() else None
        text = self.breed_cache[breed]
        if text is None:
            warnings.append(f"breed file missing: set/breed/{breed}.set")
            return None

        def field(name):
            m = re.search(r"\{" + name + r'\s+"?([^"}\s]+)"?\s*\}', text)
            return m.group(1) if m else ""

        inv = extract_block(text, "{inventory")
        if not inv:
            warnings.append(f"no inventory block in breed {breed}")
        return (
            f"- Alias: {yaml_str(breed.rsplit('/', 1)[-1])}\n"
            f"  Count: {count}\n"
            f"  FactionTag: {tag}\n"
            "  Period:\n"
            f"  BreedPath: {yaml_str('set/breed/' + breed + '.set')}\n"
            f"  RawBreedText: {yaml_dq(text)}\n"
            f"  Skin: {yaml_str(field('skin'))}\n"
            f"  Portrait: {yaml_str(field('portrait'))}\n"
            f"  Icon: {yaml_str(field('icon'))}\n"
            f"  Nationality: {yaml_str(field('nationality'))}\n"
            "  Voice:\n"
            f"  RawInventoryBlock: {yaml_dq(inv)}\n"
            f"  RawArmorsBlock: {yaml_dq(extract_block(text, '{armors'))}\n"
            f"  RawPerksBlock: {yaml_dq(extract_block(text, '{perks'))}\n"
            f"  RawVeterancyBlock: {yaml_dq(extract_block(text, '{veterancy'))}\n")

    def entity_inventory(self, name: str, warnings: list):
        entry = self.defs.get(name.lower())
        if not entry:
            warnings.append(f"entity definition not found in entity.pak: {name}.def")
            return None, ""
        text = self.pak.read(entry).decode("utf-8", errors="replace")
        m = re.search(r'\{extender\s+"inventory"', text, re.I)
        inv = extract_block(text[m.start():], "{extender") if m else ""
        if not inv:
            # Inventory comes from an include/macro or the entity has none. Export needs a non-empty block.
            warnings.append(f"{name}: no literal inventory block in its .def; exported with an empty box")
            inv = '{extender "inventory"\n\t\t{box\n\t\t}\n\t}'
        return inv, entry

    def build(self, uid: str, f: dict, tag: str):
        """Return (yaml text of the Template mapping body, unit kind, error, warnings)."""
        warnings: list[str] = []
        content = f["content"]
        m = re.match(r"^\s*(\S+)\s*\(\s*(.*?)\s*\)\s*(.*)$", content)
        entity = None
        if m:
            entity = uid if m.group(1) == "*" else m.group(1)
            inside = re.findall(r"(mp/[^\s:()]+):(\d+)", m.group(2))
            after = re.findall(r"(mp/[^\s:()]+):(\d+)", m.group(3))
            if m.group(1) == "*":
                crew, humans = inside, after
            else:
                # Mechanized squad: vehicle crew breeds are the tx_* ones, the rest ride as passengers.
                crew = [b for b in inside if b[0].rsplit("/", 1)[-1].startswith("tx_")]
                humans = [b for b in inside if b not in crew] + after
        else:
            crew, humans = [], re.findall(r"(mp/[^\s:()]+):(\d+)", content)

        def humans_yaml(members, indent):
            out, keys, failed = [], [], False
            for breed, n in members:
                y = self.human(breed, int(n), tag, warnings)
                if y is None:
                    failed = True
                    continue
                out.append("".join(indent + ln + "\n" for ln in y.rstrip("\n").split("\n")))
                keys.append((breed.rsplit("/", 1)[-1], int(n)))
            return "".join(out), keys, failed

        h_yaml, h_keys, h_fail = humans_yaml(humans, "      ")
        error = ""
        member_keys = []
        ent_yaml = "      Entities: []\n"
        kind = "SingleHuman" if sum(n for _, n in h_keys) == 1 else "InfantrySquad"
        if entity:
            inv, entry = self.entity_inventory(entity, warnings)
            c_yaml, c_keys, c_fail = humans_yaml(crew, "        ")
            h_fail = h_fail or c_fail
            if inv is None:
                error = f"entity definition not found: {entity}"
                inv = ""
            ekind = {"tanks": "Tank", "empl": "Gun"}.get(f["button"], "Vehicle")
            kind = "Gun" if ekind == "Gun" else "Vehicle"
            ent_yaml = (
                "      Entities:\n"
                f"      - EntityName: {yaml_str(entity)}\n"
                f"        EntityKind: {ekind}\n"
                f"        RawEntityDefinition: {yaml_dq(content)}\n"
                f"        RawInventoryBlock: {yaml_dq(inv)}\n"
                f"        RawExtendersBlock: {yaml_str(entry)}\n"
                + ("        Crew:\n" + c_yaml if c_yaml else "        Crew: []\n")
                + "        Warnings: []\n")
            member_keys.append("entity:" + entity)
            member_keys += ["crew:" + a for a, _ in c_keys]
        for alias, n in h_keys:
            member_keys += ["human:" + alias] * n
        if h_fail and not error:
            error = "one or more breed files are missing"
        if not member_keys and not error:
            error = "unit has no members"
        body = (
            f"      CatalogRawName: {yaml_str(uid)}\n"
            f"      CampaignExportName: {yaml_str(uid)}\n"
            f"      FactionTag: {tag}\n"
            "      Period:\n"
            f"      UnitKind: {kind}\n"
            f"      RawConquestDefinition: {yaml_dq(content)}\n"
            "      SourceConquestFile: set/multiplayer/units/wf_roster_conquest.inc\n"
            + ("      Humans:\n" + h_yaml if h_yaml else "      Humans: []\n")
            + ent_yaml
            + "      CampaignSquads:\n"
            f"      - CampaignSquadName: {yaml_str(uid)}\n"
            f"        EntityFirst: {1 if entity else 0}\n"
            + ("        TemplateMemberKeys:\n" + "".join(f"        - {yaml_str(k)}\n" for k in member_keys)
               if member_keys else "        TemplateMemberKeys: []\n")
            + "      Warnings: []\n")
        return body, error, warnings


def write_template_cache(cache_entries):
    path = PROJECT / "Assets" / "Resources" / "GohFullUnitTemplateCache.asset"
    head = path.read_text(encoding="utf-8").split("  SourceGameDirectory:", 1)[0]
    path.write_text(
        head
        + f"  SourceGameDirectory: {yaml_str(str(WF))}\n"
        "  BuiltAtUtc: generated by tools/build_wf_content.py\n"
        "  BuilderVersion: wf-1\n"
        "  GameLogicPakSignature:\n"
        "  VehiclePakSignature:\n"
        "  Entries:\n" + "".join(cache_entries), encoding="utf-8", newline="\n")


# ---------------------------------------------------------------- output

HEADER = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!114 &11400000
MonoBehaviour:
  m_ObjectHideFlags: 0
  m_CorrespondingSourceObject: {{fileID: 0}}
  m_PrefabInstance: {{fileID: 0}}
  m_PrefabAsset: {{fileID: 0}}
  m_GameObject: {{fileID: 0}}
  m_Enabled: 1
  m_EditorHideFlags: 0
  m_Script: {{fileID: 11500000, guid: {guid}, type: 3}}
  m_Name: {name}
  m_EditorClassIdentifier:
"""

EMPTY_TEMPLATE = """    FullTemplate:
      CatalogRawName:
      CampaignExportName:
      FactionTag:
      Period:
      UnitKind:
      RawConquestDefinition:
      SourceConquestFile:
      Humans: []
      Entities: []
      CampaignSquads: []
      Warnings: []
"""


def write_asset(name, script_guid, body):
    path = OUT / f"{name}.asset"
    path.write_text(HEADER.format(guid=script_guid, name=name) + body, encoding="utf-8", newline="\n")
    path.with_name(path.name + ".meta").write_text(
        f"fileFormatVersion: 2\nguid: {guid_for(name)}\nNativeFormatImporter:\n  externalObjects: {{}}\n"
        "  mainObjectFileID: 11400000\n  userData:\n  assetBundleName:\n  assetBundleVariant:\n",
        encoding="utf-8", newline="\n")


def placeholder(dst, tag, display, locked):
    """WF has no portrait for this unit. Make an obvious stand-in card, never a borrowed picture."""
    from PIL import Image, ImageDraw, ImageFont
    bg, fg = ((38, 40, 44), (120, 120, 120)) if locked else ((58, 66, 78), (225, 225, 225))
    im = Image.new("RGB", (112, 140), bg)
    d = ImageDraw.Draw(im)
    d.rectangle([1, 1, 110, 138], outline=fg)
    try:
        big, small = ImageFont.truetype("arialbd.ttf", 22), ImageFont.truetype("arial.ttf", 11)
    except OSError:
        big = small = ImageFont.load_default()
    d.text((56, 30), tag.upper(), font=big, fill=fg, anchor="mm")
    words, lines, cur = display.split(), [], ""
    for w in words:
        if d.textlength((cur + " " + w).strip(), font=small) <= 100:
            cur = (cur + " " + w).strip()
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    for i, line in enumerate(lines[:5]):
        d.text((56, 62 + i * 13), line, font=small, fill=fg, anchor="mm")
    d.text((56, 130), "no WF portrait", font=small, fill=fg, anchor="mm")
    im.save(dst)


def copy_portrait(uid, suffix, report, tag, display):
    name = f"{uid}_{suffix}.png"
    src = PORTRAITS_SRC / name
    dst = PORTRAITS_OUT / name
    if src.exists():
        shutil.copyfile(src, dst)
    else:
        report["missingPortraits"].append(name)
        placeholder(dst, tag, display, locked=(suffix == "03"))
    dst.with_name(name + ".meta").write_text(
        f"fileFormatVersion: 2\nguid: {guid_for('portrait/' + name)}\nTextureImporter:\n"
        "  mipmaps:\n    enableMipMap: 0\n  textureType: 8\n  spriteMode: 1\n  alphaIsTransparency: 1\n"
        "  nPOTScale: 0\n  spritePixelsToUnits: 100\n", encoding="utf-8", newline="\n")
    return f"Assets/Resources/GohPortraits/{name}"


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    PORTRAITS_OUT.mkdir(parents=True, exist_ok=True)
    (OUT.with_name("WfContent.meta")).write_text(
        f"fileFormatVersion: 2\nguid: {guid_for('WfContent')}\nfolderAsset: yes\nDefaultImporter:\n  externalObjects: {{}}\n",
        encoding="utf-8", newline="\n")

    breeds, units = parse_roster()
    names = parse_names()
    templates = Templates()
    cache_entries = []
    summary = {}
    for tag in TAGS:
        report = {"missingPortraits": [], "missingNames": [], "researchNodesWithoutUnit": [], "missingBreeds": [], "hidden": [],
                  "templateErrors": [], "templateWarnings": []}
        nodes = parse_research(tag)
        node_ids = {n["id"].lower() for n in nodes if not n["tech"]}
        missing_breeds = set()

        # Catalog: every conquest roster unit carrying this faction tag, plus anything the tree names.
        mine = {uid: f for uid, f in units.items()
                if tag in (f["tags"] or "").split() and f["button"] in BUTTONS}
        for n in nodes:
            if not n["tech"] and n["id"] not in mine:
                if n["id"] in units and units[n["id"]]["button"] in BUTTONS:
                    mine[n["id"]] = units[n["id"]]
                else:
                    report["researchNodesWithoutUnit"].append(n["id"])

        entries = []
        for uid in sorted(mine):
            f = mine[uid]
            section, category, _ = BUTTONS[f["button"]]
            cost, members = unit_cost(f, breeds, missing_breeds)
            is_vehicle = "*" in f["content"]
            entry_type = 2 if is_vehicle else (0 if members > 1 else 1)
            display = names.get(uid.lower())
            in_tree = uid.lower() in node_ids
            has_portrait = (PORTRAITS_SRC / f"{uid}_02.png").exists()
            # No name, no portrait, not researchable: roster-internal squads (AI/garrison), not player picks.
            hidden = not display and not has_portrait and not in_tree
            if not display:
                report["missingNames"].append(uid)
                display = uid
            if hidden:
                report["hidden"].append(uid)
                portrait = locked = ""
            else:
                portrait = copy_portrait(uid, "02", report, tag, display)
                locked = copy_portrait(uid, "03", report, tag, display)
            t_body, t_error, t_warn = templates.build(uid, f, tag)
            if t_error:
                report["templateErrors"].append(f"{uid}: {t_error}")
            report["templateWarnings"] += [f"{uid}: {w}" for w in t_warn]
            cache_entries.append(
                f"  - CatalogAssetName: GohUnitCatalog_{tag}\n"
                f"    RawName: {yaml_str(uid)}\n"
                f"    FactionTag: {tag}\n"
                f"    HasFullTemplateData: {0 if t_error else 1}\n"
                f"    BuildError: {yaml_str(t_error) if t_error else ''}\n"
                + ("    Warnings:\n" + "".join(f"    - {yaml_str(w)}\n" for w in t_warn) if t_warn else "    Warnings: []\n")
                + "    Template:\n" + t_body)
            entries.append(
                f"  - RawName: {yaml_str(uid)}\n"
                f"    DisplayName: {yaml_str(display)}\n"
                f"    EntryType: {entry_type}\n"
                "    AppendFactionTagInCampaignScn: 0\n"
                f"    Category: {category}\n"
                f"    Section: {section}\n"
                f"    PortraitAssetPath: {yaml_str(portrait) if portrait else ''}\n"
                f"    LockedPortraitAssetPath: {yaml_str(locked) if locked else ''}\n"
                "    IsResearched: 0\n"
                # WF makes units without a research declaration available from the start
                # (all of fra and idf); mirror that instead of inventing prerequisites.
                f"    ForceResearchedOverride: {0 if in_tree else 1}\n"
                f"    HideFromBattalionManagement: {1 if hidden else 0}\n"
                "    ResearchKey:\n"
                f"    ManpowerCost: {cost}\n"
                "    SupportCost: 0\n"
                "    CostsImportedFromGame: 1\n"
                "    HasFullTemplateData: 0\n"
                "    FullTemplateBuildError:\n"
                "    FullTemplateBuildWarnings: []\n" + EMPTY_TEMPLATE)
        write_asset(f"GohUnitCatalog_{tag}", CATALOG_SCRIPT_GUID, "  Entries:\n" + "".join(entries))

        tree = [f"  FactionTag: {tag}\n  Nodes:\n"]
        for n in nodes:
            if n["tech"]:
                section = "TECH UPGRADES"
            elif n.get("free"):
                section = "Positions"
            else:
                f = mine.get(n["id"])
                section = BUTTONS[f["button"]][2] if f else "Unknown"
            req = "".join(f"    - {yaml_str(r)}\n" for r in n["requires"])
            tree.append(
                f"  - Id: {yaml_str(n['id'])}\n"
                f"    Kind: {1 if n['tech'] else 0}\n"
                f"    Section: {section}\n"
                f"    Cost: {n['cost']}\n"
                f"    GridPosition: {{x: {n['pos'][0]}, y: {n['pos'][1]}}}\n"
                + ("    Requires:\n" + req if req else "    Requires: []\n"))
        write_asset(f"GohResearchTree_{tag}", TREE_SCRIPT_GUID, "".join(tree))

        report["missingBreeds"] = sorted(missing_breeds)
        report["missingPortraits"] = sorted(set(report["missingPortraits"]))
        summary[tag] = {"catalogEntries": len(entries),
                        "researchUnitNodes": sum(1 for n in nodes if not n["tech"]),
                        "researchTechNodes": sum(1 for n in nodes if n["tech"]),
                        "entriesOutsideTree": sum(1 for u in mine if u.lower() not in node_ids),
                        **{k: len(v) for k, v in report.items()}, "detail": report}

    write_template_cache(cache_entries)
    print(f"export templates: {len(cache_entries)} units, "
          f"{sum(s['templateErrors'] for s in summary.values())} not exportable, "
          f"{sum(s['templateWarnings'] for s in summary.values())} warnings")
    out = ROOT / "build" / "wf-content-report.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(f"{'tag':5} {'units':>5} {'tree':>5} {'tech':>4} {'free':>5} {'hidden':>6} {'placeholder':>11} {'noName':>6} {'nodeNoUnit':>10} {'noBreed':>7}")
    for tag, s in summary.items():
        print(f"{tag:5} {s['catalogEntries']:5} {s['researchUnitNodes']:5} {s['researchTechNodes']:4} "
              f"{s['entriesOutsideTree']:5} {s['hidden']:6} {s['missingPortraits'] // 2:11} {s['missingNames']:6} "
              f"{s['researchNodesWithoutUnit']:10} {s['missingBreeds']:7}")
    print("report:", out)


if __name__ == "__main__":
    main()
