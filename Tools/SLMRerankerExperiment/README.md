# SLM Reranker Experiment: External Scorer Protocol

Last updated: 2026-06-22T18:55:00+08:00

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

## Persistent Scorer Protocol

### Latency Rationale

The standard per-case subprocess scoring spawns a new process for each
fixture case. Measured overhead for a no-op mock is p95 ≈ 19 ms (234 cases,
3 fixture files), entirely dominated by Python interpreter startup and teardown.
For tiny LLM wrappers targeting p95 < 20 ms commit-time reranking, this
overhead consumes the entire budget before any inference happens.

The persistent protocol keeps the scorer process alive for the full
benchmark run, communicating over stdin/stdout pipes. Same mock under the
persistent protocol: p95 ≈ 45 µs — a ~430× reduction in overhead, making it
possible to measure actual model inference latency meaningfully.

### Limitations of the select(2)-Based Approach

The timeout is implemented with `select.select()` on the stdout pipe fd,
with a per-case deadline. This is a Unix-only mechanism (Linux/macOS). A
Windows-compatible implementation would require a different approach
(e.g., `threading.Timer` or `asyncio` with `ProactorEventLoop`).

The `select` approach makes a best-effort attempt to read a complete JSON
line within the deadline. Because pipe writes are atomic up to `PIPE_BUF`
(4096 bytes on Linux), a single `write + flush` from the scorer is almost
always received as a complete line. The implementation buffers partial
reads across calls for robustness.

If the stdout pipe or stderr pipe fills up (e.g., a chatty scorer logging
to stderr), the process may block. Production scorers should minimize
stderr output during the benchmark loop.

### Invocation

The persistent scorer is started once and kept alive for all fixture cases:

```bash
python3 run_experiment.py \
  --persistent-scorer-command "python3 path/to/scorer.py --persistent [args]" \
  --fixtures path/to/fixtures.jsonl [...] \
  --timeout-ms <milliseconds> \
  --output path/to/summary.json \
  --per-case-output path/to/per_case.jsonl
```

`--persistent-scorer-command` is mutually exclusive with `--scorer-command`
and `--dry-run`.

### Persistent Scorer Stdin/Stdout Protocol

For each fixture case, the runner writes one JSON line to the scorer's
stdin and reads one JSON line from the scorer's stdout. The JSON formats
are identical to the per-case protocol described above.

The scorer **must** flush stdout after each response. In Python:

```python
print(json.dumps(response, ensure_ascii=False), flush=True)
```

### Persistent Scorer Exit Behavior

| Event | Runner action |
|-------|---------------|
| Process exits during run | Mark remaining cases as `persistent_process_died` fallback |
| Timeout reading response | Mark case as `timeout` fallback, continue if process alive |
| Broken pipe on write | Process is dead; remaining cases fallback with `broken_pipe` |
| Invalid/missing JSON output | Mark case as fallback, continue |

### Mock Scorer Persistent Mode

The included `mock_tiny_llm_scorer.py` supports `--persistent`:

```bash
# Persistent mock (default mode)
python3 mock_tiny_llm_scorer.py --persistent

# Persistent oracle mock
python3 mock_tiny_llm_scorer.py --persistent --oracle
```

In persistent mode, the mock reads JSONL lines from stdin until EOF,
processing each line and writing one response per line. Default and
`--oracle` single-request behavior is unchanged.

## Candidate-Only Output Constraint

The scorer **must not generate text that is absent from the input candidate
set**. All output values must be drawn from the `readings` + `candidates`
provided in the request. The runner verifies this constraint and counts
violations as fallbacks.

**Fixture dependence:** Verification is active only when the fixture case
includes a `candidates` field (per-position candidate lists). The current
public fixtures (`taiwan_ambiguous`, `english_mixed`, `taiwan_specific`) do
**not** include this field, so candidate validation is not exercised in the
default benchmark run. A `--self-test` flag is provided to verify the
validation logic works end-to-end.

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

The runner generates sanitized per-case output only when `--per-case-output`
is explicitly passed. Per-case JSONL omits scorer output, expected text,
baseline text, candidate text, and readings; reports aggregate metrics by
fixture file and reference fixture IDs only.

