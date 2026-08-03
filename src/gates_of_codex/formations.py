from __future__ import annotations

from .models import (
    Battalion,
    BattalionRosterEntry,
    BattalionType,
    CampaignState,
    Faction,
    Formation,
    FormationKind,
)


FORMATION_DEPLOYMENTS: dict[str, str] = {
    "nato-us-armored": "Wester Ems",
    "nato-us-airborne": "province_0357",
    "nato-deu-panzergrenadier": "Hannover",
    "nato-pol-mechanized": "Warszawa",
    "nato-gbr-battlegroup": "Sussex",
    "ukr-mechanized": "Lwow",
    "ukr-air-assault": "Zhytomyr",
    "rusa-guards-tank": "Minsk",
    "rusa-motor-rifle": "Vitebsk",
    "rusa-vdv": "Pskov",
    "rusa-naval-infantry": "Leningrad",
    "rusa-prk-expeditionary": "province_0509",
    "prc-western-combined-arms": "province_0501",
    "prc-central-asia-support": "province_0508",
}


def default_formations() -> dict[str, Formation]:
    values = [
        Formation("nato-us-armored", "United States Armored Brigade", Faction.NATO, "USA", FormationKind.ARMORED_BRIGADE, "western_europe", ["armor"], ["infantry", "tank", "ifv"]),
        Formation("nato-us-airborne", "United States Airborne Brigade", Faction.NATO, "USA", FormationKind.AIRBORNE_BRIGADE, "western_europe", ["airborne", "light"], ["infantry", "recon", "artillery"]),
        Formation("nato-deu-panzergrenadier", "German Panzergrenadier Brigade", Faction.NATO, "DEU", FormationKind.PANZERGRENADIER_BRIGADE, "central_europe", ["mechanized"], ["infantry", "ifv", "tank"]),
        Formation("nato-pol-mechanized", "Polish Mechanized Brigade", Faction.NATO, "POL", FormationKind.MECHANIZED_BRIGADE, "eastern_flank", ["mechanized"], ["infantry", "ifv", "artillery"]),
        Formation("nato-gbr-battlegroup", "British Battlegroup", Faction.NATO, "GBR", FormationKind.BATTLEGROUP, "western_europe", ["combined_arms"], ["infantry", "tank", "recon"]),
        Formation("ukr-mechanized", "Ukrainian Mechanized Brigade", Faction.UKRAINE, "UKR", FormationKind.MECHANIZED_BRIGADE, "ukraine", ["mechanized"], ["infantry", "ifv", "artillery"]),
        Formation("ukr-air-assault", "Ukrainian Air Assault Brigade", Faction.UKRAINE, "UKR", FormationKind.AIR_ASSAULT_BRIGADE, "ukraine", ["air_assault", "light"], ["infantry", "recon", "artillery"]),
        Formation("rusa-guards-tank", "Russian Guards Tank Brigade", Faction.RUSSIA, "RUS", FormationKind.ARMORED_BRIGADE, "western_russia", ["guards", "armor"], ["tank", "ifv", "infantry"]),
        Formation("rusa-motor-rifle", "Russian Motor Rifle Brigade", Faction.RUSSIA, "RUS", FormationKind.MECHANIZED_BRIGADE, "western_russia", ["motor_rifle"], ["infantry", "ifv", "artillery"]),
        Formation("rusa-vdv", "Russian VDV Air Assault Brigade", Faction.RUSSIA, "RUS", FormationKind.AIR_ASSAULT_BRIGADE, "western_russia", ["vdv", "air_assault"], ["infantry", "recon", "vehicle"]),
        Formation("rusa-naval-infantry", "Russian Naval Infantry Brigade", Faction.RUSSIA, "RUS", FormationKind.NAVAL_INFANTRY_BRIGADE, "baltic", ["naval_infantry"], ["infantry", "ifv", "artillery"]),
        Formation("rusa-prk-expeditionary", "North Korean Expeditionary Brigade", Faction.RUSSIA, "PRK", FormationKind.EXPEDITIONARY_BRIGADE, "central_asia", ["foreign_contingent"], ["infantry", "artillery", "tank"], True, "Provisional Russia-aligned contingent pending Code:X roster audit."),
        Formation("prc-western-combined-arms", "PLA Western Combined-Arms Brigade", Faction.PRC, "PRC", FormationKind.COMBINED_ARMS_BRIGADE, "central_asia", ["western_theater"], ["infantry", "ifv", "tank"]),
        Formation("prc-central-asia-support", "PLA Central Asian Support Group", Faction.PRC, "PRC", FormationKind.SUPPORT_GROUP, "central_asia", ["expeditionary_support"], ["artillery", "air_defense", "vehicle"]),
    ]
    return {formation.formation_id: formation for formation in values}


def seed_formation_battalions(state: CampaignState) -> None:
    for index, (formation_id, province_id) in enumerate(FORMATION_DEPLOYMENTS.items(), 1):
        if province_id not in state.provinces:
            raise ValueError(f"Formation deployment references missing province: {province_id}")
        formation = state.formations[formation_id]
        battalion_id = f"formation-{index:02d}"
        state.battalions[battalion_id] = Battalion(
            battalion_id=battalion_id,
            faction=formation.faction,
            province_id=province_id,
            formation_id=formation_id,
            battalion_type=_battalion_type(formation.kind),
            roster=[BattalionRosterEntry(f"placeholder({formation.faction.value})", quantity=1)],
            is_player_controlled=formation.faction == state.selected_faction,
        )
        state.provinces[province_id].owner = formation.faction


def _battalion_type(kind: FormationKind) -> BattalionType:
    if kind == FormationKind.ARMORED_BRIGADE:
        return BattalionType.ARMOR
    if kind in (FormationKind.MECHANIZED_BRIGADE, FormationKind.PANZERGRENADIER_BRIGADE):
        return BattalionType.MECHANIZED
    if kind == FormationKind.SUPPORT_GROUP:
        return BattalionType.SUPPORT
    if kind in (FormationKind.AIRBORNE_BRIGADE, FormationKind.AIR_ASSAULT_BRIGADE, FormationKind.NAVAL_INFANTRY_BRIGADE):
        return BattalionType.INFANTRY
    return BattalionType.COMBINED_ARMS
