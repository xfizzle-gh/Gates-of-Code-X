# Branch protection (main)

Repository ruleset **main-required-ci** (id 20565327) is active on `refs/heads/main`.

Required status checks (strict — branch must be up to date with main):

- test (ubuntu-latest, 3.11)
- test (ubuntu-latest, 3.13)
- test (windows-latest, 3.11)
- test (windows-latest, 3.13)
- godot-map
- windows-executable

Pull requests are required. Force-push/delete of main is not allowed via this ruleset policy.
A later green hotfix does **not** satisfy the requirement that the original PR head was green before merge.

See also `docs/development-process.md`.
