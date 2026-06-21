#!/usr/bin/env python3
"""Persistent scorer for the non-generative candidate ranker model."""

import argparse
import json
import math
import sys
import time


FEATURE_TABLES = [
    "reading_candidate",
    "candidate",
    "transition",
    "baseline_prev_candidate",
    "baseline_next_candidate",
    "baseline_window_candidate",
]

OVERRIDE_EVIDENCE_TABLES = [
    "reading_candidate",
    "transition",
    "baseline_prev_candidate",
    "baseline_next_candidate",
    "baseline_window_candidate",
]


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


def token_at(tokens, idx, default):
    if tokens is None or idx < 0 or idx >= len(tokens):
        return default
    return tokens[idx]


def count_score(table, key):
    return math.log1p(table.get(key, 0))


def token_feature_keys(reading, token, previous, prev_base, next_base):
    return {
        "reading_candidate": reading + "\t" + token,
        "candidate": token,
        "transition": previous + "\t" + token,
        "baseline_prev_candidate": prev_base + "\t" + reading + "\t" + token,
        "baseline_next_candidate": reading + "\t" + token + "\t" + next_base,
        "baseline_window_candidate": (
            prev_base + "\t" + reading + "\t" + token + "\t" + next_base
        ),
    }


def token_feature_counts(model, reading, token, previous, prev_base,
                         next_base):
    counts = model.get("counts", {})
    keys = token_feature_keys(reading, token, previous, prev_base, next_base)
    return {
        name: counts.get(name, {}).get(keys[name], 0)
        for name in FEATURE_TABLES
    }


def token_score_from_features(model, feature_counts, baseline_match):
    weights = model.get("weights", {})

    score = 0.0
    if baseline_match:
        score += float(weights.get("baseline_bonus", 0.0))

    score += float(weights.get("reading_candidate_weight", 0.0)) * count_score(
        feature_counts, "reading_candidate"
    )
    score += float(weights.get("candidate_weight", 0.0)) * count_score(
        feature_counts, "candidate"
    )
    score += float(weights.get("transition_weight", 0.0)) * count_score(
        feature_counts, "transition"
    )
    score += float(weights.get("baseline_prev_candidate_weight", 0.0)) * count_score(
        feature_counts, "baseline_prev_candidate"
    )
    score += float(weights.get("baseline_next_candidate_weight", 0.0)) * count_score(
        feature_counts, "baseline_next_candidate"
    )
    score += float(weights.get("baseline_window_candidate_weight", 0.0)) * count_score(
        feature_counts, "baseline_window_candidate"
    )
    return score


def token_score(model, reading, token, previous, baseline_token,
                prev_base, next_base):
    feature_counts = token_feature_counts(
        model, reading, token, previous, prev_base, next_base
    )
    return token_score_from_features(
        model, feature_counts, baseline_token == token
    )


def selection_controls(model):
    controls = model.get("selection", {})
    if not isinstance(controls, dict):
        controls = {}
    return {
        "override_margin": float(controls.get("override_margin", 0.0)),
        "min_non_baseline_feature_hits": int(
            controls.get("min_non_baseline_feature_hits", 0)
        ),
        "prefer_baseline_on_weak_override": bool(
            controls.get("prefer_baseline_on_weak_override", False)
        ),
        "min_reading_candidate_count_for_override": int(
            controls.get("min_reading_candidate_count_for_override", 0)
        ),
    }


def override_feature_hits(feature_counts):
    return sum(
        1 for name in OVERRIDE_EVIDENCE_TABLES
        if feature_counts.get(name, 0) > 0
    )


