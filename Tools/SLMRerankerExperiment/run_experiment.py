#!/usr/bin/env python3
"""Runner for the SLM Reranker external scorer protocol.

Iterates over JSONL fixture lines, spawns the scorer subprocess per case,
measures latency, counts fallbacks, and outputs summary and per-case JSON.

Usage:
    # Dry-run with built-in mock
    python3 run_experiment.py --dry-run --fixtures cases.jsonl

    # With external scorer
    python3 run_experiment.py \\
        --scorer-command "python3 mock_tiny_llm_scorer.py" \\
        --fixtures cases.jsonl \\
        --timeout-ms 30 \\
        --output summary.json \\
        --per-case-output per_case.jsonl
"""

import argparse
import json
import math
import os
import subprocess
import sys
import time


def read_fixtures(paths):
    cases = []
    for path in paths:
        expanded = os.path.expanduser(path)
        if not os.path.isfile(expanded):
            print(f"WARN: fixture file not found: {expanded}", file=sys.stderr)
            continue
        with open(expanded, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    case = json.loads(line)
                except json.JSONDecodeError as e:
                    print(f"WARN: invalid JSON in {expanded}: {e}", file=sys.stderr)
                    continue
                if not case.get("id"):
                    continue
                cases.append(case)
    return cases


def build_scorer_request(case):
    request = {
        "id": case.get("id", ""),
        "readings": case.get("readings", []),
        "baseline_output": "",
    }
    if "expected" in case:
        request["expected"] = case["expected"]
    if "protected_english_spans" in case:
        request["protected_english_spans"] = case["protected_english_spans"]
    if "domain" in case:
        request["domain"] = case["domain"]
    return request


def call_scorer(scorer_cmd, request, timeout_ms):
    start = time.perf_counter()
    input_bytes = (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")

    try:
        proc = subprocess.run(
            scorer_cmd,
            input=input_bytes,
            capture_output=True,
            timeout=timeout_ms / 1000.0,
        )
    except subprocess.TimeoutExpired:
        elapsed_us = int((time.perf_counter() - start) * 1_000_000)
        return None, elapsed_us, "timeout"

    elapsed_us = int((time.perf_counter() - start) * 1_000_000)

    if proc.returncode != 0:
        stderr_text = proc.stderr.decode("utf-8", errors="replace").strip()
        if stderr_text:
            print(f"WARN: scorer stderr: {stderr_text}", file=sys.stderr)
        return None, elapsed_us, f"exit_{proc.returncode}"

    try:
        response = json.loads(proc.stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None, elapsed_us, "invalid_json"

    if not isinstance(response, dict):
        return None, elapsed_us, "invalid_response_type"
    if "output" not in response:
        return None, elapsed_us, "missing_output_field"
    if not isinstance(response["output"], str):
        return None, elapsed_us, "output_not_string"

    return response, elapsed_us, None


def builtin_mock(request):
    start = time.perf_counter()
    baseline = request.get("baseline_output", "")
    elapsed_us = int((time.perf_counter() - start) * 1_000_000)
    return {
        "output": baseline,
        "scorer_name": "builtin-mock",
        "latency_us": elapsed_us,
    }, elapsed_us, None


def evaluate_case(case, scorer_cmd, timeout_ms, dry_run):
    request = build_scorer_request(case)

    if dry_run:
        response, elapsed_us, error = builtin_mock(request)
    else:
        response, elapsed_us, error = call_scorer(scorer_cmd, request, timeout_ms)

    result = {
        "id": case.get("id", ""),
        "exact_match": False,
        "fallback": False,
        "fallback_reason": None,
        "latency_us": elapsed_us,
        "scorer_output": None,
        "scorer_name": None,
    }

    if error:
        result["fallback"] = True
        result["fallback_reason"] = error
        return result

    result["scorer_output"] = response["output"]
    result["scorer_name"] = response.get("scorer_name", "unknown")

    expected = case.get("expected", "")
    if isinstance(expected, str) and expected:
        result["exact_match"] = (response["output"] == expected)

    return result


def compute_latency_percentiles(latencies):
    if not latencies:
        return {"p50": 0, "p95": 0, "p99": 0}
    sorted_lat = sorted(latencies)
    n = len(sorted_lat)
    def perc(p):
        idx = max(0, min(n - 1, int(math.ceil(p / 100.0 * n) - 1)))
        return sorted_lat[idx]
    return {
        "p50": perc(50),
        "p95": perc(95),
        "p99": perc(99),
    }


def compute_summary(results, fixture_names):
    total = len(results)
    exact_matches = sum(1 for r in results if r["exact_match"])
    fallbacks = sum(1 for r in results if r["fallback"])
    scorer_calls = total - fallbacks

    fixture_counts = {}
    for r in results:
        fid = r["id"]
        prefix = fid.split("-")[0] if "-" in fid else fid
        fixture_counts[prefix] = fixture_counts.get(prefix, 0) + 1

    latencies_us = [r["latency_us"] for r in results if not r["fallback"]]
    latencies_all = [r["latency_us"] for r in results]
    successful_latency = compute_latency_percentiles(latencies_us)
    all_latency = compute_latency_percentiles(latencies_all)

    summary = {
        "experiment": "tiny-llm-scaffold",
        "date": time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime()),
        "fixture_files": fixture_names,
        "total_cases": total,
        "exact_match_count": exact_matches,
        "exact_sentence_accuracy_pct": round(100.0 * exact_matches / total, 4) if total > 0 else 0.0,
        "scorer_calls": scorer_calls,
        "fallbacks": fallbacks,
        "latency_us": all_latency,
        "latency_us_successful_only": successful_latency,
        "fallback_breakdown": {},
    }

    fallback_reasons = {}
    for r in results:
        if r["fallback"] and r["fallback_reason"]:
            reason = r["fallback_reason"]
            fallback_reasons[reason] = fallback_reasons.get(reason, 0) + 1
    summary["fallback_breakdown"] = fallback_reasons

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="SLM Reranker experiment runner"
    )
    parser.add_argument(
        "--fixtures",
        nargs="+",
        required=True,
        help="JSONL fixture file paths",
    )
    parser.add_argument(
        "--scorer-command",
        type=str,
        default=None,
        help="External scorer command string (required unless --dry-run)",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30,
        help="Per-case timeout in milliseconds (default: 30)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Summary JSON output path (default: stdout)",
    )
    parser.add_argument(
        "--per-case-output",
        type=str,
        default=None,
        help="Optional per-case JSONL output path",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use built-in mock scorer instead of external command",
    )
    args = parser.parse_args()

    if not args.dry_run and not args.scorer_command:
        print("FATAL: --scorer-command is required unless --dry-run is set", file=sys.stderr)
        sys.exit(1)

    if args.scorer_command:
        scorer_cmd = args.scorer_command.split()
    else:
        scorer_cmd = None

    cases = read_fixtures(args.fixtures)
    if not cases:
        print("FATAL: no valid fixture cases found", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(cases)} cases from {len(args.fixtures)} fixture file(s)", file=sys.stderr)

    results = []
    for i, case in enumerate(cases):
        result = evaluate_case(case, scorer_cmd, args.timeout_ms, args.dry_run)
        results.append(result)

        if result["fallback"]:
            print(f"  [{i+1}/{len(cases)}] {result['id']}: FALLBACK ({result['fallback_reason']})", file=sys.stderr)

    if args.per_case_output:
        with open(args.per_case_output, "w", encoding="utf-8") as f:
            for r in results:
                line = json.dumps(r, ensure_ascii=False)
                f.write(line + "\n")

    summary = compute_summary(results, args.fixtures)

    summary_json = json.dumps(summary, ensure_ascii=False, indent=2)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(summary_json + "\n")
        print(f"Summary written to {args.output}", file=sys.stderr)
    else:
        print(summary_json)


if __name__ == "__main__":
    main()
