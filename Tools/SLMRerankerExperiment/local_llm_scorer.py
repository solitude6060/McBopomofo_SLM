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
  - Provider ``ollama-http`` (--provider ollama-http --model <name>) using
    Ollama's local HTTP API.  Does **not** pull models - fails closed if the
    model is not installed.
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
import urllib.error
import urllib.request

PARAM_MIN = 200_000_000
PARAM_MAX = 500_000_000

_PROVIDER_CHOICES = ("command", "ollama", "ollama-http")
_PROMPT_STYLE_CHOICES = ("output", "indices")
_INDICES_REPAIR_CHOICES = ("none", "baseline-fill")

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


def enumerate_valid_outputs(candidates, limit=64):
    """Return every candidate-constrained output when the product is small."""
    if not candidates:
        return []

    outputs = [""]
    for slot in candidates:
        if not slot:
            continue
        if len(outputs) * len(slot) > limit:
            return []
        outputs = [prefix + cand for prefix in outputs for cand in slot]

    return outputs

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

def candidate_indices_for_output(output, candidates):
    """Return 1-based candidate indices for *output*, or None if invalid."""
    if not output or not candidates:
        return None

    out_pos = 0
    indices = []
    for slot in candidates:
        if not slot:
            continue
        matched = None
        for idx, cand in enumerate(slot, 1):
            if output[out_pos:out_pos + len(cand)] == cand:
                matched = idx
                out_pos += len(cand)
                break
        if matched is None:
            return None
        indices.append(matched)

    if out_pos != len(output):
        return None
    return indices


def build_prompt(request, prompt_style="output"):
    """Build a candidate-constrained prompt from request fields.

    The prompt is built in memory and never written to disk unless the
    caller explicitly uses ``{prompt_file}`` in the command template.
    The prompt explicitly requests a JSON response to facilitate strict
    output parsing.
    """
    readings = request.get("readings", [])
    baseline = request.get("baseline_output", "")
    candidates = request.get("candidates")

    parts = [f"Bopomofo readings: {' '.join(readings)}"]

    if candidates:
        cand_lines = []
        for idx, slot in enumerate(candidates):
            if prompt_style == "indices":
                indexed = [f"{cand_idx}={cand}" for cand_idx, cand in enumerate(slot, 1)]
                cand_lines.append(f"  Position {idx + 1}: {', '.join(indexed)}")
            else:
                cand_lines.append(f"  Position {idx + 1}: {', '.join(slot)}")
        parts.append("Candidates per position:\n" + "\n".join(cand_lines))

        valid_outputs = enumerate_valid_outputs(candidates)
        if valid_outputs and prompt_style == "output":
            valid_lines = [f"  - {out}" for out in valid_outputs]
            parts.append("Valid full outputs (copy exactly one):\n" + "\n".join(valid_lines))

        baseline_indices = candidate_indices_for_output(baseline, candidates)
        if baseline_indices and prompt_style == "indices":
            parts.append(f"Baseline candidate indices: {baseline_indices}")

    parts.append(f"Engine baseline: {baseline}")
    if prompt_style == "indices":
        parts.append(
            "Task: Select the correct Traditional Chinese output sequence.\n"
            "Rules:\n"
            "- Choose exactly one numeric index from each position, in order.\n"
            "- Use 1-based indices exactly as listed above.\n"
            "- Never output candidate text, readings, explanations, markdown, or alternatives.\n"
            "- Only use the baseline indices as a fallback if uncertain.\n"
            "- Return a single JSON object in exactly this format:\n"
            '  {"indices": [1, 2, 3]}'
        )
    else:
        parts.append(
            "Task: Select the correct Traditional Chinese output sequence.\n"
            "Rules:\n"
            "- Choose exactly one candidate from each position, in order.\n"
            "- Candidate text values are the only allowed output tokens.\n"
            "- Never output readings, Bopomofo symbols, pinyin, English, explanations, markdown, or alternatives.\n"
            "- Only use the baseline as a fallback if uncertain.\n"
            "- Return a single JSON object in exactly this format:\n"
            '  {"output": "<your selection>"}'
        )
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


def _ollama_http_url(base_url, path):
    """Join an Ollama base URL and API path."""
    return base_url.rstrip("/") + path