## Report Registry Validation

Use the registry validator before committing benchmark evidence:

```bash
python3 Tools/SLMRerankerExperiment/validate_experiment_reports.py
```

The validator checks that every registry `summary_file` and `result_files`
entry exists and is parseable. `summary_file` must be a single JSON document;
`result_files` may be JSON or JSONL to support older evaluator outputs.

Reports that explicitly declare `privacy.content_free: true` or
`content_policy.raw_case_strings_in_report: false` receive stricter hygiene
checks: raw text/readings/candidate/committed-text flags must be false, raw
content-bearing fields must be absent, and raw artifact locations must point
under `/tmp`.

Real-model benchmark runs do not update the registry automatically. Publish a
curated content-free summary under `docs/reports/experiments/` first, then add
that stable report path to the registry.

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

1. **Success**: exit 0, valid JSON stdout, `output` field present, and (if
   the fixture supplies candidates) each output position's content appears in
   the corresponding candidate set.
2. **Timeout**: subprocess exceeds `--timeout-ms` → killed (SIGKILL),
   counted as fallback.
3. **Non-zero exit**: scorer exited with code != 0 → counted as fallback.
4. **Invalid output**: stdout is not valid JSON, or JSON lacks `output`
   field → counted as fallback.
5. **Non-candidate output**: output content at a position is not present in
   the corresponding candidate slot — only detected when the fixture
   provides a `candidates` field. Counted as fallback with reason
   `non_candidate_output`.

**Note:** Existing public fixtures do not include the `candidates` field, so
outcomes 1 and 5 currently behave identically to a protocol that lacks
candidate validation. The protocol supports the constraint; the fixtures have
not yet been extended to supply the necessary data.

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
| `--fixtures` | (required unless `--self-test`) | One or more JSONL fixture file paths |
| `--scorer-command` | (required unless `--dry-run`) | External scorer command string |
| `--timeout-ms` | 30 | Per-case timeout in milliseconds |
| `--output` | stdout | Summary JSON output path |
| `--per-case-output` | (none) | Optional sanitized per-case JSONL output path |
| `--dry-run` | false | Use built-in mock scorer (no subprocess) |
| `--persistent-scorer-command` | (mutually exclusive with `--scorer-command` and `--dry-run`) | Persistent scorer command string; keeps process alive for all cases |
| `--self-test` | false | Run self-tests (candidate validation unit tests + pipeline + persistent scorer integration) and exit |

## Generating SLM Request Data with Candidates

The C++ contextual evaluator in `Tools/ContextualEvaluation/` can export
JSONL files with per-position candidate slots. These slots reproduce the
engine's baseline segmentation and expose the Viterbi-grid candidates,
enabling end-to-end candidate validation (`candidate_validation.exercised=true`)
in the runner.

### CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--slm-request-output <path>` | (none) | Write candidate-constrained SLM request JSONL to `<path>` |
| `--slm-candidate-limit <N>` | 16 | Max candidates per slot; the baseline node value is always included |
| `--slm-candidate-granularity node\|character` | node | Export slots as baseline Viterbi nodes or aligned single-character slots |

### Generating Requests

```bash
cd Tools/ContextualEvaluation
./build/evaluator ../../Source/Data/data.txt \
  --slm-request-output /tmp/slm_requests.jsonl \
  --slm-candidate-limit 16 \
  --slm-candidate-granularity character \
  ../../Tests/fixtures/contextual_bopomofo/taiwan_ambiguous.jsonl
```

Each line written to `/tmp/slm_requests.jsonl` is a scorer request with
the `candidates` field populated:

```json
{"id":"tw-amb-001","readings":["ㄗㄞˋ","ㄐㄧㄢˋ"],"baseline_output":"再見","expected":"再見","candidates":[["再見"]]}
```

### Running the Python Benchmark Against Generated Requests

