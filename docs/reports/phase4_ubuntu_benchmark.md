# Phase 4 Ubuntu Benchmark Report

Last updated: 2026-06-20T14:00:00+08:00
Branch: `slm-phase4-ubuntu` (based on `slm-phase1.1-reranker-mechanics`)

## Linux Build Status

| Component | Status |
|---|---|
| Engine C++ (123 tests) | ✅ 123/123 pass (2 stress tests skipped) |
| Evaluator binary | ✅ Builds and runs |
| ScorerDemo binary | ✅ Builds and runs (interactive + single-shot modes) |

Build environment: Ubuntu 22.04, GCC 11.4.0, x86_64. No macOS-specific code required changes. The engine, scorer, and evaluator are pure C++17 with no platform dependencies.

## Benchmark Results: taiwan_ambiguous (60 cases)

### Phase 0 Baseline

| Metric | Ubuntu | macOS (Phase 0) | Match? |
|---|---|---|---|
| Exact sentence accuracy | 80.00% (48/60) | 80.00% (48/60) | ✅ |
| Token accuracy | 96.63% | — | — |
| Missing readings | 0 | 0 | ✅ |
| Latency p50/p95/p99 | 2/3/4 µs | — | — |

### Phase 1 Reranker

| Metric | Ubuntu | macOS (Phase 1.1) | Match? |
|---|---|---|---|
| Exact sentence accuracy | **100.00%** (60/60) | 98.33% (59/60)* | ✅ (exceeds) |
| Token accuracy | 100.00% | — | — |
| Context ambiguity errors | 0 | — | — |
| Latency p50/p95/p99 | 179/444/486 µs | — | ✅ well under 2ms |

*The macOS result (98.33%) was recorded before the evaluator fix in commit `3776266` ("fix(evaluator): stabilize reranker override application"). The 100% result on Ubuntu includes this fix and is reproducible.

## Benchmark Results: english_mixed (25 cases)

| Metric | Ubuntu | macOS (Phase 1.1) | Match? |
|---|---|---|---|
| Exact sentence accuracy | 96.00% (24/25) | 96.00% (24/25) | ✅ |
| Token accuracy | 97.32% | — | — |
| Latency p50/p95/p99 | 137/370/384 µs | — | ✅ well under 2ms |

## CLI Demo

`Tools/ScorerDemo/scorer_demo` provides two modes:

- **Single-shot**: `./scorer_demo <data.txt> <reading_seq>` — accepts a dash-separated Bopomofo syllable sequence, outputs baseline text, reranked text, and any corrections applied.
- **Interactive**: `./scorer_demo <data.txt>` — reads lines from stdin in a loop.

Example correction:
```
Input:   ㄑㄧㄥˇ-ㄗㄞˋ-ㄕㄨㄛ-ㄧ-ㄘˋ
Base:    請在說一次
Scored:  請再說一次
Corrections:
  [1:1] ㄗㄞˋ -> 再  (12.0, rule: zai-zai)
```

## Conclusion

The engine, scorer, and evaluator run correctly on Ubuntu with no portability issues. All benchmark results match or exceed macOS Phase 1.1 results. CLI demo is operational and demonstrates reranker corrections interactively.

**Exit criteria status:**
1. ✅ Ubuntu can compile and run the evaluator
2. ✅ Same test fixtures produce matching results on Ubuntu
3. ✅ CLI demo accepts Bopomofo input and outputs ranked candidates
4. ✅ ADR-002 selects Fcitx5 addon as the integration path
5. ✅ License risks listed in ADR-002 with separate `.so` boundary strategy