def _ollama_http_json(base_url, path, payload=None, timeout=30):
    """Call an Ollama HTTP endpoint and return (json_obj, error_message)."""
    data = None
    method = "GET"
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        method = "POST"
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        _ollama_http_url(base_url, path),
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return None, f"http_{exc.code}"
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        return None, f"url_error:{reason}"
    except TimeoutError:
        return None, "http_timeout"
    except OSError as exc:
        return None, f"http_error:{exc}"

    try:
        return json.loads(body), None
    except json.JSONDecodeError:
        return None, "invalid_http_json"


def check_ollama_http_model(model_name, base_url):
    """Check whether *model_name* is available through Ollama HTTP API."""
    payload, error = _ollama_http_json(base_url, "/api/tags", timeout=30)
    if error:
        return False, f"ollama http tags failed: {error}"
    if not isinstance(payload, dict):
        return False, "ollama http tags returned non-object JSON"

    for model in payload.get("models", []):
        if not isinstance(model, dict):
            continue
        if model.get("name") == model_name or model.get("model") == model_name:
            return True, None

    return False, f"model {model_name!r} not found in ollama /api/tags"

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


def run_ollama_provider(prompt, model_name, format_json=True, keepalive="5m"):
    """Run ``ollama run <model>`` with *prompt* piped to stdin.

    When *format_json* is True (default), passes ``--format json`` to
    ``ollama run``. Some Ollama modes return the model text inside a
    ``response`` envelope, so that field is unwrapped when present.
    *keepalive* sets the model load keepalive duration (default ``"5m"``).
    """
    cmd = ["ollama", "run", model_name]
    if format_json:
        cmd.extend(["--format", "json"])
    cmd.extend(["--keepalive", keepalive])

    raw_output, error = _run_subprocess(cmd, stdin_input=prompt, timeout=120)
    if error or not raw_output:
        return raw_output, error

    if format_json:
        try:
            envelope = json.loads(raw_output)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(envelope, dict) and "response" in envelope:
                return envelope["response"], None

    return raw_output, error


def run_ollama_http_provider(prompt, model_name, base_url,
                             format_json=True, keepalive="5m"):
    """Run an Ollama model through the local HTTP API."""
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "keep_alive": keepalive,
    }
    if format_json:
        payload["format"] = "json"

    response, error = _ollama_http_json(
        base_url, "/api/generate", payload=payload, timeout=120
    )
    if error:
        return None, error
    if not isinstance(response, dict):
        return None, "ollama_http_non_object_response"
    if "response" not in response:
        return None, "ollama_http_missing_response"
    if not isinstance(response["response"], str):
        return None, "ollama_http_response_not_string"
    return response["response"], None

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


def output_from_indices(indices, candidates):
    """Convert a list of 1-based candidate indices into output text."""
    if not candidates:
        return None, "missing_candidates"
    if not isinstance(indices, list):
        return None, "indices_not_array"

    non_empty_slots = [slot for slot in candidates if slot]
    if len(indices) != len(non_empty_slots):
        return None, "indices_length_mismatch"

    output = []
    for raw_idx, slot in zip(indices, non_empty_slots):
        if isinstance(raw_idx, str) and raw_idx.isdigit():
            raw_idx = int(raw_idx)
        if not isinstance(raw_idx, int):
            return None, "index_not_integer"
        if raw_idx < 1 or raw_idx > len(slot):
            return None, "index_out_of_range"
        output.append(slot[raw_idx - 1])
    return "".join(output), None


def output_from_repaired_indices(indices, candidates, baseline_output,
                                 repair_mode):
    """Repair a wrong-length index array, then validate normally."""
    if repair_mode != "baseline-fill":
        return None, "indices_length_mismatch"

    non_empty_slots = [slot for slot in candidates or [] if slot]
    target_len = len(non_empty_slots)
    baseline_indices = candidate_indices_for_output(baseline_output, candidates)
    if baseline_indices is None or len(baseline_indices) != target_len:
        return None, "indices_length_mismatch"

    repaired = list(indices[:target_len])
    if len(repaired) < target_len:
        repaired.extend(baseline_indices[len(repaired):])
    return output_from_indices(repaired, candidates)


