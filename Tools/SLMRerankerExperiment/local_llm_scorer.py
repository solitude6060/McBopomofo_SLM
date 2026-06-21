#!/usr/bin/env python3
"""Local tiny-LLM scorer wrapper for the SLM Reranker external scoring protocol.

Supports:
  - Single-request mode (stdin JSON, stdout JSON).
  - Persistent mode (--persistent): reads JSONL from stdin until EOF.
  - Provider ``command`` (--provider command --command-template <str>)
    where placeholders {prompt} or {prompt_file} are substituted.
  - Provider ``ollama`` (--provider ollama --model <name>) using the local
    ``ollama run`` CLI if present.  Does **not** pull models - fails closed
    if the model is not installed.
  - ``--dry-run-baseline``: returns baseline_output without invoking any
    model.  For wrapper protocol verification only.
  - ``--model-manifest <path>``: JSON file describing the model.  Enforces
    parameter_count in [200M, 500M] by default.
  - ``--allow-out-of-range-model``: bypass parameter check for local
    experiments; the fact is reported in scorer_name / stderr.

Exit codes follow the protocol:
  0   success
  1   model unavailable / error (no output emitted)
  2   malformed input
  137 killed by timeout (external)
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

PARAM_MIN = 200_000_000
PARAM_MAX = 500_000_000

_PROVIDER_CHOICES = ("command", "ollama")

def validate_request(request):
    """Return (is_valid, error_reason)."""
    if not isinstance(request, dict):
        return False, "request is not a JSON object"
    if "id" not in request:
        return False, "missing required field: id"
    rid = request.get("id")
    if not isinstance(rid, str) or not rid:
        return False, "id must be a non-empty string"
    if "readings" not in request:
        return False, "missing required field: readings"
    readings = request.get("readings")
    if not isinstance(readings, list):
        return False, "readings must be an array"
    if "baseline_output" not in request:
        return False, "missing required field: baseline_output"
    return True, ""

def load_manifest(path):
    """Load and validate a model manifest JSON file.

    Returns (manifest_dict, error_str).  On error manifest_dict is None.
    Required keys: ``model_name`` (str), ``parameter_count`` (int).
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except FileNotFoundError:
        return None, f"manifest file not found: {path}"
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON in manifest: {exc}"

    if not isinstance(manifest, dict):
        return None, "manifest must be a JSON object"

    for key in ("model_name", "parameter_count"):
        if key not in manifest:
            return None, f"manifest missing required field: {key}"

    if not isinstance(manifest["model_name"], str) or not manifest["model_name"]:
        return None, "manifest.model_name must be a non-empty string"

    pc = manifest["parameter_count"]
    if not isinstance(pc, (int, float)) or pc <= 0:
        return None, f"manifest.parameter_count must be a positive number, got: {pc!r}"

    manifest["parameter_count"] = int(pc)
    return manifest, None


def check_manifest_parameters(manifest, allow_out_of_range):
    """Check parameter_count is within [PARAM_MIN, PARAM_MAX].

    Returns (ok, message).
    """
    params = manifest.get("parameter_count", 0)
    if params < PARAM_MIN or params > PARAM_MAX:
        if allow_out_of_range:
            return (
                True,
                f"out-of-range model allowed: {params} parameters "
                f"(outside [{PARAM_MIN}, {PARAM_MAX}])",
            )
        return (
            False,
            f"parameter_count {params} outside allowed range "
            f"[{PARAM_MIN}, {PARAM_MAX}]",
        )
    return True, "in-range"

def build_prompt(request):
    """Build a candidate-constrained prompt from request fields.

    The prompt is built in memory and never written to disk unless the
    caller explicitly uses ``{prompt_file}`` in the command template.
    """
    readings = request.get("readings", [])
    baseline = request.get("baseline_output", "")
    candidates = request.get("candidates")

    parts = [f"Bopomofo readings: {' '.join(readings)}"]

    if candidates:
        cand_lines = []
        for idx, slot in enumerate(candidates):
            cand_lines.append(f"  Position {idx + 1}: {', '.join(slot)}")
        parts.append("Candidates per position:\n" + "\n".join(cand_lines))

    parts.append(f"Engine baseline: {baseline}")
    parts.append("Task: Select the correct Traditional Chinese output sequence from the candidates above.")
    parts.append("Output:")
    return "\n".join(parts)

def ollama_installed():
    """Return True iff the ``ollama`` CLI is on PATH."""
    return shutil.which("ollama") is not None


def check_ollama_model(model_name):
    """Check whether *model_name* is installed without pulling.

    Returns (available, error_message).
    """
    if not ollama_installed():
        return False, "ollama CLI not found on PATH"

    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        return False, "ollama CLI not found"
    except subprocess.TimeoutExpired:
        return False, "ollama list timed out"

    if result.returncode != 0:
        return False, f"ollama list failed: {result.stderr.strip()[:200]}"

    # Parse NAME column (first whitespace-delimited token).
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("NAME"):
            continue
        installed_name = line.split(maxsplit=1)[0]
        if installed_name == model_name:
            return True, None

    return False, f"model {model_name!r} not found in ollama list"

