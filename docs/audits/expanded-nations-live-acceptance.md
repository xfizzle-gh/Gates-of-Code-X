# Expanded Nations native acceptance

## Accepted historical checks

- Serbia passed at the previously accepted implementation.
- DPRK passed at the previously accepted implementation.

These observations remain historical native evidence only.

## Current blocker: Russia

A brand-new Russia campaign crashed while opening the dynamic-campaign page at
head `3579281e630f573838bf7451f8aa0c334c415068`:

`APP_ERROR: define not found`

The generated runtime file invoked `dp_infantry_8`. Exact installed-stack capture
identified the owning purchase as `rus155_inf_rpg28(rusa)` and established that the
definition is a parenthesized cross-file declaration:

- declaration file: Code:X AI Overhaul
  `resource/set/multiplayer/units/2022s/doctrine_settings.set`
- declaration syntax: `(define "dp_infantry_8" ...)`
- declaration file SHA-256:
  `519173451b87ce6b464a5ffce3de5bfa0f0f87b59e519642ea03ee3137255365`
- purchase file: Code:X AI Overhaul
  `resource/set/multiplayer/units/2022s/doctrine_units_rusa.set`
- purchase file SHA-256:
  `d88fe754d4a7e608f153a48e5e0aa4ffdd1546dc47e07a7da7bd230cbd3bd51e`

The first same-source brace-form correction was rejected because it produced no
runtime-byte change.

The replacement correction at implementation head
`a4faf628c556d9341d4353ffa9b797002cde987a` adds bounded parenthesized-definition
scanning, installed-stack precedence, recursive cross-file closure, baseline
Conquest-settings exclusion, deterministic conflict/cycle failure, and final
runtime-artifact closure verification. The final branch head is
`dda2f5c569093f5b7b8eaa2fef16397cc628745c` after rebinding invalidated evidence.

Exact-head workflows are green, but Russia remains blocked until a regenerated
installed-stack matrix proves that Russia's actor-unit hash and projection
signature changed and the required definitions precede `rus155_inf_rpg28(rusa)`.

Do not run a native Russia campaign, proceed to France, mark PR #172 ready, or
merge before that matrix is audited and committed.
