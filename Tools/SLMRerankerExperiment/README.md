# SLM Reranker Experiment: External Scorer Protocol

Last updated: 2026-06-21T12:00:00+08:00

## Purpose

This directory defines a reproducible benchmarking scaffold for evaluating small
language models (200M–0.5B parameters) as candidate-constrained contextual
rerankers for McBopomofo. The scaffold is a **benchmark protocol only** — no
model weights, no inference runtime, and no macOS live IME integration live
here.

## Design Principle

The model may only **rerank existing candidates** from the engine's Viterbi
grid. It must not generate free text, insert new candidates, or replace the
engine's segmentation. This constraint preserves determinism, debuggability,
and user-override semantics.

## Model Size Class

| Property | Value |
|----------|-------|
| Target size | 200M – 0.5B parameters |
| Format | Any local-only format (GGUF, Core ML, ONNX) |
| Hardware target | CPU / Apple Silicon (macOS) |
| Quantization | Encouraged; must declare quant in report |
| Network | **Forbidden** — local inference only |

Rationale: Models smaller than 200M generally lack sufficient contextual
discrimination for Chinese homophone disambiguation. Models larger than 0.5B
exceed the latency budget on CPU and cannot be distributed as optional IME
assets.

## Latency Budget

| Scope | Target | Fallback trigger |
|-------|--------|------------------|
| Commit-time reranking | p95 < 20 ms | > 30 ms → fallback to baseline |
| Per-keystroke reranking | Not evaluated in this scaffold | N/A |

The runner enforces the timeout at the subprocess level. The scorer itself
should not enforce timeouts — it should process and respond as fast as
possible.

## Candidate-Only Output Constraint

The scorer **must not generate text that is absent from the input candidate
set**. All output values must be drawn from the `readings` + `candidates`
provided in the request. The runner verifies this constraint and counts
violations as fallbacks.

Rationale: Free-text generation defeats the purpose of constrained reranking,
introduces hallucination risk, breaks user-override semantics, and adds
unbounded latency.

## Privacy and Logging

### Permitted in scorer process

- Counter values (number of tokens evaluated, fallback count)
- Latency measurements (processing time per request)
- Model load status and error codes
- Fixture IDs from the request (non-content-bearing identifiers)

### Forbidden in scorer process

- Raw Bopomofo readings
- Candidate text
- Expected or baseline output text
- Prompts or model outputs when logging to disk
- Any content from the fixture that could reconstruct user input

The runner generates per-case output only when `--per-case-output` is
explicitly passed. Reports aggregate metrics by fixture file and reference
fixture IDs only.

## External Scoring Protocol

### Invocation

The runner spawns the scorer as a subprocess once per fixture case:

```bash
# The scorer reads one JSON object from stdin and writes one JSON object to stdout.
echo '{"id":"...", ...}' | scorer_command
```

Arguments beyond the stdin pipe are not used by the protocol. The scorer may
accept CLI flags for model path, device, or verbosity settings.

### Stdin JSON Format (Runner → Scorer)