def output_from_indices_with_repair(indices, request, repair_mode):
    """Convert model indices to output, optionally repairing length only."""
    candidates = request.get("candidates")
    output, err = output_from_indices(indices, candidates)
    if err != "indices_length_mismatch":
        return output, err
    return output_from_repaired_indices(
        indices,
        candidates,
        request.get("baseline_output", ""),
        repair_mode,
    )


def parse_model_output(raw_output, request, indices_repair="none"):
    """Parse and validate raw model *output*.

    The model may emit:
      - A JSON object with an ``"output"`` string field, **or**
      - A raw line that equals one valid candidate-constrained output.

    Returns ``(output_text | None, error_reason | None)``.
    """
    text = raw_output.strip()
    if not text:
        return None, "empty_output"

    candidates = request.get("candidates")

    # 1. Attempt JSON parse (lenient about leading/trailing whitespace).
    if (text.startswith("{") and text.endswith("}")) or (
        text.startswith("[") and text.endswith("]")
    ):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None, "invalid_json_object"

        if isinstance(parsed, list):
            output, err = output_from_indices_with_repair(
                parsed, request, indices_repair
            )
            if err:
                return None, err
            return output, None

        if isinstance(parsed, dict) and "output" in parsed:
            val = parsed["output"]
            if isinstance(val, str) and val:
                if validate_candidates_simple(val, candidates):
                    return val, None
                return None, "output_not_candidate"
            if isinstance(val, str):
                return None, "empty_output"
            return None, "output_not_string"

        if isinstance(parsed, dict) and "indices" in parsed:
            output, err = output_from_indices_with_repair(
                parsed["indices"], request, indices_repair
            )
            if err:
                return None, err
            return output, None

        if isinstance(parsed, dict):
            return None, "missing_output_field"

        return None, "invalid_json_object"

    # 2. Raw line: must be a valid candidate-constrained output.
    if validate_candidates_simple(text, candidates):
        return text, None

    return None, "output_not_candidate_form"

def process_request(request, provider, command_template, model_name,
                    manifest, allow_out_of_range, dry_run_baseline,
                    ollama_format_json=True, ollama_keepalive="5m",
                    ollama_url="http://127.0.0.1:11434",
                    prompt_style="output", indices_repair="none"):
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

    prompt = build_prompt(request, prompt_style=prompt_style)

    raw_output = None
    error = None

    if provider == "command":
        raw_output, error = run_command_provider(prompt, command_template)
    elif provider == "ollama":
        raw_output, error = run_ollama_provider(
            prompt, model_name,
            format_json=ollama_format_json,
            keepalive=ollama_keepalive,
        )
    elif provider == "ollama-http":
        raw_output, error = run_ollama_http_provider(
            prompt, model_name, ollama_url,
            format_json=ollama_format_json,
            keepalive=ollama_keepalive,
        )

    elapsed = int((time.perf_counter() - start) * 1_000_000)

    if error:
        rid = request.get("id", "?")
        print(f"WARN: [{rid}] provider error: {error}", file=sys.stderr)
        return {
            "scorer_name": f"local-llm-{provider}-error",
            "latency_us": elapsed,
            "error_reason": "provider_error",
        }

    effective_indices_repair = (
        indices_repair if prompt_style == "indices" else "none"
    )
    output, parse_error = parse_model_output(
        raw_output, request, indices_repair=effective_indices_repair
    )
    if parse_error:
        rid = request.get("id", "?")
        print(f"WARN: [{rid}] parse error: {parse_error}", file=sys.stderr)
        return {
            "scorer_name": f"local-llm-{provider}-parse-error",
            "latency_us": elapsed,
            "error_reason": parse_error,
        }

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
        help="Model name (required for --provider ollama or ollama-http)",
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
    parser.add_argument(
        "--prompt-style",
        choices=_PROMPT_STYLE_CHOICES,
        default="output",
        help="Prompt and parse style: output text or 1-based candidate indices",
    )
    parser.add_argument(
        "--indices-repair",
        choices=_INDICES_REPAIR_CHOICES,
        default="none",
        help=(
            "Optional repair for wrong-length candidate index arrays. "
            "'baseline-fill' pads missing suffix indices from the baseline "
            "or truncates extra indices; default: none."
        ),
    )
    parser.add_argument(
        "--ollama-format-json",
        action="store_true",
        default=True,
        dest="ollama_format_json",
        help="Pass --format json to ollama run and expect JSON output "
             "(default: true for --provider ollama)",
    )
    parser.add_argument(
        "--no-ollama-format-json",
        action="store_false",
        dest="ollama_format_json",
        help="Disable --format json for ollama run",
    )
    parser.add_argument(
        "--ollama-keepalive",
        type=str,
        default="5m",
        metavar="DURATION",
        help="Keepalive duration for ollama run (default: 5m)",
    )
    parser.add_argument(
        "--ollama-url",
        type=str,
        default="http://127.0.0.1:11434",
        metavar="URL",
        help="Ollama HTTP base URL for --provider ollama-http",
    )
    parser.add_argument("--self-test", action="store_true")
    return parser


