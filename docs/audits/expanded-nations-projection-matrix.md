# Expanded Nations projection matrix

Status: **invalidated**.

The installed-stack regeneration at head
`b7a9442009b6924a847ae1df536001bf3ee1fc28` completed structurally, but its 21
actor rows, 96 managed-file hashes, and all projection signatures were identical
to the pre-correction matrix. Russia retained actor-unit hash
`a8a37b9d757620c4f42fbe4dcbb1522ebab7ef9a3c4b039dadbafafcee7a80fa`
and projection signature
`4b66c920cbe707b144f5f0e49d68eed4a3e7ffd1829d51a88a85206d82cc8c43`.

The required `dp_infantry_8` definition was therefore not emitted. The same-source
`{define ...}` correction was not exercised against the installed stack and does
not resolve the native Russia crash.

All actor rows and signatures remain removed from authority. Do not regenerate the
matrix again until the effective definition source and syntax are captured, the
projection correction is replaced, exact-head CI passes, and the replacement is
audited.

This invalidation is not native gameplay acceptance, ready-for-review approval, or
merge approval.
