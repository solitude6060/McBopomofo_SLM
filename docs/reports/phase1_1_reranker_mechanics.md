# Phase 1.1: Reranker Mechanics Fix

Date: 2026-06-18T22:30:00+08:00

Scope: Stabilize the evaluator's reranker override application so that
corrections identified by `DeterministicContextualScorer` are actually forced
into the Viterbi result.

## Motivation

Phase 1 (commit `206d840`) reported 98.33% (59/60) on `taiwan_ambiguous` and
88.00% (22/25) on `english_mixed`. The sole Taiwan failure (`tw-amb-042`) and
two English failures (`en-mix-003`, `en-mix-011`) were flagged as
"segmentation artifact" / "bigram override failure" — the scorer correctly
identified the needed corrections, but the evaluator's override pipeline
didn't force them strongly enough to win against competing bigrams.

## Two Changes

### 1. Override type: `kOverrideValueWithScoreFromTopUnigram` → `kOverrideValueWithHighScore`

**File:** `Tools/ContextualEvaluation/evaluator.cpp` line 543

The old code used `kOverrideValueWithScoreFromTopUnigram`, which sets the
overridden node's score to the top unigram score for that grid entry. This
was often too low to beat competing multi-character bigrams (e.g. `閱讀` +
`躍進` covering positions that the scorer wanted to split into individual
characters `越` + `讀` + `越`).

The new code uses `kOverrideValueWithHighScore`, which assigns a very high
score (sourced from `kOverrideCandidateScore` in `reading_grid.h`) that
forces the Viterbi walk to pick the corrected nodes regardless of competing
paths.

**Effect:** The scorer's `suggestCorrections` output is now authoritative —
if the scorer identifies a correction, the evaluator ensures it appears in
the final output. This is the intended contract.

### 2. Duplicate source removal (ODR fix)

**File:** `Tools/ContextualEvaluation/CMakeLists.txt`

Removed `DeterministicContextualScorer.cpp` from the evaluator's
`add_executable()` source list because it was already compiled into
`libMcBopomofoLMLib.a`. This fixed a multiple-definition linker error that
prevented the evaluator from building with the scorer linked from the
library.

### 3. Fixture reading correction (en-mix-003, en-mix-011)

**File:** `Tests/fixtures/contextual_bopomofo/english_mixed.jsonl`

Corrected the reading for 考 from `ㄎㄠˋ` (4th tone) to `ㄎㄠˇ` (3rd tone)
in two fixtures. The character 考 (kǎo) is consistently listed with 3rd tone
in `BPMFMappings.txt`:

```
僅供參考 ㄐㄧㄣˇ ㄍㄨㄥ ㄘㄢ ㄎㄠˇ
入學考試 ㄖㄨˋ ㄒㄩㄝˊ ㄎㄠˇ ㄕˋ
主考 ㄓㄨˇ ㄎㄠˇ
```

These were missed in the original Phase 1 fixture audit.

## Results

### Taiwan ambiguous (60 cases)

| Stage | Exact accuracy | Token accuracy | Errors |
|-------|---------------:|---------------:|-------:|
| Original Phase 0 baseline | 71.67% (43/60) | 94.95% | 17 |
| Fixture-audited baseline | 80.00% (48/60) | 96.63% | 12 |
| Phase 1 committed reranker | 98.33% (59/60) | 99.28% | 1 |
| **Phase 1.1 reranker** | **100.00% (60/60)** | **100.00%** | **0** |

tw-amb-042 (`我越讀越進步`) is now correct. The scorer identified the
individual characters `越`, `讀`, `越`, `進步` as corrections, but
`kOverrideValueWithScoreFromTopUnigram` assigned scores too low to beat the
competing bigrams `閱讀` + `躍進`. With `kOverrideValueWithHighScore`, the
corrections are forced through.

### English mixed (25 cases)

| Stage | Exact accuracy | Token accuracy | Missing readings |
|-------|---------------:|---------------:|-----------------:|
| Phase 0 baseline | 0.00% (0/25) | 0.00% | 25 |
| Phase 1 committed reranker | 88.00% (22/25) | 95.54% | 0 |
| **Phase 1.1 reranker** | **96.00% (24/25)** | **97.32%** | **0** |

Two cases fixed:
- `en-mix-003` (`請參考 README 說明`): Both the fixture reading fix
  (`ㄎㄠˋ`→`ㄎㄠˇ` for 考) and the override type change contributed.
- `en-mix-011` (`參考 StackOverflow 上的解答`): Same as en-mix-003.

## Remaining English Error

| Case | Output | Expected | Root Cause |
|------|--------|----------|------------|
| `en-mix-006` | `安裝 Dockerfile 作境相` | `安裝 Dockerfile 做鏡像` | Two independent single-character confusions (`做`/`作`, `鏡`/`境`, `像`/`相`) not covered by any deterministic scorer rule. Adding rules for these would be overfitting — no general pattern distinguishes them reliably. |

## C++ Engine Tests

| Metric | Phase 1 (committed) | Phase 1.1 (dirty) |
|--------|--------------------:|-------------------:|
| Total tests | 113 | 123 |
| Passed | 111 | 121 |
| Skipped | 2 | 2 |
| Failed | 0 | 0 |

The test count increased from 113 to 123 because 10 new
`DeterministicScorerTest` cases were added alongside the existing 103 tests
(previously reported as 111 + 2 skipped = 113). The 2 skipped tests are
pre-existing stress tests (`ParselessLMTest.SanityCheckTest`,
`ParselessPhraseDBTest.StressTest`).

## Gate Status

| Gate | Threshold | Phase 1 | Phase 1.1 |
|------|-----------|---------|-----------|
| Taiwan error reduction | >= 10% | 94.12% ✅ | **100.00%** ✅ |
| English missing readings | 0 | 0/25 ✅ | 0/25 ✅ |
| English exact quality | monitor | 88.00% (22/25) | **96.00% (24/25)** ✅ |
| Latency p95 | < 2 ms | 98 μs ✅ | **312 μs** ✅ |
| C++ tests | all pass | 111/113 ✅ | **121/123** ✅ |
| Runtime integration | — | not started ❌ | not started ❌ |

## Decision

Phase 1.1 mechanics fixes are complete. The evaluator's override pipeline
now correctly applies all scorer-identified corrections. No further scorer
rule investment is needed — the remaining English error (`en-mix-006`)
requires either bigram coverage expansion in the dictionary or a more
sophisticated approach (Phase 2 SLM).

Next step recommendation: Phase 3 macOS runtime integration.
