#!/usr/bin/env python3
"""Generate content-free macOS dogfood evidence JSON."""

import argparse
import copy
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import validate_dogfood_evidence as validator


PROJECT_ROOT = Path(validator.PROJECT_ROOT)


def current_timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def git_value(args):
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=PROJECT_ROOT,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def default_branch():
    return git_value(["branch", "--show-current"]) or "slm-phase2-learnable"


def default_commit():
    return git_value(["rev-parse", "--short", "HEAD"]) or "TEMPLATE_COMMIT"


def prompt_text(label, default):
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def prompt_int(label, default):
    while True:
        value = prompt_text(label, str(default))
        try:
            parsed = int(value)
        except ValueError:
            print("Enter a non-negative integer.", file=sys.stderr)
            continue
        if parsed >= 0:
            return parsed
        print("Enter a non-negative integer.", file=sys.stderr)


def prompt_bool(label, default):
    default_text = "y" if default else "n"
    while True:
        value = prompt_text(f"{label} (y/n)", default_text).lower()
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Enter y or n.", file=sys.stderr)


def prompt_choice(label, choices, default):
    choices_text = "/".join(choices)
    while True:
        value = prompt_text(f"{label} ({choices_text})", default)
        if value in choices:
            return value
        print(f"Enter one of: {choices_text}", file=sys.stderr)


def clean_template():
    return copy.deepcopy(validator.load_json(validator.DEFAULT_TEMPLATE))


def checklist_default_for(status, requested_default):
    if requested_default:
        return requested_default
    if status == "session_complete":
        return "pass"
    return "not_run"


def apply_noninteractive(report, args):
    report["id"] = args.id
    report["name"] = args.name
    report["status"] = args.status
    report["date"] = args.date or current_timestamp()
    report["branch"] = args.branch or default_branch()
    report["commit"] = args.commit or default_commit()

    session = report["session"]
    session["mode_under_test"] = args.mode
    session["build_identifier"] = args.build_identifier
    session["session_duration_bucket"] = args.duration_bucket
    session["os_version_bucket"] = args.os_version_bucket
    session["hardware_class"] = args.hardware_class
    session["keyboard_layout"] = args.keyboard_layout

    mode_switching = report["mode_switching"]
    mode_switching["off_to_deterministic"] = args.off_to_deterministic
    mode_switching["deterministic_to_off"] = args.deterministic_to_off
    mode_switching["required_switches"] = args.required_switches

    checklist_value = checklist_default_for(args.status, args.checklist_default)
    for key in sorted(validator.CHECKLIST_FIELDS):
        report["checklist"][key] = checklist_value

    metrics = report["metrics"]
    metrics["fallback_count"] = args.fallback_count
    metrics["candidate_order_surprises"] = args.candidate_order_surprises
    metrics["crash_or_hang_count"] = args.crash_or_hang_count
    metrics[
        "user_disabled_due_to_latency_count"
    ] = args.user_disabled_due_to_latency_count
    metrics["latency_buckets_us"]["lt2000"] = args.latency_lt2000
    metrics["latency_buckets_us"]["2000_to_20000"] = args.latency_2000_to_20000
    metrics["latency_buckets_us"]["20000_to_100000"] = args.latency_20000_to_100000
    metrics["latency_buckets_us"]["gt100000"] = args.latency_gt100000

    report["runtime_counters_report_path"] = args.runtime_counters_report_path
    report["notes"] = [
        "generated content-free evidence; do not add typed text, readings, candidate strings, committed text, screenshots, or user phrase file contents"
    ]
    report["verification"] = [
        "python3 Tools/ContextualEvaluation/validate_dogfood_evidence.py --dogfood <generated-path>"
    ]
    return report


