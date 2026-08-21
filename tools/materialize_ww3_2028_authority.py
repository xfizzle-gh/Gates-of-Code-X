#!/usr/bin/env python3
"""Deterministically materialize the locked #225 fictional 2028 Earth3 province authority.

The compact sovereignty table is ordered by the exact authenticated selectable Earth3
province-ID set. It is the owner-reviewable result of the 2026-08-16 country/region
calibration pass. Ukraine sovereignty remains UKR; the explicit occupied-ID set changes
only starting military control. Exact DeepState geometry is intentionally not required by
the owner-approved approximation contract.
"""
from __future__ import annotations

import base64
import json
import sys
import zlib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gates_of_codex.earth3_campaign import load_earth3_authority
from gates_of_codex.scenario_2028_authority import (
    UKRAINE_FRONT_METHOD,
    authority_hash,
    load_authority_document,
    province_rows_hash,
    selectable_ids_hash,
    validate_province_authority_payload,
)

OUT = ROOT / "config" / "earth3" / "ww3_2028_province_authority.json"
NEUTRAL_GARRISON_AUTHORITY = ROOT / "src" / "gates_of_codex" / "data" / "neutral_garrisons" / "authority.json"
EXPECTED_COUNT = 3299

SOVEREIGN_CODES_B85 = 'c-rk+ZFb@~5WLV{!UPY=;sDRaOvwEYvXpR%a=T^ACWOtK`BBfZzSU~=mvpF){~R8SvN=2jzv`m*{S)wZERp~n?!{RD--Vag@_#Xpd+`<f@hD8q^_la>{(C6eqnkg~*VK6HvW<Nq4UE+tD_?r9EZvvzQq_J0tja0?^W0VI_z!@Fz+qn{Q61ZWu{s{uZ*$rPwA(r$Ro|9Xr=o|tZ2~mCs_NJ;!TACxx8PV7T0REWulMaJntC;xW@Gd(o8y2cxj@^m0Qp@(9<pf#){#1UUY{Pw!)&88vj4Vh3^{dv8gxy8_Mhdq;~t(TACZ?{>r*dpDVozRU<pk<zW%A0bMA5h-7*I_&vWWi1}G>)Hmf?|t*&BPp>4eKznBlu`YYk>A=CO*1ly>o7Gu5J4t%QScbSFVzWx?)EX)<iZTG$|0;bl1K6O30>z_*}uk6^?Ps3_cKXv>uZ0eVES-FpR>KwZ{6c=4j+ugIPbM0jXd6!@x7+3S@2M}?rF1^Io#(E;^_pCj+XP;lrhY0*f|7~?%jB=AMTYnZ=IJUbUn3vNocMSMQDS#FLeJRM0UvImIVM_jSJ^*}h{r6B*tI>VWX**W#!R{G>eIM*6ZMROZ^wKkc`G7t_M|bmE60fu|<R$S(we{gM0JQmgIM)F@=QuCVM9x`xFY1Q^dl=$1zlXjXc#HB6atdG4oc#2@D<eqz)!S<X&hW?fqX&(Z=$W?&{chJT$om+B<EDTyI3GK|6u>Vx|8aZet#%jE_*#A&jM>G%P<INLALq$-3fL^HgEZ%o3r`<|zUV83l-<N~^x?JRo{se$_TE|Nlzm`j;~d+<0&>sl_rP;<HmseYwg#awEl>94-jB_Ri)(y56<ee4tZ{0bX>Uz2#>yBf;)lmu><#T~ELHzeH`p!`gB`$$=~{Sk+k1hzx_)dY$5QRa=rm^U=ES?h*i9XAXv&MO-UUEEX_@Mau{k{oIcs(8{)O$e4RxT>fHZ+^gEMOFR!yVMzkAa6?Ao?G>#B2ESMBGN{>-&`r*yo^B=xhD4!8N;Y#G*v&l1m=oMF8S;GSrjb&yA!m^8-N948l`w?$L50k^%_xpi5G=-EnYe>yhnRNTtSS}(3OH@@ZF?^&6QJe9>rvkZC?HV*b)?;XQkq=~6(evVH|dFtJjFb&&4?J%or6;ry4@|0_}`Vcx0`D6E(Q)4J?85c$x^NlfKu@5kBtE(tm7}vLZZuvs*D6P)ZJ37)k((v-1iiv4_4s(Vb3!4`0u6p1+kUi?-hx5?U(%W~=i)TFSc_(M|%Raf*U{7yuvKzACk-7q7di?}Hqq)+O{Dl3&KXn9bVbsHyycccWOP=x-#=#eB17Gkgx$)s+F}O3C^4rO4-WwLrpM`&+{*tc2g6EI^7tSg2;h)f#vExs@bD;mAegyhqd_#34$FaU0ZTQ#^$}efVe${D!&PDA6g?%r9{zHGCWlVz(^iTO!9|gKI>Xp;hy#urNNh+tqdGFpzT<LxF!@|9!=f4Gd)q!4+S7R|U+74=mM3h&$s*cB5Ag`-m?ScL=>u_IK&NB|^d7(dNV_f<cCH0<#{x0<i<*PkQf#w~b0V!Fpu^@flXV0{Pe63?fdDz)Nkk5S6Ks$)=-hl-B=dv#PTAVj!FZMc|<&Ng08RHG!n*^O7-^zHr30}18WBZ|uNW^P}4qoij>L==0-o5huj`D-@I(-*>!KX-*U&*`JJMenEH@MiTJ#?`+z28ve=pEHl+u}1>4`mi(b-lJzeLut38uPy%iMg@%d-_hr=e>GCR+%>T9)aWJ^r^_9J;r*5ul^^2vLRPS@NCjo<{c)${I8nZy>j3$((ys2_02;shB*>n{OQm*a*QE3_m$Mmso0kK33J~4@a=}iitIhA-IHKHn70cW=Tli6VzszObneP%%QH3=ZToXQ@Wbfa!(U*&-nVNTwJ~XDdw2h=uk%1Zu+w#|_^MrJ_V7RMSLxU'
COUNTRY_LABELS = {"ALB": "Albania", "ARM": "Armenia", "AUT": "Austria", "AZE": "Azerbaijan", "BEL": "Belgium", "BGR": "Bulgaria", "BIH": "Bosnia and Herzegovina", "BLR": "Belarus", "CHE": "Switzerland", "CYP": "Cyprus", "CZE": "Czechia", "DEU": "Germany", "DNK": "Denmark", "DZA": "Algeria", "EGY": "Egypt", "ESP": "Spain", "EST": "Estonia", "FIN": "Finland", "FRA": "France", "GBR": "United Kingdom", "GEO": "Georgia", "GRC": "Greece", "HRV": "Croatia", "HUN": "Hungary", "IRL": "Ireland", "ISL": "Iceland", "ISR": "Israel", "ITA": "Italy", "JOR": "Jordan", "KAZ": "Kazakhstan", "LBN": "Lebanon", "LBY": "Libya", "LTU": "Lithuania", "LUX": "Luxembourg", "LVA": "Latvia", "MAR": "Morocco", "MDA": "Moldova", "MKD": "North Macedonia", "MNE": "Montenegro", "NLD": "Netherlands", "NOR": "Norway", "POL": "Poland", "PRT": "Portugal", "PSE": "Palestine", "ROU": "Romania", "RUS": "Russia", "SAU": "Saudi Arabia", "SRB": "Serbia", "SVK": "Slovakia", "SVN": "Slovenia", "SWE": "Sweden", "SYR": "Syria", "TUN": "Tunisia", "TUR": "Turkey", "UKR": "Ukraine", "XKX": "Kosovo"}
NATO_COUNTRIES = frozenset(['ALB', 'BEL', 'BGR', 'CAN', 'CZE', 'DEU', 'DNK', 'ESP', 'EST', 'FIN', 'FRA', 'GBR', 'GRC', 'HRV', 'HUN', 'ISL', 'ITA', 'LTU', 'LUX', 'LVA', 'MKD', 'MNE', 'NLD', 'NOR', 'POL', 'PRT', 'ROU', 'SVK', 'SVN', 'SWE', 'TUR', 'USA'])
EXPANDED_ACTOR_IDS = frozenset(['alb', 'arm', 'aut', 'aze', 'bel', 'bgr', 'bih', 'blr', 'can', 'che', 'cyp', 'cze', 'deu', 'dnk', 'donbas', 'dprk', 'dza', 'egy', 'esp', 'est', 'fin', 'fra', 'gbr', 'geo', 'grc', 'hrv', 'hun', 'irl', 'irq', 'isl', 'isr', 'ita', 'jor', 'kpa_expeditionary', 'lbn', 'lby', 'ltu', 'lva', 'mar', 'mda', 'mkd', 'mlt', 'mne', 'nld', 'nor', 'pol', 'prc', 'prt', 'rou', 'rus', 'srb', 'svk', 'svn', 'swe', 'syr', 'tun', 'tur', 'ukr', 'ukr_ildu', 'usa', 'wagner'])
RUSSIAN_CONTROLLED_UKRAINE = frozenset(['e3_1208', 'e3_1750', 'e3_1948', 'e3_1951', 'e3_1952', 'e3_1953', 'e3_1954', 'e3_1955', 'e3_1956', 'e3_1957', 'e3_1958', 'e3_1960', 'e3_2794', 'e3_2795', 'e3_2796', 'e3_2797', 'e3_2798', 'e3_2799', 'e3_2802', 'e3_2807', 'e3_3378', 'e3_3380'])
REGION_BY_COUNTRY = {
    **{code: "western_central_europe" for code in "AUT BEL CHE CZE DEU DNK ESP EST FIN FRA GBR HUN IRL ISL ITA LTU LUX LVA NLD NOR POL PRT SVK SWE".split()},
    **{code: "balkans" for code in "ALB BIH BGR HRV GRC MKD MNE ROU SRB SVN XKX".split()},
    **{code: "eastern_europe" for code in "BLR MDA RUS UKR".split()},
    **{code: "western_asia" for code in "ARM AZE CYP GEO KAZ TUR".split()},
    **{code: "middle_east" for code in "ISR JOR LBN PSE SAU SYR".split()},
    **{code: "north_africa" for code in "DZA EGY LBY MAR TUN".split()},
}


