#!/usr/bin/env python3
"""Train a tiny non-generative candidate ranker model.

The trainer consumes SLM request JSONL files produced by the evaluator's
``--slm-request-output`` mode. It learns only from cases whose expected output
can be formed by the provided candidate slots. The model stores small count
tables and has no dependency on model weights or external runtimes.
"""

import argparse
import json
import os
import sys
import time


FIXTURE_PREFIXES = {
    "taiwan_ambiguous": ["tw-amb-"],
    "english_mixed": ["en-mix-"],
    "taiwan_specific": ["tw-taiwan_specific-"],
    "heldout_generalization": ["hg-"],
}


def validate_candidates(output, candidates):
    """Return the selected candidate token per slot, or None if invalid."""
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


def read_jsonl(paths):
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield path, line_no, json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"{path}:{line_no}: invalid JSON: {exc}")


def inc(table, key, amount=1):
    table[key] = table.get(key, 0) + amount


def build_excluded_prefixes(fixture_names, explicit_prefixes):
    prefixes = []
    for name in fixture_names:
        if name not in FIXTURE_PREFIXES:
            raise RuntimeError(f"unknown fixture name for exclusion: {name}")
        prefixes.extend(FIXTURE_PREFIXES[name])
    prefixes.extend(explicit_prefixes)
    return sorted(set(prefixes))


def is_excluded(case_id, prefixes):
    return any(case_id.startswith(prefix) for prefix in prefixes)


def baseline_tokens(case, candidates):
    baseline = case.get("baseline_output", "")
    return validate_candidates(baseline, candidates)


def token_at(tokens, idx, default):
    if tokens is None or idx < 0 or idx >= len(tokens):
        return default
    return tokens[idx]


def train(paths, excluded_prefixes):
    stats = {
        "input_cases": 0,
        "excluded_cases": 0,
        "usable_cases": 0,
        "skipped_without_expected": 0,
        "skipped_without_candidates": 0,
        "skipped_expected_not_candidate": 0,
    }
    counts = {
        "reading_candidate": {},
        "candidate": {},
        "transition": {},
        "baseline_prev_candidate": {},
        "baseline_next_candidate": {},
        "baseline_window_candidate": {},
    }

    for _, _, case in read_jsonl(paths):
        stats["input_cases"] += 1
        case_id = case.get("id", "")
        if is_excluded(case_id, excluded_prefixes):
            stats["excluded_cases"] += 1
            continue

        expected = case.get("expected")
        if not isinstance(expected, str) or not expected:
            stats["skipped_without_expected"] += 1
            continue

        candidates = case.get("candidates")
        if not candidates:
            stats["skipped_without_candidates"] += 1
            continue

        tokens = validate_candidates(expected, candidates)
        if tokens is None:
            stats["skipped_expected_not_candidate"] += 1
            continue

        readings = case.get("readings", [])
        baseline = baseline_tokens(case, candidates)
        previous = "<BOS>"
        for idx, token in enumerate(tokens):
            reading = readings[idx] if idx < len(readings) else ""
            prev_base = token_at(baseline, idx - 1, "<BOS>")
            next_base = token_at(baseline, idx + 1, "<EOS>")
            inc(counts["reading_candidate"], reading + "\t" + token)
            inc(counts["candidate"], token)
            inc(counts["transition"], previous + "\t" + token)
            inc(
                counts["baseline_prev_candidate"],
                prev_base + "\t" + reading + "\t" + token,
            )
            inc(
                counts["baseline_next_candidate"],
                reading + "\t" + token + "\t" + next_base,
            )
            inc(
                counts["baseline_window_candidate"],
                prev_base + "\t" + reading + "\t" + token + "\t" + next_base,
            )
            previous = token
        inc(counts["transition"], previous + "\t<EOS>")
        stats["usable_cases"] += 1

    return counts, stats