def apply_interactive(report, args):
    report["id"] = prompt_text("Evidence id", args.id)
    report["name"] = prompt_text("Evidence name", args.name)
    report["status"] = prompt_choice(
        "Session status",
        sorted(validator.STATUS_VALUES),
        args.status,
    )
    report["date"] = prompt_text("Date", args.date or current_timestamp())
    report["branch"] = prompt_text("Branch", args.branch or default_branch())
    report["commit"] = prompt_text("Commit", args.commit or default_commit())

    session = report["session"]
    session["mode_under_test"] = prompt_choice(
        "Mode under test",
        sorted(validator.MODE_VALUES),
        args.mode,
    )
    session["build_identifier"] = prompt_text(
        "Build identifier",
        args.build_identifier,
    )
    session["session_duration_bucket"] = prompt_choice(
        "Session duration bucket",
        sorted(validator.DURATION_BUCKETS),
        args.duration_bucket,
    )
    session["os_version_bucket"] = prompt_text(
        "OS version bucket",
        args.os_version_bucket,
    )
    session["hardware_class"] = prompt_text("Hardware class", args.hardware_class)
    session["keyboard_layout"] = prompt_text("Keyboard layout", args.keyboard_layout)

    mode_switching = report["mode_switching"]
    mode_switching["off_to_deterministic"] = prompt_bool(
        "Switched Off to Deterministic",
        args.off_to_deterministic,
    )
    mode_switching["deterministic_to_off"] = prompt_bool(
        "Switched Deterministic to Off",
        args.deterministic_to_off,
    )
    mode_switching["required_switches"] = prompt_int(
        "Required switch count",
        args.required_switches,
    )

    print("Checklist values are content-free: pass/fail/not_run.", file=sys.stderr)
    for key in sorted(validator.CHECKLIST_FIELDS):
        default = checklist_default_for(report["status"], args.checklist_default)
        report["checklist"][key] = prompt_choice(
            f"Checklist {key}",
            sorted(validator.CHECKLIST_VALUES),
            default,
        )

    metrics = report["metrics"]
    metrics["fallback_count"] = prompt_int("Fallback count", args.fallback_count)
    metrics["candidate_order_surprises"] = prompt_int(
        "Candidate-order surprise count",
        args.candidate_order_surprises,
    )
    metrics["crash_or_hang_count"] = prompt_int(
        "Crash or hang count",
        args.crash_or_hang_count,
    )
    metrics["user_disabled_due_to_latency_count"] = prompt_int(
        "User-disabled-due-to-latency count",
        args.user_disabled_due_to_latency_count,
    )
    buckets = metrics["latency_buckets_us"]
    buckets["lt2000"] = prompt_int("Latency bucket lt2000 us", args.latency_lt2000)
    buckets["2000_to_20000"] = prompt_int(
        "Latency bucket 2000_to_20000 us",
        args.latency_2000_to_20000,
    )
    buckets["20000_to_100000"] = prompt_int(
        "Latency bucket 20000_to_100000 us",
        args.latency_20000_to_100000,
    )
    buckets["gt100000"] = prompt_int(
        "Latency bucket gt100000 us",
        args.latency_gt100000,
    )

    report["runtime_counters_report_path"] = prompt_text(
        "Runtime counters report path",
        args.runtime_counters_report_path,
    )
    report["notes"] = [
        "generated content-free evidence; do not add typed text, readings, candidate strings, committed text, screenshots, or user phrase file contents"
    ]
    report["verification"] = [
        "python3 Tools/ContextualEvaluation/validate_dogfood_evidence.py --dogfood <generated-path>"
    ]
    issue_count = prompt_int("Content-free issue count", 0)
    report["issues"] = []
    for index in range(issue_count):
        issue = {
            "category": prompt_choice(
                f"Issue {index + 1} category",
                sorted(validator.ISSUE_CATEGORIES),
                "other",
            ),
            "severity": prompt_choice(
                f"Issue {index + 1} severity",
                sorted(validator.ISSUE_SEVERITIES),
                "low",
            ),
            "summary": prompt_text(
                f"Issue {index + 1} content-free summary",
                "aggregate behavior summary only",
            ),
        }
        if prompt_bool(f"Issue {index + 1} has latency bucket", False):
            issue["latency_bucket"] = prompt_choice(
                f"Issue {index + 1} latency bucket",
                sorted(validator.LATENCY_BUCKETS),
                "lt2000",
            )
        report["issues"].append(issue)
    return report


def build_report(args):
    report = clean_template()
    if args.interactive:
        return apply_interactive(report, args)
    return apply_noninteractive(report, args)


