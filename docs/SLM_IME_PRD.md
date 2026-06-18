# PRD: Context-Aware Bopomofo Input With Optional Local SLM Reranking

Last updated: 2026-06-18T18:20:30+08:00

## Problem

McBopomofo is already a strong local Traditional Chinese Bopomofo input method,
but its current unigram-based conversion can choose the wrong character or
phrase during continuous input because the score for each phrase is independent
of sentence context.

Users who write long Traditional Chinese text on macOS and Ubuntu need fewer
manual candidate corrections without giving typed content to a cloud service.

The product is Taiwan-first. Correctness means Taiwan Traditional Chinese,
Taiwan vocabulary, Bopomofo input, and ordinary English mixing in technical and
work text. Simplified Chinese, Pinyin-first behavior, and non-Taiwan written
conventions are not the default target.

## Target Users

Primary users:

- Traditional Chinese writers, developers, researchers, and power users who use
  Bopomofo on macOS and write primarily for Taiwan contexts.
- Ubuntu desktop users who currently rely on libchewing, Rime, or other input
  framework frontends but want better Taiwan Traditional Chinese context
  prediction.
- Users who frequently mix English product names, code identifiers, command-line
  terms, academic terms, company names, and acronyms into Traditional Chinese
  sentences.
- Privacy-sensitive users who want local prediction and inspectable behavior.

Non-primary users:

- Mobile keyboard users.
- Users who want cloud completion, grammar rewriting, or chat-style generation.
- Users who primarily use shape-based input methods.

## Goals

- Improve top-1 Bopomofo-to-Traditional-Chinese conversion accuracy on sentence-
  level input.
- Prioritize Taiwan vocabulary, Taiwan named entities, Taiwan punctuation habits,
  and Taiwan written style.
- Handle English-mixed sentences without forcing unwanted conversion or
  candidate disruption.
- Preserve the current deterministic fallback path.
- Keep all typed text local by default.
- Make model-assisted ranking measurable, optional, and reversible.
- Support a path for self-trained or project-trained models after corpus,
  evaluation, privacy, and licensing requirements are met.
- Build a reusable scoring core that can support macOS first and Ubuntu later.

## Non-Goals

- No cloud inference in the MVP.
- No automatic upload of typed text, user dictionaries, or correction logs.
- No replacement of McBopomofo's state machine or candidate UI in the MVP.
- No Linux desktop frontend in the first milestone.
- No chat assistant, writing rewrite tool, or long-form text generator inside
  the candidate window.
- No Simplified Chinese corpus or Pinyin task should dominate model behavior.
- No training on private user text unless the user explicitly starts a local
  training/adaptation workflow.

## User Stories

- As a macOS Bopomofo user, I want the first candidate to match sentence context
  more often so I can type long text with fewer manual corrections.
- As a privacy-sensitive user, I want prediction to run locally and be
  disableable so typed content does not leave my machine.
- As an Ubuntu user, I want the core model/reranking work to be portable so the
  same improvement can later appear through IBus or Fcitx.
- As a Taiwan user, I want candidates to prefer Taiwan terms such as local
  institutions, everyday vocabulary, and local technical usage when the reading
  is ambiguous.
- As a developer or researcher, I want English tokens to remain stable in mixed
  sentences so the IME does not convert or reorder identifiers unexpectedly.
- As a developer, I want an offline benchmark so I can prove whether an SLM is
  better than a deterministic contextual baseline before adding model runtime
  complexity.

## Product Requirements

### P0: Evaluation Harness

- Convert Traditional Chinese corpus sentences into Bopomofo readings using
  existing dictionary lookup where possible.
- Label fixtures by domain: general Taiwan usage, messaging, software
  development, academic writing, finance/business, government/public services,
  and English-mixed technical text.
- Replay reading sequences through the current McBopomofo engine.
- Measure top-1 exact sentence accuracy, token accuracy, candidate-rank of the
  target, latency, and missing-reading cases.
- Store evaluation fixtures under repo-controlled test data with licensing notes.

Acceptance:

- A command can run baseline evaluation locally and produce a stable JSON or CSV
  report.
