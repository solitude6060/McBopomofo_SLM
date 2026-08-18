# adaptation_replay fixture contract

Last updated: 2026-08-18T00:40:00+08:00

The default runner path measures the current `UserOverrideModel`. It does not change capacity, half-life, or the production key. Persistence is off unless `--persist=path` is set.

Optional replay-only flags `--key=head_reading|head_next` and `--memory=shared` are experimental arms. They do not change KeyHandler. Results: `docs/reports/experiments/adaptation/uom_key_arm_2026_08_18.md`. Persist results: `docs/reports/experiments/adaptation/uom_persist_2026_08_18.md`. `--oneshot` accepts one engine multi-character candidate after the full probe: `docs/reports/experiments/adaptation/uom_oneshot_2026_08_18.md`.

## Key the runner must use

`UserOverrideModel.cpp` `FormObservationKey` builds:

```text
(anterior_reading,anterior_value)-(prev_reading,prev_value)-(head_reading,head_top_unigram)
```

Head uses the top unigram **before** the user override. Prev and anterior use current unigram values. Punctuation nodes collapse to the empty-node marker.

String-key `observe(key, candidate, timestamp)` is only for unit tests. The product measurement must go through walk-based `observe` / `suggest`.

## Record shape

One JSON object per line in `Tests/fixtures/contextual_bopomofo/adaptation_replay.jsonl`.

| Field | Meaning |
|---|---|
| `id` | Stable identity |
| `observe.readings` | First occurrence; user commits `observe.committed` |
| `probe.readings` | Second occurrence; score `probe.expected` |
| `same_key_expected` | Whether the current three-node key should match |
| `license` | MIT for hand-crafted rows |

The runner is `Tools/ContextualEvaluation/uom_replay.cpp` (binary `build/uom_replay`). Schema check: `validate_uom_replay.py`.

A row `hit` is exact after observe and not exact on the unobserved baseline. Summary fields:

- `same_key_hits` / `transfer_hits`: improvement counts (`hit`)
- `same_key_baseline_exact` / `transfer_baseline_exact`: exact before observe
- `same_key_after_exact` / `transfer_after_exact`: exact after observe
- `harmful_overrides`: exact before observe and wrong after
- `restart_hits`: improvement after a new `UserOverrideModel` instance. Default path expected 0. With `--persist=path`, expected `same_key_hits + transfer_hits`.

Do not implement 7-day / 30-day half-life or a production key change in order to run the default path of this fixture. Experimental `--key` / `--memory` stay in `uom_replay` until a user gate authorizes a KeyHandler change. `--persist` measures serialize only; KeyHandler already writes `user-override-model.txt` after observe.