```bash
cd Tools/SLMRerankerExperiment

# Dry-run (built-in mock)
python3 run_experiment.py --dry-run \
  --fixtures /tmp/slm_requests.jsonl \
  --timeout-ms 500 \
  --output /tmp/slm_dry_summary.json

# External mock scorer
python3 run_experiment.py \
  --scorer-command "python3 mock_tiny_llm_scorer.py" \
  --fixtures /tmp/slm_requests.jsonl \
  --timeout-ms 500 \
  --output /tmp/slm_mock_summary.json \
  --per-case-output /tmp/slm_mock_per_case.jsonl
```

### Privacy

Generated request JSONL files contain content-bearing data (readings,
candidates, expected text, baseline output). **Do not commit these files
to the repository.** Generate them into `/tmp` or another ephemeral
location. The runner's `--per-case-output` and report mechanisms remain
content-free per the privacy policy above.

### Limitations

- Candidate slots are **baseline-segmentation-constrained**. The walk
  determines the segmentation; each slot corresponds to one baseline node.
  The scorer may not propose alternative segmentations.
- Non-Bopomofo / protected tokens get fixed single-element slots (e.g.,
  `["Docker"]`). Space boundaries are reproduced as `[" "]` slots.

## Mock Scorer

The included `mock_tiny_llm_scorer.py` implements the protocol for
verification:

- **Default mode** (`mock_tiny_llm_scorer.py`): Returns `baseline_output`
  as-is — a no-op that does not claim any accuracy improvement.
- **Oracle mode** (`mock_tiny_llm_scorer.py --oracle`): Returns the
  `expected` field from the request — for verifying the runner/scaffold
  correctly detects exact matches.
- **Persistent mode** (`mock_tiny_llm_scorer.py --persistent`): Reads
  JSONL from stdin until EOF, processing each line as a separate request.
  Compatible with `--oracle`. Designed to test the persistent scorer
  protocol without process-spawn overhead.

Neither mode performs any model inference. All are for scaffold testing only.

## Local LLM Scorer

`local_llm_scorer.py` wraps a local tiny-LLM model (200M–0.5B parameters) as
an SLM Reranker protocol scorer. It is a **scaffold-only** wrapper — it does
not bundle model weights or inference runtimes.

### CLI

```
python3 local_llm_scorer.py [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--persistent` | false | Persistent JSONL mode (read until EOF) |
| `--provider` | `command` | Model provider: `command`, `ollama`, or `ollama-http` |
| `--command-template` | (none) | Command template with `{prompt}` or `{prompt_file}` placeholders |
| `--model` | (none) | Model name (required for `--provider ollama` or `ollama-http`) |
| `--model-manifest` | (none) | Path to model manifest JSON |
| `--allow-out-of-range-model` | false | Bypass [200M, 500M] parameter check |
| `--dry-run-baseline` | false | Return `baseline_output` without model invocation |
| `--prompt-style output\|indices` | `output` | Ask the model to return full candidate text or 1-based candidate indices |
| `--ollama-format-json` | true | Request structured JSON output from Ollama providers. Use `--no-ollama-format-json` to disable. |
| `--ollama-keepalive` | `5m` | Keepalive duration for Ollama providers (e.g., `5m`, `10m`, `0`) |
| `--ollama-url` | `http://127.0.0.1:11434` | Ollama HTTP base URL for `--provider ollama-http` |

### Providers

**`--provider command`** with `--command-template <template>`:

The template supports two placeholders:

- `{prompt}` — substituted inline (shell-quoted). Example:
  ```bash
  python3 local_llm_scorer.py \
    --provider command \
    --command-template 'llama-cli --prompt {prompt} --temp 0 --no-display-prompt'
  ```

- `{prompt_file}` — prompt written to a temp file; the file path is substituted.
  Safer for long prompts. Example:
  ```bash
  python3 local_llm_scorer.py \
    --provider command \
    --command-template 'llama-cli --file {prompt_file} --temp 0 --no-display-prompt'
  ```

If neither placeholder is present, the prompt is piped to the command's
stdin.

**`--provider ollama`** with `--model <name>`:

Uses `ollama run <name>` with the prompt piped to stdin. The wrapper checks
`ollama list` first and fails closed if the model is not installed — it
never pulls models. Persistent runner mode keeps `local_llm_scorer.py` alive,
but this provider still invokes `ollama run` for each request; treat its
latency as a scaffold measurement unless the backend itself is already
server-backed and warm. For the Phase 2 latency gate, prefer
`--provider command` pointed at a persistent/server-backed local tiny model
runtime, or use `--provider ollama-http` to avoid per-request CLI process
startup.