- At least 50 curated sentence cases cover common ambiguous Bopomofo readings.
- At least 20 curated cases cover English-mixed Taiwan text.
- Baseline output is reproducible across two runs on the same machine.

### P1: Deterministic Contextual Reranker

- Add an experimental reranking layer that receives candidate lattice context and
  returns adjusted scores.
- Start with transparent features: previous committed phrase, neighboring
  phrase compatibility, phrase length, user override history, and domain lexicon
  boosts.
- Treat English runs as protected spans unless the user explicitly enters a
  Bopomofo reading that maps to a Chinese candidate.
- Keep the existing unigram path as fallback.

Acceptance:

- Reranker can be enabled only for evaluation or via an experimental preference.
- Reranker improves curated ambiguous cases without regressing existing engine
  tests.
- Reranker latency p95 remains below the configured local budget.

### P2: Optional Local SLM Reranker

- Evaluate a small local model as a reranker, not as an unconstrained generator.
- Input to the model is bounded context plus candidate options; output is a
  candidate score or ranking.
- The model cannot emit arbitrary committed text outside the candidate set during
  MVP.
- The model must be evaluated on Taiwan Traditional Chinese and English-mixed
  fixtures separately from generic Traditional Chinese fixtures.
- The model runtime is disabled by default until benchmark evidence supports it.

Acceptance:

- SLM reranker beats the deterministic contextual reranker by a meaningful,
  predeclared margin on held-out evaluation data.
- Model loading failure, timeout, or missing model file falls back to deterministic
  behavior without losing typed text.
- No typed text is written to logs.

### P2.5: Training and Adaptation Track

- Build a reproducible data pipeline for Taiwan Traditional Chinese text,
  Bopomofo readings, ambiguous candidate sets, and English-mixed examples.
- Allow self-training experiments using public corpora, synthetic data, and
  user-provided local files.
- Keep private user adaptation local by default; do not upload local training
  examples.
- Track model version, data sources, license status, tokenizer, vocabulary
  coverage, and evaluation scores.

Acceptance:

- Training data manifests list source, license, language scope, Taiwan relevance,
  preprocessing steps, and redistribution status.
- A trained model cannot be promoted to runtime use without beating the P1
  deterministic reranker on held-out Taiwan and English-mixed fixtures.
- User-provided local training data can be excluded, reset, or deleted.

### P3: Ubuntu Feasibility Track

- Extract evaluation and scoring interfaces so they are independent of macOS IMK.
- Identify whether the Linux frontend should be IBus, Fcitx5, or a Rime/libchewing
  integration.
- Build a command-line scorer demo before any Linux UI work.

Acceptance:

- A Linux build can run the evaluation harness without macOS frameworks.
- A design note names the chosen Ubuntu integration path and rejected
  alternatives.

## Success Metrics

P0:

- Baseline report generated with corpus size, missing-reading count, accuracy,
  and latency.

P1:

- At least 10% relative reduction in wrong top-1 choices on curated ambiguous
  sentence cases.
- No statistically meaningful latency regression in ordinary short inputs.

P2:

- At least 5% additional relative reduction over P1 on held-out ambiguous cases.
- p95 reranking latency within the interactive budget selected in the technical
  spec.
- Model memory footprint acceptable for always-available desktop use.

P3:

- Evaluation harness runs on Ubuntu without macOS-only dependencies.

## Privacy Requirements

- Typed content stays on device by default.
- No network calls from ranking or evaluation runtime.
- No content-bearing logs.
- Any future telemetry must be opt-in, redacted, and covered by a separate design
  document.
- User dictionaries and correction history must remain local files under user
  control.

## Open Questions

- Which public Traditional Chinese corpus can be redistributed in test fixtures?
- Which Taiwan-specific sources can be used for training without redistribution
  or licensing problems?
- What latency budget is acceptable on Intel Mac, Apple Silicon Mac, and typical
  Ubuntu laptops?
- Should the first Ubuntu integration target IBus, Fcitx5, or Rime?
- Is a transformer SLM needed at runtime, or is a smaller neural/classical
  reranker sufficient?
- How should we tokenize mixed Traditional Chinese, Bopomofo readings, ASCII
  identifiers, and punctuation so English text remains stable?
