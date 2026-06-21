#!/usr/bin/env python3
"""Mock tiny-LLM scorer implementing the SLM Reranker external scoring protocol.

Default mode: returns baseline_output as-is (no-op, privacy-safe, no accuracy claim).
Oracle mode (--oracle): returns the expected field (for scaffold verification only).

Usage:
    echo '{"id":"test","readings":["ㄗㄞˋ","ㄐㄧㄢˋ"],"baseline_output":"在見"}' | \\
        python3 mock_tiny_llm_scorer.py
    echo '{"id":"test","readings":["ㄗㄞˋ","ㄐㄧㄢˋ"],"baseline_output":"在見","expected":"再見"}' | \\
        python3 mock_tiny_llm_scorer.py --oracle
"""

import argparse
import json
import sys
import time


def process_request(request, oracle_mode):
    start = time.perf_counter()

    baseline = request.get("baseline_output", "")
    expected = request.get("expected", "")

    if oracle_mode and expected:
        output = expected
    else:
        output = baseline

    elapsed_us = int((time.perf_counter() - start) * 1_000_000)

    return {
        "output": output,
        "scorer_name": "mock-tiny-llm-scorer" + ("-oracle" if oracle_mode else ""),
        "latency_us": elapsed_us,
    }


def validate_request(request):
    if not isinstance(request, dict):
        return False, "request is not a JSON object"
    if "id" not in request:
        return False, "missing required field: id"
    if not isinstance(request.get("id"), str) or not request["id"]:
        return False, "id must be a non-empty string"
    if "readings" not in request:
        return False, "missing required field: readings"
    if not isinstance(request.get("readings"), list):
        return False, "readings must be an array"
    if "baseline_output" not in request:
        return False, "missing required field: baseline_output"
    return True, ""


def main():
    parser = argparse.ArgumentParser(
        description="Mock tiny-LLM scorer implementing the SLM Reranker protocol."
    )
    parser.add_argument(
        "--oracle",
        action="store_true",
        help="Oracle mode: return expected field from request",
    )
    parser.add_argument(
        "--persistent",
        action="store_true",
        help="Persistent mode: read JSONL requests from stdin until EOF",
    )
    args = parser.parse_args()

    if args.persistent:
        # Persistent mode: read JSONL line by line until EOF
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError as e:
                print(
                    json.dumps({"error": f"invalid_json: {e}"}, ensure_ascii=False),
                    flush=True,
                )
                continue

            valid, error_msg = validate_request(request)
            if not valid:
                print(
                    json.dumps({"error": error_msg}, ensure_ascii=False),
                    flush=True,
                )
                continue

            response = process_request(request, oracle_mode=args.oracle)
            print(json.dumps(response, ensure_ascii=False), flush=True)
        sys.exit(0)

    stdin_text = sys.stdin.read()
    if not stdin_text.strip():
        print("FATAL: empty stdin", file=sys.stderr)
        sys.exit(2)

    try:
        request = json.loads(stdin_text)
    except json.JSONDecodeError as e:
        print(f"FATAL: invalid JSON on stdin: {e}", file=sys.stderr)
        sys.exit(2)

    valid, error_msg = validate_request(request)
    if not valid:
        print(f"FATAL: {error_msg}", file=sys.stderr)
        sys.exit(2)

    response = process_request(request, oracle_mode=args.oracle)
    print(json.dumps(response, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
