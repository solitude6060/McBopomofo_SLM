#!/usr/bin/env python3
"""Validate deterministic reranker accuracy and latency gates."""

import argparse
import json
import os
import subprocess
import sys


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", ".."))
DEFAULT_EVALUATOR = os.path.join(SCRIPT_DIR, "build", "evaluator")
DEFAULT_DATA = os.path.join(PROJECT_ROOT, "Source", "Data", "data.txt")
DEFAULT_FIXTURES_DIR = os.path.join(
    PROJECT_ROOT, "Tests", "fixtures", "contextual_bopomofo"
)

CANONICAL_FIXTURES = [
    ("taiwan_ambiguous", "taiwan_ambiguous.jsonl", 100),
    ("english_mixed", "english_mixed.jsonl", 50),
    ("taiwan_specific", "taiwan_specific.jsonl", 84),
]

HELDOUT_CLEAN_FIXTURES = [
    ("heldout_generalization_clean", "heldout_generalization_clean.jsonl", 63),
]


def parse_summary(stdout_text):
    summary = None
    for line in stdout_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "total_cases" in obj:
            summary = obj
    if summary is None:
        raise ValueError("no evaluator summary JSON found")
    return summary


def run_fixture(evaluator, data_path, fixture_path, timeout=120):
    cmd = [
        evaluator,
        data_path,
        "--scorer",
        "deterministic",
        "--candidate-diagnostics",
        fixture_path,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"evaluator not found: {evaluator}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"evaluator timed out on {fixture_path}") from exc
    if result.returncode != 0:
        stderr = result.stderr.strip() or "(no stderr)"
        raise RuntimeError(
            f"evaluator exited {result.returncode} on {fixture_path}: {stderr}"
        )
    try:
        return parse_summary(result.stdout)
    except ValueError as exc:
        raise RuntimeError(f"{fixture_path}: {exc}") from exc


def validate_summary(name, summary, expected_matches, latency_threshold_us):
    errors = []
    total_cases = summary.get("total_cases")
    exact_matches = summary.get("exact_match_count")
    p95 = summary.get("latency_microseconds_p95")
    if total_cases != expected_matches:
        errors.append(
            f"{name}: expected total_cases={expected_matches}, got {total_cases}"
        )
    if exact_matches != expected_matches:
        errors.append(
            f"{name}: expected exact_match_count={expected_matches}, "
            f"got {exact_matches}"
        )
    if not isinstance(p95, (int, float)):
        errors.append(f"{name}: missing numeric latency_microseconds_p95")
    elif p95 > latency_threshold_us:
        errors.append(
            f"{name}: p95 latency {p95}us > threshold {latency_threshold_us}us"
        )

    diagnostics = summary.get("candidate_diagnostics", {})
    if not isinstance(diagnostics, dict):
        errors.append(f"{name}: missing candidate_diagnostics object")
        return errors
    failing_cases = diagnostics.get("failing_cases")
    if failing_cases != 0:
        errors.append(f"{name}: candidate_diagnostics.failing_cases={failing_cases}")
    missing = diagnostics.get("failures_with_missing_expected_cjk_chars")
    if missing != 0:
        errors.append(
            f"{name}: failures_with_missing_expected_cjk_chars={missing}"
        )
    unavailable = diagnostics.get("failures_without_candidate_diagnostics")
    if unavailable != 0:
        errors.append(
            f"{name}: failures_without_candidate_diagnostics={unavailable}"
        )
    return errors


def fixture_set(args):
    if args.heldout:
        return "heldout clean", HELDOUT_CLEAN_FIXTURES
    return "canonical", CANONICAL_FIXTURES


def run_gate(args):
    errors = []
    summaries = []
    gate_name, fixtures = fixture_set(args)
    for name, filename, expected in fixtures:
        fixture_path = os.path.join(args.fixtures_dir, filename)
        if not os.path.isfile(fixture_path):
            errors.append(f"{name}: fixture file not found: {fixture_path}")
            continue
        try:
            summary = run_fixture(args.evaluator, args.data, fixture_path)
        except RuntimeError as exc:
            errors.append(str(exc))
            continue
        summaries.append((name, summary))
        errors.extend(
            validate_summary(
                name,
                summary,
                expected,
                args.latency_p95_threshold_us,
            )
        )

    total_cases = sum(s.get("total_cases", 0) for _, s in summaries)
    total_matches = sum(s.get("exact_match_count", 0) for _, s in summaries)
    expected_total = sum(expected for _, _, expected in fixtures)
    if total_cases != expected_total:
        errors.append(f"aggregate: expected total_cases={expected_total}, got {total_cases}")
    if total_matches != expected_total:
        errors.append(
            f"aggregate: expected exact_match_count={expected_total}, "
            f"got {total_matches}"
        )

    if errors:
        for error in errors:
            print(f"GATE FAIL: {error}", file=sys.stderr)
        return 1

    max_p95 = max(s["latency_microseconds_p95"] for _, s in summaries)
    print(
        f"GATE PASS: deterministic {gate_name} fixtures "
        f"{total_matches}/{total_cases}, max_p95={max_p95}us",
        file=sys.stderr,
    )
    return 0


def run_self_test():
    summary = parse_summary(
        "noise\n"
        + json.dumps({"id": "case", "elapsed_us": 1})
        + "\n"
        + json.dumps({
            "total_cases": 2,
            "exact_match_count": 2,
            "latency_microseconds_p95": 100,
            "candidate_diagnostics": {
                "failing_cases": 0,
                "failures_with_missing_expected_cjk_chars": 0,
                "failures_without_candidate_diagnostics": 0,
            },
        })
    )
    errors = validate_summary("self", summary, 2, 2000)
    if errors:
        for error in errors:
            print(f"SELF-TEST FAIL: {error}", file=sys.stderr)
        return 1
    failing = dict(summary)
    failing["exact_match_count"] = 1
    if not validate_summary("self", failing, 2, 2000):
        print("SELF-TEST FAIL: expected exact_match_count error", file=sys.stderr)
        return 1
    class Args:
        heldout = False
    gate_name, fixtures = fixture_set(Args())
    if gate_name != "canonical" or fixtures != CANONICAL_FIXTURES:
        print("SELF-TEST FAIL: expected canonical fixture set", file=sys.stderr)
        return 1
    Args.heldout = True
    gate_name, fixtures = fixture_set(Args())
    if gate_name != "heldout clean" or fixtures != HELDOUT_CLEAN_FIXTURES:
        print("SELF-TEST FAIL: expected heldout clean fixture set", file=sys.stderr)
        return 1
    print("SELF-TEST PASSED: deterministic gate parser", file=sys.stderr)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Validate deterministic reranker regression gates"
    )
    parser.add_argument("--evaluator", default=DEFAULT_EVALUATOR)
    parser.add_argument("--data", default=DEFAULT_DATA)
    parser.add_argument("--fixtures-dir", default=DEFAULT_FIXTURES_DIR)
    parser.add_argument("--latency-p95-threshold-us", type=int, default=2000)
    parser.add_argument(
        "--heldout",
        action="store_true",
        help="Validate heldout_generalization_clean instead of canonical fixtures",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()
    return run_gate(args)


if __name__ == "__main__":
    sys.exit(main())
