# #212 Phase C strategic icon atlas comparison

Measurement head: `14f88478632e350502221c27f9751749f2aec5c6`

Focused workflow: `31864360077`

Artifact: `9241626072`, SHA-256 `b4d6ac15ed249fd0291492269e2e4d02068404d945b66a38b7958eeaff90129e`

The Phase C prototype compares the current procedural synthetic-counter path against one repository-owned atlas texture drawn from one CanvasItem. The atlas contains 18 original procedural pixel patterns covering the complete issue vocabulary. Numeric strength remains separate text and is never baked into unique textures.

The first post-restack rerun was correctly rejected because its first recorded baseline absorbed process-first renderer/font/resource warmup: p50/p95 drift reached roughly 22%/23% despite identical draw-call and primitive counts. The corrected harness burns two unreported no-stress samples before any recorded bracket. The existing 15% p50/p95 rejection threshold is unchanged.

All corrected samples use 24-frame local brackets. Every bracket passed; the worst observed baseline drift was **2.34%**.

## Idle full-theatre stress

The incremental values below are candidate minus the local no-stress baseline.

| Counter count | Mode | Candidate frame p50 | Incremental frame p50 | Incremental draw calls | Incremental primitives |
|---:|---|---:|---:|---:|---:|
| 64 | Current procedural | 239.231 ms | +3.875 ms | +192 | +976 |
| 64 | Atlas + strength text | 237.160 ms | +2.543 ms | +128 | +336 |
| 256 | Current procedural | 253.344 ms | +18.417 ms | +768 | +3,924 |
| 256 | Atlas + strength text | 242.254 ms | +7.741 ms | +512 | +1,364 |
| 512 | Current procedural | 272.744 ms | +38.765 ms | +1,536 | +7,848 |
| 512 | Atlas + strength text | 250.946 ms | +17.124 ms | +1,024 | +2,728 |

At 512 counters, atlas + text removes **512 incremental draw calls**, **5,120 incremental primitives**, and about **21.641 ms** of incremental p50 frame cost versus the current procedural control on CI llvmpipe.

## Continuous zoom, 512 counters

| Mode | Candidate frame p50 | Incremental frame p50 | Incremental draw calls | Incremental primitives |
|---|---:|---:|---:|---:|
| Current procedural | 308.448 ms | +24.620 ms | +1,536 | +7,848 |
| Atlas + strength text | 288.468 ms | +4.147 ms | +1,024 | +2,728 |
| Atlas symbols only | 287.513 ms | +4.998 ms | **+1** | +1,024 |

The symbol-only diagnostic remains the key architectural result: all 512 atlas symbols submit as one additional draw call on this harness. The remaining atlas+text draw-call pressure comes from separately rendered numeric strength labels, not from the atlas symbols themselves. Frame-time differences between atlas+text and symbols-only are small enough here that the batching conclusion should rest on draw/primitive counts, not on claiming text removal is a deterministic frame-time win.

This supports the issue's intended architecture split:

- keep categorical strategic symbols in a shared atlas/batched CanvasItem;
- keep numeric strength out of the texture atlas;
- LOD-gate, aggregate, or otherwise reduce strength text at wide views rather than generating unique strength textures;
- do not copy reference-mod art. The prototype atlas is generated from repository-owned 7x7 patterns.

## Vocabulary and authority

The one 192x96 texture contains 18 32px cells:

`infantry`, `motorized`, `mechanized`, `armor`, `airborne`, `artillery`, `air_defense`, `engineers`, `recon`, `logistics_support`, `hq_command`, `supply`, `objective`, `battle_contact`, `stance_warning`, `readiness_warning`, `supply_warning`, `actor_flag_badge`.

Earth3 authority hashes were unchanged and PolygonMap remained live. The atlas prototype is not mounted by production `main.tscn` in this PR.

## Phase C decision

**PASS as a debug-only batching proof.** A shared atlas materially improves dense strategic-symbol presentation. The next production-oriented work should combine atlas-backed symbols with the Phase D LOD policy so wide views avoid per-counter numeric text pressure.

No production renderer switch or production atlas mount is authorized by this evidence. Owner-native visual/performance acceptance and fresh independent review remain required.
