# #212 Phase C strategic icon atlas comparison

Measurement head: `1ed391ef23bfadb0509b162886abf1fb93096b90`

Focused workflow: `31863568936`

Artifact: `9241403156`, SHA-256 `dd6887b2eaf3dfbebe0668bda4547a2b50a8836a31cd491dbe0a63487ad165f6`

The Phase C prototype compares the current procedural synthetic-counter path against one repository-owned atlas texture drawn from one CanvasItem. The atlas contains 18 original procedural pixel patterns covering the complete issue vocabulary. Numeric strength remains separate text and is never baked into unique textures.

All samples use 24-frame local brackets. The 15% p50/p95 drift rejection gate remains unchanged and every bracket passed.

## Idle full-theatre stress

The incremental values below are candidate minus the local no-stress baseline.

| Counter count | Mode | Candidate frame p50 | Incremental frame p50 | Incremental draw calls | Incremental primitives |
|---:|---|---:|---:|---:|---:|
| 64 | Current procedural | 241.184 ms | +6.957 ms | +192 | +976 |
| 64 | Atlas + strength text | 236.632 ms | +3.032 ms | +128 | +336 |
| 256 | Current procedural | 254.536 ms | +21.180 ms | +768 | +3,924 |
| 256 | Atlas + strength text | 242.041 ms | +8.223 ms | +512 | +1,364 |
| 512 | Current procedural | 272.155 ms | +38.689 ms | +1,536 | +7,848 |
| 512 | Atlas + strength text | 250.686 ms | +15.828 ms | +1,024 | +2,728 |

At 512 counters, atlas + text removes **512 incremental draw calls**, **5,120 incremental primitives**, and about **22.9 ms** of incremental p50 frame cost versus the current procedural control on CI llvmpipe.

## Continuous zoom, 512 counters

| Mode | Candidate frame p50 | Incremental frame p50 | Incremental draw calls | Incremental primitives |
|---|---:|---:|---:|---:|
| Current procedural | 308.696 ms | +25.614 ms | +1,536 | +7,848 |
| Atlas + strength text | 292.790 ms | +8.514 ms | +1,024 | +2,728 |
| Atlas symbols only | 284.031 ms | +0.619 ms | **+1** | +1,024 |

The symbol-only diagnostic is the key Phase C result: all 512 atlas symbols submit as one additional draw call on this harness. The remaining atlas+text draw-call pressure comes from the separately rendered numeric strength labels, not from the atlas symbols themselves.

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