def run_self_test():
    request = {
        "id": "self-test",
        "readings": ["r1", "r2"],
        "baseline_output": "AC",
        "candidates": [["A", "B"], ["C"]],
    }
    errors = []

    output, err = parse_model_output('{"indices":[2,1]}', request)
    if output != "BC" or err is not None:
        errors.append(f"indices object parse failed: output={output!r} err={err!r}")

    output, err = parse_model_output("[2, 1]", request)
    if output != "BC" or err is not None:
        errors.append(f"indices list parse failed: output={output!r} err={err!r}")

    output, err = parse_model_output("[2]", request)
    if output is not None or err != "indices_length_mismatch":
        errors.append(
            "default index repair changed strict length mismatch behavior: "
            f"output={output!r} err={err!r}"
        )

    output, err = parse_model_output(
        "[2]", request, indices_repair="baseline-fill"
    )
    if output != "BC" or err is not None:
        errors.append(
            f"baseline-fill short repair failed: output={output!r} err={err!r}"
        )

    output, err = parse_model_output(
        '{"indices":[2,1,1]}', request, indices_repair="baseline-fill"
    )
    if output != "BC" or err is not None:
        errors.append(
            f"baseline-fill long repair failed: output={output!r} err={err!r}"
        )

    output, err = parse_model_output('{"indices":[3,1]}', request)
    if output is not None or err != "index_out_of_range":
        errors.append(f"invalid index accepted: output={output!r} err={err!r}")

    output, err = parse_model_output(
        '{"indices":[3]}', request, indices_repair="baseline-fill"
    )
    if output is not None or err != "index_out_of_range":
        errors.append(
            "baseline-fill hid an out-of-range kept index: "
            f"output={output!r} err={err!r}"
        )

    bad_baseline_request = {
        "id": "self-test-bad-baseline",
        "readings": ["r1", "r2"],
        "baseline_output": "ZZ",
        "candidates": [["A", "B"], ["C"]],
    }
    output, err = parse_model_output(
        "[2]", bad_baseline_request, indices_repair="baseline-fill"
    )
    if output is not None or err != "indices_length_mismatch":
        errors.append(
            "baseline-fill repaired without mappable baseline: "
            f"output={output!r} err={err!r}"
        )

    prompt = build_prompt(request, prompt_style="indices")
    if '{"indices": [1, 2, 3]}' not in prompt:
        errors.append("indices prompt missing required JSON shape")

    if candidate_indices_for_output("BC", request["candidates"]) != [2, 1]:
        errors.append("candidate_indices_for_output failed")

    if errors:
        for error in errors:
            print(f"SELF-TEST FAIL: {error}", file=sys.stderr)
        return 1
    print("SELF-TEST PASSED: local LLM scorer index parsing", file=sys.stderr)
    return 0


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.self_test:
        sys.exit(run_self_test())

    if (
        args.provider in ("ollama", "ollama-http")
        and not args.model
        and not args.dry_run_baseline
    ):
        print(
            f"FATAL: --model is required for --provider {args.provider}",
            file=sys.stderr,
        )
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

    if args.provider == "ollama-http" and not args.dry_run_baseline:
        available, err_msg = check_ollama_http_model(args.model, args.ollama_url)
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
            ollama_format_json=args.ollama_format_json,
            ollama_keepalive=args.ollama_keepalive,
            ollama_url=args.ollama_url,
            prompt_style=args.prompt_style,
            indices_repair=args.indices_repair,
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
