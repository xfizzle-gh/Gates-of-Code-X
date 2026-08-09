# Expanded Nations native acceptance

## Accepted historical checks

- Serbia passed at the previously accepted implementation.
- DPRK passed at the previously accepted implementation.

These observations remain historical native evidence only.

## Current blocker: Russia

A brand-new Russia campaign crashed while opening the dynamic-campaign page at
head `3579281e630f573838bf7451f8aa0c334c415068`:

`APP_ERROR: define not found`

The engine failed on a generated purchase block invoking `dp_infantry_8` in
`conquest/goc_active_actor_units.set`. The excerpt ends the failing block on line
472; the line-474 `resolved_unit=rus155_inf_saperi(rusa)` comment begins the next
entry and does not identify the failing purchase.

The first attempted correction at head
`b7a9442009b6924a847ae1df536001bf3ee1fc28` searched only same-source brace-form
`{define ...}` declarations. Installed-stack matrix regeneration produced all 21
actor rows and passed structural verification, but every actor row, all 96 managed
file hashes, and every projection signature were identical to the pre-correction
matrix. Russia retained actor-unit hash
`a8a37b9d757620c4f42fbe4dcbb1522ebab7ef9a3c4b039dadbafafcee7a80fa`.

Therefore the required definition was not emitted and Russia remains blocked.
Capture the effective installed-stack declaration and include path for
`dp_infantry_8` before replacing the correction.

Do not run another native Russia campaign, proceed to France, mark PR #172 ready,
or merge.
