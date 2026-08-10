# Expanded Nations native recruitment-cost evidence

- schema: `gates-of-codex.expanded-nations-cost-evidence` v2
- evidence_state: `blocked`
- source_head: `4d31df555d75af2f60ed1ce865812029bfa1c314`
- playable_actors: 21
- unintended_zero_total: 8

Native recruitment cost counts money-price authority only (`{cost N}` / purchase `cost(N)` / vehicle entity `{cost}` / pure-infantry inf sums). `cp()` and `cost_sp` are recorded per unit but never counted as recruitment money.

| actor | side | units | proj_rows | min | median | max | unintended_zero | intentional_zero |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| blr | rusa | 30 | 0 | 60 | 400 | 2150 | 0 | 0 |
| can | nato | 14 | 0 | 3 | 350 | 1800 | 0 | 0 |
| deu | nato | 29 | 0 | 3 | 280 | 2400 | 0 | 0 |
| dnk | nato | 55 | 2 | 15 | 700 | 2400 | 0 | 0 |
| donbas | rusa | 46 | 10 | 42 | 274.75 | 3500 | 0 | 0 |
| dprk | rusa | 22 | 0 | 60 | 419.75 | 1100 | 0 | 0 |
| esp | nato | 50 | 24 | 3 | 700 | 2400 | 0 | 0 |
| fin | nato | 15 | 0 | 3 | 350 | 1800 | 0 | 0 |
| fra | nato | 28 | 3 | 3 | 295 | 1950 | 0 | 0 |
| gbr | nato | 33 | 0 | 0 | 293 | 1900 | 1 | 0 |
| ita | nato | 19 | 0 | 3 | 450 | 1800 | 0 | 0 |
| nld | nato | 15 | 0 | 3 | 350 | 1800 | 0 | 0 |
| nor | nato | 55 | 2 | 15 | 700 | 2400 | 0 | 0 |
| pol | nato | 18 | 0 | 3 | 400 | 2250 | 0 | 0 |
| prc | prc | 80 | 0 | 4 | 350 | 5000 | 0 | 0 |
| rus | rusa | 212 | 0 | 0 | 350 | 5600 | 2 | 0 |
| srb | rusa | 18 | 0 | 60 | 400 | 1100 | 0 | 0 |
| swe | nato | 17 | 0 | 3 | 410 | 2150 | 0 | 0 |
| tur | nato | 55 | 2 | 15 | 700 | 2400 | 0 | 0 |
| ukr | ukr | 179 | 2 | 0 | 418.5 | 5600 | 1 | 0 |
| usa | nato | 74 | 1 | 0 | 281.25 | 2150 | 4 | 0 |

## Unintended zeros

- `gbr` / `squad_gb3_mot_rifle_cougar(nato)` (vehicle_unpriced): vehicle-bearing purchase lacks purchase money cost and vehicle entity money cost for cougar-oh
- `rus` / `squad_rus155_m2a2_2022(rusa)` (vehicle_unpriced): vehicle-bearing purchase lacks purchase money cost and vehicle entity money cost for m2a2_ods_bradley_arat_rus
- `rus` / `squad_rus4_t80uk(rusa)` (vehicle_unpriced): vehicle-bearing purchase lacks purchase money cost and vehicle entity money cost for t80uk
- `ukr` / `squad_ukr93_razv_novator(ukr)` (vehicle_unpriced): vehicle-bearing purchase lacks purchase money cost and vehicle entity money cost for novator
- `usa` / `squad_tank1_m109(nato)` (vehicle_unpriced): vehicle-bearing purchase lacks purchase money cost and vehicle entity money cost for m109_paladin_n
- `usa` / `squad_tank1_m270(nato)` (vehicle_unpriced): vehicle-bearing purchase lacks purchase money cost and vehicle entity money cost for m270_n_clu
- `usa` / `squad_usmc_rifle_javelin` (vehicle_unpriced): vehicle-bearing purchase lacks purchase money cost and vehicle entity money cost for MAARS
- `usa` / `squad_usmc_rifle_m3` (vehicle_unpriced): vehicle-bearing purchase lacks purchase money cost and vehicle entity money cost for MAARS
