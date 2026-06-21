#!/usr/bin/env python3
"""Analyze candidate-ranker behavior over exported SLM request JSONL files.

The output is a content-free JSON summary: aggregate counts, latency-free
quality deltas, candidate coverage, and feature-coverage counters. It does not
write model outputs, prompts, expected strings, or candidate strings.
"""

import argparse
import json
import os
import sys

import candidate_ranker_scorer as scorer


def fixture_name_from_path(path):
    basename = os.path.basename(path)
    if basename.startswith("slm_") and basename.endswith(".jsonl"):
        return basename[len("slm_"):-len(".jsonl")]
    return basename.replace(".jsonl", "")


def read_requests(paths):
    for path in paths:
        fixture = fixture_name_from_path(path)
        with open(path, "r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield fixture, line_no, json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"{path}:{line_no}: invalid JSON: {exc}")


def inc(table, key, amount=1):
    table[key] = table.get(key, 0) + amount


def selected_tokens(output, candidates):
    return scorer.validate_candidates(output, candidates)


def token_has_evidence(model, reading, token, previous, baseline_tokens,
                       idx):
    counts = model.get("counts", {})
    prev_base = scorer.token_at(baseline_tokens, idx - 1, "<BOS>")
    next_base = scorer.token_at(baseline_tokens, idx + 1, "<EOS>")
    keys = {
        "reading_candidate": reading + "\t" + token,
        "candidate": token,
        "transition": previous + "\t" + token,
        "baseline_prev_candidate": prev_base + "\t" + reading + "\t" + token,
        "baseline_next_candidate": reading + "\t" + token + "\t" + next_base,
        "baseline_window_candidate": (
            prev_base + "\t" + reading + "\t" + token + "\t" + next_base
        ),
    }
    return {
        name: counts.get(name, {}).get(key, 0) > 0
        for name, key in keys.items()
    }


def summarize_case(model, request):
    expected = request.get("expected", "")
    baseline = request.get("baseline_output", "")
    candidates = request.get("candidates")
    readings = request.get("readings", [])

    ranker_output, ranker_error = scorer.rank_request(model, request)
    expected_tokens = selected_tokens(expected, candidates) if candidates else None
    baseline_tokens = selected_tokens(baseline, candidates) if candidates else None
    ranker_tokens = (
        selected_tokens(ranker_output, candidates)
        if candidates and ranker_output is not None else None
    )

    baseline_correct = bool(expected and baseline == expected)
    ranker_correct = bool(expected and ranker_output == expected)
    changed = ranker_output != baseline

    evidence = {
        "reading_candidate": False,
        "candidate": False,
        "transition": False,
        "baseline_prev_candidate": False,
        "baseline_next_candidate": False,
        "baseline_window_candidate": False,
    }
    non_baseline_evidence = False
    if ranker_tokens:
        previous = "<BOS>"
        for idx, token in enumerate(ranker_tokens):
            reading = readings[idx] if idx < len(readings) else ""
            token_evidence = token_has_evidence(
                model, reading, token, previous, baseline_tokens, idx
            )
            for name, present in token_evidence.items():
                evidence[name] = evidence[name] or present
            if baseline_tokens and idx < len(baseline_tokens):
                if token != baseline_tokens[idx] and any(token_evidence.values()):
                    non_baseline_evidence = True
            previous = token

    slot_count = len(candidates) if candidates else 0
    candidate_count = sum(len(slot) for slot in candidates) if candidates else 0
    multi_char_slots = 0
    max_slot_size = 0
    if candidates:
        for slot in candidates:
            max_slot_size = max(max_slot_size, len(slot))
            if any(len(token) > 1 for token in slot):
                multi_char_slots += 1

    return {
        "baseline_correct": baseline_correct,
        "ranker_correct": ranker_correct,
        "ranker_error": ranker_error,
        "changed": changed,
        "improved": (not baseline_correct) and ranker_correct,
        "regressed": baseline_correct and (not ranker_correct),
        "has_candidates": bool(candidates),
        "expected_in_candidates": expected_tokens is not None if candidates else False,
        "baseline_in_candidates": baseline_tokens is not None if candidates else False,
        "ranker_in_candidates": ranker_tokens is not None if candidates else False,
        "slot_count": slot_count,
        "candidate_count": candidate_count,
        "multi_char_slots": multi_char_slots,
        "max_slot_size": max_slot_size,
        "evidence": evidence,
        "non_baseline_evidence": non_baseline_evidence,
    }


def empty_bucket():
    return {
        "total_cases": 0,
        "baseline_exact_matches": 0,
        "ranker_exact_matches": 0,
        "improved_cases": 0,
        "regressed_cases": 0,
        "changed_cases": 0,
        "fallbacks": 0,
        "cases_with_candidates": 0,
        "expected_in_candidates": 0,
        "baseline_in_candidates": 0,
        "ranker_in_candidates": 0,
        "total_slots": 0,
        "total_candidates": 0,
        "multi_char_slots": 0,
        "max_slot_size": 0,
        "non_baseline_evidence_cases": 0,
        "feature_coverage_cases": {
            "reading_candidate": 0,
            "candidate": 0,
            "transition": 0,
            "baseline_prev_candidate": 0,
            "baseline_next_candidate": 0,
            "baseline_window_candidate": 0,
        },
        "fallback_breakdown": {},
    }


def add_case(bucket, case_summary):
    bucket["total_cases"] += 1
    if case_summary["baseline_correct"]:
        bucket["baseline_exact_matches"] += 1
    if case_summary["ranker_correct"]:
        bucket["ranker_exact_matches"] += 1
    if case_summary["improved"]:
        bucket["improved_cases"] += 1
    if case_summary["regressed"]:
        bucket["regressed_cases"] += 1
    if case_summary["changed"]:
        bucket["changed_cases"] += 1
    if case_summary["ranker_error"]:
        bucket["fallbacks"] += 1
        inc(bucket["fallback_breakdown"], case_summary["ranker_error"])
    if case_summary["has_candidates"]:
        bucket["cases_with_candidates"] += 1
    if case_summary["expected_in_candidates"]:
        bucket["expected_in_candidates"] += 1
    if case_summary["baseline_in_candidates"]:
        bucket["baseline_in_candidates"] += 1
    if case_summary["ranker_in_candidates"]:
        bucket["ranker_in_candidates"] += 1
    bucket["total_slots"] += case_summary["slot_count"]
    bucket["total_candidates"] += case_summary["candidate_count"]
    bucket["multi_char_slots"] += case_summary["multi_char_slots"]
    bucket["max_slot_size"] = max(
        bucket["max_slot_size"], case_summary["max_slot_size"]
    )
    if case_summary["non_baseline_evidence"]:
        bucket["non_baseline_evidence_cases"] += 1
    for name, present in case_summary["evidence"].items():
        if present:
            bucket["feature_coverage_cases"][name] += 1


def finalize_bucket(bucket):
    total = bucket["total_cases"]
    slots = bucket["total_slots"]
    result = dict(bucket)
    result["baseline_exact_accuracy"] = (
        round(bucket["baseline_exact_matches"] / total * 100, 4)
        if total else 0.0
    )
    result["ranker_exact_accuracy"] = (
        round(bucket["ranker_exact_matches"] / total * 100, 4)
        if total else 0.0
    )
    result["avg_candidates_per_slot"] = (
        round(bucket["total_candidates"] / slots, 4) if slots else 0.0
    )
    result["multi_char_slot_pct"] = (
        round(bucket["multi_char_slots"] / slots * 100, 4) if slots else 0.0
    )
    return result


def build_report(model, request_paths):
    aggregate = empty_bucket()
    by_fixture = {}
    for fixture, _, request in read_requests(request_paths):
        by_fixture.setdefault(fixture, empty_bucket())
        summary = summarize_case(model, request)
        add_case(aggregate, summary)
        add_case(by_fixture[fixture], summary)

    return {
        "report": "candidate-ranker-analysis",
        "model_type": model.get("model_type"),
        "model_training": model.get("training", {}),
        "aggregate": finalize_bucket(aggregate),
        "by_fixture": {
            fixture: finalize_bucket(bucket)
            for fixture, bucket in sorted(by_fixture.items())
        },
        "notes": [
            "No text outputs, expected strings, prompts, or candidate strings are stored.",
            "changed_cases counts any scorer output differing from baseline.",
            "feature_coverage_cases counts cases where the selected tokens had matching model evidence.",
        ],
    }


def run_self_test():
    model = {
        "model_type": "candidate-ranker-v1",
        "training": {"usable_cases": 1},
        "weights": {
            "baseline_bonus": 0.5,
            "reading_candidate_weight": 0.1,
            "candidate_weight": 0.05,
            "transition_weight": 0.15,
            "baseline_prev_candidate_weight": 1.5,
            "baseline_next_candidate_weight": 1.5,
            "baseline_window_candidate_weight": 2.5,
        },
        "counts": {
            "reading_candidate": {"r1\tB": 1},
            "candidate": {"B": 1},
            "transition": {"<BOS>\tB": 1},
            "baseline_prev_candidate": {"<BOS>\tr1\tB": 1},
            "baseline_next_candidate": {"r1\tB\t<EOS>": 1},
            "baseline_window_candidate": {"<BOS>\tr1\tB\t<EOS>": 1},
        },
    }
    request = {
        "id": "analysis-self-test",
        "readings": ["r1"],
        "baseline_output": "A",
        "expected": "B",
        "candidates": [["A", "B"]],
    }
    summary = summarize_case(model, request)
    errors = []
    if not summary["improved"]:
        errors.append("expected improved case")
    if not summary["expected_in_candidates"]:
        errors.append("expected candidate coverage")
    report = {"aggregate": empty_bucket()}
    add_case(report["aggregate"], summary)
    final = finalize_bucket(report["aggregate"])
    if final["ranker_exact_matches"] != 1:
        errors.append("expected one ranker exact match")
    if final["feature_coverage_cases"]["baseline_window_candidate"] != 1:
        errors.append("expected baseline window coverage")
    if errors:
        for error in errors:
            print(f"SELF-TEST FAIL: {error}", file=sys.stderr)
        return 1
    print("SELF-TEST PASSED: candidate ranker analysis", file=sys.stderr)
    return 0


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Analyze candidate-ranker behavior over request JSONL."
    )
    parser.add_argument("--model", help="Candidate ranker model JSON")
    parser.add_argument("--requests", nargs="+", help="Exported request JSONL")
    parser.add_argument("--output", help="Analysis report JSON path")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()
    if args.self_test:
        sys.exit(run_self_test())
    if not args.model or not args.requests or not args.output:
        parser.error("--model, --requests, and --output are required")

    try:
        model = scorer.load_model(args.model)
        report = build_report(model, args.requests)
    except (RuntimeError, OSError) as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        sys.exit(2)

    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


if __name__ == "__main__":
    main()