def _run_subprocess(cmd_list, stdin_input=None, timeout=60):
    """Thin wrapper around subprocess.run with consistent error handling."""
    try:
        proc = subprocess.run(
            cmd_list,
            input=stdin_input,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return None, f"executable not found: {cmd_list[0] if cmd_list else '?'}"
    except subprocess.TimeoutExpired:
        return None, "subprocess timed out"
    except OSError as exc:
        return None, f"subprocess error: {exc}"

    if proc.returncode != 0:
        detail = proc.stderr.strip()[:200] if proc.stderr else "(no stderr)"
        return None, f"exit {proc.returncode}: {detail}"

    return proc.stdout, None


def run_command_provider(prompt, command_template):
    """Execute a command provider with ``{prompt}`` or ``{prompt_file}``.

    Three modes:
      1. ``{prompt_file}`` present -> write prompt to temp file, substitute path.
      2. ``{prompt}`` present      -> quote and substitute inline.
      3. Neither present           -> pass prompt on stdin.
    """
    if "{prompt_file}" in command_template:
        # Write prompt to a temporary file.
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        )
        try:
            tmp.write(prompt)
            tmp.close()
            cmd_str = command_template.replace("{prompt_file}", tmp.name)
            cmd_list = shlex.split(cmd_str)
            output, error = _run_subprocess(cmd_list, timeout=120)
        finally:
            # Ensure cleanup even on error.
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
        return output, error

    if "{prompt}" in command_template:
        quoted = shlex.quote(prompt)
        cmd_str = command_template.replace("{prompt}", quoted)
        cmd_list = shlex.split(cmd_str)
        return _run_subprocess(cmd_list, timeout=120)

    # Pass prompt as stdin.
    cmd_list = shlex.split(command_template)
    return _run_subprocess(cmd_list, stdin_input=prompt, timeout=120)


def run_ollama_provider(prompt, model_name):
    """Run ``ollama run <model>`` with *prompt* piped to stdin."""
    return _run_subprocess(
        ["ollama", "run", model_name],
        stdin_input=prompt,
        timeout=120,
    )

def validate_candidates_simple(output, candidates):
    """Best-effort prevalidation that *output* can be formed from *candidates*.

    Matches the runner's algorithm (greedy left-to-right, longest first).
    When *candidates* is ``None`` or empty, any non-empty output passes.
    """
    if not candidates:
        return True

    out_pos = 0
    for slot in candidates:
        if not slot:
            continue
        if out_pos >= len(output):
            return False

        matched = False
        for cand in sorted(slot, key=len, reverse=True):
            cand_len = len(cand)
            if cand_len == 0:
                continue
            if output[out_pos:out_pos + cand_len] == cand:
                out_pos += cand_len
                matched = True
                break

        if not matched:
            return False

    return out_pos == len(output)

