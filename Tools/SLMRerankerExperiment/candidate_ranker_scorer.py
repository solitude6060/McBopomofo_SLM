#!/usr/bin/env python3
"""Persistent scorer for the non-generative candidate ranker model."""

import argparse
import json
import math
import sys
import time


def load_model(path):
    with open(path, "r", encoding="utf-8") as handle:
        model = json.load(handle)
    if not isinstance(model, dict):
        raise RuntimeError("model must be a JSON object")
    if model.get("model_type") != "candidate-ranker-v1":
        raise RuntimeError("unsupported model_type")
    return model


def validate_candidates(output, candidates):
    if not output or not candidates:
        return None

    out_pos = 0
    tokens = []
    for slot in candidates:
        if not slot:
            continue
        matched = None
        for cand in sorted(slot, key=len, reverse=True):
            if output[out_pos:out_pos + len(cand)] == cand:
                matched = cand
                break
        if matched is None:
            return None
        tokens.append(matched)
        out_pos += len(matched)

    if out_pos != len(output):
        return None
    return tokens


def baseline_tokens(request):
    baseline = request.get("baseline_output", "")
    candidates = request.get("candidates")
    return validate_candidates(baseline, candidates)


def count_score(table, key):
    return math.log1p(table.get(key, 0))


def token_score(model, reading, token, previous, baseline_token):
    weights = model.get("weights", {})
    counts = model.get("counts", {})

    score = 0.0
    if baseline_token == token:
        score += float(weights.get("baseline_bonus", 0.0))

    score += float(weights.get("reading_candidate_weight", 0.0)) * count_score(
        counts.get("reading_candidate", {}), reading + "\t" + token
    )
    score += float(weights.get("candidate_weight", 0.0)) * count_score(
        counts.get("candidate", {}), token
    )
    score += float(weights.get("transition_weight", 0.0)) * count_score(
        counts.get("transition", {}), previous + "\t" + token
    )
    return score


def rank_request(model, request):
    candidates = request.get("candidates")
    if not candidates:
        return request.get("baseline_output", ""), None

    readings = request.get("readings", [])
    baseline = baseline_tokens(request)
    selected = []
    previous = "<BOS>"

    for idx, slot in enumerate(candidates):
        if not slot:
            continue
        reading = readings[idx] if idx < len(readings) else ""
        baseline_token = baseline[idx] if baseline and idx < len(baseline) else None

        best = None
        best_score = None
        for token in slot:
            score = token_score(model, reading, token, previous, baseline_token)
            if best is None or score > best_score:
                best = token
                best_score = score

        if best is None:
            return None, "empty_candidate_slot"
        selected.append(best)
        previous = best

    output = "".join(selected)
    if validate_candidates(output, candidates) is None:
        return None, "output_not_candidate"
    return output, None


def process_request(model, request):
    start = time.perf_counter()
    output, error = rank_request(model, request)
    elapsed = int((time.perf_counter() - start) * 1_000_000)
    if error:
        return {
            "scorer_name": "candidate-ranker-v1-error",
            "latency_us": elapsed,
            "error_reason": error,
        }
    return {
        "output": output,
        "scorer_name": "candidate-ranker-v1",
        "latency_us": elapsed,
    }


def run_self_test():
    model = {
        "model_type": "candidate-ranker-v1",
        "weights": {
            "baseline_bonus": 0.25,
            "reading_candidate_weight": 2.0,
            "candidate_weight": 0.15,
            "transition_weight": 0.75,
        },
        "counts": {
            "reading_candidate": {"r1\tB": 2, "r2\tC": 2},
            "candidate": {"B": 2, "C": 2},
            "transition": {"<BOS>\tB": 2, "B\tC": 2},
        },
    }
    request = {
        "id": "self-test",
        "readings": ["r1", "r2"],
        "baseline_output": "AC",
        "candidates": [["A", "B"], ["C"]],
    }
    response = process_request(model, request)
    if response.get("output") != "BC":
        print(f"SELF-TEST FAIL: expected BC, got {response}", file=sys.stderr)
        return 1
    print("SELF-TEST PASSED: candidate ranker scorer", file=sys.stderr)
    return 0


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Candidate ranker scorer for the SLM protocol."
    )
    parser.add_argument("--model", help="Path to candidate ranker model JSON")
    parser.add_argument("--persistent", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.self_test:
        sys.exit(run_self_test())
    if not args.model:
        parser.error("--model is required unless --self-test")

    try:
        model = load_model(args.model)
    except RuntimeError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        sys.exit(2)

    if args.persistent:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                print(
                    json.dumps({
                        "scorer_name": "candidate-ranker-v1-error",
                        "error_reason": "invalid_json",
                    }),
                    flush=True,
                )
                continue
            print(
                json.dumps(process_request(model, request), ensure_ascii=False),
                flush=True,
            )
        return

    stdin_text = sys.stdin.read()
    if not stdin_text.strip():
        print("FATAL: empty stdin", file=sys.stderr)
        sys.exit(2)
    try:
        request = json.loads(stdin_text)
    except json.JSONDecodeError as exc:
        print(f"FATAL: invalid JSON on stdin: {exc}", file=sys.stderr)
        sys.exit(2)
    print(json.dumps(process_request(model, request), ensure_ascii=False))


if __name__ == "__main__":
    main()
