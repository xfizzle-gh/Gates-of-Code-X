# Current-main player-visible latency — #290 Phase 6

**Audit SHA:** `e830d694d68325b3764fc2c20ede3c40400ab6f0`  
**Machine JSON:** `docs/audits/goe-parity/current-main-latency.json`  
**Host:** Linux cloud-agent, Python 3.12.3, **no Godot binary**  
**Campaign:** disposable `ww3_2028_core` on Earth3 via fixture resolved catalog (same 3514-province save/validate path as production; **not** the owner Windows live stack)  
**Harness:** `<tmp>/goc-parity-latency.py` (local-only; not a repo tool)

## The question

**Why does the game still feel slow?**

Not: “is Python faster than before #266?”

## Stage coverage rule

| Stage | This session |
|---|---|
| input timestamp | **UNKNOWN** (no Godot) |
| Godot handler | **UNKNOWN** (no Godot) |
| command dispatch | **PARTIAL** (Python `measured_apply_frontend_commands`) |
| backend receive | **PARTIAL** (in-process; no TCP daemon round-trip) |
| mutate | **MEASURED** when the op succeeded |
| save/persist | **MEASURED** on mutating ops |
| snapshot / runtime patch | **MEASURED** |
| Godot receives | **UNKNOWN** |
| UI rebuild | **UNKNOWN** |
| first correct visible frame | **UNKNOWN** — not invented |

Owner-Windows Godot input→visible after #266 slices 1–4 remains **unmeasured**, exactly as #266 closeout stated.

---

## What #266 actually closed

Quoted from #266 closeout on `a4b860d5` (Linux Python, `GODOT_BIN` unset):

| Path | warm backend min |
|---|---:|
| live move batch | ~1.0 s |
| End Turn | ~1.6 s |
| Auto-Resolve | ~1.2 s |
| Godot input→visible | **N/A** |

Those three ops sit on the persistent-backend allowlist **and** the runtime-patch path.

---

## This session’s backend measurements

Fresh `ww3_2028_core` (fixture catalog). Compact campaign after first mutating save ≈ 2.8 MB. Full frontend snapshot when published ≈ 6.5 MB.

| Action | Warm lease? | ok? | load_ms | mutate_ms | save_ms | snapshot_ms | total_ms | Notes |
|---|---|---|---:|---:|---:|---:|---:|---|
| New Campaign boot | n/a | yes | — | — | — | — | **10040** | `create_new_campaign` wall |
| Continue (`load_campaign`) | n/a | yes | **2996** | — | — | — | 2996 | Python only; Godot Continue is a full launcher argv |
| Select formation (Python lookup after load) | n/a | yes | 2864 includes load | — | — | — | 2864 | **Not** a Godot click |
| Open Force Management `actor_force_panel` | no (production) | yes | **2623** | 10 | 0 | 0 | **2633** | **Not** in `SUPPORTED_OPS` → one-shot + **invalidates warm lease** |
| Force panel if it were leased | spoof | yes | 0 | 27 | 0 | 0 | **27** | Proves the wait is load/lease, not panel logic |
| Research | no | **fail** | **5239** | 5 | 0 | 0 | **5245** | `Research key is not scoped to actor nato: actor:usa:…` |
| Recruit | no | **fail** | **5920** | 11 | 0 | 0 | **5931** | Needs `actor:usa` research while command actor is `nato` |
| Assign | — | **fail** | — | — | — | — | — | Blocked by recruit |
| Repair | yes (allowlisted) | yes | 0 | 26 | 704 | **47401** | **48130** | Full 6.5 MB snapshot publish; **not** runtime-patched |
| Repair one-shot | no | yes | 2674 | 8 | 664 | **47459** | **50806** | Same snapshot tax + load |
| Refresh | yes | yes | 0 | 21 | 695 | **47294** | **48010** | Recovery path; full snapshot |
| Move + commit | yes | yes | 0 | 27 | **720** | **176** (runtime patch) | **923** | Matches #266 ~1.0 s band |
| Move + commit one-shot | no | yes | 2794 | 7 | 683 | 177 | **3661** | What the player pays if lease was killed |
| End Turn `end_player_round` | harness | **fail** | — | — | — | — | — | Op is installed only by `fast_entrypoint` / `install_frontend_turn_cycle_op`; not invented |
| Auto-Resolve | — | skip | — | — | — | — | — | No `pending_battle` on a fresh campaign; S10 inject not used |