def parse_model_output(raw_output, request):
    """Parse and validate raw model *output*.

    The model may emit:
      - A JSON object with an ``"output"`` string field, **or**
      - A raw line that equals one valid candidate-constrained output.

    Returns ``(output_text | None, error_reason | None)``.
    """
    text = raw_output.strip()
    if not text:
        return None, "empty output"

    candidates = request.get("candidates")

    # 1. Attempt JSON parse (lenient about leading/trailing whitespace).
    if text.startswith("{") and text.endswith("}"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None

        if isinstance(parsed, dict) and "output" in parsed:
            val = parsed["output"]
            if isinstance(val, str) and val:
                if validate_candidates_simple(val, candidates):
                    return val, None
                return None, "output not in candidate set"
            return None, "output field is not a non-empty string"

    # 2. Raw line: must be a valid candidate-constrained output.
    if validate_candidates_simple(text, candidates):
        return text, None

    return None, "output does not match any valid candidate-constrained form"

def process_request(request, provider, command_template, model_name,
                    manifest, allow_out_of_range, dry_run_baseline):
    """Process a single request and return a response dict.

    When the model cannot produce valid output the response **omits** the
    ``output`` field so the runner counts a ``missing_output_field`` fallback.
    """
    start = time.perf_counter()
    baseline = request.get("baseline_output", "")

    if dry_run_baseline:
        elapsed = int((time.perf_counter() - start) * 1_000_000)
        return {
            "output": baseline,
            "scorer_name": "local-llm-dry-run-baseline",
            "latency_us": elapsed,
        }

    prompt = build_prompt(request)

    raw_output = None
    error = None

    if provider == "command":
        raw_output, error = run_command_provider(prompt, command_template)
    elif provider == "ollama":
        raw_output, error = run_ollama_provider(prompt, model_name)

    elapsed = int((time.perf_counter() - start) * 1_000_000)

    if error:
        rid = request.get("id", "?")
        print(f"WARN: [{rid}] provider error: {error}", file=sys.stderr)
        return {"scorer_name": f"local-llm-{provider}-error", "latency_us": elapsed}

    output, parse_error = parse_model_output(raw_output, request)
    if parse_error:
        rid = request.get("id", "?")
        print(f"WARN: [{rid}] parse error: {parse_error}", file=sys.stderr)
        return {"scorer_name": f"local-llm-{provider}-parse-error", "latency_us": elapsed}

    if manifest:
        label = manifest.get("model_name", model_name or "unknown")
        quant = manifest.get("quantization", "")
        parts = ["local-llm", label]
        if quant:
            parts.append(quant)
        if allow_out_of_range:
            parts.append("out-of-range")
        scorer_name = "-".join(parts)
    else:
        label = model_name or command_template or "unknown"
        scorer_name = f"local-llm-{label}"

    return {
        "output": output,
        "scorer_name": scorer_name,
        "latency_us": elapsed,
    }

def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Local tiny-LLM scorer wrapper for the SLM Reranker protocol."
    )
    parser.add_argument(
        "--persistent",
        action="store_true",
        help="Persistent mode: read JSONL requests from stdin until EOF",
    )
    parser.add_argument(
        "--provider",
        choices=_PROVIDER_CHOICES,
        default="command",
        help="Model provider (default: command)",
    )
    parser.add_argument(
        "--command-template",
        type=str,
        default=None,
        metavar="TEMPLATE",
        help="Command template with {prompt} or {prompt_file} placeholders",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        metavar="NAME",
        help="Model name (required for --provider ollama)",
    )
    parser.add_argument(
        "--model-manifest",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to model manifest JSON file",
    )
    parser.add_argument(
        "--allow-out-of-range-model",
        action="store_true",
        help="Allow model outside [200M, 500M] parameter range",
    )
    parser.add_argument(
        "--dry-run-baseline",
        action="store_true",
        help="Dry-run baseline mode: return baseline_output without invoking any model",
    )
    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.provider == "ollama" and not args.model and not args.dry_run_baseline:
        print("FATAL: --model is required for --provider ollama", file=sys.stderr)
        sys.exit(2)

    if args.provider == "command" and not args.command_template and not args.dry_run_baseline:
        print(
            "FATAL: --command-template is required for --provider command "
            "(unless --dry-run-baseline is used)",
            file=sys.stderr,
        )
        sys.exit(2)

    manifest = None
    manifest_out_of_range = False

    if args.model_manifest:
        manifest, err = load_manifest(args.model_manifest)
        if err:
            print(f"FATAL: {err}", file=sys.stderr)
            sys.exit(2)

        ok, msg = check_manifest_parameters(manifest, args.allow_out_of_range_model)
        if not ok:
            print(f"FATAL: {msg}", file=sys.stderr)
            sys.exit(2)

        if args.allow_out_of_range_model:
            params = manifest.get("parameter_count", 0)
            if params < PARAM_MIN or params > PARAM_MAX:
                manifest_out_of_range = True
                print(
                    f"WARN: out-of-range model ({params} params) allowed via "
                    f"--allow-out-of-range-model; scorer_name will note this",
                    file=sys.stderr,
                )

    if args.provider == "ollama" and not args.dry_run_baseline:
        if not ollama_installed():
            print("FATAL: ollama CLI not found on PATH", file=sys.stderr)
            sys.exit(1)

        available, err_msg = check_ollama_model(args.model)
        if not available:
            print(f"FATAL: {err_msg}", file=sys.stderr)
            sys.exit(1)

    def handle_request(request):
        valid, verr = validate_request(request)
        if not valid:
            return {"error": verr}
        return process_request(
            request,
            provider=args.provider,
            command_template=args.command_template,
            model_name=args.model,
            manifest=manifest,
            allow_out_of_range=manifest_out_of_range,
            dry_run_baseline=args.dry_run_baseline,
        )

    if args.persistent:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                print(
                    json.dumps({"error": f"invalid_json: {exc}"}, ensure_ascii=False),
                    flush=True,
                )
                continue

            response = handle_request(request)
            print(json.dumps(response, ensure_ascii=False), flush=True)
        sys.exit(0)

    stdin_text = sys.stdin.read()
    if not stdin_text.strip():
        print("FATAL: empty stdin", file=sys.stderr)
        sys.exit(2)

    try:
        request = json.loads(stdin_text)
    except json.JSONDecodeError as exc:
        print(f"FATAL: invalid JSON on stdin: {exc}", file=sys.stderr)
        sys.exit(2)

    valid, verr = validate_request(request)
    if not valid:
        print(f"FATAL: {verr}", file=sys.stderr)
        sys.exit(2)

    response = handle_request(request)
    print(json.dumps(response, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
