# GoE source inventory — #290 Phase 1

**Audit SHA:** `e830d694d68325b3764fc2c20ede3c40400ab6f0`  
**Local repository:** this checkout (cloud-agent workspace root; machine-specific absolute path omitted)  
**Host:** Linux cloud-agent (no Windows `E:` / `C:`, no Steam, no Godot binary)  
**Date:** 2026-08-24  
**Session type:** audit-only. No implementation PR. Parked PRs not reopened.

`AGENTS.md` is **absent** at repository root (confirmed against live GitHub `main`). Nested skills used: `.agents/skills/README.md`, `gates-pr-gate`, `gates-authority-change`.

Open feature PRs at freeze: **none**.

---

## Classification key

| Class | Meaning |
|---|---|
| authoritative data/source | Original GoE bytes or an extract with proven field-level provenance |
| runtime/save evidence | Observed GoE campaign/save/runtime dumps |
| UI-only evidence | Screenshots, issue descriptions of panels, click models |
| derived/inferred | Clean-room reconstructions or Gates-authored data that must not be cited as GoE |
| unknown | Searched; not found on this machine |

---

## 1. What this machine does **not** contain

These were searched. They are **missing**. Do not guess behavior from them.

| Category | Expected / requested locations | Result |
|---|---|---|
| Live Gates of Europa install | `E:\Steam\steamapps\common\…`, sibling worktrees, `/mnt`, `/media`, `$HOME/.steam` | **Absent** |
| GoE Workshop / Unity project | owner-local GoE folders; any `Gates of Europa` / `Gates-of-Europa` directory | **Absent** |
| West81 | `E:\Steam\steamapps\workshop\content\400750\2897299509` | **Absent** |
| Code:X | `E:\Steam\steamapps\workshop\content\400750\3261086933` | **Absent** |
| Code:X AI Overhaul | `E:\Steam\steamapps\workshop\content\400750\3636883799` | **Absent** |
| Vanilla Gates of Hell | `E:\Steam\steamapps\common\Call to Arms - Gates of Hell` | **Absent** |
| GoE research trees / tech nodes | repo, git history, docs, ignored `live/` | **Absent** |
| GoE economy / income / upkeep tables | same | **Absent** |
| GoE recruitment / purchase lists | same | **Absent** |
| GoE building / settlement catalogs from GoE itself | same | **Absent** |
| GoE battalion TOE / card quantities from data files | same | **Absent** |
| GoE campaign saves / `campaign_state.json` original | referenced by docs, file not present | **Absent** |
| GoE `province_database_newestV7` original | extract exists; original DB **absent** | **Absent** |
| Godot player binary | `godot`, `Godot_v4.7-stable_linux.x86_64` | **Absent** (`GODOT_BIN` unset) |

`config/mod-stack.windows.json` is a **portable contract** with `${WEST81_ROOT}` / `${CODEX_ROOT}` placeholders. It is not a mounted stack.

---

## 2. Sources that **are** present (with SHA-256)

### 2.1 Extracted GoE geography (derived, not live GoE)

| Path | SHA-256 | Class | What it actually contains |
|---|---|---|---|
| `src/gates_of_codex/data/goe_graph_00.b85` | `1689267b58704bacf4ff30267a9919161daa620eafaf7a85fd71311eb237f139` | derived extract | Compressed 517-node graph chunk |
| `src/gates_of_codex/data/goe_graph_01.b85` | `e8f87e531c37dbca3329cfded9e44c3d022f47b91f0029291261665f56809988` | derived extract | chunk |
| `src/gates_of_codex/data/goe_graph_02.b85` | `c6b33c4a0e5ef4ea8bbdf95f01187303b4cd48bac659af2bd9950c4ba0475e8e` | derived extract | chunk |
| `src/gates_of_codex/data/goe_graph_03.b85` | `8b73078651bf9f0c9ed487de1ecf9e16d2513cc1fc629485aa7be9129810eb3f` | derived extract | chunk |
| `src/gates_of_codex/data/goe_graph_04.b85` | `ad9284a43c2dd357868a9e1d7f06f5fa64297be3790baf40700777e4b5f3a949` | derived extract | chunk |
| `src/gates_of_codex/data/goe_graph_05.b85` | `f800296a1d89b6cf00eee429689e95faaffb076fe6773d2d8cbcd6d0a31e7ccb` | derived extract | chunk |
| `src/gates_of_codex/data/goe_marker_layout.json` | `bd65b606036177a6bd6c62bf9ca67e6698cc2f1aa8fc976d2dfd9e049d92a02a` | derived extract | 517 marker rows from GoE `province_database_newestV7` (id, name, x/y, IdColor RGB, neighbors, unlabeled `map_region`) |
| `docs/audits/goe-province-metadata.json` | `aa279f85e74180d8843e02f5209ff8398f3cb0024c756fb3865a801cd735cabb` | derived audit | Provenance report for the extracts |
| `godot/assets/maps/europe/interim_goe/province_id_map.png` | `5ad0b4c274040caea64a1b77cbd421d57d88a2c036e50d7fd062779bbabc316e` | derived binary | Interim color-ID texture from Unity `province_idnew_map` (1314×1513 RGB24, 517 colors) |
| `godot/assets/maps/europe_mediterranean/from_goe/province_id_map.png` | `5bf42045e6b4f07f8675e0c5f9ec1cdf140e3bcdcb22f6ae1b8c18037efbed44` | derived binary | Cropped EM theatre color-ID |

