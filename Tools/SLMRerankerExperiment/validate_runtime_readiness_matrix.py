#!/usr/bin/env python3
"""Validate Phase 3 runtime readiness evidence links."""

import argparse
import json
import os
import re
import sys
import tempfile


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", ".."))
DEFAULT_MATRIX = os.path.join(
    PROJECT_ROOT,
    "docs",
    "reports",
    "experiments",
    "phase3",
    "runtime_readiness_matrix.json",
)

EXPECTED_OPEN_GATES = {
    "manual IMK dogfood": "missing",
    "SLM runtime": "not_ready",
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def project_relpath(path):
    try:
        rel = os.path.relpath(path, PROJECT_ROOT)
    except ValueError:
        return path
    return rel if not rel.startswith("..") else path


def resolve_path(value):
    if not isinstance(value, str) or not value:
        return None
    if value.startswith("http://") or value.startswith("https://"):
        return None
    if os.path.isabs(value):
        return value
    return os.path.join(PROJECT_ROOT, value)


def iter_evidence_paths(matrix):
    for idx, entry in enumerate(matrix.get("current_state", [])):
        if not isinstance(entry, dict):
            continue
        evidence = entry.get("evidence")
        if not isinstance(evidence, str):
            continue
        for raw_part in evidence.split(";"):
            part = raw_part.strip()
            if part.endswith(".json"):
                yield f"current_state[{idx}].evidence", part


def iter_verification_json_paths(matrix):
    pattern = re.compile(r"docs/reports/experiments/[^ ]+\.json")
    for idx, command in enumerate(matrix.get("verification", [])):
        if not isinstance(command, str):
            continue
        for match in pattern.findall(command):
            yield f"verification[{idx}]", match


def validate_json_path(errors, label, raw_path):
    path = resolve_path(raw_path)
    if path is None:
        return
    if not os.path.isfile(path):
        errors.append(f"{label}: missing {raw_path}")
        return
    try:
        load_json(path)
    except json.JSONDecodeError as exc:
        errors.append(f"{label}: invalid JSON {raw_path}: {exc}")


def validate_open_gates(matrix, errors):
    gates = matrix.get("promotion_gates")
    if not isinstance(gates, list):
        errors.append(".promotion_gates: expected array")
        return
    open_seen = {}
    for gate in gates:
        if not isinstance(gate, dict):
            continue
        name = gate.get("gate")
        status = gate.get("status")
        if not isinstance(name, str) or not isinstance(status, str):
            continue
        is_open = status == "missing" or status.startswith("not_ready")
        if is_open:
            open_seen[name] = status
    for name, expected_prefix in EXPECTED_OPEN_GATES.items():
        status = open_seen.get(name)
        if status is None:
            errors.append(f".promotion_gates: expected open gate {name!r}")
            continue
        if expected_prefix == "missing" and status != "missing":
            errors.append(
                f".promotion_gates[{name}].status: expected missing, got {status!r}"
            )
        elif expected_prefix != "missing" and not status.startswith(expected_prefix):
            errors.append(
                f".promotion_gates[{name}].status: expected prefix "
                f"{expected_prefix!r}, got {status!r}"
            )
    for name in sorted(set(open_seen) - set(EXPECTED_OPEN_GATES)):
        errors.append(f".promotion_gates: unexpected open gate {name!r}")


def validate_matrix(matrix):
    errors = []
    if not isinstance(matrix, dict):
        return ["$: expected object"]
    if matrix.get("id") != "phase3-runtime-readiness-matrix":
        errors.append(".id: expected phase3-runtime-readiness-matrix")
    if matrix.get("status") != "partial":
        errors.append(f".status: expected partial, got {matrix.get('status')!r}")
    if matrix.get("privacy", {}).get("content_free") is not True:
        errors.append(".privacy.content_free: expected true")
    for label, raw_path in iter_evidence_paths(matrix):
        validate_json_path(errors, label, raw_path)
    for label, raw_path in iter_verification_json_paths(matrix):
        validate_json_path(errors, label, raw_path)
    validate_open_gates(matrix, errors)
    return errors


def run_self_test():
    with tempfile.TemporaryDirectory() as tmp:
        report = os.path.join(tmp, "report.json")
        with open(report, "w", encoding="utf-8") as handle:
            json.dump({"ok": True}, handle)
        rel_report = os.path.relpath(report, PROJECT_ROOT)
        good = {
            "id": "phase3-runtime-readiness-matrix",
            "status": "partial",
            "privacy": {"content_free": True},
            "current_state": [
                {"area": "example", "state": "verified", "evidence": rel_report},
            ],
            "promotion_gates": [
                {"gate": "manual IMK dogfood", "status": "missing"},
                {
                    "gate": "SLM runtime",
                    "status": "not_ready_promotion_validator_pass_github_run_1",
                },
            ],
            "verification": [f"python3 -m json.tool {rel_report}"],
        }
        errors = validate_matrix(good)
        if errors:
            print(f"SELF-TEST FAIL: valid matrix rejected: {errors}", file=sys.stderr)
            return 1

        bad_missing = json.loads(json.dumps(good))
        bad_missing["current_state"][0]["evidence"] = "docs/reports/nope.json"
        errors = validate_matrix(bad_missing)
        if not any("missing" in error for error in errors):
            print("SELF-TEST FAIL: expected missing evidence error", file=sys.stderr)
            return 1

        bad_gate = json.loads(json.dumps(good))
        bad_gate["promotion_gates"].append({"gate": "extra", "status": "missing"})
        errors = validate_matrix(bad_gate)
        if not any("unexpected open gate" in error for error in errors):
            print("SELF-TEST FAIL: expected unexpected open gate error", file=sys.stderr)
            return 1

    print("SELF-TEST PASSED: runtime readiness matrix validator", file=sys.stderr)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Validate Phase 3 runtime readiness matrix evidence"
    )
    parser.add_argument("--matrix", default=DEFAULT_MATRIX)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()
    try:
        matrix = load_json(args.matrix)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"VALIDATION FAIL: {exc}", file=sys.stderr)
        return 1
    errors = validate_matrix(matrix)
    if errors:
        for error in errors:
            print(f"VALIDATION FAIL: {error}", file=sys.stderr)
        return 1
    print("VALIDATION PASSED: runtime readiness matrix", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
