#!/usr/bin/env python3
"""Validate uom_replay summary JSON against the adaptation_replay contract."""

import argparse
import json
import os
import subprocess
import sys


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", ".."))
DEFAULT_RUNNER = os.path.join(SCRIPT_DIR, "build", "uom_replay")
DEFAULT_DATA = os.path.join(PROJECT_ROOT, "Source", "Data", "data.txt")
DEFAULT_FIXTURE = os.path.join(
    PROJECT_ROOT,
    "Tests",
    "fixtures",
    "contextual_bopomofo",
    "adaptation_replay.jsonl",
)

REQUIRED_SUMMARY = (
    "total_rows",
    "same_key_rows",
    "same_key_hits",
    "transfer_rows",
    "transfer_hits",
    "harmful_overrides",
    "restart_hits",
)


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
        if isinstance(obj, dict) and "total_rows" in obj:
            summary = obj
    if summary is None:
        raise ValueError("no uom_replay summary JSON found")
    return summary


def validate_summary(summary, persist=False, oneshot=False):
    errors = []
    for key in REQUIRED_SUMMARY:
        if key not in summary:
            errors.append(f"missing {key}")
        elif not isinstance(summary[key], int):
            errors.append(f"{key} must be int")
    if errors:
        return errors
    if summary["total_rows"] < 1:
        errors.append("total_rows < 1")
    if summary["same_key_rows"] < 1:
        errors.append("same_key_rows < 1")
    if summary["transfer_rows"] < 1:
        errors.append("transfer_rows < 1")
    if summary["same_key_hits"] > summary["same_key_rows"]:
        errors.append("same_key_hits > same_key_rows")
    if summary["transfer_hits"] > summary["transfer_rows"]:
        errors.append("transfer_hits > transfer_rows")
    expected_restart = summary["same_key_hits"] + summary["transfer_hits"]
    if persist:
        if summary["restart_hits"] != expected_restart:
            errors.append(
                f"restart_hits={summary['restart_hits']}; "
                f"persist must restore hits ({expected_restart})"
            )
    elif summary["restart_hits"] != 0:
        errors.append(
            f"restart_hits={summary['restart_hits']}; "
            "default path must miss after a new instance"
        )
    if oneshot:
        for key in (
            "oneshot_offered",
            "oneshot_hits",
            "oneshot_transfer_hits",
            "oneshot_extra",
        ):
            if key not in summary:
                errors.append(f"missing {key}")
            elif not isinstance(summary[key], int):
                errors.append(f"{key} must be int")
        if "oneshot_transfer_hits" in summary and isinstance(
            summary["oneshot_transfer_hits"], int
        ):
            if summary["oneshot_transfer_hits"] < 1:
                errors.append(
                    "oneshot_transfer_hits < 1; "
                    "accepting one engine candidate must fix a transfer miss"
                )
        if summary.get("prefix_harms", 0) != 0:
            errors.append(
                f"prefix_harms={summary.get('prefix_harms')}; "
                "oneshot must not flip mid-input prefixes"
            )
    return errors


def persist_path_allowed(path):
    resolved = os.path.realpath(path)
    if resolved == "/tmp" or resolved.startswith("/tmp/"):
        return False
    if resolved == "/var/tmp" or resolved.startswith("/var/tmp/"):
        return False
    return True


