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
| Canadian armor | Leopard C2 MEXAS exists in Code:X | High for equipment identity |

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
- **Inference:** Generic Nordic/NATO infantry represents the personnel layer. The T-55M is treated as a reserve/legacy option, not evidence for a broad Soviet roster.
- **Confidence:** Medium.
- **Best alternative:** Add Finnish infantry and support breeds, then restrict equipment to actual Finnish-service systems.

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
- **Source evidence:** Code:X supplies Leopard C2 MEXAS and a Leopard 2A4M identifier, but no complete Canadian infantry branch.
- **Inference:** Generic NATO infantry and common support represent the missing Canadian personnel layer.
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

## Remaining important limitation

The `goc_*` ILDU, Sparta/Vostok, and Serbian entries are strategic catalog wrappers assembled from source breeds. Before final tactical export acceptance, an independent audit must verify that the battle materializer emits or resolves purchase-ready native GoH squad definitions for those IDs. A non-empty member list in the strategic catalog alone is not proof that the game engine can purchase or spawn the wrapper.
