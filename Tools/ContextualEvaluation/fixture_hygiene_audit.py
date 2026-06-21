#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", ".."))
DATA_DIR = os.path.join(PROJECT_ROOT, "Source", "Data")
FIXTURES_DIR = os.path.join(
    PROJECT_ROOT, "Tests", "fixtures", "contextual_bopomofo"
)
REPORT_DIR = os.path.join(PROJECT_ROOT, "docs", "reports", "experiments", "phase2")
REGISTRY_PATH = os.path.join(
    PROJECT_ROOT, "docs", "reports", "experiments", "registry.json"
)

FIXTURES = {
    "heldout_generalization": "heldout_generalization.jsonl",
    "taiwan_ambiguous": "taiwan_ambiguous.jsonl",
    "english_mixed": "english_mixed.jsonl",
    "taiwan_specific": "taiwan_specific.jsonl",
}

CATEGORIES = [
    "exact_reading_compatible",
    "reading_mismatch",
    "insufficient_readings",
    "missing_candidate_for_reading",
    "phrase_length_or_segmentation_gap",
    "protected_token_alignment",
]

PUNCTUATION_TOKENS = {
    "？", "?", "，", ",", "。", ".", "！", "!", "：", ":", "；", ";", "、",
}


def is_bopomofo_codepoint(ch):
    cp = ord(ch)
    return (
        0x3100 <= cp <= 0x312F
        or 0x31A0 <= cp <= 0x31BF
        or cp in {0x02CA, 0x02C7, 0x02CB, 0x02D9}
    )


def is_bopomofo_reading(token):
    return (
        bool(token)
        and token != "ㄎㄧㄤ"
        and all(is_bopomofo_codepoint(ch) for ch in token)
    )


def is_cjk(ch):
    return 0x4E00 <= ord(ch) <= 0x9FFF


def load_bpmf_base(path):
    readings_by_char = defaultdict(set)
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            parts = line.strip().split()
            if len(parts) >= 2:
                readings_by_char[parts[0]].add(parts[1])
    return {key: sorted(value) for key, value in readings_by_char.items()}


def load_phrase_mappings(path):
    readings_by_phrase = defaultdict(list)
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            parts = line.strip().split()
            if len(parts) >= 2:
                readings_by_phrase[parts[0]].append(tuple(parts[1:]))
    return dict(readings_by_phrase)


def load_data_candidates(path):
    values_by_key = defaultdict(set)
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.strip().split()
            if len(parts) >= 3:
                values_by_key[parts[0]].add(parts[1])
    return values_by_key


def load_jsonl(path):
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def cjk_text(value):
    return "".join(ch for ch in value if is_cjk(ch))


def phrase_sequences(phrase, bpmf_base, phrase_mappings):
    if len(phrase) == 1:
        return [(reading,) for reading in bpmf_base.get(phrase, [])]
    return phrase_mappings.get(phrase, [])


def segmentation_compatible(text, readings, bpmf_base, phrase_mappings):
    memo = {}

    def walk(char_index, reading_index):
        key = (char_index, reading_index)
        if key in memo:
            return memo[key]
        if char_index == len(text) and reading_index == len(readings):
            memo[key] = True
            return True
        if char_index >= len(text) or reading_index >= len(readings):
            memo[key] = False
            return False

        max_end = min(len(text), char_index + 8)
        for end in range(max_end, char_index, -1):
            phrase = text[char_index:end]
            for sequence in phrase_sequences(phrase, bpmf_base, phrase_mappings):
                next_reading = reading_index + len(sequence)
                if tuple(readings[reading_index:next_reading]) == tuple(sequence):
                    if walk(end, next_reading):
                        memo[key] = True
                        return True
        memo[key] = False
        return False

    return walk(0, 0)


def aligned_mismatch_count(text, readings, bpmf_base):
    return sum(
        1
        for char, reading in zip(text, readings)
        if reading not in bpmf_base.get(char, [])
    )


def missing_candidate_count(text, readings, bpmf_base, data_candidates):
    count = 0
    for char, reading in zip(text, readings):
        if reading in bpmf_base.get(char, []):
            if char not in data_candidates.get(reading, set()):
                count += 1
    return count


def protected_alignment_issue(case):
    expected = case.get("expected", "")
    protected = set(case.get("protected_english_spans", []))
    for token in case.get("readings", []):
        if is_bopomofo_reading(token) or token in PUNCTUATION_TOKENS:
            continue
        if token not in expected or (protected and token not in protected):
            return True
    return any(token not in expected for token in protected)


