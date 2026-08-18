# Fixture and rule freeze (Step 0)

Frozen at: 2026-08-17T23:32:24+08:00

These files are regression-only. Do not add deterministic rules, and do not edit the listed fixtures to raise accuracy.

Manifest: `Tools/ContextualEvaluation/fixture_rule_freeze.json`  
Checker: `python3 Tools/ContextualEvaluation/validate_fixture_rule_freeze.py`

## Regression re-run at freeze

| Gate | Command | Result |
|---|---|---|
| Canonical 100+50+84 | `validate_deterministic_gate.py` | 234/234 exact, max p95 1148 µs |
| Held-out clean 63 | `validate_deterministic_gate.py --heldout` | 63/63 exact, max p95 1047 µs |

`heldout_generalization.jsonl` and `heldout_generalization_clean.jsonl` are byte-identical at this snapshot.

## Unfreeze

Requires an ADR that names the file, the reason, and a new freeze snapshot. Accuracy chasing on these sets is not a product result.