**`--provider ollama-http`** with `--model <name>`:

Uses Ollama's local HTTP API instead of spawning `ollama run` for every
request. The wrapper checks `/api/tags` first and fails closed if the model is
not installed. Generation uses `/api/generate` with `stream: false`,
`keep_alive` from `--ollama-keepalive`, and `format: json` when
`--ollama-format-json` is enabled. This is the preferred Ollama path for
latency measurements because persistent runner mode keeps `local_llm_scorer.py`
alive and each case becomes one local HTTP request.

```bash
python3 local_llm_scorer.py \
  --provider ollama-http \
  --model qwen2.5:0.5b \
  --ollama-url http://127.0.0.1:11434
```

By default the wrapper passes `--format json` to `ollama run` (controlled by
`--ollama-format-json` / `--no-ollama-format-json`) and sets a 5-minute
keepalive (`--ollama-keepalive 5m`).  When `--format json` is active, Ollama
encourages the model to return a JSON object directly. The CLI provider may
return direct model JSON or wrap model text in a `response` field; the wrapper
extracts that field when present and otherwise parses the returned JSON
directly. The HTTP provider always receives the Ollama response envelope and
parses its `response` field. This mode improves
compatibility with the strict JSON parser but does **not** guarantee output
accuracy - models may still produce incorrect output.

`--prompt-style indices` is the stricter candidate-index mode. The prompt asks
for JSON like `{"indices":[1,2,3]}` and the wrapper converts the 1-based
indices back to candidate text only after range validation. This reduces
non-candidate string parsing risk, but it does not solve model latency or
semantic ranking quality by itself.

The `--no-ollama-format-json` flag is provided in case a model or Ollama
version has compatibility issues with `--format json`.  When disabled, the
wrapper receives raw text output and applies the same two-stage parse
(JSON object first, then raw candidate match).

```bash
# Query a 0.5B model with default JSON format output (must be pre-installed)
python3 local_llm_scorer.py \
  --provider ollama \
  --model qwen2.5:0.5b

# Disable JSON format for models that do not support it cleanly
python3 local_llm_scorer.py \
  --provider ollama \
  --model qwen2.5:0.5b \
  --no-ollama-format-json

# Custom keepalive for long-running persistent sessions
python3 local_llm_scorer.py \
  --provider ollama \
  --model qwen2.5:0.5b \
  --ollama-keepalive 10m
```

### Model Manifest

A JSON file describing the model. The wrapper enforces
`parameter_count ∈ [200M, 500M]` by default and exits with a fatal error if
the manifest parameter count is outside this range.

## Candidate Ranker

`train_candidate_ranker.py` and `candidate_ranker_scorer.py` provide a
non-generative alternative to tiny text-generation models. The scorer never
creates new text; it selects one existing candidate from each exported
candidate slot and emits the concatenated output through the same persistent
SLM scorer protocol.

The trainer consumes SLM request JSONL files generated by the C++ evaluator's
`--slm-request-output` mode. Use `--exclude-fixture` or `--exclude-id-prefix`
when training against benchmark exports so held-out fixture cases are not
counted as training data.

The ranker uses conservative count features: candidate frequency,
reading/candidate frequency, previous selected token transitions, and baseline
left/right context windows. Unknown contexts keep a baseline bonus, so seed
training should only override baseline when the exported candidate context has
supporting examples.

Newly trained models enable conservative override gates by default. A
non-baseline candidate must clear the configured score margin, feature-hit
count, and reading/candidate observation count before it can replace the
baseline token. This prevents one-off seed examples from broadly changing
already-correct baseline output.

```bash
python3 train_candidate_ranker.py \
  --input /tmp/slm_taiwan_ambiguous.jsonl /tmp/slm_english_mixed.jsonl \
  --exclude-fixture taiwan_ambiguous \
  --exclude-fixture english_mixed \
  --override-margin 0.1 \
  --min-non-baseline-feature-hits 2 \
  --min-reading-candidate-count-for-override 2 \
  --output /tmp/candidate_ranker.json

python3 candidate_ranker_scorer.py \
  --model /tmp/candidate_ranker.json \
  --persistent
```

