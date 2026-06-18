# Technical Spec: Contextual Reranking Architecture

Last updated: 2026-06-18T18:20:30+08:00

## Design Principle

Do not let the model own the input method. The model may only rerank candidates
produced by the existing engine until evaluation proves a broader change is
necessary.

The system must preserve:

- existing `ReadingGrid` composition behavior;
- existing user phrase and excluded phrase semantics;
- existing candidate override behavior;
- stable handling for English spans mixed into Taiwan Traditional Chinese text;
- deterministic fallback when contextual ranking is disabled or unavailable.

The scoring target is Taiwan Traditional Chinese first. Model and deterministic
features must not be trained or tuned primarily on Simplified Chinese, Pinyin
input, or non-Taiwan written conventions.

## Current Architecture Reference

Relevant local files:

- `Source/Engine/gramambular2/reading_grid.h`: owns readings, spans, nodes,
  candidates, user overrides, and `walk()`.
- `Source/Engine/gramambular2/reading_grid.cpp`: updates candidate spans and
  performs the DAG walk.
- `Source/Engine/McBopomofoLM.cpp`: returns merged and transformed unigrams for
  each reading key.
- `Source/LanguageModelManager.mm`: Objective-C++ bridge between Swift and the
  C++ language model.
- `Source/InputState.swift` and `Source/KeyHandler.mm`: state transitions and
  key event integration.

## Proposed Components

### `ContextualScorer`

C++ interface for optional score adjustment.

Responsibilities:

- Receive a bounded snapshot of readings, candidate spans, current cursor,
  previous committed context, and candidate values.
- Return score deltas, not final committed text.
- Enforce timeout and fallback behavior at the caller boundary.

Conceptual interface:

```cpp
struct CandidateScoreInput {
  std::string reading;
  std::string value;
  std::string rawValue;
  double baseScore;
  size_t start;
  size_t length;
};

struct ContextualScoreRequest {
  std::vector<std::string> readings;
  std::vector<CandidateScoreInput> candidates;
  std::string previousCommittedText;
  std::vector<std::string> protectedEnglishSpans;
  size_t cursor;
};

class ContextualScorer {
 public:
  virtual ~ContextualScorer() = default;
  virtual std::vector<double> scoreDeltas(
      const ContextualScoreRequest& request) = 0;
};
```

### `DeterministicContextualScorer`

P1 implementation with no model runtime dependency.

Candidate features:

- phrase transition table from corpus-derived counts;
- phrase length prior;
- user override recency and frequency;
- exact domain phrase boost from a user-controlled local lexicon;
- Taiwan lexical prior for local terms, named entities, and common functional
  expressions;
- protected English span preservation for identifiers, product names, acronyms,
  file paths, commands, and code-like tokens;
- penalty for context-incompatible single-character choices when a multi-
  character candidate matches the same readings.

### `LocalSLMContextualScorer`

P2 implementation gated behind benchmark results.

Requirements:

- local-only model files;
- bounded prompt/context size;
- candidate-list constrained output;
- separate score reporting for Taiwan-only, generic Traditional Chinese, and
  English-mixed fixtures;
- timeout with fallback;
- no content logging;
- model loaded lazily or in a separate helper process if process stability
  requires it.

Runtime candidates to evaluate:

- llama.cpp: C/C++, strong Apple Silicon and CPU support, quantized model
  support, plausible cross-platform path.
- Core ML: strong macOS integration, weaker Ubuntu story.
- ONNX Runtime: cross-platform inference path, model conversion complexity.

No runtime should be added before the P0/P1 benchmark proves the need.

### Training Pipeline

Self-training and project-trained models are allowed, but training is a separate
artifact pipeline from runtime integration.

Required stages:

1. Corpus manifest creation with source URL, license, redistribution status,
   language scope, Taiwan relevance, and preprocessing notes.
2. Normalization to Taiwan Traditional Chinese, including OpenCC review where
   applicable and manual checks for phrases that differ by region.
3. Bopomofo reading generation using existing dictionary lookup, with unresolved
   readings retained as explicit missing-reading records.
4. Ambiguous candidate generation from the current engine so training examples
   match actual runtime choices.
5. English span labeling for ASCII identifiers, product names, commands, file
   paths, version numbers, and code-like tokens.
6. Train/dev/test split by source and document, not by sentence only, to reduce
   data leakage.
7. Evaluation against baseline unigram, deterministic reranker, and candidate
   oracle rank.

Permitted training modes:

- Public corpus training for redistributable or locally reproducible models.
- Synthetic examples generated from public seed patterns, especially ambiguous
  Bopomofo and English-mixed Taiwan sentences.