def _articulation_points(adjacency: dict[str, tuple[str, ...]]) -> frozenset[str]:
    sys.setrecursionlimit(max(10000, len(adjacency) * 4))
    discovery: dict[str, int] = {}
    low: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    points: set[str] = set()
    clock = 0

    def visit(node: str) -> None:
        nonlocal clock
        discovery[node] = low[node] = clock
        clock += 1
        children = 0
        for neighbor in adjacency[node]:
            if neighbor not in discovery:
                parent[neighbor] = node
                children += 1
                visit(neighbor)
                low[node] = min(low[node], low[neighbor])
                if parent.get(node) is None and children > 1:
                    points.add(node)
                if parent.get(node) is not None and low[neighbor] >= discovery[node]:
                    points.add(node)
            elif neighbor != parent.get(node):
                low[node] = min(low[node], discovery[neighbor])

    for node in sorted(adjacency):
        if node not in discovery:
            parent[node] = None
            visit(node)
    return frozenset(points)


def _sovereign_codes(province_ids: list[str]) -> dict[str, str]:
    packed = base64.b85decode(SOVEREIGN_CODES_B85.encode("ascii"))
    codes = zlib.decompress(packed).decode("ascii").split(",")
    if len(codes) != EXPECTED_COUNT or len(province_ids) != EXPECTED_COUNT:
        raise SystemExit(f"selectable-count mismatch: codes={len(codes)} ids={len(province_ids)}")
    return dict(zip(province_ids, codes, strict=True))


