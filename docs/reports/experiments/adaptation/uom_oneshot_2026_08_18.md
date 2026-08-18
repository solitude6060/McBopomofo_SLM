# One-shot multi-character accept (2026-08-18)

Canonical artifact: `docs/reports/experiments/adaptation/uom_oneshot_2026_08_18.jsonl`  
Summary: `docs/reports/experiments/adaptation/uom_oneshot_2026_08_18_summary.json`  
Plan: `docs/adaptation_oneshot_suggestion_PLAN.md`  
Runner: `Tools/ContextualEvaluation/uom_replay.cpp --oneshot`  
Validator printed `REPLAY PASS: ... oneshot=True same_key 2/5, transfer 0/8, harmful 0, restart_hits 0, prefix_harms 0`.

`--oneshot` does not change the typing path. Insert still uses the three-node key at the last cursor only. After the probe has every reading, the runner looks up a `head_next` suggestion and accepts at most one engine multi-character candidate that contains it, with a high-score override. That accept is the replay stand-in for a user tapping the suggestion once.

KeyHandler is unchanged.

## Summary

| Quantity | Value | Source field |
|---|---|---|
| same-key UOM hits | 2/5 | `same_key_hits` |
| transfer UOM hits | 0/8 | `transfer_hits` |
| oneshot offered | 4 | `oneshot_offered` |
| oneshot exact and wrong at baseline | 5 | `oneshot_hits` |
| oneshot transfer hits | 3 | `oneshot_transfer_hits` |
| oneshot extras beyond current UOM | 3 | `oneshot_extra` |
| harmful overrides | 0 | `harmful_overrides` |
| prefix harms | 0 | `prefix_harms` |

`adaptation_key_harm.jsonl` with `--oneshot` also has `prefix_harms` 0 and `oneshot_offered` 0.

## Transfer rows

| Row | After UOM | Offered | After accept | Exact |
|---|---|---|---|---|
| `ar-xfer-001` | 別在說 | 再說 | 別再說 | yes |
| `ar-xfer-006` | 不要在說 | 再說 | 不要再說 | yes |
| `ar-xfer-007` | 在說一變 | 再說 | 再說一變 | no (`遍` / `變`) |
| `ar-xfer-008` | 別作是 | 做事 | 別做事 | yes |

The runner offered `再說`, not `別再`, on `別在說`. Accepting `再說` at the `ㄗㄞˋ` cursor produced `別再說`. `別再說` as a whole phrase is still not a candidate.

Same-key rows already exact after the three-node override did not receive an extra offer.

## What this measurement can and cannot decide

Accepting one engine candidate after the full reading sequence fixed three of the four informative transfer misses. Mid-input prefixes did not flip. The remaining miss is `再說一遍`, which needs `遍` rather than `變`.

This is not a KeyHandler change. A later UI may show `再說` or `做事` once for the user to accept. It may not silently rewrite earlier characters after each insert, and it may not invent `別再說`.