- User-provided local adaptation files that never leave the user's machine.
- Teacher-model distillation if prompts and outputs are license-compatible and
  do not include private user text.

Promotion gate:

- A trained SLM cannot become a runtime dependency unless it beats the
  deterministic reranker on held-out Taiwan fixtures and English-mixed fixtures,
  stays within latency and memory budgets, and has a redistributable or
  user-buildable model artifact path.

## Integration Point

Preferred insertion point: after unigrams are collected and before or during
grid path scoring.

Rationale:

- `McBopomofoLM::getUnigrams()` already merges main dictionary, user phrases,
  excluded phrases, phrase replacement, macros, conversion, and deduplication.
- `ReadingGrid::Node` already exposes value, score, candidate list, and override
  behavior.
- User overrides use explicit score semantics; the contextual scorer must not
  erase them.

Initial implementation should avoid changing the lattice shape. It should adjust
candidate scores only. Adding new candidates is a later feature.

## Evaluation Harness

Current Phase 0 baseline, generated on 2026-06-18:

- 60 `taiwan_ambiguous` cases, 43 exact matches.
- Exact sentence accuracy: 71.67%.
- CJK token accuracy: 94.95%.
- Mean candidate rank: 1.00.
- Missing readings: 0 for pure Bopomofo cases.
- Latency p50 / p95 / p99: 1 / 2 / 2 microseconds.
- 17 wrong cases are context ambiguity errors.
- `english_mixed` is not yet a reranker metric because all 25 cases currently fail as missing readings when non-Bopomofo tokens are inserted into the LM. Phase 1 must introduce protected-span passthrough.

Command-line target:

- macOS: C++ or mixed Objective-C++ test executable using the existing engine.
- Ubuntu: C++ only, without IMK or Swift dependencies.

Input format:

```json
{
  "id": "ambiguous-001",
  "readings": ["ㄓㄜˋ", "ㄕˋ", "ㄧˊ", "ㄍㄜ˙", "ㄘㄜˋ", "ㄕˋ"],
  "expected": "這是一個測試",
  "protected_english_spans": [],
  "domain": "general"
}
```

Output format:

```json
{
  "engine": "baseline-unigram",
  "cases": 50,
  "exact_sentence_accuracy": 0.72,
  "token_accuracy": 0.91,
  "candidate_rank_mean": 1.8,
  "latency_microseconds_p50": 320,
  "latency_microseconds_p95": 900,
  "missing_reading_cases": 0,
  "english_span_preservation_accuracy": 1.0
}
```

## Latency Budget

Initial budgets to validate:

- P0 baseline measurement: no added runtime.
- P1 deterministic reranker: p95 under 2 ms per rerank request on a development
  Mac.
- P2 SLM reranker: p95 under 20 ms for commit-time reranking; do not run SLM on
  every keystroke unless measured latency is acceptable.
- Training jobs are offline tasks and are not part of the IME latency budget.

The SLM should be commit-time or debounce-time first. Per-keystroke model
inference is a later optimization only if measured.

## Privacy and Logging

Allowed logs:

- counters, latency buckets, fallback counts, model load status, error codes.

Forbidden logs:

- raw readings;
- candidate text;
- committed text;
- user phrase contents;
- prompts or model outputs.
- local training examples from user-provided files.

Debugging content-bearing cases must use checked-in synthetic fixtures, not live
user input.

## Packaging

P1:

- No new model files.
- No new runtime dependencies.

P2:

- Model assets are optional downloads or separately packaged artifacts.
- App must start and function without model assets.
- Model license must permit redistribution for the intended channel.
- Quantized model size must be declared in release notes.
- Self-trained model artifacts must record their data manifest and evaluation
  report before packaging.

## Testing Strategy

- C++ unit tests for scorer interfaces and score-combination behavior.
- Regression tests for user phrase priority and excluded phrase behavior.
- Evaluation fixture tests for ambiguous sentence cases.
- Evaluation fixture tests for Taiwan vocabulary and English-mixed text.
- Fallback tests for timeout, model missing, malformed score output, and scorer
  disabled.
- Training-data leakage tests: no test sentence should share the same source
  document with training examples.
- Manual dogfood checklist for macOS candidate window behavior.

## Rejected Approaches

- Replace `ReadingGrid` with a generative model: rejected because it breaks
  determinism, user override semantics, and debuggability.
- Cloud inference in MVP: rejected because an IME processes sensitive text and
  cloud privacy requires a separate architecture.
- Ubuntu UI first: rejected because the scoring value must be proven before
  duplicating frontend work.
- SLM first without deterministic baseline: rejected because the project would
  not know whether the model is solving the actual problem or adding complexity.
