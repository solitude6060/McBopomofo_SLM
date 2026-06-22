#!/usr/bin/env python3
"""Validate content-free macOS dogfood evidence JSON."""

import argparse
import copy
import json
import os
import sys


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", ".."))
DEFAULT_TEMPLATE = os.path.join(
    PROJECT_ROOT,
    "docs",
    "reports",
    "experiments",
    "phase3",
    "dogfood_evidence_template.json",
)

REQUIRED_TOP_LEVEL = {
    "id",
    "name",
    "status",
    "date",
    "branch",
    "commit",
    "protocol_version",
    "privacy",
    "session",
    "mode_switching",
    "checklist",
    "metrics",
    "issues",
    "verification",
}

STATUS_VALUES = {"template", "session_complete", "session_aborted"}
MODE_VALUES = {"Off", "Deterministic"}
DURATION_BUCKETS = {"lt5min", "5_to_30min", "30_to_120min", "gt120min"}
CHECKLIST_FIELDS = {
    "toggle",
    "baseline_behavior",
    "long_composition",
    "candidate_ui",
    "english_mixed",
    "user_phrases",
    "phrase_replacement",
    "rapid_typing",
    "input_method_switching",
    "error_handling",
    "privacy_verified",
}
CHECKLIST_VALUES = {"pass", "fail", "not_run"}
SESSION_COMPLETE_CHECKLIST_VALUES = {"pass", "fail"}
METRIC_COUNTERS = {
    "fallback_count",
    "candidate_order_surprises",
    "crash_or_hang_count",
    "user_disabled_due_to_latency_count",
}
LATENCY_BUCKETS = {
    "lt2000",
    "2000_to_20000",
    "20000_to_100000",
    "gt100000",
}
ISSUE_CATEGORIES = {
    "latency",
    "candidate-order",
    "fallback",
    "crash",
    "privacy",
    "other",
}
ISSUE_SEVERITIES = {"low", "medium", "high", "blocker"}
PRIVACY_FALSE_KEYS = {
    "raw_text_recorded",
    "readings_recorded",
    "candidate_text_recorded",
    "committed_text_recorded",
    "screenshots_with_private_text",
    "user_phrase_files_recorded",
}
RAW_CONTENT_KEYS = {
    "baseline_output",
    "candidate_text",
    "candidates",
    "committed_text",
    "engine_output",
    "expected",
    "expected_output",
    "input",
    "output",
    "raw_text",
    "reading",
    "readings",
    "screenshot",
    "typed_text",
    "user_phrase_file",
    "user_phrase_files",
}
KNOWN_TOP_LEVEL = REQUIRED_TOP_LEVEL | {
    "runtime_counters_report_path",
    "notes",
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def walk_json(value, path="$"):
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk_json(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            yield from walk_json(child, f"{path}[{idx}]")


def require_dict(errors, report, key):
    value = report.get(key)
    if not isinstance(value, dict):
        errors.append(f".{key}: expected object")
        return {}
    return value


def require_non_empty_string(errors, section, key, path):
    value = section.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path}.{key}: expected non-empty string")
        return None
    return value


def validate_privacy(report, errors):
    privacy = require_dict(errors, report, "privacy")
    if privacy.get("content_free") is not True:
        errors.append(".privacy.content_free: expected true")
    for key in PRIVACY_FALSE_KEYS:
        if privacy.get(key) is not False:
            errors.append(f".privacy.{key}: expected false")


def validate_session(report, errors):
    session = require_dict(errors, report, "session")
    mode = session.get("mode_under_test")
    if mode not in MODE_VALUES:
        errors.append(f".session.mode_under_test: invalid value {mode!r}")
    require_non_empty_string(errors, session, "build_identifier", ".session")
    duration = session.get("session_duration_bucket")
    if duration not in DURATION_BUCKETS:
        errors.append(
            f".session.session_duration_bucket: invalid value {duration!r}"
        )
    for key in ("os_version_bucket", "hardware_class", "keyboard_layout"):
        require_non_empty_string(errors, session, key, ".session")


def validate_mode_switching(report, errors):
    mode_switching = require_dict(errors, report, "mode_switching")
    for key in ("off_to_deterministic", "deterministic_to_off"):
        if not isinstance(mode_switching.get(key), bool):
            errors.append(f".mode_switching.{key}: expected boolean")
    switches = mode_switching.get("required_switches")
    if not isinstance(switches, int) or switches < 0:
        errors.append(".mode_switching.required_switches: expected non-negative integer")


def validate_checklist(report, errors):
    checklist = require_dict(errors, report, "checklist")
    status = report.get("status")
    missing = sorted(CHECKLIST_FIELDS - set(checklist))
    for key in missing:
        errors.append(f".checklist.{key}: missing required checklist item")
    for key, value in checklist.items():
        if key not in CHECKLIST_FIELDS:
            errors.append(f".checklist.{key}: unknown checklist item")
            continue
        if value not in CHECKLIST_VALUES:
            errors.append(f".checklist.{key}: invalid value {value!r}")
        if status == "session_complete" and value not in SESSION_COMPLETE_CHECKLIST_VALUES:
            errors.append(
                f".checklist.{key}: session_complete requires pass or fail"
            )


def validate_non_negative_integer(errors, value, path):
    if not isinstance(value, int) or value < 0:
        errors.append(f"{path}: expected non-negative integer")


def validate_metrics(report, errors):
    metrics = require_dict(errors, report, "metrics")
    for key in METRIC_COUNTERS:
        validate_non_negative_integer(errors, metrics.get(key), f".metrics.{key}")
    buckets = metrics.get("latency_buckets_us")
    if not isinstance(buckets, dict):
        errors.append(".metrics.latency_buckets_us: expected object")
        return
    for key in LATENCY_BUCKETS:
        validate_non_negative_integer(
            errors, buckets.get(key), f".metrics.latency_buckets_us.{key}"
        )
    for key in buckets:
        if key not in LATENCY_BUCKETS:
            errors.append(f".metrics.latency_buckets_us.{key}: unknown bucket")


def validate_issues(report, errors):
    issues = report.get("issues")
    if not isinstance(issues, list):
        errors.append(".issues: expected array")
        return
    for idx, issue in enumerate(issues):
        path = f".issues[{idx}]"
        if not isinstance(issue, dict):
            errors.append(f"{path}: expected object")
            continue
        category = issue.get("category")
        if category not in ISSUE_CATEGORIES:
            errors.append(f"{path}.category: invalid value {category!r}")
        severity = issue.get("severity")
        if severity not in ISSUE_SEVERITIES:
            errors.append(f"{path}.severity: invalid value {severity!r}")
        require_non_empty_string(errors, issue, "summary", path)
        if "latency_bucket" in issue and issue["latency_bucket"] not in LATENCY_BUCKETS:
            errors.append(
                f"{path}.latency_bucket: invalid value {issue['latency_bucket']!r}"
            )


def validate_raw_content_keys(report, errors):
    for path, value in walk_json(report):
        if isinstance(value, dict):
            for key in value:
                if key.lower() in RAW_CONTENT_KEYS:
                    errors.append(f"{path}.{key}: raw content field is not allowed")


def validate_strict(report, errors):
    unknown = sorted(set(report) - KNOWN_TOP_LEVEL)
    for key in unknown:
        errors.append(f".{key}: unknown top-level field")


def validate_report(report, strict=False):
    errors = []
    if not isinstance(report, dict):
        return ["$: expected object"]
    for key in sorted(REQUIRED_TOP_LEVEL):
        if key not in report:
            errors.append(f".{key}: missing required field")
    status = report.get("status")
    if status not in STATUS_VALUES:
        errors.append(f".status: invalid value {status!r}")
    for key in ("id", "name", "date", "branch", "commit", "protocol_version"):
        require_non_empty_string(errors, report, key, "")
    validate_privacy(report, errors)
    validate_session(report, errors)
    validate_mode_switching(report, errors)
    validate_checklist(report, errors)
    validate_metrics(report, errors)
    validate_issues(report, errors)
    validate_raw_content_keys(report, errors)
    verification = report.get("verification")
    if not isinstance(verification, list) or not verification:
        errors.append(".verification: expected non-empty array")
    notes = report.get("notes", [])
    if notes is not None and not isinstance(notes, list):
        errors.append(".notes: expected array when present")
    if strict:
        validate_strict(report, errors)
    return errors


def run_self_test():
    good = load_json(DEFAULT_TEMPLATE)
    errors = validate_report(good)
    if errors:
        for error in errors:
            print(f"SELF-TEST FAIL: template invalid: {error}", file=sys.stderr)
        return 1

    cases = []
    missing_privacy = copy.deepcopy(good)
    del missing_privacy["privacy"]
    cases.append((missing_privacy, ".privacy"))

    privacy_false = copy.deepcopy(good)
    privacy_false["privacy"]["content_free"] = False
    cases.append((privacy_false, ".privacy.content_free"))

    raw_content = copy.deepcopy(good)
    raw_content["readings"] = ["private"]
    cases.append((raw_content, "raw content field"))

    bad_checklist = copy.deepcopy(good)
    bad_checklist["checklist"]["toggle"] = "maybe"
    cases.append((bad_checklist, ".checklist.toggle"))

    complete_not_run = copy.deepcopy(good)
    complete_not_run["status"] = "session_complete"
    cases.append((complete_not_run, "session_complete requires"))

    for report, expected in cases:
        errors = validate_report(report)
        if not any(expected in error for error in errors):
            print(
                "SELF-TEST FAIL: expected error containing "
                f"{expected!r}, got {errors}",
                file=sys.stderr,
            )
            return 1

    print("SELF-TEST PASSED: dogfood evidence validator", file=sys.stderr)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Validate content-free dogfood evidence JSON"
    )
    parser.add_argument("--dogfood", default=DEFAULT_TEMPLATE)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    try:
        report = load_json(args.dogfood)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"VALIDATION FAIL: {exc}", file=sys.stderr)
        return 1
    errors = validate_report(report, strict=args.strict)
    if errors:
        for error in errors:
            print(f"VALIDATION FAIL: {error}", file=sys.stderr)
        return 1
    print("VALIDATION PASSED: dogfood evidence", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