With all three canonical benchmark fixtures excluded, the model has zero
usable supervised cases and intentionally falls back to baseline-compatible
candidate choices. That mode is useful for validating latency and protocol
safety, but it is not expected to beat the deterministic reranker without a
separate training set.

`Tests/fixtures/contextual_bopomofo/ranker_training_seed.jsonl` is a small
independent seed split for exercising this path. It is not part of the 234-case
benchmark suite and uses `ranker-train-` ids so contamination checks can keep it
separate from held-out benchmark fixtures.

Use `analyze_candidate_ranker.py` on exported SLM request JSONL files to
diagnose ranker coverage without storing text outputs in the report:

```bash
python3 analyze_candidate_ranker.py \
  --model Models/candidate_ranker_seed.json \
  --requests /tmp/slm_taiwan_ambiguous.jsonl /tmp/slm_english_mixed.jsonl \
  --output /tmp/candidate_ranker_analysis.json
```

The analysis report tracks changed cases, improved/regressed counts, candidate
coverage, multi-character candidate-slot rate, and feature coverage. High
multi-character slot rates mean the exported candidate lattice is often too
coarse for single-character homophone learning.

```json
{
  "model_name": "qwen2.5-0.5b",
  "provider": "ollama",
  "parameter_count": 500000000,
  "quantization": "q4_k_m",
  "license": "apache-2.0",
  "redistributable": true,
  "local_only": true
}
```

Use `--allow-out-of-range-model` to bypass the parameter check for local
experiments. The fact is reported in `scorer_name` (appends
`-out-of-range`) and on stderr.

### Model Size Warning (Phase 2 Gate)

Ollama models ≥ 9B parameters (e.g., `glm4:9b`, `qwen3.5:9b`,
`deepseek-r1:14b`) are **outside the typing latency target** for
commit-time reranking (p95 < 20 ms). These large models:

- Exceed the 0.5B parameter Phase 2 gate criterion.
- Cannot meet the CPU latency budget for IME-integrated reranking.
- Should **not** be used to satisfy the Phase 2 exit gate.

Only 200M–0.5B models qualify. The manifest `parameter_count` field is the
gatekeeper for this constraint.

### Dry-Run Baseline Mode

`--dry-run-baseline` returns `baseline_output` without invoking any model.
The scorer_name is `local-llm-dry-run-baseline`. This is for wrapper
protocol testing only:

```bash
# Single request
echo '{"id":"test","readings":["ㄗㄞˋ","ㄐㄧㄢˋ"],"baseline_output":"在見"}' | \
  python3 local_llm_scorer.py --dry-run-baseline

# Persistent mode
python3 run_experiment.py \
  --persistent-scorer-command "python3 local_llm_scorer.py --dry-run-baseline --persistent" \
  --fixtures /tmp/slm_taiwan_ambiguous.jsonl /tmp/slm_english_mixed.jsonl /tmp/slm_taiwan_specific.jsonl \
  --timeout-ms 30 \
  --output /tmp/local_llm_dry_summary.json
```

### Prompt Construction

The wrapper builds a candidate-constrained prompt from request fields:

```
Bopomofo readings: ㄗㄞˋ ㄐㄧㄢˋ
Candidates per position:
  Position 1: 在, 再
  Position 2: 見, 建
Engine baseline: 在見
Task: Select the correct Traditional Chinese output sequence from the candidates above.
Output:
```

The prompt is constructed in memory and never logged to disk. The
`{prompt_file}` template placeholder writes it to a temporary file that is
cleaned up after execution.

### Output Parsing

The wrapper accepts three forms of model output:

1. **JSON object** with an `"output"` string field (e.g.,
   `{"output": "再見"}`).
2. **JSON object/list** with 1-based candidate indices when
   `--prompt-style indices` is used (e.g., `{"indices": [2, 1]}` or
   `[2, 1]`).
3. **Raw line** that equals one valid candidate-constrained output.