def run_self_test():
    good = {
        "total_rows": 10,
        "same_key_rows": 5,
        "same_key_hits": 2,
        "transfer_rows": 5,
        "transfer_hits": 0,
        "harmful_overrides": 1,
        "restart_hits": 0,
    }
    if validate_summary(good):
        print("SELF-TEST FAIL: good summary rejected", file=sys.stderr)
        return 1
    bad = dict(good)
    bad["restart_hits"] = 3
    if not validate_summary(bad):
        print("SELF-TEST FAIL: restart_hits error expected", file=sys.stderr)
        return 1
    persist_good = dict(good)
    persist_good["restart_hits"] = 2
    if validate_summary(persist_good, persist=True):
        print("SELF-TEST FAIL: persist summary rejected", file=sys.stderr)
        return 1
    persist_bad = dict(good)
    persist_bad["restart_hits"] = 0
    if not validate_summary(persist_bad, persist=True):
        print("SELF-TEST FAIL: persist restart_hits error expected", file=sys.stderr)
        return 1
    oneshot_good = dict(good)
    oneshot_good["oneshot_offered"] = 3
    oneshot_good["oneshot_hits"] = 2
    oneshot_good["oneshot_transfer_hits"] = 1
    oneshot_good["oneshot_extra"] = 1
    oneshot_good["prefix_harms"] = 0
    if validate_summary(oneshot_good, oneshot=True):
        print("SELF-TEST FAIL: oneshot summary rejected", file=sys.stderr)
        return 1
    oneshot_bad = dict(oneshot_good)
    oneshot_bad["oneshot_transfer_hits"] = 0
    if not validate_summary(oneshot_bad, oneshot=True):
        print("SELF-TEST FAIL: oneshot_transfer_hits error expected", file=sys.stderr)
        return 1
    print("SELF-TEST PASSED: uom_replay summary schema", file=sys.stderr)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Run uom_replay and validate the contract summary"
    )
    parser.add_argument("--runner", default=DEFAULT_RUNNER)
    parser.add_argument("--data", default=DEFAULT_DATA)
    parser.add_argument("--fixture", default=DEFAULT_FIXTURE)
    parser.add_argument(
        "--key",
        default="three_node",
        choices=("three_node", "head_reading", "head_next"),
    )
    parser.add_argument(
        "--memory",
        default="isolated",
        choices=("isolated", "shared"),
    )
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--persist",
        nargs="?",
        const=os.path.join(SCRIPT_DIR, "build", "uom_persist_replay.txt"),
        default=None,
        help="Write after observe and load into the restart instance",
    )
    parser.add_argument("--output", default=None, help="Write runner stdout here")
    parser.add_argument(
        "--oneshot",
        action="store_true",
        help="Accept one engine multi-character candidate after the full probe",
    )
    args = parser.parse_args()
    if args.self_test:
        return run_self_test()

    if not os.path.isfile(args.runner):
        print(f"REPLAY FAIL: runner not found: {args.runner}", file=sys.stderr)
        return 1
    if args.persist is not None:
        persist_dir = os.path.dirname(os.path.abspath(args.persist))
        if persist_dir and not os.path.isdir(persist_dir):
            print(
                f"REPLAY FAIL: persist directory missing: {persist_dir}",
                file=sys.stderr,
            )
            return 1
        if not persist_path_allowed(args.persist):
            print(
                f"REPLAY FAIL: persist path not allowed: {args.persist}",
                file=sys.stderr,
            )
            return 1
    cmd = [
        args.runner,
        args.data,
        args.fixture,
        "--key=" + args.key,
        "--memory=" + args.memory,
    ]
    if args.persist is not None:
        cmd.append("--persist=" + args.persist)
    if args.oneshot:
        cmd.append("--oneshot")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        print("REPLAY FAIL: uom_replay timed out", file=sys.stderr)
        return 1
    if result.returncode != 0:
        print(
            f"REPLAY FAIL: exit {result.returncode}: {result.stderr.strip()}",
            file=sys.stderr,
        )
        return 1
    if args.output:
        output_dir = os.path.dirname(os.path.abspath(args.output))
        if output_dir and not os.path.isdir(output_dir):
            print(
                f"REPLAY FAIL: output directory missing: {output_dir}",
                file=sys.stderr,
            )
            return 1
        if not persist_path_allowed(args.output):
            print(
                f"REPLAY FAIL: output path not allowed: {args.output}",
                file=sys.stderr,
            )
            return 1
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(result.stdout)
    try:
        summary = parse_summary(result.stdout)
    except ValueError as exc:
        print(f"REPLAY FAIL: {exc}", file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return 1
    errors = validate_summary(
        summary, persist=args.persist is not None, oneshot=args.oneshot
    )
    if args.key in ("head_reading", "head_next") and args.memory == "isolated":
        fixture_name = os.path.basename(args.fixture)
        if fixture_name == "adaptation_replay.jsonl" and summary.get(
            "transfer_hits", 0
        ) < 1:
            errors.append(
                f"{args.key} expected transfer_hits >= 1 on adaptation_replay"
            )
    if errors:
        for error in errors:
            print(f"REPLAY FAIL: {error}", file=sys.stderr)
        return 1
    prefix = summary.get("prefix_harms")
    prefix_text = f", prefix_harms {prefix}" if prefix is not None else ""
    print(
        "REPLAY PASS: "
        f"key={args.key} memory={args.memory} "
        f"persist={args.persist is not None} "
        f"oneshot={args.oneshot} "
        f"same_key {summary['same_key_hits']}/{summary['same_key_rows']}, "
        f"transfer {summary['transfer_hits']}/{summary['transfer_rows']}, "
        f"harmful {summary['harmful_overrides']}, "
        f"restart_hits {summary['restart_hits']}"
        f"{prefix_text}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
