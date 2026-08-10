# Vehicle money-cost gap source audit (read-only)

Exact installed stack: Vanilla → West81 → Code:X → Code:X AI Overhaul → Gates.
Implementation head bound in evidence: see `expanded-nations-cost-evidence.json` `source_head`.

## Resolved by exact authority (implemented)

### `t80uk`
- **Exact vehicle entity money row found:** Code:X / AI Overhaul `units_rusa.set`
- Form: `("vehicle2" ...)` not `("vehicle" ...)`
- Cost: **1950.0** (`not_for_player_sale 1`)
- Purchase use: `squad_rus4_t80uk(rusa)` → `vehicle(t80uk)`
- **Disposition:** index `vehicle2`/`vehicleN` entity forms (implemented + regression).
- Note: purchase-name block `squad_rus4_t80uk(rusa)` also has `{cost 2500}`; classifier uses vehicle-entity money authority first (1950).

## Remaining gaps — no exact money row for the purchase vehicle ID

No prices invented. Nearby IDs listed only as non-authoritative context.

### 1. `cougar-oh` (GBR `squad_gb3_mot_rifle_cougar`)
- Exact money definition: **NONE**
- Purchase uses: Code:X/AI `units_nato.set` `vehicle(cougar-oh)`
- Assets: unit icons exist (`cougar-oh_*.png`)
- Nearby priced ID: `cougar-og` cost **230** (`not_for_player_sale`)
- **Not an exact alias** (`oh` ≠ `og`)
- **Needs disposition / native UI test**

### 2. `m2a2_ods_bradley_arat_rus` (RUS `squad_rus155_m2a2_2022`)
- Exact money definition: **NONE**
- Purchase uses: Code:X/AI `units_rusa.set` `vehicle(m2a2_ods_bradley_arat_rus)`
- Nearby: `m2a2_ods_bradley` **450**; `m2a2_ods_bradley_arat` **480** (UKR, nfs on arat)
- **Not exact** (missing/extra `_rus` nationalization suffix)
- **Needs disposition / native UI test**

### 3. `novator` (UKR `squad_ukr93_razv_novator`)
- Exact money definition for `novator`: **NONE**
- Purchase uses: `vehicle(novator)`
- Nearby exact priced entity: `novator_stugna-p` **270** (same pack)
- **Not exact ID match**
- **Needs disposition** (possible narrow alias only if native UI proves same body)

### 4. `m109_paladin_n` (USA `squad_tank1_m109`)
- Exact money definition: **NONE**
- Purchase uses: `vehicle(m109_paladin_n)`
- Nearby: `m109_paladin` **2500** (UKR pack); legacy `m109`/`paladin` West81 rows
- **Not exact** (`_n` NATO suffix)
- **Needs disposition / native UI test**

### 5. `m270_n_clu` (USA `squad_tank1_m270`)
- Exact money definition: **NONE**
- Purchase uses: `vehicle(m270_n_clu)`
- Nearby: `m270_n` **1800** (nfs); `m270_ukr_clu` **4500**
- **Not exact** (`_clu` cluster munition variant suffix)
- **Needs disposition / native UI test**

### 6–7. `MAARS` (USA `squad_usmc_rifle_javelin`, `squad_usmc_rifle_m3`)
- Exact money definition: **NONE**
- Purchase uses: `vehicle(MAARS)` on USMC rifle variants
- Assets: icons only (`maars_*.png`)
- Nearby UGVs priced under different IDs (`ugv_mg_ap` 160, etc.) — **not MAARS**
- **Needs disposition / native UI test** (may be free/support drone in native UI)

## Explicit non-actions
- No fuzzy aliasing of `_n` / `_clu` / `_rus` / `oh`↔`og` without owner/native proof
- No invented balance values
- No Phase 2 / #201 work

## Recommended next
For each remaining ID: either
1. authorize a **narrow exact alias** with provenance after native UI cost observation, or
2. mark as **intentional source-native unpriced vehicle** with allowlist + rationale, or
3. remove/replace the purchase selector if the vehicle body is non-recruitable junk.
