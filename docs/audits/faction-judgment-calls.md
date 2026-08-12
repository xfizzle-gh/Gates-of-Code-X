# Faction wiring judgment calls

Audit date: 2026-08-08

This document separates direct source-backed mappings from decisions made to complete individual-country rosters where Code:X does not provide a complete national conquest package.

The rule is:

- **High confidence** means Code:X directly supplies the formation, soldier family, vehicle, or research branch under that identity.
- **Medium confidence** means the national equipment is direct, but infantry, support, or progression needs a coalition-common bridge.
- **Low confidence** means the country is intentionally represented by a proxy or coalition fallback because no complete national source exists.

None of the medium- or low-confidence decisions should be presented as proof that Code:X contains a complete native faction.

## Cut-and-dry source-backed mappings

| Actor/component | Source-backed basis | Confidence |
|---|---|---|
| United States | Code:X USMC, Stryker, and armored branches | High |
| United Kingdom | Code:X `2022uk3` infantry, reconnaissance, mechanized, tank, artillery, and aviation content | High |
| Germany | Code:X `2022pz10` Bundeswehr/Panzergrenadier branch, with Dutch/Swedish stepping-stones filtered | High |
| Russia | Code:X regular army, VDV, armor, artillery, aviation, and support branches | High |
| Ukraine | Code:X 93rd, 47th, HUR/Kraken, Azov, 95th, 21st, armor, and artillery branches | High |
| PRC | Code:X PLA formation, armor, artillery, aviation, and research branches | High |
| KPA expeditionary infantry | Code:X `kor_*` squads embedded in the Russian `2022vdv106` branch | High |
| Donbas native branch | Code:X `2022rusldpr` branch and its `lud_*` / `ldnr_*` content | High |
| Wagner | Code:X `2022sto` Wagner/PMC content | High |
| French armor | Leclerc, Leclerc SXXI, Leclerc AZUR, AMX-10RC, Roland, and Tiger assets exist in Code:X | High for equipment identity |
| Italian armor | Centauro, Ariete, OTOMATIC, and FH70 exist in Code:X | High for equipment identity |
| Polish armor/artillery | T-72, Leopard 2PL, K2, 2S1, RM-70, and Rosomak exist in Code:X | High for equipment identity |
| Swedish armor | CV90/Strf and Strv assets exist in Code:X | High for equipment identity |
| Dutch mechanized equipment | YPR-765 and CV9035 assets exist in Code:X | High for equipment identity |
| Canadian armor | Leopard C2 MEXAS and Leopard 2A4M exist in Code:X | High for equipment identity |

## Winged / judgment-call decisions

### France

- **Exact component:** `nato_common_infantry` plus `france_national`
- **Source evidence:** Code:X has French armor and a small `fr_*` personnel family. The `fr_*` soldiers use USMC desert skins, US weapons, US nationality tags, and elite perks.
- **Inference:** Generic ARF/NATO infantry is used as temporary French line infantry. The `fr_*` family is restricted to elite/SOF roles rather than treated as the French Army line force.
- **Confidence:** Medium.
- **Best alternative:** Author a real French Army breed family with French skins, nationality, FAMAS/HK416F-era weapons, support roles, and national portraits before removing the ARF bridge.

### Poland

- **Exact component:** `nato_common_infantry` plus `poland_national`
- **Source evidence:** Code:X supplies a useful Polish equipment spine inside EFP, including Rosomak and major armor/artillery. It does not supply a clearly complete Polish line-infantry breed family.
- **Inference:** Generic NATO infantry carries the Polish equipment tree. US and British EFP elements are not treated as Polish national units.
- **Confidence:** Medium.
- **Best alternative:** Add a source-backed Polish infantry family and Polish crew/support wrappers while retaining the existing vehicle IDs.

### Italy

- **Exact component:** `nato_common_infantry` plus `italy_national`
- **Source evidence:** Code:X directly supplies Centauro, Ariete, OTOMATIC, and FH70 equipment but no complete Italian line-infantry family.
- **Inference:** Generic NATO infantry and support fill the missing personnel categories.
- **Confidence:** Medium.
- **Best alternative:** Add an Italian infantry/crew family and national transport progression.

