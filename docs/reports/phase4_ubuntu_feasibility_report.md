# Phase 4 Ubuntu Feasibility Report

Last updated: 2026-06-20T14:00:00+08:00
Branch: `slm-phase4-ubuntu`

## Summary

Phase 4 confirms that the McBopomofo C++ engine, deterministic reranker, and evaluation tooling all run correctly on Ubuntu Linux with no portability issues. The command-line demo is operational, benchmark results match macOS, and an Architecture Decision Record selects Fcitx5 as the Linux desktop integration path.

## Linux Build Status

| Component | Status | Notes |
|---|---|---|
| Engine C++ (123 tests) | ✅ Pass | 2 stress tests skipped (expected) |
| Evaluator binary | ✅ Builds | `Tools/ContextualEvaluation` |
| CLI Demo binary | ✅ Builds | `Tools/ScorerDemo` (new in Phase 4) |

**Fixes needed**: None. All code is pure C++17 with no platform-specific dependencies.

## Benchmark Comparison: Ubuntu vs macOS

### taiwan_ambiguous (60 cases)

| Metric | Ubuntu | macOS | Match? |
|---|---|---|---|
| Phase 0 exact accuracy | 80.00% (48/60) | 80.00% (48/60) | ✅ |
| Phase 1 reranker accuracy | **100.00%** (60/60) | 98.33% (59/60)* | ✅ exceeds |
| Phase 1 latency p95 | 444 µs | — | ✅ well under 2ms |

### english_mixed (25 cases)

| Metric | Ubuntu | macOS | Match? |
|---|---|---|---|
| Phase 1 reranker accuracy | 96.00% (24/25) | 96.00% (24/25) | ✅ |
| Phase 1 latency p95 | 370 µs | — | ✅ well under 2ms |

*The macOS Phase 1.1 result (98.33%) was recorded before commit `3776266` ("fix(evaluator): stabilize reranker override application"). Ubuntu includes this fix and achieves 100%.

## CLI Demo Status

`Tools/ScorerDemo/scorer_demo` — a standalone CLI tool that:
- Loads `data.txt` (McBopomofo language model dictionary)
- Accepts dash-separated Bopomofo reading sequences
- Runs engine walk + deterministic reranker
- Outputs baseline text, reranked text, and per-correction details
- Supports both single-shot (`./scorer_demo <data.txt> <readings>`) and interactive (stdin loop) modes

Verified correct: `ㄑㄧㄥˇ-ㄗㄞˋ-ㄕㄨㄛ-ㄧ-ㄘˋ` → baseline "請在說一次" → reranked "請再說一次" (zai-zai rule, +12.0 delta).

## ADR Summary

**ADR-002** selects **Fcitx5 addon** as the Ubuntu integration path.

**Key decision factors:**
1. Fcitx5 is the most actively maintained Linux IME framework (2.3k stars, 60 contributors, 2026-05 last push)
2. fcitx5-chewing provides a proven reference architecture (~700 lines C++ wrapping external engine)
3. First-class Wayland support via `text-input-v3` protocol
4. Clean license boundary via separate `.so` strategy: `libmbengine.so` (MIT) + `mcbopomofo.so` (LGPL wrapper)

**Rejected alternatives:**
- **IBus**: Valid but losing momentum to Fcitx5 (972 stars, slower development)
- **Rime**: Fundamental architectural mismatch — Rime has its own segmentation engine; our scorer is tightly coupled to Gramambular2
- **Standalone**: 6+ months effort for what existing frameworks provide

## License Risk Assessment

| Risk | Severity | Mitigation |
|---|---|---|
| LGPL contamination of MIT engine | Medium | Separate `.so` strategy: engine (MIT) and addon (LGPL) are distinct shared libraries |
| GPL code copied into MIT project | Low | Referenced projects (HuoziIME, ibus-chewing) are GPL — studied for design only |
| Fcitx5 addon license ambiguity | Low | fcitx5-chewing precedent: addon is LGPL-2.1+, engine is unaffected |
| User confusion about licensing | Low | Document in README and license headers |

## Remaining Risks and Open Questions

1. **Wayland desktop testing**: The Fcitx5 addon has not been tested on an actual Ubuntu desktop with Wayland. A VM or physical test environment is needed for Phase 5.

2. **Key event mapping completeness**: Bopomofo keyboard layouts (Standard, ETen, Hsu, ETen26, IBM, Hanyu Pinyin) exist in the engine but need Fcitx5 key event → engine key mapping in the addon.

3. **Candidate window UI**: Fcitx5 provides `CommonCandidateList`, but candidate display behavior (horizontal vs vertical, key labels) must match user expectations. macOS McBopomofo uses horizontal candidates by default.

4. **Configuration UI**: Fcitx5 addons use `FCITX_CONFIGURATION()` macros for settings. The reranker toggle needs to be exposed here. No GUI toolkit required — Fcitx5 handles config UI rendering.

5. **`.deb` packaging**: The repository has no packaging infrastructure. Packaging for Ubuntu (debhelper, cmake, install paths) needs setup in Phase 5.

6. **CI for Linux**: The macOS CI (Xcode) doesn't help for Linux. A GitHub Actions workflow for Linux (cmake + make + ctest) would be valuable to prevent regressions.
