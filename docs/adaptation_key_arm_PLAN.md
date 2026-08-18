# Adaptation key-arm plan

Date: 2026-08-18  
Parent: `docs/台灣繁中注音輸入法_2026_08_方向重評.md` step 1 follow-on

## Need

The current three-node key improved same-key probes that were wrong at baseline (2/2) and improved none of the four transfer probes that were wrong at baseline (0/4). The product need is: remember 再 / 做 in a new left context without flipping 在吃飯.

## Assumption to test, not inherit

Inherited claim: “change the key” under the current KeyHandler protocol (suggest after each insert at `length-1`).

Verified this session from `UserOverrideModel.cpp` `FormObservationKey` and `uom_replay.cpp` `convertWithUom`:

- The current key is `(anterior_value)-(prev_value)-(head_reading, head_top_unigram)`.
- Suggest runs when the new syllable is the last node. The following syllable does not exist yet.
- Therefore a forward (`head_next`) key cannot fire at the same moment as production suggest, unless replay also re-suggests earlier nodes after later inserts.

A `head_reading` key can transfer 請再說 → 別再說 at the moment ㄗㄞˋ is typed. It can also flip 在吃飯 at the moment ㄗㄞˋ is typed, before 吃 exists.

## Arms (replay only; KeyHandler unchanged)

| ID | Key | Suggest protocol | Purpose |
|---|---|---|---|
| K0 | three_node (current) | end-only | already measured |
| K1 | head_reading | end-only | literal “looser key” |
| K2 | head_next | re-suggest earlier nodes after each insert | first-principles: 說 vs 吃 |

Shared-memory harm fixture: observe 請再說一次, then probe 我在吃飯 with the same `UserOverrideModel` instance. Isolated per-row replay cannot see this harm.

## Exit

Recorded 2026-08-18 in `docs/reports/experiments/adaptation/uom_key_arm_2026_08_18.md`:

- K1 transfers 1/8 on `adaptation_replay.jsonl` and has `prefix_harms` 1 (`在` → `再` after the first reading of `在吃飯`). Do not promote K1.
- K2 transfers 2/8, keeps same-key 2/5, and has `prefix_harms` 0 on the harm and shared fixtures. Wiring K2 needs a KeyHandler re-suggest protocol change. That is a user gate.
- `別在說` stays wrong on K0/K1/K2 (soft override loses to the `別在` phrase). Do not train n-gram from this result.

Final-sentence `harmful_overrides` is 0 on all three arms. Mid-input `prefix_harms` is the load-bearing harm metric.

## Out of scope

- Persist / serialize in KeyHandler
- Half-life change
- n-gram / SLM training
- Editing frozen 234 / 63 fixtures
- Commit
