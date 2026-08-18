# UserOverrideModel persist replay (2026-08-18)

Canonical artifact: `docs/reports/experiments/adaptation/uom_persist_2026_08_18.jsonl`  
Summary: `docs/reports/experiments/adaptation/uom_persist_2026_08_18_summary.json`  
Runner: `Tools/ContextualEvaluation/uom_replay.cpp --persist`  
Validator: `python3 Tools/ContextualEvaluation/validate_uom_replay.py --persist` printed `REPLAY PASS: key=three_node memory=isolated persist=True same_key 2/5, transfer 0/8, harmful 0, restart_hits 2, prefix_harms 0`.

The default path without `--persist` still reports `restart_hits 0`. That path is unchanged.

## Summary

| Quantity | Default | Persist | Source field |
|---|---|---|---|
| same-key improvements (`hit`) | 2/5 | 2/5 | `same_key_hits` |
| transfer improvements (`hit`) | 0/8 | 0/8 | `transfer_hits` |
| harmful overrides | 0 | 0 | `harmful_overrides` |
| prefix harms | 0 | 0 | `prefix_harms` |
| restart improvements | 0 | 2 | `restart_hits` |

`restart_hits` counts probes that were wrong at baseline and exact after a new `UserOverrideModel` instance. With `--persist`, that instance loads the file written after `observe`.

The two restart hits are the same rows as the same-key hits: `ar-same-002` (`請再說一次`) and `ar-same-004` (`做事要小心`).

## File format

```text
# McBopomofo-UserOverrideModel 1
<key>\t<candidate>\t<override_count>\t<timestamp>\t<0|1>\t<observation_count>
```

Runtime path (macOS): `user-override-model.txt` next to `data.txt` in the user data folder. The file is local and can be deleted. It is not a public n-gram or SLM corpus.

`save` / `load` reject paths under `/tmp` or `/var/tmp`.

## What this measurement can and cannot decide

On this fixture, persist restores the same-key improvements after a new instance. Transfer stays 0/8. KeyHandler still uses the three-node key and does not re-suggest earlier nodes. macOS and Ubuntu dogfood still need the user.
