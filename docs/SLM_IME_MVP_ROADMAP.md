# MVP Roadmap: SLM-Assisted McBopomofo

Last updated: 2026-06-18T18:20:30+08:00

## MVP Thesis

The MVP is successful if it proves, with a local benchmark and dogfood use, that
context-aware reranking reduces Bopomofo conversion corrections without
compromising latency, privacy, or fallback behavior.

The MVP is not successful merely because a model runs inside the input method.

The MVP is Taiwan-first: Taiwan Traditional Chinese, Bopomofo, Taiwan usage,
and English-mixed desktop writing are first-class requirements.

## Phase 0: Ground Truth and Baseline

Duration: 1-2 weeks.

Deliverables:

- Curated ambiguous Bopomofo sentence fixture set.
- Taiwan vocabulary and English-mixed sentence fixture set.
- Baseline replay tool using the current engine.
- Metrics report: exact sentence accuracy, token accuracy, candidate rank,
  latency, missing readings.
- Decision note for corpus licensing and fixture policy.

Exit criteria:

- Baseline report is reproducible.
- At least 50 curated cases exist.
- At least 20 English-mixed Taiwan cases exist.
- Current top failure categories are ranked by frequency.

## Phase 1: Deterministic Contextual Reranker

Duration: 2-4 weeks.

Deliverables:

- `ContextualScorer` interface.
- Deterministic scorer implementation.
- Feature flags for evaluation-only and experimental runtime use.
- Protected English span handling.
- Tests for fallback and user override preservation.
- Updated benchmark report comparing baseline versus deterministic reranker.

Exit criteria:

- At least 10% relative reduction in wrong top-1 choices on curated cases.
- No regression in current C++ engine tests.
- p95 added reranking latency under 2 ms on development Mac.
- English-mixed cases do not regress against baseline.
- No content-bearing logs.

## Phase 2: Training Data and Local SLM Reranker Spike

Duration: 3-5 weeks.

Deliverables:

- Taiwan Traditional Chinese corpus manifest with license and redistribution
  status.
- Bopomofo reading generation and missing-reading report.
- English span labeling rules.
- Self-training experiment plan for public, synthetic, and user-provided local
  data.
- Offline experiment comparing at least one local SLM against the deterministic
  reranker.
- Candidate-constrained prompt or scoring protocol.
- Timeout and fallback prototype outside the live IME path.
- Model license, size, and packaging assessment.

Exit criteria:

- SLM beats deterministic reranker by at least 5% relative additional error
  reduction on held-out Taiwan ambiguous cases and does not regress
  English-mixed cases, or the SLM path is deferred.
- p95 commit-time reranking latency under 20 ms in the prototype.
- Model runtime can fail closed without breaking ordinary input.
- Training and evaluation splits are documented and source-separated.

## Phase 2.5: Self-Training Tooling

Duration: 2-4 weeks if Phase 2 shows value.

Deliverables:

- Local training command for user-supplied text files.
- Data deletion/reset workflow.
- Model manifest with training sources, tokenizer, model version, and benchmark
  report.
- Guardrails to keep private local training data out of logs, commits, and
  packaged release artifacts.

Exit criteria:

- A user can train or adapt a model locally without network access.
- The generated model can be enabled, disabled, and removed.
- The runtime always falls back to the default scorer if the self-trained model
  is missing or invalid.

## Phase 3: macOS Experimental Runtime

Duration: 3-5 weeks.

Deliverables:

- Experimental preference to enable contextual reranking.
- Local-only scorer integration in the macOS input method.
- Fallback path for disabled scorer, timeout, model missing, or model error.
- Manual dogfood checklist and issue template.

Exit criteria:

- Dogfood users can enable and disable the scorer without reinstalling.
- Candidate UI behavior remains consistent with existing McBopomofo behavior.
- No typed content appears in logs.
- Crash-free ordinary typing session over a defined dogfood period.

## Phase 4: Ubuntu Feasibility

Duration: 2-4 weeks.

Deliverables:

- Linux build of evaluation/scoring core.
- Architecture decision record choosing IBus, Fcitx5, Rime integration, or
  libchewing-adjacent integration.
- Minimal command-line conversion demo on Ubuntu.

Exit criteria:

- The same benchmark can run on Ubuntu without macOS frameworks.
- The chosen Linux integration path has a scoped implementation plan.

## Phase 5: Public Alpha

Duration: 4-6 weeks after Phases 0-4.

Deliverables:

- macOS alpha package with contextual reranking disabled by default or clearly
  marked experimental.
- Benchmark summary in release notes.
- Privacy statement.
- Known limitations and rollback instructions.

Exit criteria:

- Alpha users can install, enable, disable, and remove the feature.
- Release notes include accuracy, latency, model size if applicable, and
  unsupported cases.
- No cloud behavior exists.

## Milestone Decision Gates

| Gate | Continue If | Stop Or Pivot If |
|---|---|---|
| After Phase 0 | Baseline errors are measurable and dominated by contextual ambiguity | Failures are mostly missing dictionary entries or bugs unrelated to context |
| After Phase 1 | Deterministic reranker improves accuracy with low latency | Improvement is negligible or causes user override regressions |
| After Phase 2 | SLM materially beats deterministic reranker under latency budget on Taiwan and English-mixed fixtures | SLM is slower, unstable, only matches deterministic features, or regresses English-mixed text |
| After Phase 3 | macOS dogfood confirms lower correction work | Users disable it due to latency, surprising candidates, or instability |
| After Phase 4 | Linux core can run cleanly and frontend path is clear | Ubuntu support requires a separate product architecture |

## Backlog

- Personal local phrase memory with explicit user controls.
- Domain profiles for coding, finance, academic writing, and messaging.
- Model distillation from larger teacher models into a compact reranker.
- Taiwan named-entity update packs for public institutions, products, places,
  organizations, and current terminology.
- Self-trained user style models with local-only storage and explicit reset.
- Candidate explanation mode for debug builds.
- Optional Rime schema experiment for users who prefer Rime frontends.

## Risks

- SLM may not outperform simpler contextual ranking.
- Model runtime may add unacceptable startup time or memory use.
- Public Traditional Chinese corpus licensing may limit redistributable fixtures.
- Taiwan-specific corpus quality may be uneven, and generic Traditional Chinese
  corpora may import non-Taiwan vocabulary preferences.
- Self-training can overfit to user files or preserve sensitive phrases if reset,
  packaging, and logging boundaries are weak.
- Ubuntu support may become a separate frontend project rather than a simple port.
- Candidate changes may surprise users even when offline accuracy improves.
