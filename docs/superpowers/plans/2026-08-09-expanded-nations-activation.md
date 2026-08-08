# Expanded Nations activation implementation boundary

## Goal

Expose the accepted strategic actor rosters and research graphs in the native Gates of Hell Conquest UI without globally mixing countries that share a tactical side.

## Implemented slice

- Compile the validated five-layer stack through the accepted faction compiler.
- Select exactly one playable strategic actor.
- Project only that actor's purchase-ready definitions into a managed final-layer unit file.
- Project only that actor's research graph into the matching tactical-side research file.
- Replace the final-layer roster root with settings, infantry settings, and the selected actor unit file only.
- Preserve Core Code:X by removing the verified generated files.
- Reject hosted actors, warnings, errors, unmanaged overrides, modified managed files, missing source definitions, and actor/research mismatches.
- Keep all generated output ignored and outside tracked Workshop deployment.

## Non-goals for this PR

- No upstream Code:X, West81, AI Overhaul, or Vanilla mutation.
- No global national wrapper include.
- No new strategic simulation authority.
- No changes to actor economy rules.
- No custom in-game country-selection scene yet. The first player-facing boundary is the one-command PowerShell actor selector and launcher.

## Acceptance order

1. Repository and focused CI pass.
2. Run Serbia activation and confirm only the Serbian projection appears in native recruitment and research.
3. Purchase and spawn representative Serbian units.
4. Repeat representative tests for DPRK, Ukraine with ILDU, France, Germany, Russia, and PRC.
5. Run the full 21-actor projection matrix.
6. Restore Core mode and confirm canonical Code:X behavior returns.
