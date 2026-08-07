# Earth3 crop mask v6 — owner visual review

**Status:** pending owner visual approval. Do **not** treat as approved.

## Correction goals

1. Restore Africa → Middle East land corridor through Egypt / Nile Delta / Sinai / Levant / southern Turkey.
2. Complete Scandinavia (Norway, Sweden, Finland) to natural northern coasts; include Kola approach; exclude Arkhangelsk / deep Arctic Russia.

## Authority numbers (provisional)

| Field | Value |
|------|------:|
| Candidate | `em_reference_masked` mask **v6** |
| Province count | **3345** |
| Land / water | 3133 / 212 |
| included_ids_sha256 | `4fe9d98bbf40d2588286d3d4ec5513ffa3a8f0b7b2ae5689373217b4cb569a1b` |
| Prior v5 count/hash | 3038 / `7effdffb…` |

## Evidence images

- `full_theatre_labelled.png`
- `egypt_sinai_levant.png`
- `turkey_east_med.png`
- `scandinavia_full.png`
- `north_africa.png`
- `black_sea_caucasus.png`

Also under `docs/earth3-crop/preview_em_reference_masked.png` and `docs/earth3-crop/closeups/`.

## Required-location gates (pass)

Cairo, Alexandria, Port Said, Suez, Arish/Sinai, Jerusalem, Beirut, Damascus, Adana, Narvik, Kiruna, Rovaniemi, plus prior Europe theatre set. Arkhangelsk excluded. Murmansk informational (Kola approach).

## Follow-ups (after approval)

- Rebase water-presentation PR #101 onto approved geometry.
- Freeze production dataset / Godot assets if not already refreshed on this branch.
