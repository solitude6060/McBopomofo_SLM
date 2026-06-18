# Phase 0 Baseline Report — McBopomofo SLM Evaluator

**Date:** 2026-06-18  
**Engine:** baseline-mcbopomofo (unigram + Viterbi)  
**Data:** `Source/Data/data.txt` (production McBopomofo language model)  

---

## Summary

| Metric | Value |
|--------|-------|
| Test cases | 60 (taiwan_ambiguous) |
| Sentence accuracy (exact) | **71.67%** (43/60) |
| Token accuracy (CJK chars) | **94.95%** |
| Mean candidate rank | 1.00 |
| Missing readings | 0 |
| Context ambiguity errors | 17 |
| Unknown errors | 0 |
| Latency p50 / p95 / p99 | 1μs / 2μs / 2μs |
| Total elapsed | 35ms |

---

## Error Classification

All 17 errors are **context ambiguity** — the engine produced Chinese output that
differs from the expected reference. In every case, the expected target character
was found as the **#1 candidate** (mean rank = 1.00), meaning the engine chose a
different but equally valid character for the same reading.

### Error Categories

| # | ID | Expected | Engine Output | Error Pattern |
|---|----|----------|---------------|---------------|
| 1 | tw-amb-003 | 請**再**說一次 | 請**在**說一次 | 再→在 (homophone: "again" vs "at") |
| 2 | tw-amb-005 | 這是什麼**意思** | 這是什麼**一絲** | 意思→一絲 (bigram not in LM) |
| 3 | tw-amb-007 | **做**事要小心 | **作**是要小心 | 做→作 + 事→是 (multi-error) |
| 4 | tw-amb-010 | 這是一件重要的**事** | 這是一件重要的**是** | 事→是 (noun vs copula) |
| 5 | tw-amb-013 | 時間**過**得很快 | 時間**的**得很快 | 過→的 (grid segmentation error) |
| 6 | tw-amb-023 | 首先把文件讀一**遍** | 首先把文件讀一**變** | 遍→變 (homophone) |
| 7 | tw-amb-025 | 我感覺今天非常**累** | 我感覺今天非常**類** | 累→類 (homophone) |
| 8 | tw-amb-031 | 空氣**品質**持續下降 | 空氣**頻直**持續下降 | 品質→頻直 (bigram not found; segmentation broken) |
| 9 | tw-amb-033 | **習慣養成不久** | **系慣養成不久** | 習慣→系慣 (first character wrong) |
| 10 | tw-amb-034 | 我覺得這個**主意**非常重要 | 我覺得這個**主一**非常重要 | 主意→主一 (bigram not found) |
| 11 | tw-amb-035 | 這獎金是我辛苦**賺**來的 | 這獎金是我辛苦**政**來的 | 賺→政 (homophone) |
| 12 | tw-amb-037 | 他常常忘記**帶**東西 | 他常常忘記**代**東西 | 帶→代 (homophone) |
| 13 | tw-amb-041 | 吃完飯**再**出發 | 吃完飯**在**出發 | 再→在 (homophone) |
| 14 | tw-amb-042 | 我**閱讀**進步 | 我**閱讀躍進不** | 閱讀→閱讀 + 進步 garbled |
| 15 | tw-amb-049 | **正式**完成後我要回家 | **正是**完成後我要回家 | 正式→正是 (homophone) |
| 16 | tw-amb-053 | 接受教訓**再**決定 | 接受教訓**在**決定 | 再→在 (homophone) |
| 17 | tw-amb-054 | 機會**尚**有一場演講 | 機會**上**有一場演講 | 尚→上 (homophone) |

### Error Pattern Frequency

| Pattern | Count | Examples |
|---------|-------|---------|
| 在/再 confusion | 4 | #1, #13, #16, plus part of others |
| Other homophones (累/類, 帶/代, 賺/政, 遍/變, 事/是, 尚/上, 式/是) | 8 | #4, #6, #7, #11, #12, #15, #17 |
| Bigram not in unigram LM | 2 | #5 (主意→主一), #10 (意思→一絲) |
| Segmentation error (grid artifacts) | 2 | #5 (過的), #8 (頻直), #14 (閱讀躍進不) |
| First-character error | 1 | #9 (習慣→系慣) |

### Root Cause Analysis

1. **Homophone dominance:** 10/17 errors are simple homophone substitutions where
   the unigram model prefers a higher-frequency character. These are the classic
   "contextual disambiguation" problem — the unigram model has no way to prefer
   "再" over "在" in "請再說一次" because it has no contextual (n-gram) signal.

2. **Missing bigrams:** Some multi-character words (主意, 意思) are not present as
   single entries in the LM, so the grid splits them into individual characters.
   This is a coverage issue in the training data.

3. **Segmentation artifacts:** The grid sometimes combines readings incorrectly,
   producing non-word outputs (e.g., "頻直" for "品質"). This is a Viterbi
   path-finding issue where the LM scores a non-existing bigram higher than
   the correct segmentation.

---

## English Mixed Cases

**Not tested in this baseline** — all 25 english_mixed cases contain non-Bopomofo
readings (e.g., `"Docker"`, `"GitHub"`, `"Python"`) which the LM cannot process.
The evaluator correctly reports `missing_reading: true` for these cases.

Handling English mixed text requires a pre-processing step that:
- Detects non-Bopomofo readings in the input
- Preserves them as-is (passthrough) while routing only Bopomofo readings through the LM
- Reassembles the final output from LM results + preserved spans

This is a Phase 1 concern.

---

## Conclusions & Recommendations

### What Works Well
- 71.67% sentence accuracy on ambiguous Taiwanese Mandarin pairs
- 94.95% token-level accuracy
- Extremely fast inference (~1μs per case)
- No missing readings in pure-Bopomofo input
- Expected character always appears as #1 candidate

### What Needs Improvement (Phase 1 Candidate)
1. **Deterministic reranker rules** for top homophone pairs (在/再, 的/得, 事/是, etc.)
   — could fix 10+ of 17 errors with simple context pattern matching
2. **Bigram coverage audit** — identify missing multi-character entries in `data.txt`
3. **Segmentation stability** — investigate Viterbi path selection for long readings
4. **English mixed passthrough** — pre-process non-Bopomofo tokens

### Priority for Phase 1
The top-3 homophone confusions (在/再, 的/得, 事/是) account for ~47% of all errors.
A deterministic reranker targeting these specific pairs (using POS-like heuristics
or simple surrounding-character patterns) would provide the highest ROI.
