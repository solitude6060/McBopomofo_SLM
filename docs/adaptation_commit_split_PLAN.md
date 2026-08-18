# Uncommitted work split Implementation Plan

> Survey: `../../docs/survey/2026-08-18_oneshot_ui_commit_halflife_ngram.md`. Do not commit until the user asks. This file is the split, not a commit.

**Goal:** When the user asks to commit, land independently reviewable Conventional Commit slices on `McBopomofo_SLM` (`slm-phase2-learnable`) without mixing frozen-fixture policy, PII, or build trees.

**Architecture:** Inner repo is the history that matters. The outer `llm_typing` tree currently has no commits; do not invent an outer history unless the user asks. Each slice below is one commit. TDD pairs (test then feat) stay adjacent and may be two commits on the same slice.

**Tech Stack:** git on `McBopomofo_SLM` only, unless the user explicitly wants the outer wrapper recorded.

**Spec:** User commit rules in the conversation; Conventional Commits; no AI `Co-Authored-By` trailer.

## Global Constraints

- Do not commit `data/opendata/7307_orglist.big5.csv` (addresses and phones).
- Do not commit `docs/reports/experiments/adaptation/uom_replay_2026_08_17.jsonl` (0 bytes; canonical is `_v3.jsonl`).
- Do not commit `Tools/ContextualEvaluation/build/`, `build_fcitx_original/`, `.omo/`, `.sisyphus/`, outer `.omc/`, outer `fcitx5-mcbopomofo/`.
- Do not mix Step 0 freeze files with adaptation replay reports in one commit if a reviewer would want to revert one without the other.
- Inspect `docs/台灣繁中注音輸入法_台灣語料路線.md` before adding it; the current session did not own that diff.
- Do not `git add -A`.
- Do not push unless asked.
- Replay flags live in one `uom_replay.cpp`. Do not pretend `--persist` and `--oneshot` are separate files.

---

## Recommended order

Freeze first (below, Slice F moved to first). Then persist engine, persist IME, replay, UOM reports, new held-out, direction.

### Slice F0 — `test(eval)`: freeze (do this first)

Together: `fixture_rule_freeze.json`, `validate_fixture_rule_freeze.py`, `docs/FIXTURE_RULE_FREEZE.md`.

Subject: `test: freeze contextual fixture rules`

The frozen 234/63 JSONLs and `DeterministicContextualScorer` are clean. Do not add new sentences.

### Slice A — `test` + `feat(engine)`: persist

Together: `UserOverrideModel.h`, `UserOverrideModel.cpp`, `UserOverrideModelTest.cpp`.

Subject: `feat(engine): persist UserOverrideModel to a local file`

Why: TDD pair for `save` / `load`. Reviewable without macOS.

### Slice B — `feat(ime)`: persist path

Together: `LanguageModelManager.h`, `LanguageModelManager.mm`, `KeyHandler.mm` (the save-after-observe line only).

Subject: `feat(ime): write user-override-model.txt next to data.txt`

Depends on A.

### Slice C — `test` + `feat(eval)`: replay runner

Together: `Tools/ContextualEvaluation/CMakeLists.txt`, `uom_replay.cpp`, `validate_uom_replay.py`, `validate_adaptation_replay_schema.py`, `adaptation_replay_CONTRACT.md`, fixtures `adaptation_replay.jsonl`, `adaptation_key_harm.jsonl`, `adaptation_key_shared.jsonl`.

Subject: `feat(eval): add UserOverrideModel walk replay`

This is the largest slice. Flags cannot be split by file. If history must show red/green, use sequential patches on the same files: default replay, then `--key`/`--memory`, then `--persist`, then `--oneshot`. Do not split a flag from its validator. `--candidates` has no validator flag; land it with the oneshot/candidate reports.

### Slice D — `docs`: adaptation measurements

Together: `docs/reports/experiments/adaptation/*` (all uom_* and heldout report files except those that belong in E), `docs/adaptation_*_PLAN.md`, `docs/reports/experiments/registry.json` hunks for those ids.

Subject: `docs: record UOM replay, persist, key arms, and oneshot`

Depends on C if the reports cite the runner.

### Slice E — `test` + `docs`: new held-out

Together: `heldout_opendata_names_2026_08_18.jsonl`, `write_opendata_heldout.py`, `data/opendata/README.md`, `data/opendata/7307_org_names.txt`, held-out reports. **Exclude** `7307_orglist.big5.csv`.

Subject: `test: add OGDL name held-out disjoint from frozen fixtures`

### Slice G — `docs`: direction

Together: `docs/台灣繁中注音輸入法_2026_08_方向重評.md`, `docs/台灣繁中注音輸入法_規劃索引.md`, GROK review + FIX_LOG if they belong with the direction text.

Subject: `docs: record 2026-08 adaptive IME direction`

### Slice H — outer management files (only if the user wants the wrapper repo initialized)

`status.md`, `tracker.md`, `handover.md`, `docs/survey/2026-08-18_oneshot_ui_commit_halflife_ngram.md`. The outer repo has no commits today. Initializing it is a separate user decision.

---

## Verification before each commit

```text
cd McBopomofo_SLM/Source/Engine/build && ./McBopomofoLMLibTest --gtest_filter='UserOverrideModelTest.*'
cd McBopomofo_SLM/Tools/ContextualEvaluation && python3 validate_uom_replay.py && python3 validate_uom_replay.py --persist && python3 validate_uom_replay.py --oneshot
```

Do not add `Co-Authored-By` or generated-with footers.

Inner PR grouping if the user wants fewer reviews: freeze | persist (A+B) | replay (C) | UOM reports (D) | new held-out (E) | direction (G). Keep E out of the freeze commit. Bump the outer gitlink only after inner commits land. Add a `uom-candidates` registry row if those two files are committed.
