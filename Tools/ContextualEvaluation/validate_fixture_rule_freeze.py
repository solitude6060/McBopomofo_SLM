#!/usr/bin/env python3
"""Check that frozen rule and fixture files still match the Step 0 snapshot."""

import argparse
import hashlib
import json
import os
import sys
import tempfile


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", ".."))
DEFAULT_MANIFEST = os.path.join(SCRIPT_DIR, "fixture_rule_freeze.json")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path):
    with open(path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("algorithm") != "sha256":
        raise ValueError("manifest algorithm must be sha256")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("manifest files list is empty")
    return manifest


def validate_manifest(manifest, project_root):
    errors = []
    for entry in manifest["files"]:
        rel = entry.get("path")
        expected = entry.get("sha256")
        expected_bytes = entry.get("bytes")
        if not rel or not expected:
            errors.append("manifest entry missing path or sha256")
            continue
        abs_path = os.path.join(project_root, rel)
        if not os.path.isfile(abs_path):
            errors.append(f"{rel}: missing")
            continue
        actual_bytes = os.stat(abs_path).st_size
        if expected_bytes is not None and actual_bytes != expected_bytes:
            errors.append(
                f"{rel}: size {actual_bytes} != frozen {expected_bytes}"
            )
        actual = sha256_file(abs_path)
        if actual != expected:
            errors.append(f"{rel}: sha256 {actual} != frozen {expected}")
    return errors


def run_self_test():
    payload = b"fixture-rule-freeze-self-test\n"
    expected = hashlib.sha256(payload).hexdigest()
    with tempfile.TemporaryDirectory() as tmp:
        rel = "probe.bin"
        path = os.path.join(tmp, rel)
        with open(path, "wb") as handle:
            handle.write(payload)
        manifest = {
            "algorithm": "sha256",
            "files": [{"path": rel, "sha256": expected, "bytes": len(payload)}],
        }
        errors = validate_manifest(manifest, tmp)
        if errors:
            print(f"SELF-TEST FAIL: {errors}", file=sys.stderr)
            return 1
        manifest["files"][0]["sha256"] = "0" * 64
        if not validate_manifest(manifest, tmp):
            print("SELF-TEST FAIL: expected hash mismatch", file=sys.stderr)
            return 1
    print("SELF-TEST PASSED: fixture rule freeze validator", file=sys.stderr)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Validate Step 0 rule/fixture freeze hashes"
    )
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--project-root", default=PROJECT_ROOT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    try:
        manifest = load_manifest(args.manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FREEZE FAIL: cannot read manifest: {exc}", file=sys.stderr)
        return 1

    errors = validate_manifest(manifest, args.project_root)
    if errors:
        for error in errors:
            print(f"FREEZE FAIL: {error}", file=sys.stderr)
        return 1

    print(
        f"FREEZE PASS: {len(manifest['files'])} files match "
        f"{manifest.get('frozen_at', 'unknown')}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
