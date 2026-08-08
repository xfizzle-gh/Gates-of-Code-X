# Serbia native acceptance blocker

Exact implementation head: `01f7a83f33bdc0b1d90a6146e0adfdcfcbb2fc0b`

The first native Serbia activation stopped before game launch during opponent projection.

Observed exception:

```text
gates_of_codex.expanded_nations_models.ExpandedNationsError:
Opponent entry 'squad_pzgren_moto2_con_nato(frg)' explicit side 'csa' disagrees with canonical side 'frg'
```

The exact-state guard passed. The local branch was clean at the accepted head after preserving prior local work in a named stash. Package installation succeeded. The failure occurred in `project_opponent_units()` before activation committed generated files or launched Gates of Hell.

This is a reproducible implementation-side native-stack blocker. Serbia is neither passed nor failed at the gameplay layer because the game did not launch.

Do not proceed to DPRK or any later actor until the source definition is located, the side-authority conflict is corrected with regression coverage, CI passes, and a fresh independent audit accepts the new exact head.
