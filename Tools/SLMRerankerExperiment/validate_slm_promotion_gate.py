#!/usr/bin/env python3
"""Validate whether an SLM benchmark report is promotable to runtime."""

import argparse
import copy
import json
import sys


DEFAULT_FALLBACK_THRESHOLD = 0
DEFAULT_LATENCY_TARGET_US = 20000
DEFAULT_MIN_RER_VS_DETERMINISTIC_PCT = 0.0


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def require_dict(errors, value, path):
    if not isinstance(value, dict):
        errors.append(f"{path}: expected object")
        return {}
    return value


def require_number(errors, value, path):
    if not isinstance(value, (int, float)):
        errors.append(f"{path}: expected number")
        return None
    return value


def validate_fixture_requirements(report, required_fixtures, errors):
    if not required_fixtures:
        return
    fixture_names = set()
    fixtures = report.get("fixtures")
    if isinstance(fixtures, dict):
        fixture_names.update(
            key for key in fixtures
            if key != "total" and isinstance(key, str)
        )
    slm_fixtures = (
        report.get("slm", {})
        .get("per_fixture", [])
    )
    if isinstance(slm_fixtures, list):
        for entry in slm_fixtures:
            if isinstance(entry, dict) and isinstance(entry.get("fixture"), str):
                fixture_names.add(entry["fixture"])
    for fixture in required_fixtures:
        if fixture not in fixture_names:
            errors.append(f"fixtures: missing required fixture {fixture!r}")


def validate_model_manifest(report, errors):
    if report.get("real_model_benchmarked") is not True:
        errors.append(".real_model_benchmarked: expected true")
    scorer = require_dict(errors, report.get("scorer"), ".scorer")
    manifest = scorer.get("model_manifest")
    if not isinstance(manifest, dict):
        errors.append(".scorer.model_manifest: expected object for promotion")
        return
    if manifest.get("local_only") is not True:
        errors.append(".scorer.model_manifest.local_only: expected true")
    if manifest.get("redistributable") is not True:
        errors.append(".scorer.model_manifest.redistributable: expected true")
    parameter_count = manifest.get("parameter_count")
    if not isinstance(parameter_count, int) or parameter_count <= 0:
        errors.append(".scorer.model_manifest.parameter_count: expected positive integer")


def validate_candidate_safety(slm_aggregate, errors):
    cv = require_dict(
        errors,
        slm_aggregate.get("candidate_validation"),
        ".slm.aggregate.candidate_validation",
    )
    if cv.get("exercised") is not True:
        errors.append(".slm.aggregate.candidate_validation.exercised: expected true")
    cases = cv.get("cases_with_candidates")
    if not isinstance(cases, int) or cases <= 0:
        errors.append(
            ".slm.aggregate.candidate_validation.cases_with_candidates: "
            "expected positive integer"
        )
    violations = cv.get("non_candidate_violations")
    if violations != 0:
        errors.append(
            ".slm.aggregate.candidate_validation.non_candidate_violations: "
            f"expected 0, got {violations!r}"
        )