def classify_case(case, bpmf_base, phrase_mappings, data_candidates, debug=False):
    case_id = case.get("id", "")
    readings = [token for token in case.get("readings", []) if is_bopomofo_reading(token)]
    expected_cjk = cjk_text(case.get("expected", ""))
    secondary = []

    protected_issue = protected_alignment_issue(case)
    if protected_issue:
        secondary.append("protected_token_alignment")

    if not expected_cjk:
        category = "protected_token_alignment" if protected_issue else "exact_reading_compatible"
        return make_result(case_id, category, secondary, debug, {})

    compatible = segmentation_compatible(
        expected_cjk, readings, bpmf_base, phrase_mappings
    )
    if compatible and not protected_issue:
        return make_result(case_id, "exact_reading_compatible", secondary, debug, {})

    mismatch_count = aligned_mismatch_count(expected_cjk, readings, bpmf_base)
    candidate_missing = missing_candidate_count(
        expected_cjk, readings, bpmf_base, data_candidates
    )

    if len(readings) < len(expected_cjk):
        category = "insufficient_readings"
    elif mismatch_count:
        category = "reading_mismatch"
    elif candidate_missing:
        category = "missing_candidate_for_reading"
    elif protected_issue:
        category = "protected_token_alignment"
    else:
        category = "phrase_length_or_segmentation_gap"

    details = {}
    if debug:
        details = {
            "readings": readings,
            "expected_cjk": expected_cjk,
            "mismatch_count": mismatch_count,
            "missing_candidate_count": candidate_missing,
            "segmentation_compatible": compatible,
        }
    return make_result(case_id, category, secondary, debug, details)


def make_result(case_id, category, secondary, debug, details):
    result = {
        "id": case_id,
        "category": category,
        "secondary": sorted(set(item for item in secondary if item != category)),
    }
    if debug:
        result["debug"] = details
    return result


def summarize_fixture(name, cases):
    counts = Counter(case["category"] for case in cases)
    return {
        "fixture": name,
        "total_cases": len(cases),
        "categories": {category: counts.get(category, 0) for category in CATEGORIES},
        "problematic_cases": len(cases) - counts.get("exact_reading_compatible", 0),
        "problem_case_ids_by_category": {
            category: [case["id"] for case in cases if case["category"] == category]
            for category in CATEGORIES
            if category != "exact_reading_compatible" and counts.get(category, 0)
        },
    }


def run_audit(fixture_names, debug=False):
    bpmf_base = load_bpmf_base(os.path.join(DATA_DIR, "BPMFBase.txt"))
    phrase_mappings = load_phrase_mappings(os.path.join(DATA_DIR, "BPMFMappings.txt"))
    data_candidates = load_data_candidates(os.path.join(DATA_DIR, "data.txt"))
    return {
        fixture_name: [
            classify_case(
                case, bpmf_base, phrase_mappings, data_candidates, debug=debug
            )
            for case in load_jsonl(os.path.join(FIXTURES_DIR, FIXTURES[fixture_name]))
        ]
        for fixture_name in fixture_names
    }


def build_summary(results, elapsed_seconds):
    per_fixture = [summarize_fixture(name, cases) for name, cases in results.items()]
    aggregate_counts = Counter()
    total_cases = 0
    for item in per_fixture:
        total_cases += item["total_cases"]
        aggregate_counts.update(item["categories"])
    return {
        "audit": "fixture_hygiene_audit",
        "date": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "total_cases": total_cases,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "aggregate": {
            "categories": {
                category: aggregate_counts.get(category, 0)
                for category in CATEGORIES
            },
            "problematic_cases": total_cases - aggregate_counts.get(
                "exact_reading_compatible", 0
            ),
        },
        "per_fixture": per_fixture,
    }


def write_debug(results, path):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(results, handle, ensure_ascii=False, indent=2)


def write_report(summary, output_path):
    report = {
        "audit": "fixture_hygiene_audit",
        "date": summary["date"],
        "branch": current_branch(),
        "commit": current_commit(),
        "content_policy": {
            "raw_case_strings_in_report": False,
            "raw_debug_output_location": "/tmp/",
        },
        "total_cases": summary["total_cases"],
        "aggregate": summary["aggregate"],
        "per_fixture": summary["per_fixture"],
        "verification": [
            "python3 Tools/ContextualEvaluation/fixture_hygiene_audit.py --self-test",
            "python3 Tools/ContextualEvaluation/fixture_hygiene_audit.py --fixtures all",
        ],
        "next_steps": [
            "Use exact_reading_compatible cases for scorer and tiny-LLM promotion gates",
            "Fix or isolate reading-mismatch cases before treating them as model failures",
        ],
    }
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def current_branch():
    return run_git(["rev-parse", "--abbrev-ref", "HEAD"])


def current_commit():
    return run_git(["rev-parse", "HEAD"])


