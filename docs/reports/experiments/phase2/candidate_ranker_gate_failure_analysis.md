# Candidate Ranker Gate Failure: Disjoint Context Generalization

**Date:** 2026-06-22T00:30:00+08:00
**Experiment:** candidate-ranker-synthetic-heldout
**Gate Result:** FAIL

## Executive Summary

The count-based candidate ranker (`candidate-ranker-v1`) was trained on a
35-case synthetic fixture (`ranker_training_synthetic.jsonl`, 22 usable cases)
whose contents were verified disjoint from all evaluation fixtures. The
intent was to test whether a lightweight count-feature model can learn
disambiguation patterns that generalize to unseen evaluation contexts.

**It cannot.** The ranker produces zero changes on heldout (39/63, same as
baseline) and +1 over baseline on the saturated suite (182/234 vs 181/234).
It does not beat the deterministic reranker (41/63 heldout, 234/234
saturated) and the heldout gate fails outright.

## Root Cause: Exact Feature Matching

The ranker's core mechanism is exact-string feature counting:

```python
# Training: counts[feature_type][feature_key] += 1
# Feature keys are string-concatenated context + candidate:
"reading_candidate":  reading + "\t" + token
"transition":         previous + "\t" + token
"baseline_window":    prev + "\t" + reading + "\t" + token + "\t" + next
```

At scoring time, the ranker checks whether the **same exact feature key**
exists in its count table. If an evaluation case and a training case share
the same reading and target candidate but differ in left or right context,
their keys still do not match. A generic example is
`left_A\treading\ttoken\tright_A` versus
`left_B\treading\ttoken\tright_B`: the ranker records zero feature hits
despite partial similarity.

This is a fundamental expressivity limitation: the ranker treats each context
as an opaque string and cannot recognize partial pattern similarity.

## Quantitative Proof

### Heldout Feature Coverage (63 cases)

| Feature Type | Cases with Coverage | Note |
|---|---|---|
| `reading_candidate` | 46 | Most readings seen in training (common Bopomofo syllables) |
| `candidate` | 53 | Most characters seen in training |
| `transition` | 30 | Some transition patterns overlap |
| `baseline_prev_candidate` | 26 | Some left-context patterns overlap |
| `baseline_next_candidate` | 24 | Some right-context patterns overlap |
| `baseline_window_candidate` | 8 | Very few full 3-token contexts overlap |
| **non_baseline_evidence** | **0** | **Zero cases where override actually triggered** |

Individual features have coverage (e.g., 46/63 have reading+candidate in
training), but the **conservative gate requires at least 2 non-baseline feature hits
for an override**. Even when hits accumulate, the features must point to a
non-baseline candidate to change the output. The feature overlap that exists
only confirms the baseline choice; it never overrides it.

### Saturated Suite Feature Coverage (234 cases)

| Feature Type | Cases with Coverage |
|---|---|
| `reading_candidate` | 188 |
| `candidate` | 216 |
| `transition` | 100 |
| `baseline_prev_candidate` | 90 |
| `baseline_next_candidate` | 65 |
| `baseline_window_candidate` | 27 |
| **non_baseline_evidence** | **2** |

On the saturated suite, 2 cases have non-baseline evidence (vs 0 on
heldout). This is because the saturated suite uses common Taiwan-specific
phrases that partially overlap with the synthetic training data. But even
here, only 1 case actually improved; the other was rejected by the
`rejected_by_count` gate because the count threshold wasn't met.

### Conservative Gate Impact

The ranker applies three gates before allowing a non-baseline override:

1. **Margin gate** (`override_margin=0.1`): The non-baseline candidate's
   score must exceed the baseline candidate's score by at least 0.1.
2. **Evidence gate** (`min_non_baseline_feature_hits=2`): At least 2
   feature types must support the non-baseline choice.
3. **Count gate** (`min_reading_candidate_count_for_override=2`): The
   reading+candidate pair must appear at least 2 times in training.

These gates are designed to prevent one-off noise from changing correct
baseline output. But they also prevent the ranker from acting on weak
but genuine partial-overlap signals, which is a necessary safety tradeoff.

| Gate | Heldout cases blocked | Saturated cases blocked |
|---|---|---|
| `rejected_by_margin` | 0 | 0 |
| `rejected_by_evidence` | 0 | 0 |
| `rejected_by_count` | 1 | 3 |