def normalize_curated_clean_gate_report(report):
    """Map content-free clean-gate summaries to slm-benchmark-suite shape."""
    if report.get("suite") == "slm-benchmark-suite":
        return report
    if not (
        isinstance(report.get("fixture"), dict)
        and isinstance(report.get("reference"), dict)
        and isinstance(report.get("slm"), dict)
        and "gate_result" in report
    ):
        return report

    fixture = report.get("fixture", {})
    fixture_name = fixture.get("name")
    total_cases = fixture.get("total_cases")
    scorer = report.get("scorer", {})
    reference = report.get("reference", {})
    deterministic = reference.get("deterministic", {})
    slm = report.get("slm", {})

    det_total = deterministic.get("total_cases", total_cases)
    det_matches = deterministic.get("exact_matches")
    det_errors = deterministic.get("errors")
    if det_errors is None and isinstance(det_total, int) and isinstance(det_matches, int):
        det_errors = det_total - det_matches

    slm_total = slm.get("total_cases", total_cases)
    slm_matches = slm.get("exact_matches")
    slm_errors = slm.get("errors")
    if slm_errors is None and isinstance(slm_total, int) and isinstance(slm_matches, int):
        slm_errors = slm_total - slm_matches

    slm_latency = slm.get("latency_us", slm.get("latency_microseconds"))
    slm_rer = slm.get("relative_error_reduction_pct", {})
    if isinstance(slm_rer, dict):
        rer_vs_deterministic = slm_rer.get("vs_deterministic")
    else:
        rer_vs_deterministic = None

    return {
        "suite": "slm-benchmark-suite",
        "real_model_benchmarked": scorer.get(
            "real_model_benchmarked",
            report.get("real_model_benchmarked"),
        ),
        "fixtures": {
            fixture_name: total_cases,
            "total": total_cases,
        },
        "scorer": {
            "model_manifest": scorer.get("model_manifest"),
        },
        "deterministic": {
            "aggregate": {
                "total_cases": det_total,
                "exact_matches": det_matches,
                "errors": det_errors,
            },
        },
        "slm": {
            "per_fixture": [
                {
                    "fixture": fixture_name,
                    "total_cases": slm_total,
                    "exact_matches": slm_matches,
                    "errors": slm_errors,
                },
            ],
            "aggregate": {
                "total_cases": slm_total,
                "exact_matches": slm_matches,
                "errors": slm_errors,
                "fallbacks": slm.get("fallbacks"),
                "latency_us": slm_latency,
                "candidate_validation": slm.get("candidate_validation"),
            },
        },
        "relative_error_reduction_pct": {
            "slm_vs_deterministic": {
                fixture_name: rer_vs_deterministic,
                "aggregate": rer_vs_deterministic,
            },
        },
        "gate": {
            "result": report.get("gate_result"),
            "reasons": report.get("gate_reasons", []),
        },
    }


def validate_report(report, args):
    errors = []
    if not isinstance(report, dict):
        return ["$: expected object"]
    report = normalize_curated_clean_gate_report(report)
    if report.get("suite") != "slm-benchmark-suite":
        errors.append(".suite: expected 'slm-benchmark-suite'")

    gate = require_dict(errors, report.get("gate"), ".gate")
    if gate.get("result") != "PASS":
        errors.append(f".gate.result: expected PASS, got {gate.get('result')!r}")

    validate_model_manifest(report, errors)
    validate_fixture_requirements(report, args.required_fixture, errors)

    deterministic = require_dict(
        errors,
        report.get("deterministic"),
        ".deterministic",
    )
    deterministic_aggregate = require_dict(
        errors,
        deterministic.get("aggregate"),
        ".deterministic.aggregate",
    )
    slm = require_dict(errors, report.get("slm"), ".slm")
    slm_aggregate = require_dict(errors, slm.get("aggregate"), ".slm.aggregate")

    det_errors = require_number(
        errors,
        deterministic_aggregate.get("errors"),
        ".deterministic.aggregate.errors",
    )
    slm_errors = require_number(errors, slm_aggregate.get("errors"), ".slm.aggregate.errors")
    if det_errors is not None and slm_errors is not None and slm_errors >= det_errors:
        errors.append(
            ".slm.aggregate.errors: expected fewer errors than deterministic "
            f"({slm_errors} >= {det_errors})"
        )

    fallbacks = slm_aggregate.get("fallbacks")
    if not isinstance(fallbacks, int) or fallbacks < 0:
        errors.append(".slm.aggregate.fallbacks: expected non-negative integer")
    elif fallbacks > args.fallback_threshold:
        errors.append(
            ".slm.aggregate.fallbacks: "
            f"{fallbacks} > threshold {args.fallback_threshold}"
        )

    latency = require_dict(errors, slm_aggregate.get("latency_us"), ".slm.aggregate.latency_us")
    p95 = require_number(errors, latency.get("p95"), ".slm.aggregate.latency_us.p95")
    if p95 is not None and p95 > args.latency_target_us:
        errors.append(
            ".slm.aggregate.latency_us.p95: "
            f"{p95}us > target {args.latency_target_us}us"
        )

    validate_candidate_safety(slm_aggregate, errors)

    rer = require_dict(
        errors,
        report.get("relative_error_reduction_pct"),
        ".relative_error_reduction_pct",
    )
    rer_vs_det = require_dict(
        errors,
        rer.get("slm_vs_deterministic"),
        ".relative_error_reduction_pct.slm_vs_deterministic",
    )
    aggregate_rer = require_number(
        errors,
        rer_vs_det.get("aggregate"),
        ".relative_error_reduction_pct.slm_vs_deterministic.aggregate",
    )
    if (
        aggregate_rer is not None
        and aggregate_rer <= args.min_rer_vs_deterministic_pct
    ):
        errors.append(
            ".relative_error_reduction_pct.slm_vs_deterministic.aggregate: "
            f"{aggregate_rer}% <= required {args.min_rer_vs_deterministic_pct}%"
        )
    return errors


