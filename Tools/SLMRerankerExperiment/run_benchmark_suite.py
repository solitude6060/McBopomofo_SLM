#!/usr/bin/env python3
"""Benchmark suite runner - orchestrates C++ evaluator + SLM experiment runner.

Iterates over all three canonical fixtures (taiwan_ambiguous, english_mixed,
taiwan_specific), runs baseline / deterministic / SLM-reranker evaluation,
and produces a comprehensive content-free JSON report with gate evaluation.

Usage:
    # Self-test
    python3 run_benchmark_suite.py --self-test

    # Dry-run smoke (no real model, uses local_llm_scorer.py --dry-run-baseline)
    python3 run_benchmark_suite.py \\
        --dry-run-local-wrapper \\
        --work-dir /tmp/slm_suite_smoke \\
        --output /tmp/slm_suite_smoke_report.json

    # Include the in-tree bigram scorer as an opt-in comparison lane
    python3 run_benchmark_suite.py \\
        --dry-run-local-wrapper \\
        --run-bigram \\
        --bigram-model Models/bigram_model.bin \\
        --work-dir /tmp/slm_suite_smoke \\
        --output /tmp/slm_suite_smoke_report.json

    # Persistent real model
    python3 run_benchmark_suite.py \\
        --persistent-scorer-command "python3 your_scorer.py --persistent" \\
        --model-manifest manifest.json \\
        --work-dir /tmp/slm_bench \\
        --output /tmp/slm_report.json

    # Per-case subprocess mode
    python3 run_benchmark_suite.py \\
        --scorer-command "python3 your_scorer.py" \\
        --work-dir /tmp/slm_bench \\
        --output /tmp/slm_report.json
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import math


# ---------------------------------------------------------------------------
# Paths resolved from script location
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", ".."))

EVALUATOR_BIN = os.path.join(
    PROJECT_ROOT, "Tools", "ContextualEvaluation", "build", "evaluator"
)
DATA_TXT = os.path.join(PROJECT_ROOT, "Source", "Data", "data.txt")
DEFAULT_BIGRAM_MODEL = os.path.join(PROJECT_ROOT, "Models", "bigram_model.bin")
FIXTURES_DIR = os.path.join(
    PROJECT_ROOT, "Tests", "fixtures", "contextual_bopomofo"
)
EXPERIMENT_RUNNER = os.path.join(
    SCRIPT_DIR, "run_experiment.py"
)
LOCAL_LLM_SCORER = os.path.join(
    SCRIPT_DIR, "local_llm_scorer.py"
)
SMOKE_REPORT_PATH = os.path.join(
    PROJECT_ROOT,
    "docs", "reports", "experiments", "phase2",
    "slm_benchmark_suite_smoke.json",
)
REGISTRY_PATH = os.path.join(
    PROJECT_ROOT, "docs", "reports", "experiments", "registry.json"
)

HYGIENE_SCRIPT = os.path.join(
    PROJECT_ROOT, "Tools", "ContextualEvaluation", "fixture_hygiene_audit.py"
)


FIXTURE_NAME_MAP = {
    "taiwan_ambiguous": "taiwan_ambiguous.jsonl",
    "english_mixed": "english_mixed.jsonl",
    "taiwan_specific": "taiwan_specific.jsonl",
    "heldout_generalization": "heldout_generalization.jsonl",
}

# Fixtures resolved at runtime via subprocess (no static file).
# Each entry maps runner-facing fixture name to parameters for the resolver.
DYNAMIC_FIXTURES = {
    "heldout_generalization_clean": {
        "source_fixture": "heldout_generalization",
    },
}


# ---------------------------------------------------------------------------
# Evaluator output parsing
# ---------------------------------------------------------------------------

def parse_evaluator_output(stdout_text):
    """Split evaluator stdout into (per_case, summary).

    The evaluator writes one JSON line per case then a final summary JSON with
    keys including 'engine', 'total_cases', 'exact_sentence_accuracy',
    'exact_match_count', 'latency_microseconds_p50/p95/p99'.

    Returns (list[dict], dict | None).
    """
    per_case = []
    summary = None
    for line in stdout_text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Skip non-JSON lines (e.g. FATAL, usage)
        if line.startswith("FATAL") or line.startswith("Usage"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        # Summary line: has both engine and total_cases
        if "total_cases" in obj and "exact_sentence_accuracy" in obj:
            summary = obj
        elif "id" in obj and "elapsed_us" in obj:
            per_case.append(obj)
    return per_case, summary


def run_evaluator(fixture_path, scorer=None, model_path=None,
                  slm_request_output=None,
                  candidate_limit=16, slm_candidate_granularity="node",
                  timeout=120):
    """Run the C++ evaluator subprocess.

    Returns (per_case, summary) on success.
    Raises RuntimeError on failure.
    """
    cmd = [EVALUATOR_BIN, DATA_TXT]
    if scorer:
        cmd.extend(["--scorer", scorer])
    if model_path:
        cmd.extend(["--model", model_path])
    if slm_request_output:
        cmd.extend([
            "--slm-request-output", slm_request_output,
            "--slm-candidate-limit", str(candidate_limit),
            "--slm-candidate-granularity", slm_candidate_granularity,
        ])
    cmd.append(fixture_path)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        raise RuntimeError(f"Evaluator binary not found: {EVALUATOR_BIN}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Evaluator timed out after {timeout}s on {fixture_path}")
    except OSError as exc:
        raise RuntimeError(f"Evaluator subprocess error: {exc}")

    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else "(no stderr)"
        raise RuntimeError(
            f"Evaluator exited {result.returncode} on {fixture_path}: {stderr}"
        )

    per_case, summary = parse_evaluator_output(result.stdout)
    if summary is None:
        raise RuntimeError(
            f"No evaluator summary found in output for {fixture_path}"
        )
    return per_case, summary


# ---------------------------------------------------------------------------
# Latency percentile helpers
# ---------------------------------------------------------------------------

def compute_percentiles(values):
    """Compute p50, p95, p99 from a list of ints. Returns dict."""
    if not values:
        return {"p50": 0, "p95": 0, "p99": 0}
    sorted_v = sorted(values)
    n = len(sorted_v)

    def perc(p):
        idx = max(0, min(n - 1, int(math.ceil(p / 100.0 * n) - 1)))
        return sorted_v[idx]

    return {"p50": perc(50), "p95": perc(95), "p99": perc(99)}


# ---------------------------------------------------------------------------
# Fixture resolution
# ---------------------------------------------------------------------------

def _parse_export_clean_stdout(stdout_text, source_fixture):
    try:
        data = json.loads(stdout_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Failed to parse export-clean output: {e}"
        )
    if not isinstance(data, dict):
        raise RuntimeError(
            "export-clean output is not a JSON object"
        )
    exports = data.get("clean_exports")
    if not isinstance(exports, list):
        raise RuntimeError(
            "export-clean output missing 'clean_exports' list"
        )
    for entry in exports:
        if entry.get("fixture") == source_fixture:
            path = entry.get("path")
            if not isinstance(path, str) or not path:
                raise RuntimeError(
                    f"clean_exports entry for {source_fixture!r} "
                    "missing or empty 'path'"
                )
            clean = entry.get("clean")
            if not isinstance(clean, int) or clean <= 0:
                raise RuntimeError(
                    f"clean_exports entry for {source_fixture!r} "
                    "has non-positive 'clean' count"
                )
            return entry
    raise RuntimeError(
        "clean_exports has no entry for "
        f"fixture {source_fixture!r}"
    )


def _resolve_dynamic_fixture(name):
    params = DYNAMIC_FIXTURES.get(name)
    if params is None:
        raise RuntimeError(f"Unknown dynamic fixture: {name!r}")
    if not os.path.isfile(HYGIENE_SCRIPT):
        raise RuntimeError(
            f"Hygiene audit script not found: {HYGIENE_SCRIPT}"
        )
    source = params["source_fixture"]
    cmd = [sys.executable, HYGIENE_SCRIPT, "--export-clean", source]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"Hygiene audit subprocess timed out for {name!r}"
        )
    except OSError as exc:
        raise RuntimeError(
            f"Hygiene audit subprocess error: {exc}"
        )
    if result.returncode != 0:
        stderr = result.stderr.strip() or "(no stderr)"
        raise RuntimeError(
            f"Hygiene audit exited {result.returncode} for "
            f"{name!r}: {stderr}"
        )
    clean_export = _parse_export_clean_stdout(result.stdout, source)
    clean_path = clean_export["path"]
    if not os.path.isfile(clean_path):
        raise RuntimeError(
            f"Clean export file not found: {clean_path}"
        )
    with open(clean_path, "r", encoding="utf-8") as handle:
        line_count = sum(1 for line in handle if line.strip())
    if line_count <= 0:
        raise RuntimeError(f"Clean export file is empty: {clean_path}")
    if line_count != clean_export["clean"]:
        raise RuntimeError(
            f"Clean export count mismatch for {name!r}: "
            f"metadata={clean_export['clean']} file_lines={line_count}"
        )
    return clean_path


def resolve_fixtures(fixture_names):
    """Resolve fixture names to absolute paths. Raises on missing."""
    paths = []
    for name in fixture_names:
        if name in DYNAMIC_FIXTURES:
            path = _resolve_dynamic_fixture(name)
            paths.append(path)
            continue
        filename = FIXTURE_NAME_MAP.get(name)
        if filename is None:
            raise RuntimeError(f"Unknown fixture name: {name!r}")
        path = os.path.join(FIXTURES_DIR, filename)
        if not os.path.isfile(path):
            raise RuntimeError(f"Fixture file not found: {path}")
        paths.append(path)
    return paths


def fixture_name_from_path(path):
    """Return short name (e.g. 'taiwan_ambiguous') from an absolute path."""
    basename = os.path.basename(path)
    for name, filename in FIXTURE_NAME_MAP.items():
        if filename == basename:
            return name
    stem = basename.replace(".jsonl", "")
    if stem.startswith("slm_"):
        candidate = stem[len("slm_"):]
        if candidate in FIXTURE_NAME_MAP:
            return candidate
    return stem


def read_per_case_latencies(path):
    latencies = []
    if not os.path.isfile(path):
        return latencies
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            latency = row.get("latency_us")
            if isinstance(latency, int):
                latencies.append(latency)
    return latencies


# ---------------------------------------------------------------------------
# SLM experiment runner integration
# ---------------------------------------------------------------------------

def run_slm_experiment(request_path, mode, command_str, timeout_ms,
                       output_path, work_dir):
    """Run run_experiment.py over a single exported SLM request file.

    *mode* is one of 'persistent', 'per-case', 'dry-run-local-wrapper'.
    *command_str* is the full command string for per-case/persistent modes.
    *timeout_ms* per-case timeout.
    *output_path* where summary JSON will be written.
    *work_dir* for per-case output.

    Returns the summary dict parsed from output_path.
    """
    cmd = [sys.executable, EXPERIMENT_RUNNER, "--output", output_path]

    if mode == "persistent":
        cmd.extend(["--persistent-scorer-command", command_str])
    elif mode == "per-case":
        cmd.extend(["--scorer-command", command_str])
    elif mode == "dry-run-local-wrapper":
        scorer_cmd = (
            f"{sys.executable} {LOCAL_LLM_SCORER} --dry-run-baseline --persistent"
        )
        cmd.extend(["--persistent-scorer-command", scorer_cmd])
    else:
        raise ValueError(f"Unknown SLM mode: {mode}")

    cmd.extend(["--timeout-ms", str(timeout_ms)])
    cmd.extend(["--fixtures", request_path])

    # Always write per-case output into work-dir (sanitized, content-free)
    fixture_name = fixture_name_from_path(request_path)
    per_case_path = os.path.join(work_dir, f"slm_per_case_{fixture_name}.jsonl")
    cmd.extend(["--per-case-output", per_case_path])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("SLM experiment runner timed out")
    except OSError as exc:
        raise RuntimeError(f"SLM experiment subprocess error: {exc}")

    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else "(no stderr)"
        raise RuntimeError(
            f"SLM experiment runner exited {result.returncode}: {stderr}"
        )

    if not os.path.isfile(output_path):
        raise RuntimeError(
            f"SLM experiment runner did not produce output at {output_path}"
        )

    with open(output_path, "r", encoding="utf-8") as f:
        summary = json.load(f)

    summary["_per_case_latencies"] = read_per_case_latencies(per_case_path)
    return summary


# ---------------------------------------------------------------------------
# Relative error reduction
# ---------------------------------------------------------------------------

def relative_error_reduction_pct(reference_errors, candidate_errors):
    """Compute relative error reduction in percent.

    If reference_errors == 0:
      - If candidate_errors == 0: return 100.0 (both perfect = 100% reduction)
      - Else: return 0.0 (no improvement from perfect)
    Otherwise:
      - (ref - cand) / ref * 100
    """
    if reference_errors == 0:
        if candidate_errors == 0:
            return 100.0
        return 0.0
    return round(
        (reference_errors - candidate_errors) / reference_errors * 100, 4
    )


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def _extract_eval_metrics(per_case, summary):
    """Extract metrics dict from evaluator per_case and summary."""
    total_cases = summary["total_cases"]
    exact_matches = summary["exact_match_count"]
    errors = total_cases - exact_matches
    latencies = [c["elapsed_us"] for c in per_case]
    return {
        "exact_accuracy": summary["exact_sentence_accuracy"],
        "exact_matches": exact_matches,
        "errors": errors,
        "latency_us": compute_percentiles(latencies),
    }


def _aggregate_eval_fixtures(eval_fixtures, latencies, total_cases):
    """Aggregate evaluator-style per-fixture metrics."""
    exact = sum(m["exact_matches"] for m in eval_fixtures)
    errors = sum(m["errors"] for m in eval_fixtures)
    return {
        "total_cases": total_cases,
        "exact_accuracy": round(exact / total_cases * 100, 4)
        if total_cases > 0 else 0.0,
        "exact_matches": exact,
        "errors": errors,
        "latency_us": compute_percentiles(latencies),
    }


def _extract_slm_metrics(slm_summary, total_cases):
    """Extract metrics dict from run_experiment.py summary."""
    exact_matches = slm_summary.get("exact_match_count", 0)
    errors = total_cases - exact_matches
    return {
        "exact_accuracy": slm_summary.get("exact_sentence_accuracy_pct", 0.0),
        "exact_matches": exact_matches,
        "errors": errors,
        "fallbacks": slm_summary.get("fallbacks", 0),
        "latency_us": slm_summary.get("latency_us", {"p50": 0, "p95": 0, "p99": 0}),
        "candidate_validation": slm_summary.get("candidate_validation", {}),
        "fallback_breakdown": slm_summary.get("fallback_breakdown", {}),
        "_latencies": slm_summary.get("_per_case_latencies", []),
    }


def _aggregate_slm_metrics(slm_fixtures, latencies):
    """Aggregate per-fixture SLM metrics into a single aggregate dict."""
    total = sum(m["total_cases"] for m in slm_fixtures)
    exact = sum(m["exact_matches"] for m in slm_fixtures)
    errors = sum(m["errors"] for m in slm_fixtures)
    fallbacks = sum(m["fallbacks"] for m in slm_fixtures)

    result = {
        "total_cases": total,
        "exact_accuracy": round(exact / total * 100, 4) if total > 0 else 0.0,
        "exact_matches": exact,
        "errors": errors,
        "fallbacks": fallbacks,
        "latency_us": compute_percentiles(latencies),
    }

    # Candidate validation: use the most-exercised fixture's cv
    best_cv = {"protocol_available": False, "exercised": False,
               "cases_with_candidates": 0, "non_candidate_violations": 0}
    for m in slm_fixtures:
        cv = m.get("candidate_validation", {})
        if cv.get("exercised"):
            best_cv["exercised"] = True
            best_cv["protocol_available"] = True
        best_cv["cases_with_candidates"] = (
            best_cv.get("cases_with_candidates", 0)
            + cv.get("cases_with_candidates", 0))
        best_cv["non_candidate_violations"] = (
            best_cv.get("non_candidate_violations", 0)
            + cv.get("non_candidate_violations", 0))
    result["candidate_validation"] = best_cv

    # Merge fallback breakdown
    merged = {}
    for m in slm_fixtures:
        for reason, count in m.get("fallback_breakdown", {}).items():
            merged[reason] = merged.get(reason, 0) + count
    result["fallback_breakdown"] = merged

    return result


def build_report(baseline_data, deterministic_data, slm_data,
                 fixture_names, fixture_paths, scorer_mode,
                 model_manifest, real_model_benchmarked,
                 gate_thresholds, slm_candidate_granularity,
                 bigram_data=None, bigram_model_path=None):
    """Assemble the comprehensive suite report dict.

    *slm_data* is a list of [{"name": ..., "summary": ...}, ...] per fixture.
    """
    # -- Fixture counts --
    fixture_counts = {}
    total_cases_all = 0
    for i, name in enumerate(fixture_names):
        cases = baseline_data[i]["summary"]["total_cases"]
        fixture_counts[name] = cases
        total_cases_all += cases

    # -- Build per-fixture + aggregate metrics --
    base_fixtures = []
    det_fixtures = []
    bigram_fixtures = []
    slm_fixtures = []
    base_all_lat = []
    det_all_lat = []
    bigram_all_lat = []
    slm_all_lat = []

    for i, name in enumerate(fixture_names):
        tc = baseline_data[i]["summary"]["total_cases"]

        bl = [c["elapsed_us"] for c in baseline_data[i]["per_case"]]
        bm = _extract_eval_metrics(baseline_data[i]["per_case"],
                                    baseline_data[i]["summary"])
        bm["total_cases"] = tc
        base_all_lat.extend(bl)
        base_fixtures.append({"fixture": name, **bm})

        dl = [c["elapsed_us"] for c in deterministic_data[i]["per_case"]]
        dm = _extract_eval_metrics(deterministic_data[i]["per_case"],
                                    deterministic_data[i]["summary"])
        dm["total_cases"] = tc
        det_all_lat.extend(dl)
        det_fixtures.append({"fixture": name, **dm})

        if bigram_data:
            gl = [c["elapsed_us"] for c in bigram_data[i]["per_case"]]
            gm = _extract_eval_metrics(bigram_data[i]["per_case"],
                                       bigram_data[i]["summary"])
            gm["total_cases"] = tc
            bigram_all_lat.extend(gl)
            bigram_fixtures.append({"fixture": name, **gm})

        sm = _extract_slm_metrics(slm_data[i]["summary"], tc)
        sm["total_cases"] = tc
        slm_all_lat.extend(sm.pop("_latencies", []))
        slm_fixtures.append({"fixture": name, **sm})

    # Aggregate baseline
    base_agg = _aggregate_eval_fixtures(
        base_fixtures, base_all_lat, total_cases_all
    )

    # Aggregate deterministic
    det_agg = _aggregate_eval_fixtures(
        det_fixtures, det_all_lat, total_cases_all
    )

    # Aggregate optional bigram scorer
    bigram_agg = None
    if bigram_data:
        bigram_agg = _aggregate_eval_fixtures(
            bigram_fixtures, bigram_all_lat, total_cases_all
        )

    # Aggregate SLM
    slm_agg = _aggregate_slm_metrics(slm_fixtures, slm_all_lat)

    # -- Relative error reduction --
    rer_slm_vs_baseline = {}
    rer_slm_vs_deterministic = {}
    rer_bigram_vs_baseline = {}
    rer_bigram_vs_deterministic = {}

    for sf in slm_fixtures:
        name = sf["fixture"]
        bf = next(f for f in base_fixtures if f["fixture"] == name)
        df = next(f for f in det_fixtures if f["fixture"] == name)
        rer_slm_vs_baseline[name] = relative_error_reduction_pct(
            bf["errors"], sf["errors"]
        )
        rer_slm_vs_deterministic[name] = relative_error_reduction_pct(
            df["errors"], sf["errors"]
        )
        if bigram_data:
            gf = next(f for f in bigram_fixtures if f["fixture"] == name)
            rer_bigram_vs_baseline[name] = relative_error_reduction_pct(
                bf["errors"], gf["errors"]
            )
            rer_bigram_vs_deterministic[name] = relative_error_reduction_pct(
                df["errors"], gf["errors"]
            )

    agg_rer_vs_base = relative_error_reduction_pct(
        base_agg["errors"], slm_agg["errors"]
    )
    agg_rer_vs_det = relative_error_reduction_pct(
        det_agg["errors"], slm_agg["errors"]
    )

    rer_slm_vs_baseline["aggregate"] = agg_rer_vs_base
    rer_slm_vs_deterministic["aggregate"] = agg_rer_vs_det

    if bigram_data:
        rer_bigram_vs_baseline["aggregate"] = relative_error_reduction_pct(
            base_agg["errors"], bigram_agg["errors"]
        )
        rer_bigram_vs_deterministic["aggregate"] = relative_error_reduction_pct(
            det_agg["errors"], bigram_agg["errors"]
        )

    # -- Gate --
    gate_result, gate_reasons = _evaluate_gate(
        slm_agg, agg_rer_vs_det, gate_thresholds
    )

    # -- Scorer info --
    scorer_info = {
        "mode": scorer_mode,
        "real_model_benchmarked": real_model_benchmarked,
        "candidate_granularity": slm_candidate_granularity,
    }
    if model_manifest and real_model_benchmarked:
        # Include sanitized manifest fields only
        sanitized = {
            k: model_manifest[k]
            for k in ("model_name", "provider", "parameter_count",
                      "quantization", "license", "redistributable", "local_only")
            if k in model_manifest
        }
        scorer_info["model_manifest"] = sanitized
    else:
        scorer_info["model_manifest"] = None
    if bigram_data:
        scorer_info["bigram_model"] = _project_relpath(bigram_model_path)

    # -- Date/branch/commit --
    date_str = time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime())
    branch = _git_cmd("rev-parse", "--abbrev-ref", "HEAD")
    commit = _git_cmd("rev-parse", "HEAD")

    report = {
        "suite": "slm-benchmark-suite",
        "date": date_str,
        "branch": branch,
        "commit": commit,
        "fixtures": {**fixture_counts, "total": total_cases_all},
        "scorer": scorer_info,
        "baseline": {
            "per_fixture": base_fixtures,
            "aggregate": base_agg,
        },
        "deterministic": {
            "per_fixture": det_fixtures,
            "aggregate": det_agg,
        },
        "slm": {
            "per_fixture": slm_fixtures,
            "aggregate": slm_agg,
        },
        "relative_error_reduction_pct": {
            "slm_vs_baseline": rer_slm_vs_baseline,
            "slm_vs_deterministic": rer_slm_vs_deterministic,
        },
        "gate": {
            "result": gate_result,
            "reasons": gate_reasons,
        },
        "real_model_benchmarked": real_model_benchmarked,
    }

    if bigram_data:
        report["bigram"] = {
            "per_fixture": bigram_fixtures,
            "aggregate": bigram_agg,
        }
        report["relative_error_reduction_pct"]["bigram_vs_baseline"] = (
            rer_bigram_vs_baseline
        )
        report["relative_error_reduction_pct"]["bigram_vs_deterministic"] = (
            rer_bigram_vs_deterministic
        )

    return report


def _evaluate_gate(slm_agg, agg_rer_vs_det, thresholds):
    """Evaluate gate criteria.

    Returns (result: "PASS"|"FAIL", reasons: list[str]).
    PASS requires ALL of:
      1. candidate_validation.exercised == true
      2. total fallbacks <= thresholds.fallback_threshold
      3. aggregate slm p95 <= thresholds.slm_latency_target_us
      4. aggregate slm relative error reduction vs deterministic > 0
    """
    if thresholds.get("skip_gate"):
        return "SKIPPED", ["gate evaluation skipped by --no-gate"]

    reasons = []
    passed = True

    # Criterion 1: candidate validation exercised
    cv = slm_agg.get("candidate_validation", {})
    if cv.get("exercised"):
        pass
    else:
        passed = False
        has_cv = cv.get("cases_with_candidates", 0)
        reasons.append(
            f"candidate_validation not exercised (cases_with_candidates={has_cv})"
        )

    # Criterion 2: fallbacks <= threshold
    fallbacks = slm_agg.get("fallbacks", 0)
    threshold = thresholds["fallback_threshold"]
    if fallbacks <= threshold:
        pass
    else:
        passed = False
        reasons.append(
            f"fallbacks {fallbacks} > threshold {threshold}"
        )

    # Criterion 3: aggregate SLM p95 <= target
    slm_p95 = slm_agg.get("latency_us", {}).get("p95", 0)
    target = thresholds["slm_latency_target_us"]
    if slm_p95 <= target:
        pass
    else:
        passed = False
        reasons.append(
            f"SLM p95 latency {slm_p95}us > target {target}us"
        )

    # Criterion 4: aggregate SLM RER vs deterministic > 0
    if agg_rer_vs_det > 0:
        pass
    else:
        passed = False
        reasons.append(
            f"SLM vs deterministic relative error reduction={agg_rer_vs_det}% "
            "(need > 0%)"
        )

    result = "PASS" if passed else "FAIL"
    return result, reasons


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _git_cmd(*args):
    """Run a git command and return stdout (stripped), or empty string on error."""
    try:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True, text=True, timeout=10,
            cwd=PROJECT_ROOT,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ""


def _project_relpath(path):
    """Return a stable project-relative path when possible."""
    if not path:
        return None
    abs_path = os.path.abspath(path)
    try:
        rel = os.path.relpath(abs_path, PROJECT_ROOT)
    except ValueError:
        return abs_path
    if rel == "." or rel.startswith(".."):
        return abs_path
    return rel


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="SLM Reranker Benchmark Suite Runner"
    )

    parser.add_argument(
        "--work-dir",
        type=str,
        default=None,
        help="Directory for intermediate files (default: temp dir)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Report JSON output path (default: stdout)",
    )
    parser.add_argument(
        "--fixtures",
        nargs="+",
        default=["taiwan_ambiguous", "english_mixed", "taiwan_specific"],
        help="Fixture names (default: taiwan_ambiguous english_mixed "
             "taiwan_specific)",
    )
    parser.add_argument(
        "--candidate-limit",
        type=int,
        default=16,
        help="Max candidates per slot (default: 16)",
    )
    parser.add_argument(
        "--slm-candidate-granularity",
        choices=["node", "character"],
        default="node",
        help="Candidate slot export granularity (default: node)",
    )
    parser.add_argument(
        "--scorer-command",
        type=str,
        default=None,
        help="External scorer command (per-case subprocess mode)",
    )
    parser.add_argument(
        "--persistent-scorer-command",
        type=str,
        default=None,
        help="Persistent scorer command",
    )
    parser.add_argument(
        "--dry-run-local-wrapper",
        action="store_true",
        help="Use local_llm_scorer.py --dry-run-baseline --persistent",
    )
    parser.add_argument(
        "--run-bigram",
        action="store_true",
        help="Also run the in-process BigramContextualScorer comparison lane",
    )
    parser.add_argument(
        "--bigram-model",
        type=str,
        default=DEFAULT_BIGRAM_MODEL,
        help="BIGR model path for --run-bigram (default: Models/bigram_model.bin)",
    )
    parser.add_argument(
        "--model-manifest",
        type=str,
        default=None,
        help="Model manifest path (for report metadata)",
    )
    parser.add_argument(
        "--fallback-threshold",
        type=int,
        default=0,
        help="Max allowed fallbacks for gate (default: 0)",
    )
    parser.add_argument(
        "--slm-latency-target-us",
        type=int,
        default=20000,
        help="SLM p95 latency target in microseconds (default: 20000)",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30000,
        help="Per-case timeout for SLM scorer in ms (default: 30000)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run self-tests and exit",
    )
    parser.add_argument(
        "--no-gate",
        action="store_true",
        help="Skip gate evaluation",
    )
    return parser


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _gen_mock_evaluator_output(per_case_lines, summary_line):
    """Build a mock evaluator stdout string from per-case dicts and summary."""
    lines = []
    for case in per_case_lines:
        lines.append(json.dumps(case, ensure_ascii=False))
    if summary_line:
        lines.append(json.dumps(summary_line, ensure_ascii=False))
    return "\n".join(lines)


def run_self_test():
    """Run self-tests for evaluator parsing, aggregation, and gate logic.

    Returns 0 on success, 1 on failure.
    """
    errors = []

    # -- 1. parse_evaluator_output: basic split --
    per_case_data = [
        {"id": "t1", "elapsed_us": 100, "exact_match": True},
        {"id": "t2", "elapsed_us": 200, "exact_match": False},
    ]
    summary_data = {
        "engine": "baseline-mcbopomofo",
        "total_cases": 2,
        "exact_sentence_accuracy": 50.0,
        "exact_match_count": 1,
        "latency_microseconds_p50": 100,
        "latency_microseconds_p95": 200,
        "latency_microseconds_p99": 200,
    }
    stdout_text = _gen_mock_evaluator_output(per_case_data, summary_data)
    parsed_cases, parsed_summary = parse_evaluator_output(stdout_text)
    if len(parsed_cases) != 2:
        errors.append(f"parse: expected 2 per-case, got {len(parsed_cases)}")
    if parsed_summary is None:
        errors.append("parse: expected summary, got None")
    elif parsed_summary.get("total_cases") != 2:
        errors.append("parse: expected total_cases=2")
    elif parsed_summary.get("exact_sentence_accuracy") != 50.0:
        errors.append("parse: expected accuracy=50.0")

    # -- 2. parse_evaluator_output: handles non-JSON lines --
    messy = (
        "FATAL: some error\n"
        + stdout_text
        + "\nUsage: evaluator <data.txt> [options] [test_cases.jsonl]\n"
    )
    parsed_cases2, parsed_summary2 = parse_evaluator_output(messy)
    if len(parsed_cases2) != 2:
        errors.append(f"parse messy: expected 2 per-case, got {len(parsed_cases2)}")
    if parsed_summary2 is None:
        errors.append("parse messy: expected summary")

    # -- 3. parse_evaluator_output: empty output --
    ec, es = parse_evaluator_output("")
    if ec != []:
        errors.append("parse empty: expected empty list")
    if es is not None:
        errors.append("parse empty: expected None summary")

    # -- 4. parse_evaluator_output: multiple summaries (use last) --
    multi_sum = (
        json.dumps(per_case_data[0]) + "\n"
        + json.dumps({"engine": "first", "total_cases": 1,
                       "exact_sentence_accuracy": 100.0, "exact_match_count": 1,
                       "latency_microseconds_p50": 0, "latency_microseconds_p95": 0,
                       "latency_microseconds_p99": 0}) + "\n"
        + json.dumps({"engine": "second", "total_cases": 2,
                       "exact_sentence_accuracy": 50.0, "exact_match_count": 1,
                       "latency_microseconds_p50": 100,
                       "latency_microseconds_p95": 200,
                       "latency_microseconds_p99": 200}) + "\n"
    )
    _, multi_summary = parse_evaluator_output(multi_sum)
    if multi_summary is None or multi_summary.get("engine") != "second":
        errors.append("parse multi-summary: expected 'second' as last summary")

    # -- 5. relative_error_reduction_pct edge cases --
    # Both perfect: 100.0
    rer = relative_error_reduction_pct(0, 0)
    if rer != 100.0:
        errors.append(f"rer both 0: expected 100.0, got {rer}")
    # Reference 0, candidate > 0: 0.0
    rer = relative_error_reduction_pct(0, 5)
    if rer != 0.0:
        errors.append(f"rer ref=0 cand>0: expected 0.0, got {rer}")
    # Normal case
    rer = relative_error_reduction_pct(100, 50)
    if rer != 50.0:
        errors.append(f"rer 100->50: expected 50.0, got {rer}")
    # Negative (worse)
    rer = relative_error_reduction_pct(50, 75)
    if rer != -50.0:
        errors.append(f"rer 50->75: expected -50.0, got {rer}")

    # -- 6. _evaluate_gate --
    thresholds = {"fallback_threshold": 0, "slm_latency_target_us": 20000}

    # Gate PASS case
    slm_agg_pass = {
        "fallbacks": 0,
        "candidate_validation": {"exercised": True, "cases_with_candidates": 10},
        "latency_us": {"p95": 500},
    }
    result, reasons = _evaluate_gate(slm_agg_pass, 10.0, thresholds)
    if result != "PASS":
        errors.append(f"gate PASS: expected PASS, got {result}: {reasons}")

    # Gate FAIL: candidate_validation not exercised
    slm_agg_fail1 = {
        "fallbacks": 0,
        "candidate_validation": {"exercised": False, "cases_with_candidates": 0},
        "latency_us": {"p95": 500},
    }
    result, reasons = _evaluate_gate(slm_agg_fail1, 10.0, thresholds)
    if result != "FAIL":
        errors.append("gate FAIL1: expected FAIL")
    if not any("candidate_validation" in r for r in reasons):
        errors.append("gate FAIL1: expected candidate_validation reason")

    # Gate FAIL: fallbacks > threshold
    slm_agg_fail2 = {
        "fallbacks": 3,
        "candidate_validation": {"exercised": True, "cases_with_candidates": 10},
        "latency_us": {"p95": 500},
    }
    result, reasons = _evaluate_gate(slm_agg_fail2, 10.0, thresholds)
    if result != "FAIL":
        errors.append("gate FAIL2: expected FAIL")
    if not any("fallback" in r for r in reasons):
        errors.append("gate FAIL2: expected fallback reason")

    # Gate FAIL: p95 > target
    slm_agg_fail3 = {
        "fallbacks": 0,
        "candidate_validation": {"exercised": True, "cases_with_candidates": 10},
        "latency_us": {"p95": 999999},
    }
    result, reasons = _evaluate_gate(slm_agg_fail3, 10.0, thresholds)
    if result != "FAIL":
        errors.append("gate FAIL3: expected FAIL")
    if not any("latency" in r for r in reasons):
        errors.append("gate FAIL3: expected latency reason")

    # Gate FAIL: RER <= 0
    slm_agg_fail4 = {
        "fallbacks": 0,
        "candidate_validation": {"exercised": True, "cases_with_candidates": 10},
        "latency_us": {"p95": 500},
    }
    result, reasons = _evaluate_gate(slm_agg_fail4, 0.0, thresholds)
    if result != "FAIL":
        errors.append("gate FAIL4: expected FAIL")
    if not any("reduction" in r for r in reasons):
        errors.append("gate FAIL4: expected RER reason")

    # Gate FAIL: RER < 0
    result, reasons = _evaluate_gate(slm_agg_fail4, -5.0, thresholds)
    if result != "FAIL":
        errors.append("gate FAIL5: expected FAIL")

    result, reasons = _evaluate_gate(slm_agg_fail4, -5.0,
                                     {**thresholds, "skip_gate": True})
    if result != "SKIPPED":
        errors.append(f"gate skip: expected SKIPPED, got {result}")

    # -- 7. compute_percentiles --
    p = compute_percentiles([100, 200, 300, 400, 500])
    if p["p50"] != 300:
        errors.append(f"percentile p50: expected 300, got {p['p50']}")
    if p["p95"] != 500:
        errors.append(f"percentile p95: expected 500, got {p['p95']}")
    if p["p99"] != 500:
        errors.append(f"percentile p99: expected 500, got {p['p99']}")

    p_empty = compute_percentiles([])
    if p_empty["p50"] != 0 or p_empty["p95"] != 0 or p_empty["p99"] != 0:
        errors.append("percentile empty: expected all 0")

    # -- 8. _extract_eval_metrics --
    summary = {"total_cases": 2, "exact_match_count": 1,
               "exact_sentence_accuracy": 50.0,
               "latency_microseconds_p50": 100,
               "latency_microseconds_p95": 200,
               "latency_microseconds_p99": 200}
    per_case = [{"id": "a", "elapsed_us": 100}, {"id": "b", "elapsed_us": 200}]
    metrics = _extract_eval_metrics(per_case, summary)
    if metrics["exact_accuracy"] != 50.0:
        errors.append("extract eval: accuracy mismatch")
    if metrics["exact_matches"] != 1:
        errors.append("extract eval: matches mismatch")
    if metrics["errors"] != 1:
        errors.append("extract eval: errors mismatch")
    if metrics["latency_us"]["p50"] != 100:
        errors.append("extract eval: latency p50 mismatch")

    # -- 9. build_report: optional bigram lane --
    baseline_sample = [{"per_case": per_case, "summary": summary}]
    deterministic_sample = [{
        "per_case": [{"id": "a", "elapsed_us": 110},
                     {"id": "b", "elapsed_us": 210}],
        "summary": {"total_cases": 2, "exact_match_count": 2,
                    "exact_sentence_accuracy": 100.0},
    }]
    bigram_sample = [{
        "per_case": [{"id": "a", "elapsed_us": 120},
                     {"id": "b", "elapsed_us": 240}],
        "summary": {"total_cases": 2, "exact_match_count": 1,
                    "exact_sentence_accuracy": 50.0},
    }]
    slm_sample = [{
        "name": "sample_fixture",
        "summary": {
            "exact_match_count": 1,
            "exact_sentence_accuracy_pct": 50.0,
            "fallbacks": 0,
            "latency_us": {"p50": 10, "p95": 20, "p99": 20},
            "candidate_validation": {
                "protocol_available": True,
                "exercised": True,
                "cases_with_candidates": 2,
                "non_candidate_violations": 0,
            },
            "_per_case_latencies": [10, 20],
        },
    }]
    report = build_report(
        baseline_sample, deterministic_sample, slm_sample,
        ["sample_fixture"], ["/tmp/sample_fixture.jsonl"],
        "dry-run-local-wrapper", None, False,
        {"fallback_threshold": 0, "slm_latency_target_us": 20000},
        "node", bigram_data=bigram_sample,
        bigram_model_path=DEFAULT_BIGRAM_MODEL,
    )
    if "bigram" not in report:
        errors.append("build report bigram: missing bigram section")
    elif report["bigram"]["aggregate"]["exact_matches"] != 1:
        errors.append("build report bigram: aggregate matches mismatch")
    rer_block = report.get("relative_error_reduction_pct", {})
    if "bigram_vs_baseline" not in rer_block:
        errors.append("build report bigram: missing bigram_vs_baseline RER")
    if "bigram_vs_deterministic" not in rer_block:
        errors.append(
            "build report bigram: missing bigram_vs_deterministic RER"
        )
    if report.get("scorer", {}).get("bigram_model") != "Models/bigram_model.bin":
        errors.append("build report bigram: expected project-relative model path")

    if fixture_name_from_path("/tmp/slm_taiwan_ambiguous.jsonl") != "taiwan_ambiguous":
        errors.append("fixture name: expected generated SLM request prefix stripped")

    # -- 10. fixture_name_from_path: dynamic fixture path --
    clean_path = "/tmp/heldout_generalization_clean.jsonl"
    if fixture_name_from_path(clean_path) != "heldout_generalization_clean":
        errors.append(
            "fixture name: expected 'heldout_generalization_clean' "
            f"got {fixture_name_from_path(clean_path)!r}"
        )

    # -- 11. _parse_export_clean_stdout: valid parse --
    valid_stdout = json.dumps({
        "audit": "fixture_hygiene_audit",
        "total_cases": 63,
        "clean_exports": [
            {
                "path": "/tmp/heldout_generalization_clean.jsonl",
                "fixture": "heldout_generalization",
                "total": 63,
                "clean": 57,
                "blocked": 6,
            },
        ],
    })
    try:
        parsed = _parse_export_clean_stdout(
            valid_stdout, "heldout_generalization"
        )
        if parsed.get("path") != "/tmp/heldout_generalization_clean.jsonl":
            errors.append(
                "parse export-clean valid: expected "
                "/tmp/heldout_generalization_clean.jsonl, "
                f"got {parsed!r}"
            )
    except RuntimeError as e:
        errors.append(f"parse export-clean valid: unexpected error: {e}")

    # -- 11. _parse_export_clean_stdout: malformed JSON --
    try:
        _parse_export_clean_stdout("not valid json", "heldout_generalization")
        errors.append("parse export-clean malformed: expected RuntimeError")
    except RuntimeError:
        pass

    # -- 12. _parse_export_clean_stdout: missing clean_exports --
    try:
        _parse_export_clean_stdout(
            json.dumps({"audit": "fixture_hygiene_audit"}),
            "heldout_generalization",
        )
        errors.append("parse export-clean no array: expected RuntimeError")
    except RuntimeError:
        pass

    # -- 13. _parse_export_clean_stdout: missing entry --
    wrong_fixture = json.dumps({
        "clean_exports": [
            {"fixture": "taiwan_ambiguous",
             "path": "/tmp/taiwan_ambiguous_clean.jsonl"},
        ],
    })
    try:
        _parse_export_clean_stdout(
            wrong_fixture, "heldout_generalization"
        )
        errors.append("parse export-clean wrong fixture: expected RuntimeError")
    except RuntimeError:
        pass

    # -- 14. _parse_export_clean_stdout: present but empty path --
    empty_path = json.dumps({
        "clean_exports": [
            {"fixture": "heldout_generalization",
             "path": ""},
        ],
    })
    try:
        _parse_export_clean_stdout(empty_path, "heldout_generalization")
        errors.append("parse export-clean empty path: expected RuntimeError")
    except RuntimeError:
        pass

    # -- 15. _parse_export_clean_stdout: zero clean count --
    zero_clean = json.dumps({
        "clean_exports": [
            {"fixture": "heldout_generalization",
             "path": "/tmp/heldout_generalization_clean.jsonl",
             "clean": 0},
        ],
    })
    try:
        _parse_export_clean_stdout(zero_clean, "heldout_generalization")
        errors.append("parse export-clean zero clean: expected RuntimeError")
    except RuntimeError:
        pass

    # -- 16. DYNAMIC_FIXTURES entry integrity --
    if "heldout_generalization_clean" not in DYNAMIC_FIXTURES:
        errors.append("DYNAMIC_FIXTURES missing heldout_generalization_clean")
    else:
        src = DYNAMIC_FIXTURES["heldout_generalization_clean"].get(
            "source_fixture"
        )
        if src != "heldout_generalization":
            errors.append(
                f"DYNAMIC_FIXTURES source_fixture: expected "
                f"'heldout_generalization', got {src!r}"
            )

    # -- Report --
    if errors:
        for e in errors:
            print(f"SELF-TEST FAIL: {e}", file=sys.stderr)
        return 1

    print(
        "SELF-TEST PASSED: evaluator parsing + RER + gate + "
        "percentile + metrics extraction + dynamic fixture",
        file=sys.stderr,
    )
    return 0


# ---------------------------------------------------------------------------
# Registry update
# ---------------------------------------------------------------------------

def register_experiment(report):
    """Append a registry entry for this suite run."""
    entry = {
        "id": "slm-benchmark-suite",
        "name": "SLM Reranker Benchmark Suite Runner",
        "status": "scaffold-verified" if not report.get("real_model_benchmarked")
                 else "benchmarked",
        "date": report.get("date", ""),
        "branch": report.get("branch", ""),
        "commit_suite": report.get("commit", ""),
        "protocol_version": "1.2",
        "model": None,
        "results_dir": "docs/reports/experiments/phase2/",
        "summary_file": "docs/reports/experiments/phase2/"
                        "slm_benchmark_suite_smoke.json",
        "description": (
            "Orchestrated benchmark suite runner that evaluates baseline, "
            "deterministic reranker, and SLM reranker across three canonical "
            "fixture sets. Produces aggregate metrics, relative error "
            "reduction, and gate evaluation."
        ),
        "fixtures_count": report.get("fixtures", {}).get("total", 0),
        "real_model_benchmarked": report.get("real_model_benchmarked", False),
        "gate_result": report.get("gate", {}).get("result", "N/A"),
        "verification": [
            "py_compile",
            "self-test passed",
            "dry-run-local-wrapper smoke",
        ],
        "next_steps": [
            "Benchmark a real 200M-0.5B model through the suite",
            "Gate: SLM must beat deterministic reranker before Phase 3",
        ],
    }

    # Read existing registry
    registry = {"registry_version": 1, "experiments": []}
    if os.path.isfile(REGISTRY_PATH):
        try:
            with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
                registry = json.load(f)
        except (json.JSONDecodeError, OSError):
            registry = {"registry_version": 1, "experiments": []}

    # Check if entry already exists; update if so
    existing = [e for e in registry.get("experiments", [])
                if e.get("id") == "slm-benchmark-suite"]
    if existing:
        registry["experiments"] = [
            entry if e.get("id") == "slm-benchmark-suite" else e
            for e in registry["experiments"]
        ]
    else:
        registry.setdefault("experiments", []).append(entry)

    # Write back
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)
        f.write("\n")

    return REGISTRY_PATH


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.self_test:
        sys.exit(run_self_test())

    # Validate scorer mode
    mode_count = sum([
        1 if args.scorer_command else 0,
        1 if args.persistent_scorer_command else 0,
        1 if args.dry_run_local_wrapper else 0,
    ])
    if mode_count == 0:
        print(
            "FATAL: one of --scorer-command, --persistent-scorer-command, "
            "or --dry-run-local-wrapper is required (unless --self-test)",
            file=sys.stderr,
        )
        sys.exit(1)
    if mode_count > 1:
        print(
            "FATAL: --scorer-command, --persistent-scorer-command, and "
            "--dry-run-local-wrapper are mutually exclusive",
            file=sys.stderr,
        )
        sys.exit(1)

    bigram_model_path = os.path.abspath(args.bigram_model)
    if args.run_bigram and not os.path.isfile(bigram_model_path):
        print(
            f"FATAL: --bigram-model not found: {bigram_model_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Determine mode
    if args.dry_run_local_wrapper:
        scorer_mode = "dry-run-local-wrapper"
        real_model_benchmarked = False
    elif args.persistent_scorer_command:
        scorer_mode = "persistent"
        real_model_benchmarked = _check_manifest(args.model_manifest)
    else:
        scorer_mode = "per-case"
        real_model_benchmarked = _check_manifest(args.model_manifest)

    # Load manifest if provided
    model_manifest = None
    if args.model_manifest:
        try:
            with open(args.model_manifest, "r", encoding="utf-8") as f:
                model_manifest = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"FATAL: cannot load model manifest: {exc}", file=sys.stderr)
            sys.exit(1)

    # Resolve fixtures
    fixture_paths = resolve_fixtures(args.fixtures)
    fixture_names = [fixture_name_from_path(p) for p in fixture_paths]

    print(
        f"Resolved {len(fixture_paths)} fixture(s): "
        f"{', '.join(fixture_names)}",
        file=sys.stderr,
    )

    # Work directory
    if args.work_dir:
        work_dir = args.work_dir
        os.makedirs(work_dir, exist_ok=True)
    else:
        work_dir = tempfile.mkdtemp(prefix="slm_benchmark_suite_")

    print(f"Work directory: {work_dir}", file=sys.stderr)

    # -- Phase 1: Baseline evaluation --
    print("Phase 1/4: Running baseline evaluation...", file=sys.stderr)
    baseline_data = []
    for fpath in fixture_paths:
        name = fixture_name_from_path(fpath)
        print(f"  Baseline: {name}...", file=sys.stderr)
        pc, summary = run_evaluator(fpath, scorer=None)
        baseline_data.append({"per_case": pc, "summary": summary})
        print(
            f"    accuracy={summary['exact_sentence_accuracy']}%, "
            f"matches={summary['exact_match_count']}/{summary['total_cases']}",
            file=sys.stderr,
        )

    # -- Phase 2: Deterministic evaluation --
    print("Phase 2/4: Running deterministic reranker evaluation...",
          file=sys.stderr)
    deterministic_data = []
    for fpath in fixture_paths:
        name = fixture_name_from_path(fpath)
        print(f"  Deterministic: {name}...", file=sys.stderr)
        pc, summary = run_evaluator(fpath, scorer="deterministic")
        deterministic_data.append({"per_case": pc, "summary": summary})
        print(
            f"    accuracy={summary['exact_sentence_accuracy']}%, "
            f"matches={summary['exact_match_count']}/{summary['total_cases']}",
            file=sys.stderr,
        )

    # -- Optional Phase 2.5: Bigram model evaluation --
    bigram_data = None
    if args.run_bigram:
        print("Phase 2.5/4: Running bigram reranker evaluation...",
              file=sys.stderr)
        bigram_data = []
        for fpath in fixture_paths:
            name = fixture_name_from_path(fpath)
            print(f"  Bigram: {name}...", file=sys.stderr)
            pc, summary = run_evaluator(
                fpath, scorer="bigram", model_path=bigram_model_path
            )
            bigram_data.append({"per_case": pc, "summary": summary})
            print(
                f"    accuracy={summary['exact_sentence_accuracy']}%, "
                f"matches={summary['exact_match_count']}/{summary['total_cases']}",
                file=sys.stderr,
            )

    # -- Phase 3: Export SLM request files --
    print("Phase 3/4: Exporting SLM candidate request files...",
          file=sys.stderr)
    slm_request_paths = []
    for fpath in fixture_paths:
        name = fixture_name_from_path(fpath)
        req_path = os.path.join(work_dir, f"slm_{name}.jsonl")
        print(f"  Export: {name} -> {req_path}", file=sys.stderr)
        # Run evaluator with --slm-request-output (discard stdout)
        run_evaluator(
            fpath,
            scorer="deterministic",
            slm_request_output=req_path,
            candidate_limit=args.candidate_limit,
            slm_candidate_granularity=args.slm_candidate_granularity,
        )
        if not os.path.isfile(req_path):
            raise RuntimeError(f"SLM request export failed: {req_path}")
        # Count lines
        with open(req_path, "r") as f:
            line_count = sum(1 for _ in f if _.strip())
        print(f"    {line_count} requests exported", file=sys.stderr)
        slm_request_paths.append(req_path)

    # -- Phase 4: SLM experiment (per fixture) --
    print("Phase 4/4: Running SLM experiment per fixture...", file=sys.stderr)

    if args.dry_run_local_wrapper:
        slm_mode = "dry-run-local-wrapper"
        command = None
    elif args.persistent_scorer_command:
        slm_mode = "persistent"
        command = args.persistent_scorer_command
    else:
        slm_mode = "per-case"
        command = args.scorer_command

    slm_data = []
    for req_path in slm_request_paths:
        name = fixture_name_from_path(req_path)
        slm_output_path = os.path.join(work_dir, f"slm_summary_{name}.json")
        print(f"  SLM: {name}...", file=sys.stderr)
        slm_summary = run_slm_experiment(
            req_path, slm_mode, command,
            args.timeout_ms, slm_output_path, work_dir,
        )
        slm_data.append({"name": name, "summary": slm_summary})
        print(
            f"    accuracy={slm_summary.get('exact_sentence_accuracy_pct', '?')}%, "
            f"fallbacks={slm_summary.get('fallbacks', '?')}",
            file=sys.stderr,
        )

    # -- Build report --
    gate_thresholds = {
        "fallback_threshold": args.fallback_threshold,
        "slm_latency_target_us": args.slm_latency_target_us,
        "skip_gate": args.no_gate,
    }

    report = build_report(
        baseline_data, deterministic_data, slm_data,
        fixture_names, fixture_paths, scorer_mode,
        model_manifest, real_model_benchmarked,
        gate_thresholds, args.slm_candidate_granularity,
        bigram_data=bigram_data,
        bigram_model_path=bigram_model_path if args.run_bigram else None,
    )

    # -- Output --
    report_json = json.dumps(report, ensure_ascii=False, indent=2)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report_json + "\n")
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(report_json)

    # -- Smoke report for dry-run --
    if args.dry_run_local_wrapper and not args.no_gate:
        os.makedirs(os.path.dirname(SMOKE_REPORT_PATH), exist_ok=True)
        # Add explicit note about no real model
        report["description"] = (
            "Dry-run smoke test using local_llm_scorer.py --dry-run-baseline. "
            "No real model was benchmarked. "
            "Candidate-exported requests exercise the candidate validation path. "
            "Gate is expected to FAIL because the dry-run baseline scorer does "
            "not improve over the deterministic reranker."
        )
        report["real_model_benchmarked"] = False
        report["scorer"]["real_model_benchmarked"] = False
        smoke_json = json.dumps(report, ensure_ascii=False, indent=2)
        with open(SMOKE_REPORT_PATH, "w", encoding="utf-8") as f:
            f.write(smoke_json + "\n")
        print(
            f"Smoke report written to {SMOKE_REPORT_PATH}",
            file=sys.stderr,
        )

    # -- Register in experiment registry --
    if not args.no_gate:
        try:
            registry_path = register_experiment(report)
            print(f"Registry updated: {registry_path}", file=sys.stderr)
        except OSError as exc:
            print(f"WARN: registry update failed: {exc}", file=sys.stderr)
    else:
        print("Registry not updated because --no-gate was used", file=sys.stderr)


def _check_manifest(manifest_path):
    """Check if a model manifest declares parameter_count in [200M, 500M]."""
    if not manifest_path:
        return False
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        pc = manifest.get("parameter_count", 0)
        return 200_000_000 <= pc <= 500_000_000
    except (OSError, json.JSONDecodeError):
        return False


if __name__ == "__main__":
    main()