If the output is invalid (empty, not in candidate set, or malformed JSON
without a matching raw line), the response **omits** the `output` field,
causing the runner to count a `missing_output_field` fallback.

`--indices-repair baseline-fill` is an optional diagnostic mode for
candidate-index prompts. If the model emits too few indices, the missing suffix
is filled from the baseline candidate indices; if it emits too many, extras are
truncated. Repaired outputs still pass the same candidate validation, and
non-integer or out-of-range kept indices fail closed.

### Best-Effort Candidate Prevalidation

The wrapper performs best-effort prevalidation of model output against the
request's `candidates` field (same greedy left-to-right, longest-first
algorithm as the runner). This is a courtesy check to avoid returning
obviously bad output. The runner's authoritative `validate_candidates`
remains the gatekeeper.

## Benchmark Suite Runner

`run_benchmark_suite.py` orchestrates the C++ contextual evaluator and the Python SLM reranker experiment runner across all three canonical fixtures, producing a comprehensive content-free JSON report with gate evaluation.

### CLI

```
python3 run_benchmark_suite.py [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--work-dir <path>` | temp dir | Directory for intermediate files (SLM request JSONL, per-case output) |
| `--output <path>` | stdout | Report JSON output path |
| `--fixtures <names...>` | `taiwan_ambiguous english_mixed taiwan_specific` | Fixture names resolved from `Tests/fixtures/contextual_bopomofo/` (static) or via subprocess (dynamic, e.g. `heldout_generalization_clean`) |
| `--candidate-limit <N>` | 16 | Max candidates per slot for export |
| `--scorer-command <cmd>` | — | External scorer command (per-case subprocess mode) |
| `--persistent-scorer-command <cmd>` | — | Persistent scorer command |
| `--dry-run-local-wrapper` | false | Use `local_llm_scorer.py --dry-run-baseline --persistent` |
| `--model-manifest <path>` | — | Model manifest path (for report metadata only) |
| `--fallback-threshold <N>` | 0 | Max allowed fallbacks for gate |
| `--slm-latency-target-us <us>` | 20000 | SLM p95 latency target for gate (microseconds) |
| `--timeout-ms <N>` | 30000 | Per-case timeout for SLM scorer (milliseconds) |
| `--self-test` | false | Run self-test and exit |
| `--no-gate` | false | Skip gate evaluation |

One of `--scorer-command`, `--persistent-scorer-command`, or `--dry-run-local-wrapper` is required (unless `--self-test`).

### Usage Examples

**Self-test (no external model, no C++ evaluator):**

```bash
python3 run_benchmark_suite.py --self-test
```

**Dry-run smoke (full pipeline with mock scorer):**

```bash
python3 run_benchmark_suite.py \
  --dry-run-local-wrapper \
  --work-dir /tmp/slm_suite_smoke \
  --output /tmp/slm_suite_smoke_report.json
```

**Persistent real model:**

```bash
python3 run_benchmark_suite.py \
  --persistent-scorer-command "python3 your_scorer.py --persistent --model /path/to/model" \
  --model-manifest /path/to/manifest.json \
  --work-dir /tmp/slm_benchmark \
  --output /tmp/slm_report.json
```

**Per-case subprocess mode:**

```bash
python3 run_benchmark_suite.py \
  --scorer-command "python3 your_scorer.py" \
  --work-dir /tmp/slm_benchmark \
  --output /tmp/slm_report.json
```

**Dry-run smoke on clean promotion gate (`heldout_generalization_clean`):**

The `heldout_generalization_clean` fixture is resolved at runtime by
calling `fixture_hygiene_audit.py --export-clean heldout_generalization`.
The runner validates the export metadata and reads the raw fixture JSONL from
`/tmp/`.

```bash
python3 run_benchmark_suite.py \
  --dry-run-local-wrapper \
  --fixtures heldout_generalization_clean \
  --slm-candidate-granularity character \
  --work-dir /tmp/slm_clean_gate_smoke \
  --output /tmp/slm_clean_gate_smoke.json \
  --no-gate
```

### Gate Criteria

The automatic gate evaluation in the report summarizes:

| Condition | Default threshold |
|-----------|-------------------|
| Candidate validation exercised | `candidate_validation.exercised == true` |
| Fallbacks ≤ threshold | `slm.total_fallbacks ≤ 0` (configurable via `--fallback-threshold`) |
| SLM p95 latency ≤ target | `slm.latency_us.p95 ≤ 20000µs` (configurable via `--slm-latency-target-us`) |
| SLM vs deterministic RER > 0% | Aggregate SLM relative error reduction vs deterministic must be positive |

PASS requires **all** conditions met; otherwise FAIL with specific reasons listed.

### Privacy & Content-Free Reports

The report contains only aggregate metrics — no readings, candidates, expected text, baseline output, scorer output, prompts, or model raw output. Fixture counts are included but per-case data is excluded. The `real_model_benchmarked` flag is `false` for `--dry-run-local-wrapper` and read from `--model-manifest` when provided.

## Verification

Before committing changes to this directory, run:

```bash
# 1. Syntax check
python3 -m py_compile mock_tiny_llm_scorer.py
python3 -m py_compile run_experiment.py
python3 -m py_compile local_llm_scorer.py

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

# 6. Run persistent mock on candidate-exported requests (requires pre-generated files in /tmp)
python3 run_experiment.py \
  --persistent-scorer-command "python3 mock_tiny_llm_scorer.py --persistent" \
  --fixtures /tmp/slm_taiwan_ambiguous.jsonl /tmp/slm_english_mixed.jsonl /tmp/slm_taiwan_specific.jsonl \
  --timeout-ms 500 \
  --output /tmp/slm_persistent_mock.json \
  --per-case-output /tmp/slm_persistent_mock_cases.jsonl

# 7. Test local LLM scorer (dry-run baseline mode)
echo '{"id":"v-test","readings":["ㄗㄞˋ","ㄐㄧㄢˋ"],"baseline_output":"在見","expected":"再見"}' | \
  python3 local_llm_scorer.py --dry-run-baseline

# 8. Run local LLM scorer on candidate-exported requests via persistent protocol
# Generate these /tmp/slm_*.jsonl files with the C++ evaluator first; raw
# fixture files do not contain candidate slots and will not exercise
# candidate_validation.exercised=true.
python3 run_experiment.py \
  --persistent-scorer-command "python3 local_llm_scorer.py --dry-run-baseline --persistent" \
  --fixtures /tmp/slm_taiwan_ambiguous.jsonl /tmp/slm_english_mixed.jsonl /tmp/slm_taiwan_specific.jsonl \
  --timeout-ms 30 \
  --output /tmp/local_llm_dry_summary.json \
  --per-case-output /tmp/local_llm_dry_cases.jsonl

# 9. Run self-tests (validates candidate validation + persistent scorer integration)
python3 run_experiment.py --self-test

# 10. Verify no whitespace errors
git diff --check

# 11. Dynamic fixture: syntax check
python3 -m py_compile run_benchmark_suite.py

# 12. Dynamic fixture: self-test (includes parsing + resolution tests)
python3 run_benchmark_suite.py --self-test

# 13. Dynamic fixture: export clean heldout directly
python3 ../ContextualEvaluation/fixture_hygiene_audit.py \
  --export-clean heldout_generalization

# 14. Dynamic fixture: dry-run smoke on clean promotion gate
python3 run_benchmark_suite.py \
  --dry-run-local-wrapper \
  --fixtures heldout_generalization_clean \
  --slm-candidate-granularity character \
  --work-dir /tmp/slm_clean_gate_smoke \
  --output /tmp/slm_clean_gate_smoke.json \
  --no-gate
```

## File Layout

```
Tools/SLMRerankerExperiment/
├── README.md                       # This protocol document
├── run_experiment.py               # Runner script (Python stdlib; PersistentScorer class)
├── mock_tiny_llm_scorer.py         # Mock scorer for verification (supports --persistent)
├── local_llm_scorer.py             # Local tiny-LLM wrapper (--provider command/ollama, --dry-run-baseline)
├── model_manifest.example.json     # Example model manifest for a 0.5B-class model
└── (future: model download scripts, additional wrappers)
```