**Provenance (already recorded in `docs/audits/goe-province-source.md`, issue #49):**

- Graph: clean-room data-contract reconstruction from a **supplied GoE alpha `campaign_state.json` that is not in this checkout**.
- 63 named provinces; remaining IDs are generated labels.
- Marker coordinates: extracted; 302/517 graph rows map to markers; 215 placed by neighbor average (not click authority).
- **Not in these extracts:** country ownership, capitals, ports, rail, terrain, buildings, research, economy, units, supply, AI.

### 2.2 Production Earth3 map (NOT GoE; KEEP as production geography)

| Path | SHA-256 | Class |
|---|---|---|
| `godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json` | `4aadab4b5106bbfa4c2d37e8173c3d1675f35a448cbd7f32a8b871c464ce1b84` | repository immutable authority (matches `APPROVED_DATASET_RAW_SHA256`) |
| `godot/assets/maps/earth3_europe_mediterranean/map_manifest.json` | `614a926e79f11e3cfac8c867c7bacce107fc69344b17fabb6b4545cdeaa6a357` | repository immutable authority |
| `godot/assets/maps/earth3_europe_mediterranean/dataset_meta.json` | `4dadaa1da207e9d22c9ed90d39cef8e225dd5a2e606228e4c81266568932108d` | metadata |

3514 provinces (3299 land / 215 water). Production default scenario `ww3_2028_core` uses this map, **not** the 517-node GoE graph.

### 2.3 Tactical `conquest.lua` on current main (NOT GoE strategic)

| Path | SHA-256 | Class |
|---|---|---|
| `resource/script/multiplayer/modes/conquest.lua` | `d685dd35148ea9b97cbf7dbbe9572ced4a59bfd50eebbfa9dfc668a56b68ebdd` | Gates tactical overlay |

Header identifies **Code:X Reversion 1.5.6** wave/purchase timings. This is Dynamic Conquest AI, not GoE's strategic campaign loop.

Git history contains `e100b61` (`feat(spike): add GatesOfEuropa conquest.lua with goc nations`) on `origin/spike/201-custom-tactical-factions` only. Commit message: base Steam Workshop `3717998771` `modes/conquest.lua`. That spike is **not** on production `main` and is **not** a GoE strategic research/economy source. It was not copied into this audit.

### 2.4 UI-only / issue-text evidence (not simulation proof)

| Source | Class | What it can support | What it cannot |
|---|---|---|---|
| #52 body | UI-only | GoE strategic UI showed battalion **cards**, approximate composition, long names that overflowed; player wanted a clearer stack panel | Roster quantities, merge/split rules, tactical waves |
| #185 body | UI-only | Screenshots of GoE strategic battalions with roster cards, strength, supply upkeep, distinct heavy/medium tank compositions | How GoE materializes those battalions in GoH. Issue itself forbids that inference |
| #49 comments | derived + UI | Color-ID pipeline (MapChart HOI4 → unique RGB → adjacency → markers) | Economy/research |
| README | derived | Project recreates **observable interoperability** of a supplied GoE Workshop project **without redistributing** executable/Unity assets | The missing Workshop bytes |

### 2.5 Explicitly **not** GoE source

| Source | Why it is not GoE |
|---|---|
| #65 / #82 / #83 / #86–#88 building tables | Collaborator-authored **provisional** catalogs (`buildings (1).docx` never present here). #217 later parked the full city-builder as post-v1 |
| `docs/economy-and-progression.md` | Gates catalog-derived costs, not GoE |
| `docs/actor-economy.md` | Actor-scoped Code:X wiring |
| `docs/research/noresus-*.md` | **NORESUS**, a different reference game |
| `resource/set/dynamic_campaign/unit_research_goc_*.set` | Gates-authored Expanded Nations trees from Code:X/West81 wiring, not GoE |
| `src/gates_of_codex/economy.py` category graph | Invented Core Forces → Vehicles → IFVs → Tanks chain |

---

## 3. Git history note

Useful history exists for **geography only** (graph chunks, marker extract, color-ID import). No commit in this checkout stores GoE research, economy, buildings, or recruitment tables.

`live/` is gitignored and empty here.

---

## 4. Missing-file request to the owner (exact)

To complete Phase 2 GoE **player-loop** claims, this session needs **at least one** of the following mounted or copied as read-only reference (not to be committed):

1. **GoE install or Unity/Workshop folder** containing campaign/map data.
2. Original **`campaign_state.json`** (or equivalent save) from a new campaign, mid campaign, and late campaign.
3. GoE **research / tech / unlock** definitions (ScriptableObjects, JSON, Lua, or Unity assets — whatever the project actually uses).
4. GoE **economy**: starting money, income, upkeep, purchase costs, repair/replenish costs.
5. GoE **recruitment / battalion TOE / assignment** data.
6. GoE **building / settlement** data **if** those systems exist in GoE (do not assume #65 is GoE).
7. Optional: a short screen recording of one GoE turn (UI-only evidence).

Until those exist, every research/economy/recruitment/building/supply/AI row in the parity matrix is `UNKNOWN` on the GoE side.

---

## 5. What can still be audited without GoE bytes

- Current Gates production `main` (Phase 3): **done** from code/data.
- #46 tooling gap vs current-main scanners: **done**.
- Player-visible latency on this Linux host (backend stages only): **done**.
- Conservative KEEP / REWORK / NOT_BUILT dispositions for **Gates** systems, with GoE comparison blocked.
