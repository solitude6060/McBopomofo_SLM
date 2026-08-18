# Current UserOverrideModel replay (2026-08-17)

Canonical artifact: `docs/reports/experiments/adaptation/uom_replay_2026_08_17_v3.jsonl`  
Summary: `docs/reports/experiments/adaptation/uom_replay_2026_08_17_summary.json`  
Runner: `Tools/ContextualEvaluation/uom_replay.cpp`  
Validator: `python3 Tools/ContextualEvaluation/validate_uom_replay.py` printed `REPLAY PASS: same_key 2/5, transfer 0/8, harmful 0, restart_hits 0`.

This run measures the current `UserOverrideModel` only. Capacity 500, half-life 5400 s, three-node `FormObservationKey`, no serialize.

## Run history

| File | Fixture | Note |
|---|---|---|
| `uom_replay_2026_08_17.jsonl` | 10 rows, `ar-xfer-001` reading `ㄅㄧㄭˊ` | Empty output; not used |
| `uom_replay_2026_08_17_v2.jsonl` | 10 rows, reading fixed to `ㄅㄧㄝˊ` | 1 informative transfer miss |
| `uom_replay_2026_08_17_v3.jsonl` | 13 rows (`ar-xfer-006`–`008` added) | Canonical |

## Summary (v3)

| Quantity | Value | Source field |
|---|---|---|
| same-key rows | 5 | `same_key_rows` |
| same-key already exact before observe | 3 | `same_key_baseline_exact` |
| same-key exact after observe | 5 | `same_key_after_exact` |
| same-key improvements (`hit`) | 2 | `same_key_hits` |
| transfer rows | 8 | `transfer_rows` |
| transfer already exact before observe | 4 | `transfer_baseline_exact` |
| transfer exact after observe | 4 | `transfer_after_exact` |
| transfer improvements (`hit`) | 0 | `transfer_hits` |
| harmful overrides | 0 | `harmful_overrides` |
| restart improvements | 0 | `restart_hits` |

`hit` means the probe was wrong before observe and exact after observe.

## Per-row observations

Same-key improvements:

- `ar-same-002`: baseline `請在說一次` → after `請再說一次`
- `ar-same-004`: baseline `作是要小心` → after `做事要小心`

Informative transfer misses (baseline already wrong; after unchanged):

- `ar-xfer-001`: `別在說` (expected `別再說`)
- `ar-xfer-006`: `不要在說` (expected `不要再說`)
- `ar-xfer-007`: `在說一變` (expected `再說一遍`)
- `ar-xfer-008`: `別作是` (expected `別做事`)

The other four transfer rows were already exact before observe.

## What this measurement can and cannot decide

On this fixture the current three-node key improved both same-key probes that were wrong at baseline (2/2). It improved none of the four transfer probes that were wrong at baseline (0/4). Harmful overrides are 0. A new `UserOverrideModel` instance never improved a probe.

The direction document said a near-zero transfer rate is the condition for a later key-change arm. That arm is not implemented in this step.

Do not persist UOM or change half-life from this file.
