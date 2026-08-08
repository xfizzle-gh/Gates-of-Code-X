# Expanded Nations corrected projection matrix

The corrected implementation was exercised against the accepted 24-actor resolved payload and the audited West81, Code:X, AI Overhaul, and Gates source layers. All 21 playable actors generated, semantically verified, and restored to Core mode successfully.

The opponent-entry count is the filtered set preserved for non-selected tactical sides. Entries belonging to the selected actor's tactical side are excluded and replaced by that actor's roster.

| Actor | Actor units | Preserved opponent entries | Research nodes |
|---|---:|---:|---:|
| blr | 36 | 1194 | 50 |
| can | 14 | 1272 | 21 |
| deu | 29 | 1272 | 42 |
| dnk | 55 | 1272 | 64 |
| donbas | 52 | 1194 | 70 |
| dprk | 28 | 1194 | 37 |
| esp | 55 | 1272 | 64 |
| fin | 15 | 1272 | 23 |
| fra | 21 | 1272 | 29 |
| gbr | 33 | 1272 | 44 |
| ita | 19 | 1272 | 27 |
| nld | 15 | 1272 | 23 |
| nor | 55 | 1272 | 64 |
| pol | 18 | 1272 | 26 |
| prc | 80 | 1454 | 100 |
| rus | 212 | 1194 | 249 |
| srb | 24 | 1194 | 35 |
| swe | 17 | 1272 | 26 |
| tur | 55 | 1272 | 64 |
| ukr | 185 | 1281 | 227 |
| usa | 74 | 1272 | 93 |

This is deterministic implementation-side source and projection validation. It is not independent audit acceptance and it is not native Gates of Hell acceptance. The corrected exact head still requires full CI, fresh independent review, and the documented live matrix before the PR can leave draft state.