### Finland

- **Exact component:** `nato_common_infantry`, `finland_national`, and NATO-common support
- **Source evidence:** Code:X supplies `t_55m_fin`, CV9030, and a Leopard 2A4 variant, but no complete Finnish infantry tree.
- **Inference:** Generic Nordic/NATO infantry represents the personnel layer. The T-55M is treated as a direct Finnish reserve/legacy option. The second self-audit removed `soviet_legacy_core` because the full Soviet pool was not justified by the source evidence.
- **Confidence:** Medium.
- **Best alternative:** Add Finnish infantry and support breeds, then restrict equipment to deliberately selected Finnish-service systems.

### Sweden

- **Exact component:** `nato_common_infantry` plus `sweden_national`
- **Source evidence:** Code:X supplies Swedish CV90/Strf and Strv equipment but no full Swedish soldier family.
- **Inference:** Generic NATO infantry fills the personnel gap.
- **Confidence:** Medium.
- **Best alternative:** Add Swedish infantry, crews, artillery, and air-defense personnel.

### Netherlands

- **Exact component:** `nato_common_infantry` plus `netherlands_national`
- **Source evidence:** Code:X supplies YPR-765/CV9035 equipment but no complete Dutch soldier family.
- **Inference:** Generic NATO infantry fills the personnel and support gap.
- **Confidence:** Medium.
- **Best alternative:** Add Dutch infantry and crew breeds.

### Canada

- **Exact component:** `nato_common_infantry` plus `canada_national`
- **Source evidence:** Code:X supplies both Leopard C2 MEXAS and Leopard 2A4M, but no complete Canadian infantry branch.
- **Inference:** Generic NATO infantry and common support represent the missing Canadian personnel layer. The second self-audit added Leopard 2A4M to the Canadian national component because its omission left the directly supported armor progression incomplete.
- **Confidence:** Medium.
- **Best alternative:** Add Canadian infantry, LAV-family units, artillery, and crew definitions.

### Norway, Denmark, Spain, and Turkey

- **Exact component:** `nato_full_fallback`
- **Source evidence:** No complete national conquest branch or soldier family was found for these actors in the audited source snapshots.
- **Inference:** They remain individually addressable strategic countries but use an explicitly labeled NATO coalition-fallback roster.
- **Confidence:** Low.
- **Best alternative:** Keep them non-playable until national content exists, or author country-specific infantry and equipment overlays.

### North Korea

- **Exact component:** `kpa_infantry` plus `soviet_legacy_core`
- **Source evidence:** Code:X directly supplies seven `kor_*` infantry/support squads for the Kursk-style expeditionary contingent. It does not supply a complete DPRK armor, artillery, air-defense, logistics, or aviation tree.
- **Inference:** West81 Soviet-pattern equipment fills the standalone DPRK heavy-force progression.
- **Confidence:** High for infantry, medium-low for the standalone heavy roster.
- **Best alternative:** Author a DPRK-specific legacy and modern equipment tree using actual DPRK vehicles and crews.

### Donbas Forces

- **Exact component:** `donbas_native`, `donbas_latent`, and `soviet_legacy_core`
- **Source evidence:** Code:X provides the LDPR branch and latent Sparta/Vostok breed families.
- **Inference:** DPR/LPR, Sparta, and Vostok are combined into one initial actor rather than modeled as separate organizations. West81 supplies broad legacy heavy equipment.
- **Confidence:** Medium-high for infantry, medium for the combined actor and heavy equipment.
- **Best alternative:** Split DPR, LPR, Sparta, and Vostok into hosted components with narrower equipment pools.

### Belarus

- **Exact component:** `belarus_modern_support` plus `soviet_legacy_core`
- **Source evidence:** No dedicated Belarusian breed, conquest roster, or research tree was found. Russian-compatible modern and Soviet legacy equipment exists.
- **Inference:** Belarus is a constructed proxy hybrid using Russian-compatible modernization and West81 legacy equipment.
- **Confidence:** Low.
- **Best alternative:** Add Belarusian infantry/crew breeds and a deliberately selected Belarus equipment list instead of inheriting a filtered Russian branch.

### Serbia

