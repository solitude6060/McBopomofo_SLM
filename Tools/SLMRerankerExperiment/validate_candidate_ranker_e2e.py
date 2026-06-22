#!/usr/bin/env python3
"""Validate the candidate-ranker end-to-end benchmark contract.

This gate protects the non-generative learned reranker path:

  evaluator --slm-request-output
    -> run_experiment.py persistent scorer protocol
    -> candidate_ranker_scorer.py model loading and candidate choices
    -> analyze_candidate_ranker.py content-free aggregate analysis

The committed reports remain content-free. Request JSONL and per-case outputs
are generated only under /tmp by default.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", ".."))

RUN_BENCHMARK_SUITE = os.path.join(SCRIPT_DIR, "run_benchmark_suite.py")
ANALYZE_CANDIDATE_RANKER = os.path.join(SCRIPT_DIR, "analyze_candidate_ranker.py")
CANDIDATE_RANKER_SCORER = os.path.join(SCRIPT_DIR, "candidate_ranker_scorer.py")

DEFAULT_MODEL = os.path.join(
    PROJECT_ROOT, "Models", "candidate_ranker_seed_char.json"
)
DEFAULT_SCHEMA_MODELS = [
    os.path.join(PROJECT_ROOT, "Models", "candidate_ranker_seed_char.json"),
    os.path.join(PROJECT_ROOT, "Models", "candidate_ranker_seed.json"),
    os.path.join(PROJECT_ROOT, "Models", "candidate_ranker_synthetic.json"),
    os.path.join(PROJECT_ROOT, "Models", "candidate_ranker_heldout_clean.json"),
]

E2E_SUITES = {
    "canonical": {
        "fixtures": [
            ("taiwan_ambiguous", 100),
            ("english_mixed", 50),
            ("taiwan_specific", 84),
        ],
        "candidate_granularity": None,
        "deterministic_exact_required": True,
        "require_non_baseline_evidence": True,
    },
    "heldout": {
        "fixtures": [
            ("heldout_generalization_clean", 63),
        ],
        "candidate_granularity": "character",
        "deterministic_exact_required": True,
        "require_non_baseline_evidence": False,
    },
}

FEATURE_TABLES = [
    "reading_candidate",
    "candidate",
    "transition",
    "baseline_prev_candidate",
    "baseline_next_candidate",
    "baseline_window_candidate",
]
WEIGHT_KEYS = [
    "baseline_bonus",
    "reading_candidate_weight",
    "candidate_weight",
    "transition_weight",
    "baseline_prev_candidate_weight",
    "baseline_next_candidate_weight",
    "baseline_window_candidate_weight",
]
SELECTION_KEYS = [
    "override_margin",
    "min_non_baseline_feature_hits",
    "min_reading_candidate_count_for_override",
    "prefer_baseline_on_weak_override",
]


def project_relpath(path):
    abs_path = os.path.abspath(path)
    try:
        rel = os.path.relpath(abs_path, PROJECT_ROOT)
    except ValueError:
        return abs_path
    if rel == "." or rel.startswith(".."):
        return abs_path
    return rel


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_model_schema(model, label, require_full_schema=False):
    errors = []
    if not isinstance(model, dict):
        return [f"{label}: model must be a JSON object"]
    if model.get("model_type") != "candidate-ranker-v1":
        errors.append(f"{label}: model_type must be candidate-ranker-v1")

    counts = model.get("counts")
    if not isinstance(counts, dict):
        errors.append(f"{label}: counts must be an object")
    else:
        required_tables = FEATURE_TABLES if require_full_schema else [
            "reading_candidate",
            "candidate",
            "transition",
        ]
        for table_name in required_tables:
            table = counts.get(table_name)
            if not isinstance(table, dict):
                errors.append(f"{label}: counts.{table_name} must be an object")
        for table_name, table in counts.items():
            if not isinstance(table, dict):
                errors.append(f"{label}: counts.{table_name} must be an object")

    weights = model.get("weights")
    if not isinstance(weights, dict):
        errors.append(f"{label}: weights must be an object")
    else:
        required_weights = WEIGHT_KEYS if require_full_schema else [
            "baseline_bonus",
            "reading_candidate_weight",
            "candidate_weight",
            "transition_weight",
        ]
        for key in required_weights:
            value = weights.get(key)
            if not isinstance(value, (int, float)):
                errors.append(f"{label}: weights.{key} must be numeric")
        for key, value in weights.items():
            if not isinstance(value, (int, float)):
                errors.append(f"{label}: weights.{key} must be numeric")

    selection = model.get("selection")
    if require_full_schema and not isinstance(selection, dict):
        errors.append(f"{label}: selection must be an object")
    elif selection is not None and not isinstance(selection, dict):
        errors.append(f"{label}: selection must be an object when present")
    elif isinstance(selection, dict):
        for key in SELECTION_KEYS:
            if key not in selection:
                errors.append(f"{label}: selection.{key} is missing")

    training = model.get("training")
    if training is not None:
        if not isinstance(training, dict):
            errors.append(f"{label}: training must be an object when present")
        elif "usable_cases" in training and not isinstance(
            training["usable_cases"], int
        ):
            errors.append(f"{label}: training.usable_cases must be an integer")
    return errors


def validate_schema_models(model_paths, require_full_schema=False):
    errors = []
    for path in model_paths:
        if not os.path.isfile(path):
            errors.append(f"{project_relpath(path)}: missing model file")
            continue
        try:
            model = load_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{project_relpath(path)}: cannot load JSON: {exc}")
            continue
        errors.extend(
            validate_model_schema(
                model,
                project_relpath(path),
                require_full_schema=require_full_schema,
            )
        )
    return errors


def run_command(cmd, timeout=120):
    try:
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"command timed out: {' '.join(cmd)}") from exc
    except OSError as exc:
        raise RuntimeError(f"command failed to start: {' '.join(cmd)}: {exc}") from exc
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else "(no stderr)"
        stdout = result.stdout.strip() if result.stdout else "(no stdout)"
        raise RuntimeError(
            "command exited "
            f"{result.returncode}: {' '.join(cmd)}\nstdout:\n{stdout}\n"
            f"stderr:\n{stderr}"
        )
    return result


def suite_total(suite):
    return sum(count for _, count in suite["fixtures"])


def validate_suite_report(report, suite):
    errors = []
    total = suite_total(suite)
    fixtures = report.get("fixtures", {})
    if fixtures.get("total") != total:
        errors.append(
            f"fixtures.total expected {total}, got {fixtures.get('total')}"
        )
    for name, expected_count in suite["fixtures"]:
        if fixtures.get(name) != expected_count:
            errors.append(
                f"fixtures.{name} expected {expected_count}, got {fixtures.get(name)}"
            )

    scorer = report.get("scorer", {})
    if scorer.get("mode") != "persistent":
        errors.append(f"scorer.mode expected persistent, got {scorer.get('mode')}")
    if report.get("real_model_benchmarked") is not False:
        errors.append("real_model_benchmarked must be false for in-tree ranker gate")

    deterministic = report.get("deterministic", {}).get("aggregate", {})
    if deterministic.get("total_cases") != total:
        errors.append("deterministic aggregate did not cover expected total")
    if (
        suite["deterministic_exact_required"]
        and deterministic.get("exact_matches") != total
    ):
        errors.append(f"deterministic aggregate must remain {total}/{total}")

    slm = report.get("slm", {}).get("aggregate", {})
    if slm.get("total_cases") != total:
        errors.append("candidate ranker aggregate did not cover expected total")
    if slm.get("fallbacks") != 0:
        errors.append(f"candidate ranker fallbacks expected 0, got {slm.get('fallbacks')}")
    latency = slm.get("latency_us", {})
    if latency.get("p95", 0) <= 0:
        errors.append("candidate ranker p95 latency must be positive")
    if latency.get("p95", 0) > 20000:
        errors.append(
            f"candidate ranker p95 latency expected <=20000us, got {latency.get('p95')}"
        )

    cv = slm.get("candidate_validation", {})
    if cv.get("exercised") is not True:
        errors.append("candidate validation must be exercised")
    if cv.get("cases_with_candidates") != total:
        errors.append(
            "candidate validation cases_with_candidates expected "
            f"{total}, got {cv.get('cases_with_candidates')}"
        )
    if cv.get("non_candidate_violations") != 0:
        errors.append(
            "candidate validation non_candidate_violations expected 0, got "
            f"{cv.get('non_candidate_violations')}"
        )
    return errors


def validate_analysis_report(report, suite):
    errors = []
    total = suite_total(suite)
    aggregate = report.get("aggregate", {})
    if aggregate.get("total_cases") != total:
        errors.append(
            f"analysis total_cases expected {total}, "
            f"got {aggregate.get('total_cases')}"
        )
    if aggregate.get("cases_with_candidates") != total:
        errors.append("analysis must see candidates for every expected case")
    if aggregate.get("ranker_in_candidates") != total:
        errors.append("analysis ranker_in_candidates must cover every case")
    if aggregate.get("fallbacks") != 0:
        errors.append(f"analysis fallbacks expected 0, got {aggregate.get('fallbacks')}")
    if suite["require_non_baseline_evidence"] and aggregate.get("changed_cases", 0) <= 0:
        errors.append("analysis changed_cases must be > 0 to cover override path")
    if (
        suite["require_non_baseline_evidence"]
        and aggregate.get("non_baseline_evidence_cases", 0) <= 0
    ):
        errors.append(
            "analysis non_baseline_evidence_cases must be > 0 to cover "
            "learned evidence path"
        )
    feature_coverage = aggregate.get("feature_coverage_cases", {})
    if feature_coverage.get("candidate", 0) <= 0:
        errors.append("analysis feature_coverage_cases.candidate must be > 0")
    if feature_coverage.get("transition", 0) <= 0:
        errors.append("analysis feature_coverage_cases.transition must be > 0")
    return errors


def request_paths(work_dir, suite):
    return [
        os.path.join(work_dir, f"slm_{name}.jsonl")
        for name, _ in suite["fixtures"]
    ]


def validate_request_files(paths, suite):
    errors = []
    for (name, expected_count), path in zip(suite["fixtures"], paths):
        if not os.path.isfile(path):
            errors.append(f"missing request export for {name}: {path}")
            continue
        with open(path, "r", encoding="utf-8") as handle:
            rows = [line for line in handle if line.strip()]
        if len(rows) != expected_count:
            errors.append(
                f"{name} request rows expected {expected_count}, got {len(rows)}"
            )
    return errors


def run_e2e(args):
    suite_name = "heldout" if args.heldout else "canonical"
    suite_profile = E2E_SUITES[suite_name]
    schema_errors = validate_schema_models(args.schema_model)
    schema_errors.extend(validate_schema_models([args.model], require_full_schema=True))
    if schema_errors:
        return schema_errors

    work_dir = args.work_dir
    if work_dir is None:
        work_dir = tempfile.mkdtemp(prefix="candidate_ranker_e2e_")
    os.makedirs(work_dir, exist_ok=True)

    suite_report = args.suite_report
    if suite_report is None:
        suite_report = os.path.join(
            tempfile.gettempdir(), "candidate_ranker_e2e_report.json"
        )
    analysis_report = args.analysis_report
    if analysis_report is None:
        analysis_report = os.path.join(
            tempfile.gettempdir(), "candidate_ranker_e2e_analysis.json"
        )

    scorer_cmd = (
        f"{sys.executable} {CANDIDATE_RANKER_SCORER} "
        f"--model {os.path.abspath(args.model)} --persistent"
    )
    benchmark_cmd = [
        sys.executable,
        RUN_BENCHMARK_SUITE,
        "--persistent-scorer-command",
        scorer_cmd,
        "--work-dir",
        work_dir,
        "--output",
        suite_report,
        "--no-gate",
        "--timeout-ms",
        str(args.timeout_ms),
        "--fixtures",
        *[name for name, _ in suite_profile["fixtures"]],
    ]
    if suite_profile["candidate_granularity"]:
        benchmark_cmd.extend([
            "--slm-candidate-granularity",
            suite_profile["candidate_granularity"],
        ])
    run_command(benchmark_cmd, timeout=180)

    errors = []
    req_paths = request_paths(work_dir, suite_profile)
    errors.extend(validate_request_files(req_paths, suite_profile))
    if errors:
        return errors

    run_command([
        sys.executable,
        ANALYZE_CANDIDATE_RANKER,
        "--model",
        os.path.abspath(args.model),
        "--requests",
        *req_paths,
        "--output",
        analysis_report,
    ], timeout=120)

    try:
        generated_suite_report = load_json(suite_report)
        analysis = load_json(analysis_report)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot load generated report: {exc}"]

    errors.extend(validate_suite_report(generated_suite_report, suite_profile))
    errors.extend(validate_analysis_report(analysis, suite_profile))
    if errors:
        return errors

    print(
        "VALIDATION PASSED: candidate ranker E2E "
        f"suite={suite_name} requests={suite_total(suite_profile)} "
        f"model={project_relpath(args.model)} "
        f"suite_report={suite_report} analysis_report={analysis_report}",
        file=sys.stderr,
    )
    return []


def run_self_test():
    good_model = {
        "model_type": "candidate-ranker-v1",
        "training": {"usable_cases": 1},
        "weights": {key: 1.0 for key in WEIGHT_KEYS},
        "selection": {
            "override_margin": 0.0,
            "min_non_baseline_feature_hits": 0,
            "min_reading_candidate_count_for_override": 0,
            "prefer_baseline_on_weak_override": False,
        },
        "counts": {name: {} for name in FEATURE_TABLES},
    }
    errors = validate_model_schema(good_model, "good")
    if errors:
        print(f"SELF-TEST FAIL: valid model rejected: {errors}", file=sys.stderr)
        return 1

    bad_model = json.loads(json.dumps(good_model))
    del bad_model["counts"]["transition"]
    bad_errors = validate_model_schema(bad_model, "bad")
    if not any("counts.transition" in error for error in bad_errors):
        print("SELF-TEST FAIL: missing transition table accepted", file=sys.stderr)
        return 1

    canonical = E2E_SUITES["canonical"]
    suite_report = {
        "fixtures": {
            "taiwan_ambiguous": 100,
            "english_mixed": 50,
            "taiwan_specific": 84,
            "total": 234,
        },
        "scorer": {"mode": "persistent"},
        "real_model_benchmarked": False,
        "deterministic": {
            "aggregate": {"total_cases": 234, "exact_matches": 234}
        },
        "slm": {
            "aggregate": {
                "total_cases": 234,
                "fallbacks": 0,
                "latency_us": {"p95": 100},
                "candidate_validation": {
                    "exercised": True,
                    "cases_with_candidates": 234,
                    "non_candidate_violations": 0,
                },
            }
        },
    }
    suite_errors = validate_suite_report(suite_report, canonical)
    if suite_errors:
        print(f"SELF-TEST FAIL: valid suite rejected: {suite_errors}", file=sys.stderr)
        return 1

    bad_suite = json.loads(json.dumps(suite_report))
    bad_suite["slm"]["aggregate"]["candidate_validation"][
        "non_candidate_violations"
    ] = 1
    if not validate_suite_report(bad_suite, canonical):
        print("SELF-TEST FAIL: bad suite accepted", file=sys.stderr)
        return 1

    analysis = {
        "aggregate": {
            "total_cases": 234,
            "cases_with_candidates": 234,
            "ranker_in_candidates": 234,
            "fallbacks": 0,
            "changed_cases": 1,
            "non_baseline_evidence_cases": 1,
            "feature_coverage_cases": {"candidate": 1, "transition": 1},
        }
    }
    analysis_errors = validate_analysis_report(analysis, canonical)
    if analysis_errors:
        print(
            f"SELF-TEST FAIL: valid analysis rejected: {analysis_errors}",
            file=sys.stderr,
        )
        return 1
    bad_analysis = json.loads(json.dumps(analysis))
    bad_analysis["aggregate"]["changed_cases"] = 0
    if not validate_analysis_report(bad_analysis, canonical):
        print("SELF-TEST FAIL: bad analysis accepted", file=sys.stderr)
        return 1

    heldout = E2E_SUITES["heldout"]
    heldout_report = {
        "fixtures": {
            "heldout_generalization_clean": 63,
            "total": 63,
        },
        "scorer": {"mode": "persistent"},
        "real_model_benchmarked": False,
        "deterministic": {
            "aggregate": {"total_cases": 63, "exact_matches": 63}
        },
        "slm": {
            "aggregate": {
                "total_cases": 63,
                "fallbacks": 0,
                "latency_us": {"p95": 100},
                "candidate_validation": {
                    "exercised": True,
                    "cases_with_candidates": 63,
                    "non_candidate_violations": 0,
                },
            }
        },
    }
    heldout_suite_errors = validate_suite_report(heldout_report, heldout)
    if heldout_suite_errors:
        print(
            "SELF-TEST FAIL: valid heldout suite rejected: "
            f"{heldout_suite_errors}",
            file=sys.stderr,
        )
        return 1

    heldout_analysis = {
        "aggregate": {
            "total_cases": 63,
            "cases_with_candidates": 63,
            "ranker_in_candidates": 63,
            "fallbacks": 0,
            "changed_cases": 0,
            "non_baseline_evidence_cases": 0,
            "feature_coverage_cases": {"candidate": 1, "transition": 1},
        }
    }
    heldout_analysis_errors = validate_analysis_report(heldout_analysis, heldout)
    if heldout_analysis_errors:
        print(
            "SELF-TEST FAIL: valid heldout analysis rejected: "
            f"{heldout_analysis_errors}",
            file=sys.stderr,
        )
        return 1

    print("SELF-TEST PASSED: candidate ranker E2E validator", file=sys.stderr)
    return 0


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Validate candidate-ranker E2E benchmark contract."
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Candidate ranker model used for the E2E run",
    )
    parser.add_argument(
        "--schema-model",
        action="append",
        default=list(DEFAULT_SCHEMA_MODELS),
        help="Candidate ranker model JSON to schema-check. Can be repeated.",
    )
    parser.add_argument("--work-dir", help="Temporary benchmark work directory")
    parser.add_argument("--suite-report", help="Generated suite report path")
    parser.add_argument("--analysis-report", help="Generated analysis report path")
    parser.add_argument("--timeout-ms", type=int, default=500)
    parser.add_argument(
        "--heldout",
        action="store_true",
        help="Run the E2E contract on heldout_generalization_clean instead of "
             "the canonical 234-case suite",
    )
    parser.add_argument("--self-test", action="store_true")
    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()
    if args.self_test:
        sys.exit(run_self_test())

    errors = run_e2e(args)
    if errors:
        for error in errors:
            print(f"VALIDATION FAIL: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
