#!/usr/bin/env python3
"""Validate experiment registry references and content-free report hygiene."""

import argparse
import json
import os
import sys
import tempfile


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", ".."))
DEFAULT_REGISTRY = os.path.join(
    PROJECT_ROOT, "docs", "reports", "experiments", "registry.json"
)

CONTENT_FREE_FALSE_KEYS = {
    "raw_text_recorded",
    "readings_recorded",
    "candidate_text_recorded",
    "committed_text_recorded",
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
    "reading",
    "readings",
}

RAW_LOCATION_KEYS = {
    "raw_artifacts_location",
    "raw_benchmark_outputs_location",
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_json_or_jsonl(path):
    try:
        return load_json(path)
    except json.JSONDecodeError as json_error:
        rows = []
        with open(path, "r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as line_error:
                    raise json.JSONDecodeError(
                        f"{json_error}; JSONL line {line_no}: {line_error}",
                        line_error.doc,
                        line_error.pos,
                    ) from line_error
        if not rows:
            raise json_error
        return rows


def project_relpath(path):
    try:
        rel = os.path.relpath(path, PROJECT_ROOT)
    except ValueError:
        return path
    return rel if not rel.startswith("..") else path


def resolve_report_path(entry, value):
    if not isinstance(value, str) or not value:
        return None
    if os.path.isabs(value):
        return value
    if os.sep in value or "/" in value:
        return os.path.join(PROJECT_ROOT, value)
    results_dir = entry.get("results_dir")
    if isinstance(results_dir, str) and results_dir:
        return os.path.join(PROJECT_ROOT, results_dir, value)
    return os.path.join(PROJECT_ROOT, value)


def iter_registry_paths(entry):
    seen = set()
    for key in ("summary_file",):
        path = resolve_report_path(entry, entry.get(key))
        if path and path not in seen:
            seen.add(path)
            yield key, path
    result_files = entry.get("result_files", [])
    if isinstance(result_files, list):
        for idx, value in enumerate(result_files):
            path = resolve_report_path(entry, value)
            if path and path not in seen:
                seen.add(path)
                yield f"result_files[{idx}]", path


def walk_json(value, path="$"):
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk_json(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            yield from walk_json(child, f"{path}[{idx}]")


def declares_content_free(report):
    privacy = report.get("privacy")
    if isinstance(privacy, dict) and privacy.get("content_free") is True:
        return True
    policy = report.get("content_policy")
    if isinstance(policy, dict):
        return policy.get("raw_case_strings_in_report") is False
    return False


def validate_content_free_report(report, report_path):
    errors = []
    for json_path, value in walk_json(report):
        if not isinstance(value, dict):
            continue
        for key in CONTENT_FREE_FALSE_KEYS:
            if key in value and value[key] is not False:
                errors.append(
                    f"{report_path}: {json_path}.{key} must be false"
                )
        if value.get("content_free") is False:
            errors.append(f"{report_path}: {json_path}.content_free is false")

        for key in RAW_CONTENT_KEYS:
            if key in value:
                errors.append(
                    f"{report_path}: raw content field present at {json_path}.{key}"
                )
        for key in RAW_LOCATION_KEYS:
            raw_location = value.get(key)
            if isinstance(raw_location, str) and not raw_location.startswith("/tmp"):
                errors.append(
                    f"{report_path}: {json_path}.{key} must point under /tmp"
                )
    return errors


def validate_registry(registry_path, strict_content_free=False):
    errors = []
    registry = load_json(registry_path)
    experiments = registry.get("experiments")
    if not isinstance(experiments, list):
        return ["registry.experiments must be a list"]

    seen_ids = {}
    for idx, entry in enumerate(experiments):
        if not isinstance(entry, dict):
            errors.append(f"experiments[{idx}] must be an object")
            continue
        exp_id = entry.get("id")
        if not isinstance(exp_id, str) or not exp_id:
            errors.append(f"experiments[{idx}].id must be a non-empty string")
        elif exp_id in seen_ids:
            errors.append(
                f"duplicate experiment id {exp_id!r}: "
                f"experiments[{seen_ids[exp_id]}] and experiments[{idx}]"
            )
        else:
            seen_ids[exp_id] = idx

        for label, report_path in iter_registry_paths(entry):
            if not os.path.isfile(report_path):
                errors.append(
                    f"{exp_id or idx}: {label} missing: "
                    f"{project_relpath(report_path)}"
                )
                continue
            try:
                report = (
                    load_json(report_path)
                    if label == "summary_file"
                    else load_json_or_jsonl(report_path)
                )
            except json.JSONDecodeError as exc:
                errors.append(
                    f"{exp_id or idx}: {label} invalid JSON "
                    f"{project_relpath(report_path)}: {exc}"
                )
                continue
            if isinstance(report, dict) and (
                strict_content_free or declares_content_free(report)
            ):
                errors.extend(
                    validate_content_free_report(
                        report, project_relpath(report_path)
                    )
                )
    return errors


def run_self_test():
    with tempfile.TemporaryDirectory() as tmp:
        report_path = os.path.join(tmp, "content_free.json")
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump({
                "privacy": {
                    "content_free": True,
                    "raw_text_recorded": False,
                    "readings_recorded": False,
                    "candidate_text_recorded": False,
                    "committed_text_recorded": False,
                },
                "raw_artifacts_location": "/tmp/example*",
            }, handle)

        bad_report_path = os.path.join(tmp, "bad.json")
        with open(bad_report_path, "w", encoding="utf-8") as handle:
            json.dump({
                "privacy": {"content_free": True},
                "expected_output": "raw text",
            }, handle)

        jsonl_path = os.path.join(tmp, "rows.jsonl")
        with open(jsonl_path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"id": "row-1"}) + "\n")
            handle.write(json.dumps({"total_cases": 1}) + "\n")

        registry_path = os.path.join(tmp, "registry.json")
        with open(registry_path, "w", encoding="utf-8") as handle:
            json.dump({
                "registry_version": 1,
                "experiments": [
                    {
                        "id": "ok",
                        "summary_file": report_path,
                        "result_files": [jsonl_path],
                    },
                    {
                        "id": "bad",
                        "summary_file": bad_report_path,
                    },
                    {
                        "id": "bad",
                        "summary_file": os.path.join(tmp, "missing.json"),
                    },
                ],
            }, handle)

        errors = validate_registry(registry_path)
        if not any("raw content field" in err for err in errors):
            print("SELF-TEST FAIL: expected raw content field error", file=sys.stderr)
            return 1
        if not any("duplicate experiment id" in err for err in errors):
            print("SELF-TEST FAIL: expected duplicate id error", file=sys.stderr)
            return 1
        if not any("missing" in err for err in errors):
            print("SELF-TEST FAIL: expected missing file error", file=sys.stderr)
            return 1

    print("SELF-TEST PASSED: registry paths + content-free hygiene", file=sys.stderr)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Validate experiment registry references and report hygiene"
    )
    parser.add_argument("--registry", default=DEFAULT_REGISTRY)
    parser.add_argument(
        "--strict-content-free",
        action="store_true",
        help="Apply content-free field checks to every referenced report",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    errors = validate_registry(
        os.path.abspath(args.registry),
        strict_content_free=args.strict_content_free,
    )
    if errors:
        for error in errors:
            print(f"VALIDATION FAIL: {error}", file=sys.stderr)
        return 1
    print("VALIDATION PASSED: experiment registry reports", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