def _core_controller(province_id: str, sovereign: str) -> str:
    if sovereign == "UKR":
        return "rusa" if province_id in RUSSIAN_CONTROLLED_UKRAINE else "ukr"
    if sovereign == "RUS":
        return "rusa"
    if sovereign == "BLR":
        return "prc"
    if sovereign in NATO_COUNTRIES:
        return "nato"
    return "neutral"


def _expanded_controller(sovereign: str, core: str) -> str:
    if core == "ukr":
        return "ukr"
    if core == "rusa":
        return "rus"
    if core == "prc":
        return "prc"
    actor = sovereign.lower()
    if core == "nato":
        return actor if actor in EXPANDED_ACTOR_IDS else "nato"
    return actor


def main() -> int:
    earth3 = load_earth3_authority(ROOT)
    selectable = {str(row["id"]): dict(row) for row in earth3.provinces if not bool(row["is_water"])}
    province_ids = sorted(selectable)
    if len(province_ids) != EXPECTED_COUNT:
        raise SystemExit(f"expected {EXPECTED_COUNT} selectable provinces, got {len(province_ids)}")
    sovereign_by_id = _sovereign_codes(province_ids)

    garrison_doc = json.loads(NEUTRAL_GARRISON_AUTHORITY.read_text(encoding="utf-8"))
    garrison_by_id = {str(row["province_id"]): row for row in garrison_doc.get("provinces", [])}
    adjacency = {
        province_id: tuple(sorted(str(value) for value in selectable[province_id]["neighbors"] if str(value) in selectable))
        for province_id in province_ids
    }
    chokepoints = _articulation_points(adjacency)

    rows: list[dict[str, object]] = []
    for province_id in province_ids:
        source = selectable[province_id]
        sovereign = sovereign_by_id[province_id]
        core = _core_controller(province_id, sovereign)
        garrison = garrison_by_id.get(province_id) if core == "neutral" else None
        row: dict[str, object] = {
            "province_id": province_id,
            "country_label": COUNTRY_LABELS[sovereign],
            "region_label": REGION_BY_COUNTRY[sovereign],
            "sovereign_owner": sovereign,
            "military_controller": core,
            "core_controller": core,
            "expanded_controller": _expanded_controller(sovereign, core),
            "garrison_actor": f"garrison:{province_id}" if garrison else None,
            "neutral_garrison_region": garrison.get("neutral_garrison_region") if garrison else None,
            "neutral_garrison_tier": garrison.get("neutral_garrison_tier") if garrison else None,
            "neighbors": list(adjacency[province_id]),
            "hostile_neighbors": [],
            "metrics": {
                "graph_degree": len(source["neighbors"]),
                "selectable_degree": len(adjacency[province_id]),
            },
            "strategic": {
                "is_chokepoint": province_id in chokepoints,
                "strategic_value": float(len(adjacency[province_id]) + (5 if province_id in chokepoints else 0)),
            },
        }
        if sovereign == "UKR":
            row.update({
                "front_reference_date": "2026-08-12",
                "front_source": "deepstate_approximate",
                "front_method": UKRAINE_FRONT_METHOD,
            })
        rows.append(row)

    coalition = {"nato": "west", "ukr": "west", "rusa": "east", "prc": "east", "neutral": "neutral"}
    by_id = {str(row["province_id"]): row for row in rows}
    for row in rows:
        own = coalition[str(row["core_controller"])]
        if own not in {"west", "east"}:
            continue
        row["hostile_neighbors"] = sorted(
            neighbor for neighbor in row["neighbors"]
            if coalition[str(by_id[neighbor]["core_controller"])] in {"west", "east"}
            and coalition[str(by_id[neighbor]["core_controller"])] != own
        )

    authority_document = load_authority_document(ROOT)
    counts_counter = Counter(str(row["core_controller"]) for row in rows)
    counts = {power: int(counts_counter.get(power, 0)) for power in ("nato", "ukr", "rusa", "prc")}
    mean = sum(counts.values()) / 4
    lower = mean * 0.85
    upper = mean * 1.15
    deficits = {power: max(0, int(lower - count + 0.999999999)) for power, count in counts.items() if count < lower}
    surpluses = {power: max(0, int(count - upper + 0.999999999)) for power, count in counts.items() if count > upper}

    payload = {
        "schema": "gates-of-codex.ww3-2028-province-authority",
        "version": 1,
        "authority_id": "earth3_ww3_2028_v1",
        "provenance": {
            "earth3_dataset_sha256": earth3.dataset_sha256,
            "earth3_geometry_sha256": earth3.geometry_sha256,
            "earth3_included_ids_sha256": earth3.included_ids_sha256,
            "earth3_selectable_ids_sha256": selectable_ids_hash(province_ids),
            "authority_document_sha256": authority_hash(authority_document),
            "ukraine_front_method": UKRAINE_FRONT_METHOD,
            "generator": "tools/materialize_ww3_2028_authority.py",
            "country_mapping_method": "earth3_city_calibrated_country_centroid_assignment",
            "owner_visual_audit_required": True,
        },
        "controller_balance": {
            "counts": counts,
            "mean": mean,
            "lower_bound": lower,
            "upper_bound": upper,
            "deficits": deficits,
            "surpluses": surpluses,
            "within_target": not deficits and not surpluses,
        },
        "rows_sha256": province_rows_hash(rows),
        "provinces": rows,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    validate_province_authority_payload(payload, root=ROOT)
    print(json.dumps({"rows": len(rows), "counts": counts, "deficits": deficits, "surpluses": surpluses, "rows_sha256": payload["rows_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
