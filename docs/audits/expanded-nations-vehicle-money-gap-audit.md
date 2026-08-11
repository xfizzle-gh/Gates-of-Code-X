# Vehicle money-cost gap disposition (owner UI verified)

Exact head binding: see `expanded-nations-cost-evidence.json` `source_head`.

## Owner disposition applied

The following **exact vehicle IDs** were owner-verified in native GoH UI as having
**positive recruitment money** while the installed stack still has **no parseable
exact money-cost row** for that ID.

Classifier class: `native_ui_verified_positive_unknown`  
`native_recruitment_cost`: `null` (unknown numeric; not invented)  
`zero_cost`: false  
Not counted in `unintended_zero_total`.

Exact allowlist (case-insensitive):

- `cougar-oh`
- `m2a2_ods_bradley_arat_rus`
- `novator`
- `m109_paladin_n`
- `m270_n_clu`
- `maars` / `MAARS`

Purchases covered after regeneration:

- GBR `squad_gb3_mot_rifle_cougar(nato)`
- RUS `squad_rus155_m2a2_2022(rusa)`
- UKR `squad_ukr93_razv_novator(ukr)`
- USA `squad_tank1_m109(nato)`
- USA `squad_tank1_m270(nato)`
- USA `squad_usmc_rifle_javelin`
- USA `squad_usmc_rifle_m3`

## Explicit non-actions

- No numeric price invented from nearby IDs
- Unknown vehicle IDs outside the allowlist still fail closed as `vehicle_unpriced`
- `t80uk` remains resolved by exact `vehicle2` money row (1950), not this allowlist

## Counts contract

Per actor and globally the evidence reports:

- `native_positive_count` / `native_positive_total`
- `native_unknown_numeric_count` / `native_unknown_numeric_total`
- `unintended_zero_count` / `unintended_zero_total`
