# S10 Operational Resolution Presentation Design

## Status and authority

Issue #108 and the implementation prompt approve and lock this design. S10 is presentation-only. Python remains authoritative for movement, contact selection and location, Ambush, blocking, retreat, battle state, and the single pending-battle pause.

The implementation starts from `503a71eeb804c5c33e301912228f617847f32df0` on `feat/s10-operational-resolution-presentation`. It must not begin S11 or alter Earth3, OpenGS, supply, AI, tactical battle behavior, or Python gameplay rules.

## Chosen approach

Use an additive transient command-result contract feeding a session-only Godot presentation controller.

Two alternatives are rejected:

- Snapshot diff alone cannot preserve the authoritative `trapped_no_legal_retreat` reason after the formation is removed.
- Persisted presentation/replay history violates the nonpersistent replay and presentation-only constraints.

The current frontend schema remains version 13. Existing snapshots already provide authoritative strategic-formation positions, display pixels, move-order paths, encounter kind, and encounter location. S10 adds only optional detailed participant rows to `pending_battle` and transient presentation data to command results. No presentation state is written to campaign saves.

## Python adapter contract

`frontend.py` exports optional `attacking_participants` and `defending_participants` arrays alongside the existing battalion ID arrays. Each row copies S9 participant authority and adds the battalion's strategic formation ID and existing formation display name. The copied fields are:

- `battalion_id`
- `strategic_formation_id`
- `formation_display_name`
- `faction`
- `stage`
- `is_primary`
- `contact_initiator`
- `ambush_eligible`
- `ambush_triggered`
- `ambush_strength_multiplier_milli`
- `ambush_readiness_consumed`

`frontend_commands.py` records a read-only before/after presentation delta around successful commands. Movement records contain formation ID, exact start/end operational positions and pixels, and the backend move-order node/edge path. Battle finalization records contain the winner and the exact `BattleFinalizationReport.retreat_outcomes`, with the destination pixel derived from the post-resolution authoritative formation position when the formation survives.

The frontend adapter captures the existing finalization report without changing `campaign.py`: a private frontend-only `CampaignEngine` subclass records the value returned by `apply_battle_result` while preserving the existing resolution path and winner API.

## Godot presentation controller

Create `operational_resolution_presenter.gd` as a simulation-free session controller. It consumes transient command results plus committed snapshots and exposes immutable presentation view models to the active scene.

Responsibilities:

- Build tracks only from backend-provided start/end positions, pixels, and move-order paths.
- Interpolate all tracks against one shared 0.45-second clock so unrelated formations move in parallel.
- Validate that movement follows the supplied operational path. If a record cannot be connected safely, snap to the authoritative endpoint instead of inventing geometry.
- Snap every completed or skipped track exactly to its authoritative endpoint.
- Resolve contact display from the backend `encounter_kind` and existing `BattleLocation` authority; never infer kind from geometry.
- Retain only the most recent primary contact in memory for replay.
- Reset replay state on initial snapshot load or explicit campaign reload.
- Replay without invoking the command runner, changing the snapshot, or creating a battle.
- Expose exact retreat destination and trapped reason from transient battle-finalization data.

## Scene integration

The existing map transform, marker primitives, overlay layers, async command runner, transactional snapshot commit, and handoff actions remain in place.

On successful command completion, `main_writeback.gd` parses the backend payload before committing the replacement snapshot, then supplies the previous snapshot, committed snapshot, and transient result to the presenter. Active tracks override only rendered counter positions. Interpolated values never enter `snapshot` or any write-back payload.

The active map scene draws:

- parallel formation movement at presenter pixels;
- a visible Skip control while animation is active;
- direct labels for `node_contact`, `node_simultaneous`, `edge_cross`, and `edge_catchup`;
- participant emphasis and unrelated-map de-emphasis at contact;
- Ambush only for participant formations whose authoritative row has `ambush_triggered == true`, displaying the received 1150 value as `+15%`;
- a transient successful-retreat destination or `trapped_no_legal_retreat` outcome.

## Pending-battle modal

While `pending_battle` is present, an opaque modal gate states that operational resolution is paused, displays the exact contact kind/location, lists participating sides and formation names, and shows triggered Ambush metadata. It exposes the existing Auto-resolve and Handoff actions plus Replay Last Contact.

All background map orders, selection, operational commands, panning, zooming, and unrelated panel actions are consumed while the modal exists. The modal cannot be dismissed while the battle remains pending. Replay may run under the modal and returns to the identical modal state.

## Compatibility and failure behavior

- Schema version remains 13.
- Schema-12+ snapshots without participant rows or transient presentation fields continue to load.
- Missing optional presentation data disables the associated label/replay rather than synthesizing authority.
- Malformed or disconnected movement records snap to authoritative endpoints.
- A missing authoritative encounter or retreat datum is surfaced as unavailable; Godot does not calculate a substitute.
- Command failure preserves the prior snapshot, presenter state, selection, and camera using the existing transactional path.

## Test and visual evidence strategy

Python contract tests prove deterministic additive participant, movement, and retreat output without campaign persistence. A focused Godot test exercises interpolation endpoints, parallel timing, skip, all contact labels, exact contact stopping, modal gating, Ambush filtering, replay state neutrality/session reset, retreat/trapped display, and old-snapshot compatibility.

The standard screenshot harness captures true runtime 1920x1080 evidence for node contact, simultaneous node contact, edge contact, prepared Ambush, the pending-battle modal, successful retreat, and trapped removal. Automated captures are artifacts for owner review, not visual approval.