def make_pass_report():
    return {
        "suite": "slm-benchmark-suite",
        "real_model_benchmarked": True,
        "fixtures": {
            "heldout_generalization_clean": 63,
            "total": 63,
        },
        "scorer": {
            "model_manifest": {
                "model_name": "synthetic-promotable",
                "provider": "local-test",
                "parameter_count": 250000000,
                "quantization": "q4",
                "redistributable": True,
                "local_only": True,
            },
        },
        "deterministic": {
            "aggregate": {
                "total_cases": 63,
                "exact_matches": 60,
                "errors": 3,
            },
        },
        "slm": {
            "per_fixture": [
                {
                    "fixture": "heldout_generalization_clean",
                    "total_cases": 63,
                    "exact_matches": 62,
                    "errors": 1,
                },
            ],
            "aggregate": {
                "total_cases": 63,
                "exact_matches": 62,
                "errors": 1,
                "fallbacks": 0,
                "latency_us": {"p50": 2000, "p95": 10000, "p99": 12000},
                "candidate_validation": {
                    "protocol_available": True,
                    "exercised": True,
                    "cases_with_candidates": 63,
                    "non_candidate_violations": 0,
                },
            },
        },
        "relative_error_reduction_pct": {
            "slm_vs_deterministic": {
                "heldout_generalization_clean": 66.6667,
                "aggregate": 66.6667,
            },
        },
        "gate": {"result": "PASS", "reasons": []},
    }


def make_curated_pass_report():
    return {
        "suite": "slm-qwen2.5-0.5b-clean-gate-summary",
        "fixture": {
            "name": "heldout_generalization_clean",
            "total_cases": 63,
        },
        "scorer": {
            "real_model_benchmarked": True,
            "model_manifest": {
                "model_name": "synthetic-promotable",
                "provider": "local-test",
                "parameter_count": 250000000,
                "quantization": "q4",
                "redistributable": True,
                "local_only": True,
            },
        },
        "reference": {
            "deterministic": {
                "total_cases": 63,
                "exact_matches": 60,
                "exact_accuracy": 95.2381,
            },
        },
        "slm": {
            "total_cases": 63,
            "exact_matches": 62,
            "exact_accuracy": 98.4127,
            "errors": 1,
            "fallbacks": 0,
            "latency_microseconds": {"p50": 2000, "p95": 10000, "p99": 12000},
            "candidate_validation": {
                "protocol_available": True,
                "exercised": True,
                "cases_with_candidates": 63,
                "non_candidate_violations": 0,
            },
            "relative_error_reduction_pct": {
                "vs_baseline": 80.0,
                "vs_deterministic": 66.6667,
            },
        },
        "gate_result": "PASS",
        "gate_reasons": [],
    }


def self_test_args():
    return argparse.Namespace(
        fallback_threshold=DEFAULT_FALLBACK_THRESHOLD,
        latency_target_us=DEFAULT_LATENCY_TARGET_US,
        min_rer_vs_deterministic_pct=DEFAULT_MIN_RER_VS_DETERMINISTIC_PCT,
        required_fixture=["heldout_generalization_clean"],
    )


