# Adaptation key-arm replay (2026-08-18)

Plan: `docs/adaptation_key_arm_PLAN.md`  
Runner: `Tools/ContextualEvaluation/uom_replay.cpp` (`--key`, `--memory`)  
KeyHandler and `LanguageModelManager` were not changed.

Replay-only experimental keys. Default `--key=three_node --memory=isolated` reproduces the 2026-08-17 current-model measurement (same-key 2/5, transfer 0/8).

## Artifacts

| File | Arm | Fixture |
|---|---|---|
| `uom_key_k0_2026_08_18.jsonl` | three_node, isolated | `adaptation_replay.jsonl` |
| `uom_key_k1_2026_08_18.jsonl` | head_reading, isolated | `adaptation_replay.jsonl` |
| `uom_key_k2_2026_08_18.jsonl` | head_next + re-suggest, isolated | `adaptation_replay.jsonl` |
| `uom_key_k0_harm_2026_08_18.jsonl` | three_node, isolated | `adaptation_key_harm.jsonl` |
| `uom_key_k1_harm_2026_08_18.jsonl` | head_reading, isolated | `adaptation_key_harm.jsonl` |
| `uom_key_k2_harm_2026_08_18.jsonl` | head_next, isolated | `adaptation_key_harm.jsonl` |
| `uom_key_k1_shared_2026_08_18.jsonl` | head_reading, shared | `adaptation_key_shared.jsonl` |
| `uom_key_k2_shared_2026_08_18.jsonl` | head_next, shared | `adaptation_key_shared.jsonl` |
| `uom_key_arm_2026_08_18_summary.json` | all summaries | this run |

`hit` is exact after observe and not exact on the unobserved baseline.  
`harmful_overrides` is exact at baseline and wrong after observe on the **final** walk.  
`prefix_harms` is exact at the `prefix_after` snapshot on the unobserved baseline and wrong after observe. That snapshot is the walk after N readings, before later syllables can pull the path back.

## Replay fixture (`adaptation_replay.jsonl`)

| Arm | same-key hits | transfer hits | final harmful | prefix_harms | Source |
|---|---|---|---|---|---|
| K0 three_node | 2/5 | 0/8 | 0 | 0 | `uom_key_k0_2026_08_18.jsonl` summary |
| K1 head_reading | 1/5 | 1/8 | 0 | 0 | `uom_key_k1_2026_08_18.jsonl` summary |
| K2 head_next | 2/5 | 2/8 | 0 | 0 | `uom_key_k2_2026_08_18.jsonl` summary |

Same-key improvements that remain on K0 and K2:

- `ar-same-002`: `請在說一次` → `請再說一次`
- `ar-same-004`: `作是要小心` → `做事要小心`

K1 lost `ar-same-004`. Observe stored the two-reading candidate `做事` under `(ㄗㄨㄛˋ,作)`. Suggest fires when only `ㄗㄨㄛˋ` exists, so `overrideCandidate(0, "做事")` cannot apply.

Transfer improvements:

- K1 `ar-xfer-006`: `不要在說` → `不要再說`
- K1 `ar-xfer-007`: `在說一變` → `再說一變` (changed; expected `再說一遍`; `遍`/`變` is a different homophone)
- K2 `ar-xfer-006`: `不要在說` → `不要再說`
- K2 `ar-xfer-007`: `在說一變` → `再說一變` (same partial change)
- K2 `ar-xfer-008`: `別作是` → `別做事`

Informative transfer misses that remain:

- K0/K1/K2 `ar-xfer-001`: `別在說` (expected `別再說`). Debug: K1 suggests `再` at cursor 1; soft override loses to the `別在` phrase.
- K0/K1 `ar-xfer-008`: `別作是` (K2 only)

## Harm fixtures

Final-sentence `harmful_overrides` is 0 on K0, K1, and K2.

`prefix_harms` on `adaptation_key_harm.jsonl`:

| Arm | prefix_harms | Row |
|---|---|---|
| K0 | 0 | `uom_key_k0_harm_2026_08_18.jsonl` |
| K1 | 1 | `ar-harm-zai-003`: prefix `在` → `再` |
| K2 | 0 | `uom_key_k2_harm_2026_08_18.jsonl` |

Shared-memory session (`adaptation_key_shared.jsonl`): observe `請再說一次`, then probe later rows on the same `UserOverrideModel` instance.

| Arm | prefix_harms | Row |
|---|---|---|
| K1 | 1 | `ar-shared-harm-002`: prefix `在` → `再` |
| K2 | 0 | `uom_key_k2_shared_2026_08_18.jsonl` |

`ar-harm-zai-001` (`我在吃飯`) stays `我在` at the two-reading prefix on K1. Debug on that row still shows suggest `再` at `ㄗㄞˋ`. The `我在` phrase plus a soft override keeps the final and prefix strings as `我在`. The standalone `在吃飯` prefix does not have that phrase, so K1 shows `再` after the first reading. Later `吃`/`飯` pull the final walk back to `在吃飯`.

## What the arms actually keyed

Experimental observe finds the first reading whose before-walk character differs from the committed text, then stores a syllable key `(reading, top_one_reading_unigram)` or `next_reading-(reading, top_unigram)`. Suggest uses `grid.readings()[cursor]`, not the multi-character walk node. That is required because `別在` is one node; a node-level head key is `(ㄅㄧㄝˊ-ㄗㄞˋ,別在)` and misses `(ㄗㄞˋ,在)`.

K2 re-suggests every earlier cursor after each insert. Production KeyHandler suggests only at `length-1`.

## Decision from the plan exit

- K1 transfers on this fixture and has prefix harm > 0. Do not promote K1.
- K2 transfers more than K0 (2/8 vs 0/8), keeps both same-key hits, and has prefix harm 0 on these fixtures. Wiring it requires a KeyHandler protocol change (re-suggest earlier nodes). That change is a user gate.
- Transfer is still incomplete (`別在說` stays wrong on all arms). That is not a reason to train a public n-gram in this session. The direction document still gates n-gram on remaining cross-sentence generalization **after** a product increment, or on a D regression break.

Do not persist UOM, do not change production half-life, and do not change the production default key from this file.
