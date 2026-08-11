# Division/brigade operation commitment decision

Source: NORESUS study #209 / PR #210 plus owner approval of the Shutkar1992 division-scale direction.

## Product decision

Gates of Code:X should pursue a strategic formation model in which the normal on-map maneuver counter may represent a brigade or division while battalions remain persistent roster/tactical identities inside that formation.

Before a tactical engagement, the player should explicitly commit subordinate battalions and support packages to roles. GoH should receive only a bounded tactical representation of the committed force. Non-committed battalions remain in strategic reserve.

This is an additive extension of the existing `StrategicFormation -> battalion_ids[] -> Battalion` model and the existing guarded `PendingBattle` / export / verify / import bridge. It is not permission to replace Earth3, operational movement, actor identity, exact-stack validation, or battle-result verification.

## Intended operation shape

```text
StrategicFormation (brigade/division)
  -> Battalion A
  -> Battalion B
  -> Battalion C
  -> Tank Battalion
  -> Artillery / Air Defense / Engineer / Recon support

Operation
  -> maneuver commitments
  -> reserve commitments
  -> support commitments
  -> tactical scaling / wave plan

PendingBattle
  -> exact participating battalion identities
  -> exact actor/tactical-faction authority

GoH tactical battle
  -> bounded committed tactical slice
  -> sequential/coherent waves when proven by #185

Verified result import
  -> survivors/losses to exact battalion
  -> formation readiness/condition/experience summary
  -> operational retreat/control consequence
```

## Sequencing

1. Complete the current #201 tactical-faction architecture gate.
2. Complete the first #176 Earth3 strategic-to-tactical-to-strategic golden path.
3. Use #185 to prove coherent battalion materialization/waves and practical tactical scale.
4. Add an explicit versioned Operation / OperationCommitment schema.
5. Add backend commitment validation and compilation into existing pending-battle participants.
6. Add Godot formation hierarchy / task-assignment UI.
7. Add post-battle formation roll-up and measured balance.

## Guardrails

- Division is the largest normal player-controlled strategic echelon unless a later owner ruling changes it.
- Independent battalions remain valid map formations.
- Do not spawn literal real-world division headcounts into one tactical mission.
- Do not choose final battalion quantities before #185 performance/AI measurements.
- Preserve one-week strategic turns and the existing deterministic operational-tick model.
- Preserve exact battalion identity through commitment, tactical materialization, and survivor import.
- Do not describe native purchased units as persistent battalion assets unless stable attribution is proven.