- **Exact component:** `serbia_infantry` plus `soviet_legacy_core`
- **Source evidence:** Code:X contains a small `Serb_*` volunteer breed family but no complete Serbian conquest package.
- **Inference:** The volunteer personnel seed is expanded into rifle, AT, and reconnaissance wrappers and paired with Eastern/Balkan legacy equipment.
- **Confidence:** Medium-low.
- **Best alternative:** Add Serbian national crews, transports, armor, artillery, and support breeds.

### Ukraine International Legion

- **Exact component:** `ukraine_ildu`
- **Source evidence:** Code:X includes `nato_*` / ILDU-style volunteer breeds in the Ukraine side but no complete purchase-ready International Legion squad tree.
- **Inference:** Six actor-scoped squad wrappers are assembled for rifle, AT, Javelin, reconnaissance, engineering, and MANPADS roles.
- **Confidence:** Medium.
- **Best alternative:** Use named source-backed legion formations if Code:X later adds complete wrappers.

### AMX-10RC and Rosomak source-side reuse

- **Exact units:** `amx10rc` and `rosomak`
- **Source evidence:** Both vehicles exist, but their purchase-ready Code:X wrappers are registered on the Ukraine side and use Ukrainian crews.
- **Inference:** The strategic catalog currently reuses those wrappers for French and Polish equipment identity while remapping the tactical export side.
- **Confidence:** Medium for vehicle identity, low for crew-nationality fidelity.
- **Best alternative:** Add NATO-side wrappers with appropriate French/Polish or generic NATO crews before tactical battle export relies on them.

### Generated and hybrid research

- **Exact behavior:** National hybrids use generated category/tier research; mixed native actors use hybrid research.
- **Source evidence:** Code:X only has native research trees for the original tactical factions and formation branches.
- **Inference:** The compiler reconstructs actor-scoped progression for countries assembled from scattered units.
- **Confidence:** Medium.
- **Best alternative:** Hand-author country-specific research trees after balance testing.

## Breed repairs applied by Gates of Code:X

These are narrow overlay corrections, not replacement national families.

| Breed | Upstream defect | Applied correction | Confidence |
|---|---|---|---|
| `kor_crew` | Empty inventory item and no weapon-crew perk | Removed the empty item and added the standard `guncrew` perk while preserving KPA skin, portrait, nationality, rifle, ammunition, grenades, bandages, and shovel | High |
| `fr_spotter` | Stray text after the binocular inventory entry | Removed the malformed trailing token and preserved the existing SOF kit | High |
| `rus114_marksman` | Empty inventory item and malformed stealth perk notation | Removed the empty item and normalized the stealth perk while preserving the 114th marksman kit | High |

## Purchase-ready wrapper materialization

The 14 inferred `goc_*` ILDU, Sparta/Vostok, and Serbian squads now have native final-layer definitions in:

```text
resource/set/multiplayer/units/conquest/units_goc_national_wrappers.set
```

The definitions reference the same existing breeds as the actor manifest. Repository tests require every virtual manifest unit to resolve through `CodeXCatalogScanner`, remain materializable, use only supported tactical sides, and match the manifest composition exactly.

This closes the earlier repository-level gap where the actor economy could purchase a strategic wrapper that the tactical catalog could not resolve. Live Gates of Hell acceptance is still required to prove the generated `campaign.scn` containing these explicit humans and squad rows is accepted by the current engine and full Workshop stack.

### PRC legacy / reserve equipment separation