def write_report(report, output):
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        return
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def require_valid(report):
    errors = validator.validate_report(report)
    if errors:
        for error in errors:
            print(f"GENERATION FAIL: {error}", file=sys.stderr)
        return False
    return True


def run_self_test():
    default_args = parse_args([])
    default_report = build_report(default_args)
    if not require_valid(default_report):
        return 1

    deterministic_args = parse_args(["--mode", "Deterministic"])
    deterministic_report = build_report(deterministic_args)
    if deterministic_report["session"]["mode_under_test"] != "Deterministic":
        print("SELF-TEST FAIL: deterministic mode not applied", file=sys.stderr)
        return 1
    if not require_valid(deterministic_report):
        return 1

    aborted_args = parse_args(["--status", "session_aborted"])
    aborted_report = build_report(aborted_args)
    if aborted_report["status"] != "session_aborted":
        print("SELF-TEST FAIL: session_aborted status not applied", file=sys.stderr)
        return 1
    if not require_valid(aborted_report):
        return 1

    complete_args = parse_args(["--status", "session_complete"])
    complete_report = build_report(complete_args)
    if any(value == "not_run" for value in complete_report["checklist"].values()):
        print("SELF-TEST FAIL: session_complete kept not_run", file=sys.stderr)
        return 1
    if not require_valid(complete_report):
        return 1

    invalid_report = copy.deepcopy(complete_report)
    invalid_report["checklist"]["toggle"] = "not_run"
    invalid_errors = validator.validate_report(invalid_report)
    if not any("session_complete requires" in error for error in invalid_errors):
        print(
            "SELF-TEST FAIL: expected session_complete checklist rejection",
            file=sys.stderr,
        )
        return 1

    print("SELF-TEST PASSED: dogfood evidence generator", file=sys.stderr)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        description="Generate validator-backed, content-free dogfood evidence JSON"
    )
    parser.add_argument("--output", help="Write JSON to this path; stdout if omitted")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--id", default="phase3-dogfood-generated")
    parser.add_argument("--name", default="Phase 3 macOS Dogfood Evidence")
    parser.add_argument("--status", choices=sorted(validator.STATUS_VALUES), default="template")
    parser.add_argument("--date")
    parser.add_argument("--branch")
    parser.add_argument("--commit")
    parser.add_argument("--mode", choices=sorted(validator.MODE_VALUES), default="Off")
    parser.add_argument("--build-identifier", default="TEMPLATE_BUILD_IDENTIFIER")
    parser.add_argument(
        "--duration-bucket",
        choices=sorted(validator.DURATION_BUCKETS),
        default="lt5min",
    )
    parser.add_argument("--os-version-bucket", default="macos-15-or-newer")
    parser.add_argument("--hardware-class", default="apple-silicon-or-intel")
    parser.add_argument("--keyboard-layout", default="bopomofo")
    parser.add_argument(
        "--checklist-default",
        choices=sorted(validator.CHECKLIST_VALUES),
        help="Default checklist value; session_complete defaults to pass, others to not_run",
    )
    parser.add_argument("--off-to-deterministic", action="store_true")
    parser.add_argument("--deterministic-to-off", action="store_true")
    parser.add_argument("--required-switches", type=int, default=0)
    parser.add_argument("--fallback-count", type=int, default=0)
    parser.add_argument("--candidate-order-surprises", type=int, default=0)
    parser.add_argument("--crash-or-hang-count", type=int, default=0)
    parser.add_argument("--user-disabled-due-to-latency-count", type=int, default=0)
    parser.add_argument("--latency-lt2000", type=int, default=0)
    parser.add_argument("--latency-2000-to-20000", type=int, default=0)
    parser.add_argument("--latency-20000-to-100000", type=int, default=0)
    parser.add_argument("--latency-gt100000", type=int, default=0)
    parser.add_argument("--runtime-counters-report-path", default="")
    return parser


def parse_args(argv=None):
    return build_parser().parse_args(argv)


def main():
    args = parse_args()
    if args.self_test:
        return run_self_test()
    if args.required_switches < 0:
        print("GENERATION FAIL: --required-switches must be non-negative", file=sys.stderr)
        return 1
    report = build_report(args)
    if not require_valid(report):
        return 1
    write_report(report, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