```json
{
  "id": "tw-amb-001",
  "readings": ["ㄗㄞˋ", "ㄐㄧㄢˋ"],
  "baseline_output": "在見",
  "expected": "再見",
  "protected_english_spans": [],
  "domain": "general"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Fixture case identifier |
| `readings` | string[] | yes | Bopomofo reading sequence |
| `baseline_output` | string | yes | Baseline engine output for comparison |
| `expected` | string | no | Ground-truth expected output (for oracle/eval) |
| `protected_english_spans` | string[] | no | English spans to preserve |
| `domain` | string | no | Fixture domain tag |

### Stdout JSON Format (Scorer → Runner)

```json
{
  "output": "再見",
  "scorer_name": "tiny-llm-v0.1",
  "latency_us": 10
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `output` | string | yes | The scorer's chosen output text |
| `scorer_name` | string | yes | Human-readable scorer identifier |
| `latency_us` | number | no | Self-reported processing time in microseconds |

### Exit Codes

| Code | Meaning | Runner action |
|------|---------|---------------|
| 0 | Success | Parse stdout as JSON response |
| 1 | Model unavailable / error | Increment fallback count, skip result |
| 2 | Malformed input | Increment fallback count, skip result |
| 137 | Killed by timeout | Increment fallback count, skip result |
| Other | Unknown error | Increment fallback count, skip result |

### Error Handling

The runner classifies each invocation into one of these outcomes:

1. **Success**: exit 0, valid JSON stdout, `output` field present, output
   characters are candidate-constrained (each output position's characters
   appear in the corresponding candidate set).
2. **Timeout**: subprocess exceeds `--timeout-ms` → killed (SIGKILL),
   counted as fallback.
3. **Non-zero exit**: scorer exited with code != 0 → counted as fallback.
4. **Invalid output**: stdout is not valid JSON, or JSON lacks `output`
   field → counted as fallback.
5. **Non-candidate output**: output contains characters not present in any
   candidate → counted as fallback.

## Runner CLI

```
python3 run_experiment.py \
  --fixtures path/to/fixtures.jsonl [...] \
  --scorer-command "python3 path/to/scorer.py [args]" \
  --timeout-ms <milliseconds> \
  --output path/to/summary.json \
  --per-case-output path/to/per_case.jsonl \
  --dry-run
```

| Flag | Default | Description |
|------|---------|-------------|
| `--fixtures` | (required) | One or more JSONL fixture file paths |
| `--scorer-command` | (required unless `--dry-run`) | External scorer command string |
| `--timeout-ms` | 30 | Per-case timeout in milliseconds |
| `--output` | stdout | Summary JSON output path |
| `--per-case-output` | (none) | Optional per-case JSONL output path |
| `--dry-run` | false | Use built-in mock scorer (no subprocess) |

## Mock Scorer

The included `mock_tiny_llm_scorer.py` implements the protocol for
verification:

- **Default mode** (`mock_tiny_llm_scorer.py`): Returns `baseline_output`
  as-is — a no-op that does not claim any accuracy improvement.
- **Oracle mode** (`mock_tiny_llm_scorer.py --oracle`): Returns the
  `expected` field from the request — for verifying the runner/scaffold
  correctly detects exact matches.

Neither mode performs any model inference. Both are for scaffold testing only.

## Verification

Before committing changes to this directory, run:

```bash
# 1. Syntax check
python3 -m py_compile mock_tiny_llm_scorer.py
python3 -m py_compile run_experiment.py

# 2. Test mock scorer (default mode)
echo '{"id":"v-test","readings":["ㄗㄞˋ","ㄐㄧㄢˋ"],"baseline_output":"在見","expected":"再見"}' | \
  python3 mock_tiny_llm_scorer.py

# 3. Test mock scorer (oracle mode)
echo '{"id":"v-test","readings":["ㄗㄞˋ","ㄐㄧㄢˋ"],"baseline_output":"在見","expected":"再見"}' | \
  python3 mock_tiny_llm_scorer.py --oracle

# 4. Run on all fixtures with --dry-run
python3 run_experiment.py --dry-run \
  --fixtures ../../Tests/fixtures/contextual_bopomofo/taiwan_ambiguous.jsonl \
               ../../Tests/fixtures/contextual_bopomofo/english_mixed.jsonl \
               ../../Tests/fixtures/contextual_bopomofo/taiwan_specific.jsonl \
  --timeout-ms 30

# 5. Run on all fixtures with mock scorer (should match --dry-run)
python3 run_experiment.py \
  --scorer-command "python3 mock_tiny_llm_scorer.py" \
  --fixtures ../../Tests/fixtures/contextual_bopomofo/taiwan_ambiguous.jsonl \
               ../../Tests/fixtures/contextual_bopomofo/english_mixed.jsonl \
               ../../Tests/fixtures/contextual_bopomofo/taiwan_specific.jsonl \
  --timeout-ms 30 \
  --output /tmp/tiny_llm_summary.json

# 6. Verify no whitespace errors
git diff --check
```

## File Layout

```
Tools/SLMRerankerExperiment/
├── README.md                  # This protocol document
├── run_experiment.py          # Runner script (Python stdlib)
├── mock_tiny_llm_scorer.py    # Mock scorer for verification
└── (future: real scorer wrappers, model download scripts)
```
