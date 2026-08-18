#!/usr/bin/env python3
"""Check adaptation_replay.jsonl records against the Step 1 contract."""

import argparse
import json
import os
import sys


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", ".."))
DEFAULT_FIXTURE = os.path.join(
    PROJECT_ROOT,
    "Tests",
    "fixtures",
    "contextual_bopomofo",
    "adaptation_replay.jsonl",
)

REQUIRED_TOP = ("id", "observe", "probe", "same_key_expected")


def validate_row(row, line_no):
    errors = []
    prefix = f"line {line_no}"
    if not isinstance(row, dict):
        return [f"{prefix}: not an object"]
    for key in REQUIRED_TOP:
        if key not in row:
            errors.append(f"{prefix}: missing {key}")
    observe = row.get("observe")
    probe = row.get("probe")
    if isinstance(observe, dict):
        if not observe.get("readings"):
            errors.append(f"{prefix}: observe.readings empty")
        if not observe.get("committed"):
            errors.append(f"{prefix}: observe.committed empty")
    else:
        errors.append(f"{prefix}: observe must be an object")
    if isinstance(probe, dict):
        if not probe.get("readings"):
            errors.append(f"{prefix}: probe.readings empty")
        if not probe.get("expected"):
            errors.append(f"{prefix}: probe.expected empty")
    else:
        errors.append(f"{prefix}: probe must be an object")
    if "same_key_expected" in row and not isinstance(
        row["same_key_expected"], bool
    ):
        errors.append(f"{prefix}: same_key_expected must be boolean")
    return errors


def validate_fixture(path):
    errors = []
    ids = []
    same = 0
    transfer = 0
    with open(path, encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {line_no}: {exc}")
                continue
            errors.extend(validate_row(row, line_no))
            if isinstance(row, dict) and "id" in row:
                ids.append(row["id"])
                if row.get("same_key_expected") is True:
                    same += 1
                elif row.get("same_key_expected") is False:
                    transfer += 1
    if len(ids) != len(set(ids)):
        errors.append("duplicate id")
    if same == 0:
        errors.append("need at least one same_key_expected=true row")
    if transfer == 0:
        errors.append("need at least one same_key_expected=false row")
    return errors, len(ids), same, transfer


def run_self_test():
    good = {
        "id": "t1",
        "observe": {"readings": ["a"], "committed": "甲"},
        "probe": {"readings": ["a"], "expected": "甲"},
        "same_key_expected": True,
    }
    if validate_row(good, 1):
        print("SELF-TEST FAIL: good row rejected", file=sys.stderr)
        return 1
    bad = {"id": "t2", "observe": {}, "probe": {}, "same_key_expected": "yes"}
    if not validate_row(bad, 2):
        print("SELF-TEST FAIL: bad row accepted", file=sys.stderr)
        return 1
    print("SELF-TEST PASSED: adaptation_replay schema", file=sys.stderr)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Validate adaptation_replay.jsonl schema"
    )
    parser.add_argument("--fixture", default=DEFAULT_FIXTURE)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return run_self_test()
    errors, total, same, transfer = validate_fixture(args.fixture)
    if errors:
        for error in errors:
            print(f"SCHEMA FAIL: {error}", file=sys.stderr)
        return 1
    print(
        f"SCHEMA PASS: {total} rows, same_key={same}, transfer={transfer}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