def run_self_test():
    args = self_test_args()
    good = make_pass_report()
    errors = validate_report(good, args)
    if errors:
        for error in errors:
            print(f"SELF-TEST FAIL: valid report rejected: {error}", file=sys.stderr)
        return 1
    curated_good = make_curated_pass_report()
    errors = validate_report(curated_good, args)
    if errors:
        for error in errors:
            print(
                f"SELF-TEST FAIL: valid curated report rejected: {error}",
                file=sys.stderr,
            )
        return 1

    cases = []
    gate_fail = copy.deepcopy(good)
    gate_fail["gate"]["result"] = "FAIL"
    cases.append((gate_fail, ".gate.result"))

    mock_report = copy.deepcopy(good)
    mock_report["real_model_benchmarked"] = False
    mock_report["scorer"]["model_manifest"] = None
    cases.append((mock_report, ".real_model_benchmarked"))

    no_win = copy.deepcopy(good)
    no_win["slm"]["aggregate"]["errors"] = 3
    no_win["relative_error_reduction_pct"]["slm_vs_deterministic"]["aggregate"] = 0.0
    cases.append((no_win, "fewer errors than deterministic"))

    unsafe = copy.deepcopy(good)
    unsafe["slm"]["aggregate"]["candidate_validation"]["non_candidate_violations"] = 1
    cases.append((unsafe, "non_candidate_violations"))

    slow = copy.deepcopy(good)
    slow["slm"]["aggregate"]["latency_us"]["p95"] = 50000
    cases.append((slow, "latency_us.p95"))

    missing_fixture = copy.deepcopy(good)
    missing_fixture["fixtures"] = {"taiwan_ambiguous": 100, "total": 100}
    missing_fixture["slm"]["per_fixture"][0]["fixture"] = "taiwan_ambiguous"
    cases.append((missing_fixture, "missing required fixture"))

    curated_gate_fail = copy.deepcopy(curated_good)
    curated_gate_fail["gate_result"] = "FAIL"
    cases.append((curated_gate_fail, ".gate.result"))

    for report, expected in cases:
        errors = validate_report(report, args)
        if not any(expected in error for error in errors):
            print(
                "SELF-TEST FAIL: expected error containing "
                f"{expected!r}, got {errors}",
                file=sys.stderr,
            )
            return 1

    print("SELF-TEST PASSED: SLM promotion gate validator", file=sys.stderr)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        description="Validate whether an SLM benchmark report may be promoted"
    )
    parser.add_argument("--report", help="SLM benchmark suite JSON report")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--expect-fail",
        action="store_true",
        help="Return success only when the report fails promotion validation",
    )
    parser.add_argument(
        "--fallback-threshold",
        type=int,
        default=DEFAULT_FALLBACK_THRESHOLD,
    )
    parser.add_argument(
        "--latency-target-us",
        type=int,
        default=DEFAULT_LATENCY_TARGET_US,
    )
    parser.add_argument(
        "--min-rer-vs-deterministic-pct",
        type=float,
        default=DEFAULT_MIN_RER_VS_DETERMINISTIC_PCT,
    )
    parser.add_argument(
        "--required-fixture",
        action="append",
        default=[],
        help="Fixture name that must be present in the benchmark report",
    )
    return parser


def main():
    args = build_parser().parse_args()
    if args.self_test:
        return run_self_test()
    if not args.report:
        print("VALIDATION FAIL: --report is required", file=sys.stderr)
        return 1
    if args.fallback_threshold < 0:
        print("VALIDATION FAIL: --fallback-threshold must be non-negative", file=sys.stderr)
        return 1
    if args.latency_target_us < 0:
        print("VALIDATION FAIL: --latency-target-us must be non-negative", file=sys.stderr)
        return 1

    try:
        report = load_json(args.report)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"VALIDATION FAIL: {exc}", file=sys.stderr)
        return 1

    errors = validate_report(report, args)
    if args.expect_fail:
        if errors:
            for error in errors:
                print(f"EXPECTED FAIL: {error}", file=sys.stderr)
            return 0
        print("VALIDATION FAIL: report unexpectedly passed promotion gate", file=sys.stderr)
        return 1

    if errors:
        for error in errors:
            print(f"VALIDATION FAIL: {error}", file=sys.stderr)
        return 1
    print("VALIDATION PASSED: SLM promotion gate", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