def make_model(counts, stats, excluded_prefixes, source_paths,
               selection_controls=None):
    total_candidate_observations = sum(counts["candidate"].values())
    vocabulary = len(counts["candidate"])
    if selection_controls is None:
        selection_controls = {
            "override_margin": 0.1,
            "min_non_baseline_feature_hits": 2,
            "min_reading_candidate_count_for_override": 2,
            "prefer_baseline_on_weak_override": True,
        }
    return {
        "model_type": "candidate-ranker-v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime()),
        "description": (
            "Non-generative candidate ranker. Scores only existing candidate "
            "tokens and emits one candidate-constrained output string."
        ),
        "training": {
            **stats,
            "excluded_id_prefixes": excluded_prefixes,
            "source_files": [os.path.basename(path) for path in source_paths],
            "contamination_guard": "excluded cases are not counted",
        },
        "weights": {
            "baseline_bonus": 0.5,
            "reading_candidate_weight": 0.1,
            "candidate_weight": 0.05,
            "transition_weight": 0.15,
            "baseline_prev_candidate_weight": 1.5,
            "baseline_next_candidate_weight": 1.5,
            "baseline_window_candidate_weight": 2.5,
        },
        "selection": selection_controls,
        "defaults": {
            "unknown_score": 0.0,
            "total_candidate_observations": total_candidate_observations,
            "vocabulary_size": vocabulary,
        },
        "counts": counts,
    }


def run_self_test():
    sample = {
        "id": "sample-001",
        "readings": ["r1", "r2"],
        "baseline_output": "\u5728\u898b",
        "expected": "\u518d\u898b",
        "candidates": [["\u5728", "\u518d"], ["\u898b"]],
    }
    tmp = None
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as handle:
            tmp = handle.name
            handle.write(json.dumps(sample, ensure_ascii=False) + "\n")
        counts, stats = train([tmp], [])
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    errors = []
    if stats["usable_cases"] != 1:
        errors.append("expected one usable case")
    if counts["reading_candidate"].get("r1\t\u518d") != 1:
        errors.append("missing reading_candidate count")
    if counts["transition"].get("\u518d\t\u898b") != 1:
        errors.append("missing transition count")
    if counts["baseline_next_candidate"].get("r1\t\u518d\t\u898b") != 1:
        errors.append("missing baseline_next_candidate count")
    if (
        counts["baseline_window_candidate"]
        .get("<BOS>\tr1\t\u518d\t\u898b") != 1
    ):
        errors.append("missing baseline_window_candidate count")

    if validate_candidates("\u5728\u898b", sample["candidates"]) != [
        "\u5728", "\u898b"
    ]:
        errors.append("candidate validation failed")
    if validate_candidates("\u518d\u6703", sample["candidates"]) is not None:
        errors.append("invalid candidate output accepted")

    if errors:
        for error in errors:
            print(f"SELF-TEST FAIL: {error}", file=sys.stderr)
        return 1
    print("SELF-TEST PASSED: candidate ranker trainer", file=sys.stderr)
    return 0


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Train a tiny candidate ranker from SLM request JSONL."
    )
    parser.add_argument("--input", nargs="+", help="Input request JSONL files")
    parser.add_argument("--output", help="Output model JSON path")
    parser.add_argument(
        "--exclude-fixture",
        action="append",
        default=[],
        choices=sorted(FIXTURE_PREFIXES),
        help="Exclude all cases from a canonical fixture",
    )
    parser.add_argument(
        "--exclude-id-prefix",
        action="append",
        default=[],
        help="Exclude cases whose id starts with this prefix",
    )
    parser.add_argument(
        "--override-margin",
        type=float,
        default=0.1,
        help="Required score margin over baseline for non-baseline overrides",
    )
    parser.add_argument(
        "--min-non-baseline-feature-hits",
        type=int,
        default=2,
        help="Required non-baseline evidence features before overriding baseline",
    )
    parser.add_argument(
        "--min-reading-candidate-count-for-override",
        type=int,
        default=2,
        help="Required reading/candidate observations before overriding baseline",
    )
    parser.add_argument(
        "--disable-conservative-overrides",
        action="store_true",
        help="Use raw highest-score candidate selection without baseline gates",
    )
    parser.add_argument("--self-test", action="store_true")
    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()
    if args.self_test:
        sys.exit(run_self_test())
    if not args.input or not args.output:
        parser.error("--input and --output are required unless --self-test")

    excluded = build_excluded_prefixes(args.exclude_fixture, args.exclude_id_prefix)
    try:
        counts, stats = train(args.input, excluded)
    except RuntimeError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        sys.exit(2)

    selection_controls = {
        "override_margin": args.override_margin,
        "min_non_baseline_feature_hits": args.min_non_baseline_feature_hits,
        "min_reading_candidate_count_for_override": (
            args.min_reading_candidate_count_for_override
        ),
        "prefer_baseline_on_weak_override": (
            not args.disable_conservative_overrides
        ),
    }
    model = make_model(
        counts, stats, excluded, args.input, selection_controls
    )
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(model, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")

    print(
        "trained candidate ranker: "
        f"usable={stats['usable_cases']} excluded={stats['excluded_cases']} "
        f"output={args.output}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