def choose_slot_token(model, slot, reading, previous, baseline_token,
                      prev_base, next_base):
    best = None
    best_score = None
    best_feature_counts = {}
    baseline_score = None

    for token in slot:
        feature_counts = token_feature_counts(
            model, reading, token, previous, prev_base, next_base
        )
        score = token_score_from_features(
            model, feature_counts, baseline_token == token
        )
        if token == baseline_token:
            baseline_score = score
        if best is None or score > best_score:
            best = token
            best_score = score
            best_feature_counts = feature_counts

    decision = {
        "selected": best,
        "raw_best": best,
        "raw_best_score": best_score,
        "baseline_token": baseline_token,
        "baseline_score": baseline_score,
        "override_feature_hits": 0,
        "rejected_by_margin": False,
        "rejected_by_evidence": False,
        "rejected_by_count": False,
    }

    controls = selection_controls(model)
    if (
        baseline_token in slot
        and best is not None
        and best != baseline_token
        and controls["prefer_baseline_on_weak_override"]
    ):
        hits = override_feature_hits(best_feature_counts)
        decision["override_feature_hits"] = hits
        if hits < controls["min_non_baseline_feature_hits"]:
            decision["selected"] = baseline_token
            decision["rejected_by_evidence"] = True
            return decision
        min_reading_count = controls[
            "min_reading_candidate_count_for_override"
        ]
        if (
            min_reading_count > 0
            and best_feature_counts.get("reading_candidate", 0)
            < min_reading_count
        ):
            decision["selected"] = baseline_token
            decision["rejected_by_count"] = True
            return decision
        if baseline_score is not None:
            required = baseline_score + controls["override_margin"]
            if best_score < required:
                decision["selected"] = baseline_token
                decision["rejected_by_margin"] = True
                return decision

    return decision


def rank_request_details(model, request):
    candidates = request.get("candidates")
    if not candidates:
        return {
            "output": request.get("baseline_output", ""),
            "error": None,
            "decisions": [],
        }

    readings = request.get("readings", [])
    baseline = baseline_tokens(request)
    selected = []
    decisions = []
    previous = "<BOS>"

    for idx, slot in enumerate(candidates):
        if not slot:
            continue
        reading = readings[idx] if idx < len(readings) else ""
        baseline_token = baseline[idx] if baseline and idx < len(baseline) else None
        prev_base = token_at(baseline, idx - 1, "<BOS>")
        next_base = token_at(baseline, idx + 1, "<EOS>")

        decision = choose_slot_token(
            model, slot, reading, previous, baseline_token, prev_base, next_base
        )
        if decision["selected"] is None:
            return {"output": None, "error": "empty_candidate_slot",
                    "decisions": decisions}
        selected.append(decision["selected"])
        decisions.append(decision)
        previous = decision["selected"]

    output = "".join(selected)
    if validate_candidates(output, candidates) is None:
        return {"output": None, "error": "output_not_candidate",
                "decisions": decisions}
    return {"output": output, "error": None, "decisions": decisions}


def rank_request(model, request):
    details = rank_request_details(model, request)
    return details["output"], details["error"]


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
            "baseline_bonus": 0.5,
            "reading_candidate_weight": 0.1,
            "candidate_weight": 0.05,
            "transition_weight": 0.15,
            "baseline_prev_candidate_weight": 1.5,
            "baseline_next_candidate_weight": 1.5,
            "baseline_window_candidate_weight": 2.5,
        },
        "selection": {
            "override_margin": 0.1,
            "min_non_baseline_feature_hits": 2,
            "min_reading_candidate_count_for_override": 2,
            "prefer_baseline_on_weak_override": True,
        },
        "counts": {
            "reading_candidate": {"r1\tB": 2, "r2\tC": 2},
            "candidate": {"B": 2, "C": 2},
            "transition": {"<BOS>\tB": 2, "B\tC": 2},
            "baseline_prev_candidate": {"<BOS>\tr1\tB": 2, "A\tr2\tC": 2},
            "baseline_next_candidate": {"r1\tB\tC": 2, "r2\tC\t<EOS>": 2},
            "baseline_window_candidate": {
                "<BOS>\tr1\tB\tC": 2,
                "A\tr2\tC\t<EOS>": 2,
            },
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
    weak_model = json.loads(json.dumps(model))
    weak_model["counts"]["reading_candidate"] = {}
    weak_model["counts"]["transition"] = {}
    weak_model["counts"]["baseline_prev_candidate"] = {}
    weak_model["counts"]["baseline_next_candidate"] = {}
    weak_model["counts"]["baseline_window_candidate"] = {}
    weak_response = process_request(weak_model, request)
    if weak_response.get("output") != "AC":
        print(
            "SELF-TEST FAIL: expected weak evidence to preserve baseline, "
            f"got {weak_response}",
            file=sys.stderr,
        )
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
