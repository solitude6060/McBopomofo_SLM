# Local Reranker Privacy Statement

The contextual reranker is designed as a local-only experiment. It must not send
typed content, Bopomofo readings, candidate lists, committed text, screenshots
with private text, or user phrase files to any network service.

## Local Processing

- The deterministic reranker runs inside the local input method process.
- Experimental model scorers, if added later, must run locally and fail closed.
- The default runtime mode is `Off`.
- Any model path must be explicitly enabled by the user or dogfood operator.

## Data Not Collected

The project must not collect or persist:

- raw keystrokes;
- Bopomofo readings;
- candidate strings;
- committed text;
- user phrase files;
- excluded phrase files;
- phrase replacement tables;
- screenshots containing private writing.

## Allowed Diagnostics

Diagnostics may include only non-content metadata:

- selected reranker mode;
- latency buckets;
- fallback counts;
- error categories;
- build identifier;
- fixture or synthetic case identifiers;
- aggregate benchmark counts.

## Logs

Runtime logs must not include typed content or candidate text. If a bug requires
content to reproduce, create a synthetic fixture and reference that fixture ID
instead of attaching private text.

## Model Experiments

Prompt-only tiny LLM experiments are benchmark-only unless a future runtime path
has:

- candidate-constrained output;
- timeout handling;
- fallback behavior that preserves current typing;
- local-only execution;
- content-free diagnostics;
- explicit user control to enable, disable, and remove the model.

## Reset And Removal

Users must be able to disable the reranker by setting the runtime mode to
`Off`. Future self-training or model-cache features must include a local reset
and deletion path before they can be enabled in dogfood builds.