The `rejected_by_count` cases on the saturated suite are the closest the
ranker came to acting: it identified a non-baseline candidate with evidence,
but the candidate appeared only once in training (below the threshold of 2).
Relaxing this gate could activate these cases but would increase regression
risk.

## Comparison: Candidate Ranker Attempts

| Model | Training Data | Usable Cases | Heldout | Saturated vs Baseline | vs Deterministic |
|---|---|---|---|---|---|
| `seed` | `ranker_training_seed.jsonl` (node) | 12 | not measured | 154/234 (+1) | N/A |
| `seed_char` | `ranker_training_seed.jsonl` (char) | 21 | 39/63 (0 changed) | 154/234 (+1) | -25% RER |
| `synthetic` | `ranker_training_synthetic.jsonl` (char) | 22 | **39/63 (0 changed)** | **182/234 (+1 vs current 181 baseline)** | **-52 cases** |

All three attempts converge to the same result: **~0 impact on heldout, ~1
case improvement on saturated suite**. The training data specifics matter
less than the fundamental limitation of the approach.

## Why Other Approaches Might Work

### Embedding-Based Similarity

Instead of exact string matching, encode context windows as dense vectors
and find similar training examples by cosine similarity. This can transfer
evidence between contexts that are semantically similar but not identical.

**Cost:** Embedding model + nearest-neighbor lookup for each slot.
**Risk:** Embedding quality on Bopomofo contexts is unknown.
**Effort:** Add an embedding step to `candidate_ranker_scorer.py` and a
training step that stores embeddings instead of count tables.

### Classifier Over N-grams

Train a lightweight classifier (logistic regression, small MLP) over
character/reading n-grams rather than exact context strings. Feature hashing
or character-level TF-IDF can capture partial pattern overlap.

**Cost:** Small model, fast inference.
**Risk:** Feature engineering quality determines success.
**Effort:** New training pipeline; scorer remains compatible with protocol.

### True Tiny Language Model

A 200M-0.5B transformer with constrained decoding can internalize
disambiguation patterns during pretraining and apply them zero-shot to
unseen contexts. The qwen2.5:0.5b experiment showed this is possible
in principle but failed at output format reliability (51 fallbacks from
indices_length_mismatch).

**Cost:** Runs on CPU, p95 about 500ms in the local Qwen 0.5B run, which exceeds the 20ms latency target by 25x.
**Risk:** Output format reliability, latency, model distribution.
**Effort:** Significant: model selection, quantization, constrained decoding,
fallback strategy.

### Expand Deterministic Rules

The deterministic reranker already achieves 234/234 on the saturated suite
and 41/63 on heldout. Adding more Taiwan-specific context rules can
continue improving both without any learned-model complexity.

**Cost:** Developer time to write rules.
**Risk:** Rule explosion, maintenance burden.
**Effort:** Incremental: add rules per remaining heldout error.

## Decision: Abandon Count-Based Candidate Ranker

The count-based `candidate-ranker-v1` approach is **not viable** for the
intended use case (generalization to new evaluation contexts). The exact
feature matching is fundamentally local and cannot compose partial patterns.
Three independent attempts (seed node, seed char, synthetic char) converge
to the same null result on heldout.

**Path forward:** Either:

1. **Embedding-based ranker** - replace exact count features with dense
   embedding similarity. This retains the lightweight scorer protocol while
   adding generalization capability.
2. **Deterministic rules** - invest in expanding the deterministic reranker
   to close the remaining 22 heldout errors. Simpler, no learned-model risk.
3. **Tiny LLM with constrained decoding** - accept the latency cost if the
   accuracy gain warrants it for async/background reranking.

**Recommendation:** Try option 1 (embedding-based ranker) first because it has the
best effort-to-impact ratio for the heldout case. Meanwhile continue
expanding deterministic rules (option 2) in parallel. Option 3 is a fallback
if both simpler approaches fail.

## Appendix: Heldout Error Categories (22 remaining after deterministic)

| Category | Errors |
|---|---:|
| Homophone | 10 |
| Taiwan-specific | 3 |
| English-mixed | 2 |
| Slang | 3 |
| Punctuation spacing | 2 |
| Stress test | 2 |

The homophone category (10/22 errors) is the largest and most suited for
a learned approach because it requires contextual disambiguation. The
remaining categories are more syntactic and may benefit more from rule
expansion.