def run_git(args):
    try:
        return subprocess.check_output(
            ["git"] + args,
            cwd=PROJECT_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


def update_registry(summary):
    with open(REGISTRY_PATH, "r", encoding="utf-8") as handle:
        registry = json.load(handle)

    entry = {
        "id": "fixture-hygiene-audit",
        "name": "Fixture Hygiene Audit",
        "status": "verified",
        "date": summary["date"],
        "branch": current_branch(),
        "commit": current_commit(),
        "protocol_version": "1.0",
        "model": None,
        "results_dir": "docs/reports/experiments/phase2/",
        "summary_file": "docs/reports/experiments/phase2/fixture_hygiene_audit.json",
        "result_files": [
            "docs/reports/experiments/phase2/fixture_hygiene_audit.json"
        ],
        "description": "Content-free fixture/readings hygiene audit for contextual_bopomofo fixtures.",
        "total_cases": summary["total_cases"],
        "aggregate": summary["aggregate"],
        "verification": [
            "python3 Tools/ContextualEvaluation/fixture_hygiene_audit.py --self-test",
            "python3 Tools/ContextualEvaluation/fixture_hygiene_audit.py --fixtures all",
        ],
        "next_steps": [
            "Use exact_reading_compatible cases for scorer and tiny-LLM promotion gates",
            "Fix or isolate reading-mismatch cases before treating them as model failures",
        ],
    }

    experiments = registry.setdefault("experiments", [])
    experiments[:] = [
        item for item in experiments if item.get("id") != "fixture-hygiene-audit"
    ]
    experiments.append(entry)

    with open(REGISTRY_PATH, "w", encoding="utf-8") as handle:
        json.dump(registry, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def export_clean_cases(fixture_name, results_map):
    cases = results_map.get(fixture_name, [])
    fixture_file = FIXTURES[fixture_name]
    all_cases = load_jsonl(os.path.join(FIXTURES_DIR, fixture_file))

    clean_ids = {
        case["id"]
        for case in cases
        if case["category"] == "exact_reading_compatible"
    }
    clean_cases = [c for c in all_cases if c["id"] in clean_ids]
    blocked_ids = sorted(
        {case["id"] for case in cases if case["category"] != "exact_reading_compatible"}
    )

    out_path = os.path.join(tempfile.gettempdir(), f"{fixture_name}_clean.jsonl")
    with open(out_path, "w", encoding="utf-8") as handle:
        for case in clean_cases:
            handle.write(json.dumps(case, ensure_ascii=False) + "\n")

    return {
        "path": out_path,
        "fixture": fixture_name,
        "total": len(all_cases),
        "clean": len(clean_cases),
        "blocked": len(cases) - len(clean_cases),
        "blocked_ids": blocked_ids,
        "clean_ids": sorted(clean_ids),
    }


def self_test():
    assert is_bopomofo_reading("ㄨㄛˇ")
    assert not is_bopomofo_reading("ㄎㄧㄤ")
    assert not is_bopomofo_reading("AI")
    assert cjk_text("用 AI 分析") == "用分析"
    bpmf_base = load_bpmf_base(os.path.join(DATA_DIR, "BPMFBase.txt"))
    phrase_mappings = load_phrase_mappings(os.path.join(DATA_DIR, "BPMFMappings.txt"))
    data_candidates = load_data_candidates(os.path.join(DATA_DIR, "data.txt"))
    assert "我" in bpmf_base
    assert "朋友" in phrase_mappings
    assert "ㄨㄛˇ" in data_candidates
    case = {
        "id": "self-test",
        "readings": ["ㄨㄛˇ"],
        "expected": "我",
        "protected_english_spans": [],
    }
    result = classify_case(case, bpmf_base, phrase_mappings, data_candidates)
    assert result["category"] == "exact_reading_compatible", result


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixtures",
        nargs="+",
        default=list(FIXTURES.keys()),
        choices=list(FIXTURES.keys()) + ["all"],
    )
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--update-registry", action="store_true")
    parser.add_argument(
        "--export-clean",
        nargs="+",
        metavar="FIXTURE",
        choices=list(FIXTURES.keys()) + ["all"],
        help="Export exact_reading_compatible cases as clean JSONL to /tmp/",
    )
    return parser.parse_args()


def resolve_fixture_names(names):
    return list(FIXTURES.keys()) if "all" in names else names


def main():
    args = parse_args()
    if args.self_test:
        self_test()
        print("self-test passed", file=sys.stderr)
        return 0

    fixture_names = resolve_fixture_names(args.fixtures)
    export_fixtures = (
        resolve_fixture_names(args.export_clean) if args.export_clean else []
    )
    audit_fixtures = list(dict.fromkeys(fixture_names + export_fixtures))
    start = time.time()
    results = run_audit(audit_fixtures, debug=args.debug)
    display_results = {name: results[name] for name in fixture_names}
    summary = build_summary(results, time.time() - start)

    if args.verbose:
        for fixture_name, cases in display_results.items():
            for case in cases:
                print(json.dumps({"fixture": fixture_name, **case}, ensure_ascii=False))

    if export_fixtures:
        summary["clean_exports"] = [
            export_clean_cases(name, results) for name in export_fixtures
        ]

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.debug:
        path = os.path.join(
            tempfile.gettempdir(), f"fixture_hygiene_audit_{int(start)}.json"
        )
        write_debug(results, path)
        print(f"debug={path}", file=sys.stderr)

    if args.report:
        os.makedirs(REPORT_DIR, exist_ok=True)
        report_path = os.path.join(REPORT_DIR, "fixture_hygiene_audit.json")
        write_report(summary, report_path)
        if args.update_registry:
            update_registry(summary)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
