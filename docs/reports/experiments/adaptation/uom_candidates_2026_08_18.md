# Engine candidate existence on adaptation_replay (2026-08-18)

Artifact: `docs/reports/experiments/adaptation/uom_candidates_2026_08_18.jsonl`  
Runner: `Tools/ContextualEvaluation/uom_replay.cpp --candidates`

This run does not change KeyHandler. It asks whether the expected string, or a multi-character engine candidate that appears inside the expected string, is already in `ReadingGrid::candidatesAt`.

## Transfer misses

| Row | Walk | Expected | Full expected in candidates | Longest multi-character candidate inside expected |
|---|---|---|---|---|
| `ar-xfer-001` | 別在說 | 別再說 | no | 別再 |
| `ar-xfer-006` | 不要在說 | 不要再說 | no | 再說 |
| `ar-xfer-007` | 在說一變 | 再說一遍 | no | 再說 |
| `ar-xfer-008` | 別作是 | 別做事 | no | 做事 |

Summary field `transfer_misses_with_multichar` is 4. All four informative transfer misses have at least one two-character engine candidate that appears in the expected sentence.

`別再說` as a whole phrase is not a candidate. A later one-shot suggestion can offer `別再`, `再說`, or `做事`. It cannot offer `別再說` without inventing text outside the engine list.

## Same-key hits

`請再說一次` and `做事要小心` are also not whole-sentence candidates. The longest listed pieces are `請再` and `做事`. The current three-node override still makes those two probes exact after observe, without a multi-character suggestion UI.