- **Exact components:** `prc_regular` and `prc_legacy_reserve`
- **Source evidence:** Independent issue #150 provenance traversal found fourteen PRC rows whose effective terminal definitions come from West81 rather than Code:X: `artillery_barrage_light_prc`, `artillery_barrage_medium_prc`, `artillery_barrage_rocket_prc`, `artillery_barrage_smoke_prc`, `mortar_barrage_light_prc`, `mortar_barrage_medium_prc`, `mortar_barrage_smoke_prc`, `paradrop_supply_prc`, `ptl-02`, `t62_545`, `type80`, `ztz852`, `ztz853`, and `ztz96a`.
- **Inference:** These rows remain useful as historical, mobilization, or reserve content, but they must not be presented as modern Code:X-authoritative PLA equipment. They are isolated under the visible `PRC Legacy / Reserve Equipment` research branch. `prc_regular` is enforced as `modern_only`; `prc_legacy_reserve` is enforced as `legacy_explicit` using terminal resolved provenance.
- **Rejected unsupported rows:** `airstrike_cluster_prc`, `airstrike_heavy_prc`, `airstrike_light_prc`, `airstrike_wp_prc`, and `artillery_barrage_heavy_prc` are also West81-only, but were not among the fourteen independently approved legacy rows and their referenced payload identifiers were not independently materialized by the effective stack. They are excluded from both the modern and legacy PRC branches rather than being silently relabeled or accepted through a validation exception.
- **Paradrop indirection:** `paradrop_supply_prc` uses the West81 display token `ammo_pallet`, while its explicit `airstrike:flare_paradrop_ammo` interaction spawns `paradrop_ammo_pallet`. The definition index records that source-proven action-to-spawn alias and still requires the terminal parachute entity to exist.
- **Confidence:** High for the effective West81 provenance and the need to separate it; medium for the historical/reserve gameplay framing.
- **Best alternative:** Replace individual reserve rows with authoritative Code:X definitions when equivalent modern or historically accurate PRC content is supplied, then remove those rows from the legacy component rather than copying upstream definitions into Gates.

## Phase 2 / #191 Western-Northern-Central (accepted #190 selectors)

| Actor | Disposition | Components | Tactical ID | Notes |
|---|---|---|---|---|
| bel/prt/hun/ltu/lva/est | coalition_fallback | nato_full_fallback | goc_* | Explicit NATO coalition fallback; not full-national |
| cze | national_hybrid | cze_equipment_identity + nato_common_infantry_bridge | goc_cze | Exact DANA only; infantry is bridge gap-fill |
| svk | national_hybrid | svk_equipment_identity + nato_common_infantry_bridge | goc_svk | Shared DANA; not SK-exclusive infantry |
| aut/che/irl/isl | strategic_only | (none) | goc_* | Non-playable; no roster/research |

Production army numeric IDs: 70�81 in `goc_tactical_army_registry.json`. Reserved 90�94 for disposable #201 spike. Core nato/ukr/rusa/prc unchanged.

## Phase 2 / #193 Near East-Caucasus-North Africa (accepted #190 selectors)

| Actor | Disposition | Components | Tactical ID | Notes |
|---|---|---|---|---|
| geo | strategic_only | (none) | goc_geo | theatre_present; non-playable; coalition family nato alignment only |
| arm | strategic_only | (none) | goc_arm | theatre_present; non-playable; coalition family rusa alignment only |
| aze | strategic_only | (none) | goc_aze | theatre_present; non-playable; coalition family nato alignment only |
| isr | strategic_only | (none) | goc_isr | theatre_present; non-playable; coalition family nato alignment only |
| lbn | strategic_only | (none) | goc_lbn | theatre_present; non-playable; coalition family nato alignment only |
| syr | strategic_only | (none) | goc_syr | theatre_present; non-playable; coalition family rusa alignment only |
| jor | strategic_only | (none) | goc_jor | theatre_present; non-playable; coalition family nato alignment only |
| irq | strategic_only | (none) | goc_irq | theatre_present; non-playable; coalition family nato alignment only |
| mar | strategic_only | (none) | goc_mar | theatre_present; non-playable; coalition family nato alignment only |
| dza | strategic_only | (none) | goc_dza | theatre_present; non-playable; coalition family rusa alignment only |
| tun | strategic_only | (none) | goc_tun | theatre_present; non-playable; coalition family nato alignment only |
| lby | strategic_only | (none) | goc_lby | theatre_present; non-playable; coalition family rusa alignment only |
| egy | strategic_only | (none) | goc_egy | theatre_present; non-playable; coalition family nato alignment only |
| cyp | strategic_only | (none) | goc_cyp | theatre_present; non-playable; coalition family nato alignment only |
| mlt | strategic_only | (none) | goc_mlt | theatre_present; non-playable; coalition family nato alignment only |

Production army numeric IDs: 55-69 in goc_tactical_army_registry.json. No roster/research/purchase fabrication. #48 remains encounter authority.