`repair` / `refresh` `runtime_patch_fast_path` flags in the JSON are **misleading** (`compact_save_path` was aliased in the harness). Code authority: `_RUNTIME_PATCH_OPS = {end_player_round, auto_resolve}` plus the exact live `issue_move_order+commit_move_orders` batch. **Repair and refresh publish a full snapshot.**

---

## Why it still feels slow (evidence, not slogans)

1. **#266 only sped the three allowlisted hot ops.** Force Management, Research, Recruit, Assign, Repair, Refresh, Continue are a **second latency class**.

2. **Warm lease is fragile.** `persistent_backend.SUPPORTED_OPS` omits `actor_force_panel`, `research`, `recruit`, `assign`. Those ops **invalidate** the daemon (`persistent_backend.py` ~601–604). The next move/End Turn then pays **~2.6–5.9 s deserialize** again. A comment in `SUPPORTED_OPS` even claims force ops have “no measured player-facing warm-path need.” Owner-observed sluggishness contradicts that assumption.

3. **Full snapshot publication is still catastrophic** for Repair/Refresh: **~47 s** to write a 6.5 MB snapshot on this VM, versus **~176 ms** runtime patch on move. Owner Windows will be faster hardware, but the **architectural ratio** remains: any non-patched mutating UI action republishes the Earth3 frontend snapshot. #266’s 1.0–1.6 s table never included these ops.

4. **The Core 2028 identity split makes the intended loop fail, then wait.** Selected command actor is `nato`; formation economy/research is `usa`/`deu`/`pol`. Research/recruit return errors **after** a 5 s load. The player experiences “I clicked Research and the game hung, then nothing happened.”

5. **Save still costs ~0.7 s** on every successful mutation (`save_validate_ms` ≈ 0.58–0.62 s). That is the remaining #266 leftover on the good path. Combined with Godot apply (historically ~0.5–1.2 s, **not remeasured**), even a “fast” move can still feel like ~1.5–2+ s input→visible on Windows.

6. **Busy UX amplifies wait.** Godot rejects map orders while a command is in flight and redraws a busy banner every frame (`main_order_controls.gd`, `main_color_id.gd`). A 1–5 s backend wait is presented as a freeze.

7. **Godot still deep-copies and reindexes** the live snapshot on runtime-patch consume (`main_perf_measured.gd`). That stage is **UNKNOWN ms** here. Pre-#266 Godot reload was ~1.2 s. Nobody has proven the post-#266 visible frame is instant.

8. **Ownership mesh may not refresh** on `_commit_snapshot_state` (`refresh_snapshot` lives on `_load_snapshot` in `main_color_id.gd`). After End Turn / Auto-Resolve the player can wait and still see stale fills — “did anything happen?”

---

## What can be made effectively instant (recommendation, not implementation)

These are **product** conclusions for owner ruling. Not a PR.

| Action | Instant if |
|---|---|
| Select province / formation / battalion | Already local in Godot if no `query_supply` miss |
| Open Force Management | Add `actor_force_panel` to warm allowlist (it is already read-only / skip-save) → backend ~27 ms here |
| Research / Recruit / Assign | Warm allowlist **and** runtime-patch **and** fix nato-vs-usa command/economy identity |
| Repair | Stop full snapshot; reuse runtime-patch (mutate is 8–26 ms) |
| Move + commit | Already ~0.9 s warm; remaining: save validate (~0.6 s) + Godot apply (UNKNOWN). Optimistic UI on committed order could hide save |
| End Turn | Keep runtime-patch; remaining mutate is AI/turn-cycle (~1.2 s on #266). That is a different cut |
| Refresh | Should be rare; 47 s snapshot is unacceptable as a recovery click |
| Auto-Resolve | Already patched; not remeasured here |

**Do not** treat “Python is 1.0 s on move” as player-visible acceptance.

---

## Comparison to owner-observed sluggishness

Owner-observed sluggishness is **sufficient** to keep this open even if backend microbenchmarks on move/End Turn/Auto-Resolve are green. This session **reproduced** multi-second (and, for snapshot ops, multi-tens-of-second) waits on the everyday force/repair/refresh path, plus a **functional** research/recruit failure on the production Core NATO seat.

Godot input→visible on the owner Windows box is still required before any “the game feels fast” claim.
