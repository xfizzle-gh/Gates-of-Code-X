"""Author data/scenario_2032.json: the "2032 Continental War" draft mapped onto the province map.

Ownership is written as rules over the recovered (1939) province database so the intent stays readable:
modern states are approximated from 1939 owners plus explicit name lists. Unnamed provinces are referred
to by number (see `python tools/render_scenario_map.py --ids`).

    python tools/author_scenario_2032.py
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DB = glob.glob(str(ROOT / "recovered" / "unity" / "ExportedProject" / "Assets" / "TextAsset" / "province_database_*.json"))[0]

O_GERMANY, O_USSR, O_UK, O_POLAND, O_FINLAND, O_FRANCE, O_ROMANIA, O_ESTONIA, O_LATVIA, O_LITHUANIA = 0, 1, 3, 4, 5, 10, 12, 13, 14, 15

# --- BLUFOR ---------------------------------------------------------------------------------------
GERMANY_2032 = ["Baden", "Brandenburg", "Franken", "Hannover", "Hessen", "Holstein", "Mecklenburg", "Moselland",
                "Niederbayern", "Oberbayern", "Rhineland", "Sachsen", "Schleswig", "Thuringen", "Vorpommern",
                "Wester Ems", "Westfalen"]
# Bundeswehr's Lithuania brigade area plus Latvia, which has no faction of its own.
GER_FORWARD = ["Kaunas", "Siauliai", "Zemaitija", "Wilno", "Kurzeme", "Latgale", "Riga", "Vidzeme", "Zemgale", "Zemgale2"]

# US Army: Poland as its area of responsibility (V Corps forward HQ), plus the UK air-base region as a rear base.
POLAND_2032 = ["Bialystok", "Danzig", "Gdynia", "Katowice", "Kielce", "Krakow", "Lodz", "Lublin", "Plock", "Poznan",
               "Warszawa", "Hinterpommern", "Niederschlesien", "Oberschlesien", "Ermland Masuren", "Ostmark"]
USA_REAR = ["East Anglia"]
USA_UKRAINE = ["Kyiv", "Zhytomyr", "Chernigov", "Sumy", "Kharkov", "Poltava", "Cherkasy", "Lwow", "Wolyn",
               "Stanislawow", "Proskuriv", "Podkarpatska Rus"]

FRANCE_COLONIAL_1939 = ["Aleppo", "Algerian Desert", "Algiers", "Casablanca", "Constantine", "Deir az Zur", "Gabes",
                        "Lebanon", "Marrakech", "Syria", "Tunis"]
# France leads NATO's Romania formation.
ROMANIA_2032 = ["Banat", "Bucovina", "Crisana", "Dobrudja", "Moldova", "North Transylvania", "Oltenia", "South Transylvania"]
FRA_UKRAINE = ["Odessa", "Mykolaiv", "Vinnytsia", "Dnipropetrovsk"]

# USMC: prepositioned in northern Norway, Estonia's littoral, and the eastern Mediterranean bases.
USMC = ["Harju", "Parnu", "Saaremaa", "Tartu", "Virumaa", "Crete", "Cyprus", "#509", "#508", "#511", "#512", "#507", "#505"]

# IDF: Israel plus the buffer it holds in Lebanon and southern Syria.
IDF = ["Palestine", "Lebanon", "Syria"]

# United Arab Force: Egypt, Jordan and the Arabian peninsula / Gulf states.
UAF = ["Cairo", "Alexandria", "Suez", "Sinai", "Matrouh", "Western Desert", "Eastern Desert", "Aswan", "Jordan",
       "#77", "#71", "#68", "#63", "#57", "#59", "#60", "#70", "#73", "#69", "#82", "#58", "#44"]

# --- OPFOR ----------------------------------------------------------------------------------------
# Former Soviet republics that are independent and not in this war.
USSR_NOW_NEUTRAL = ["Georgia", "Armenia", "Azerbaijan", "Abkhazia", "Ashkhabad", "Tashauz", "Khiva", "Karakalpakstan",
                    "Ust Urt", "Guryev", "Uralsk"]
# Ukraine has no faction of its own (UAF is the United Arab Force); it is split between the US Army and France above.
UKRAINE_FREE = USA_UKRAINE + FRA_UKRAINE
# Eastern Europe Rebels: "generic Donbas and Balkan style irregular force" (WF team). Russian-held Ukraine,
# Transnistria and the Moldovan republic, and a Balkan bloc.
EER = ["Stalino", "Voroshilovgrad", "Zaporozhe", "Kherson", "Crimea", "Balta Tiraspol", "Bessarabia", "Northern Bessarabia",
       "Serbia", "Vojvodina", "Kosovo", "Bosnia", "Montenegro"]
# AFRF beyond Russia proper: Kaliningrad, Belarus (incl. its 1939-Polish west), ceded Finnish land, the Suwalki corridor.
RUS_EXTRA = ["Koningsberg", "Nowogrodek", "Wilejka", "Polesie", "Karjala", "Petsamo", "Suwalki"]

# Global Revolutionary Movement: northern/eastern Syria, Iraq, Yemen and Libya.
GRM = ["Aleppo", "Deir az Zur", "Yemen", "#108", "#84", "#100",
       "Tripoli", "Tripolitania", "Sirte", "Fezzan", "El Agheila", "Benghasi", "Derna", "Cyrenaica", "Libyan Desert"]
# PLA: expeditionary lodgement on Iran's southern coast, pushed into southern Iraq toward Kuwait.
PLA = ["#75", "#76", "#74", "#96", "#88", "Al Hajara"]

# Factions with no Manpower-specialization province in their territory cannot raise battalions at all.
SPECIALIZATION_OVERRIDES = {"Stalino": "Manpower", "Serbia": "Manpower", "Crete": "Manpower", "Palestine": "Manpower", "#75": "Manpower", "#63": "Manpower", "Tripoli": "Manpower"}
# Home-base yields for factions whose map footprint understates what they can field (reinforcement from off-map
# or national mobilisation). Values are (Manpower, Ammunition) per turn for that province.
YIELD_OVERRIDES = {"Palestine": (160, 160), "#75": (150, 170), "Crete": (120, 150), "#509": (60, 80), "Stalino": (120, 100),
                   "Serbia": (80, 60), "East Anglia": (150, 200), "Aleppo": (120, 120), "#63": (80, 120)}


def main() -> None:
    db = json.load(open(SRC_DB, encoding="utf-8"))["Provinces"]

    def label(p):
        n = p["DisplayName"]
        return "#" + n[len("province_"):].lstrip("0") if n.startswith("province_") else n

    by_label = {}
    for p in db:
        by_label.setdefault(label(p), []).append(p)
    owner = {}
    unknown = []

    def give(tag, names):
        for n in names:
            if n not in by_label:
                unknown.append(n)
                continue
            for p in by_label[n]:
                owner[p["ProvinceId"]] = tag

    for p in db:
        n = label(p)
        if p["Owner"] == O_USSR and n not in USSR_NOW_NEUTRAL and n not in UKRAINE_FREE:
            owner[p["ProvinceId"]] = "rus"
        elif p["Owner"] == O_FRANCE and n not in FRANCE_COLONIAL_1939:
            owner[p["ProvinceId"]] = "fra"
    give("rus", RUS_EXTRA)
    give("reb", EER)
    give("ger", GERMANY_2032 + GER_FORWARD)
    give("usa", POLAND_2032 + USA_REAR + USA_UKRAINE)
    give("fra", ROMANIA_2032 + FRA_UKRAINE)
    give("usmc", USMC)
    give("idf", IDF)
    give("uaf", UAF)
    give("grm", GRM)
    give("pla", PLA)
    if unknown:
        raise SystemExit(f"unknown province names: {unknown}")

    base = json.load(open(ROOT / "data" / "scenario_europe.json", encoding="utf-8"))
    for f in base["factions"]:
        f.pop("flag", None)
    names = {"usa": "US Army", "usmc": "USMC", "uaf": "United Arab Force", "ger": "Bundeswehr", "fra": "France", "idf": "IDF",
             "grm": "GRM", "reb": "EER", "rus": "AFRF", "pla": "PLA"}
    for f in base["factions"]:
        f["name"] = names[f["tag"]]
    overrides = {}
    for n, spec in SPECIALIZATION_OVERRIDES.items():
        for p in by_label[n]:
            overrides[p["ProvinceId"]] = spec
    yields = {}
    for n, (mp_y, ammo_y) in YIELD_OVERRIDES.items():
        for p in by_label[n]:
            yields[p["ProvinceId"]] = {"Manpower": mp_y, "Ammunition": ammo_y}
            p["ResourceYield"]["Manpower"], p["ResourceYield"]["Ammunition"] = mp_y, ammo_y
    scenario = {
        "id": "continental_war_2032",
        "status": "DRAFT for owner review. Province ownership is a first pass from a geopolitical brief; see docs/scenario-2032.md.",
        "theater": "ww3",
        "startDate": "2032-09-05",
        "sides": base["sides"],
        "factions": base["factions"],
        "startingResources": base["startingResources"],
        "diplomacy": base["diplomacy"],
        "specializationOverrides": overrides,
        "yieldOverrides": yields,
        "provinces": dict(sorted(owner.items())),
    }
    out = ROOT / "data" / "scenario_2032.json"
    out.write_text(json.dumps(scenario, indent=1) + "\n", encoding="utf-8")

    # balance sheet
    by_id = {p["ProvinceId"]: p for p in db}
    print(f"{'tag':5} {'prov':>4} {'MP':>5} {'supply':>6} {'manpowerProv':>12}  borders enemy")
    side = {f["tag"]: f["side"] for f in base["factions"]}
    for f in base["factions"]:
        tag = f["tag"]
        mine = [by_id[i] for i, t in owner.items() if t == tag]
        mp = sum(p["ResourceYield"]["Manpower"] for p in mine)
        sup = sum(p["ResourceYield"]["Ammunition"] for p in mine)
        spawn = sum(1 for p in mine if overrides.get(p["ProvinceId"], p["Specialization"]) == "Manpower")
        enemies = sorted({owner[n] for p in mine for n in p["NeighborProvinceIds"] if n in owner and side[owner[n]] != side[tag]})
        print(f"{tag:5} {len(mine):4} {mp:5} {sup:6} {spawn:12}  {', '.join(enemies) or 'NONE'}")
    print(f"neutral: {len(db) - len(owner)}")
    print("wrote", out)


if __name__ == "__main__":
    main()
