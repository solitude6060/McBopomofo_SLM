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


def validate_candidates(output, candidates):
    """Validate that output can be formed by picking one item from each candidate slot.

    Candidates is a list of lists — each inner list contains the valid strings
    (typically single characters) for that position. Uses greedy left-to-right
    matching, trying longest candidates first to handle multi-character tokens
    such as "Docker".

    Returns (is_valid: bool, error_reason: str | None).
    """
    if not candidates:
        return True, None

    out_pos = 0
    for slot_idx, slot in enumerate(candidates):
        if not slot:
            continue
        if out_pos >= len(output):
            return (
                False,
                f"non_candidate_output: position {slot_idx} exhausted"
            )

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
            return (
                False,
                f"non_candidate_output: position {slot_idx} "
                f"'{output[out_pos:out_pos + 3]}' not in {slot}"
            )

    if out_pos != len(output):
        return (
            False,
            f"non_candidate_output: extra output after candidates "
            f"'{output[out_pos:]}'"
        )

    return True, None


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
    if "candidates" in case:
        request["candidates"] = case["candidates"]
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
        "candidate_validated": False,
        "candidate_valid": None,
    }

    if error:
        result["fallback"] = True
        result["fallback_reason"] = error
        return result

    result["scorer_output"] = response["output"]
    result["scorer_name"] = response.get("scorer_name", "unknown")

    # Candidate validation — only when the fixture supplies candidates.
    candidates = case.get("candidates")
    if candidates is not None:
        result["candidate_validated"] = True
        valid, reason = validate_candidates(response["output"], candidates)
        result["candidate_valid"] = valid
        if not valid:
            result["fallback"] = True
            result["fallback_reason"] = "non_candidate_output"
            return result

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

    # Candidate validation stats
    cases_with_candidates = sum(1 for r in results if r.get("candidate_validated"))
    non_candidate_violations = sum(
        1 for r in results if r.get("fallback_reason") == "non_candidate_output"
    )
    summary["candidate_validation"] = {
        "protocol_available": True,
        "exercised": cases_with_candidates > 0,
        "cases_with_candidates": cases_with_candidates,
        "non_candidate_violations": non_candidate_violations,
    }

    return summary


def run_self_test():
    """Run self-tests for candidate validation and pipeline integrity.

    Returns 0 on success, 1 on failure. Uses Python stdlib only — no test
    framework dependency.
    """
    import tempfile
    import os

    errors = []

    # ── Unit tests for validate_candidates ──

    # 1. Valid single-char match
    valid, reason = validate_candidates("再見", [["再"], ["見"]])
    if not valid:
        errors.append(f"Unit 1 failed: valid match rejected: {reason}")

    # 2. Invalid: char not in candidate slot
    valid, reason = validate_candidates("再見", [["在"], ["見"]])
    if valid:
        errors.append("Unit 2 failed: should reject char not in slot")

    # 3. None / empty candidates  →  always valid (no-op)
    valid, reason = validate_candidates("anything", None)
    if not valid:
        errors.append(f"Unit 3 failed: None candidates rejected: {reason}")
    valid, reason = validate_candidates("anything", [])
    if not valid:
        errors.append(f"Unit 4 failed: empty candidates rejected: {reason}")

    # 4. Multi-character token (e.g. "Docker")
    valid, reason = validate_candidates("Docker", [["Docker"]])
    if not valid:
        errors.append(f"Unit 5 failed: multi-char token rejected: {reason}")

    # 5. Output shorter than candidates
    valid, reason = validate_candidates("再", [["再"], ["見"]])
    if valid:
        errors.append("Unit 6 failed: should reject short output")

    # 6. Output longer than candidates
    valid, reason = validate_candidates("再見!", [["再"], ["見"]])
    if valid:
        errors.append("Unit 7 failed: should reject extra output")

    # ── Pipeline integration test ──

    fixture_cases = [
        {
            "id": "cand-valid-001",
            "readings": ["ㄗㄞˋ", "ㄐㄧㄢˋ"],
            "candidates": [["在", "再"], ["見", "建"]],
            "expected": "再見",
        },
        {
            "id": "cand-invalid-001",
            "readings": ["ㄗㄞˋ", "ㄐㄧㄢˋ"],
            "candidates": [["在"], ["見"]],
            "expected": "再見",
        },
        {
            "id": "no-cand-001",
            "readings": ["ㄗㄞˋ", "ㄐㄧㄢˋ"],
            "expected": "再見",
        },
    ]

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        for case in fixture_cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")
        fixture_path = f.name

    scorer_code = (
        "#!/usr/bin/env python3\n"
        "import sys, json\n"
        "req = json.load(sys.stdin)\n"
        "out = req.get('expected') or req.get('baseline_output', '')\n"
        "print(json.dumps({'output': out, 'scorer_name': 'self-test-scorer'}))\n"
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(scorer_code)
        scorer_path = f.name

    try:
        cases = read_fixtures([fixture_path])
        if len(cases) != 3:
            errors.append(f"Pipeline: expected 3 cases, got {len(cases)}")

        results = []
        for case in cases:
            result = evaluate_case(
                case, ["python3", scorer_path], 30000, dry_run=False
            )
            results.append(result)

        # cand-valid-001: scorer returns "再見" which is in candidates
        r1 = results[0]
        if r1["fallback"]:
            errors.append(
                "Pipeline: cand-valid-001 should not fallback, "
                f"got: {r1['fallback_reason']}"
            )
        if not r1["candidate_validated"]:
            errors.append("Pipeline: cand-valid-001 should be validated")
        if r1["candidate_valid"] is not True:
            errors.append("Pipeline: cand-valid-001 should be valid")

        # cand-invalid-001: "再" not in candidates[0]=["在"]
        r2 = results[1]
        if not r2["fallback"]:
            errors.append("Pipeline: cand-invalid-001 should fallback")
        if r2["fallback_reason"] != "non_candidate_output":
            errors.append(
                "Pipeline: cand-invalid-001 reason should be "
                f"non_candidate_output, got: {r2['fallback_reason']}"
            )

        # no-cand-001: no candidates → no validation, no fallback
        r3 = results[2]
        if r3["fallback"]:
            errors.append(
                f"Pipeline: no-cand-001 should not fallback, "
                f"got: {r3['fallback_reason']}"
            )
        if r3["candidate_validated"]:
            errors.append("Pipeline: no-cand-001 should not be validated")

    finally:
        try:
            os.unlink(fixture_path)
            os.unlink(scorer_path)
        except OSError:
            pass

    if errors:
        for e in errors:
            print(f"SELF-TEST FAIL: {e}", file=sys.stderr)
        return 1

    print(
        "SELF-TEST PASSED: validate_candidates unit tests "
        "+ pipeline integration",
        file=sys.stderr,
    )
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="SLM Reranker experiment runner"
    )
    parser.add_argument(
        "--fixtures",
        nargs="+",
        default=None,
        help="JSONL fixture file paths (required unless --self-test)",
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
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run self-tests and exit",
    )
    args = parser.parse_args()

    if args.self_test:
        sys.exit(run_self_test())

    if not args.fixtures:
        print("FATAL: --fixtures is required unless --self-test is used", file=sys.stderr)
        sys.exit(1)

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
