# Expanded Nations projection matrix

Status: **invalidated**.

The previously committed schema-3 matrix is no longer authoritative because the
actor projection now preserves source-local `{define ...}` dependencies ahead of
purchase blocks. That correction changes generated actor-unit bytes and projection
signatures.

All prior actor rows and signatures have been removed from authority. Regenerate
the complete 21-actor matrix from the exact installed five-layer stack only after
the correction passes exact-head focused CI, full repository CI, and review.

This invalidation is not native gameplay acceptance, ready-for-review approval, or
merge approval.
