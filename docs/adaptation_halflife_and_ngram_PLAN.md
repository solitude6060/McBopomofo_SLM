# Half-life and public n-gram (deferred) Implementation Plan

> Survey: `../../docs/survey/2026-08-18_oneshot_ui_commit_halflife_ngram.md`. Do not change production half-life. Do not train n-gram in this file’s first tasks.

**Goal:** Write the exact continue / stop gates so a later session does not open these arms because transfer is still 0/8 on the silent three-node path.

**Architecture:** Half-life is a replay-only arm after persist dogfood. Public n-gram is a single 5-gram experiment after a product increment or a D break, not a six-stage trainer ladder.

**Tech Stack:** Existing `UserOverrideModel` score, `uom_replay`, frozen fixtures, `Tools/Training/bigram_trainer.py` (already equal to baseline).

**Spec:** `docs/台灣繁中注音輸入法_2026_08_方向重評.md` §第 2 步 and item 2 (5400 s).

## Global Constraints

- Production `kObservedOverrideHalflife` stays 5400.0 until a measured arm plus user gate.
- Official fcitx5-mcbopomofo uses the same 5400.0 (`fcitx5-mcbopomofo/src/KeyHandler.cpp`).
- Do not train on dataset 7307 while it is held-out.
- Do not copy librime-octagram sources.
- Do not use OpenCC `s2tw` of People’s Daily as Taiwan text.
- Paid ASBC / news / LDC remain user applications.

---

## Half-life

### Why not now

Persist just started writing timestamps to disk. Overnight recall is unmeasured on a real Mac. Changing 5400 s in the same era as persist would confound “file missing” with “score decayed”. No paper in the repo derives 5400; the comment is only `// 1.5 hr.` The persist TSV does not store half-life. Replay uses one `kNow` for observe and suggest, so changing `kHalfLife` alone does not move current replay counts.

`Score = (count/total) * exp((now-ts)*ln(0.5)/5400)`. Twenty half-lives (~30 h) reach the coded zero threshold (`kDecayThreshold = 1/1048576`). Twelve hours is already ~8 half-lives.

Tokunaga, Kazama, and Torisawa, WTIM 2011: personalization can make conversion worse. Forgetting stays until dogfood shows harmless overnight misses.

### When to open

1. Persist dogfood on macOS: a same-key pair still works after a restart **in the same hour**.
2. Repeat the pair after ≥8 h. If the file still contains the row and `suggest` is empty, decay is the cause.
3. Only then add replay `--halflife=5400|86400|604800` with a timestamp offset, same fixture, require `harmful_overrides` 0 and `prefix_harms` 0.
4. User gate before changing `LanguageModelManager.mm`.

### Out of scope until that gate

7-day / 30-day production defaults, per-key half-life, uploading events.

---

## Public n-gram

### Why not now

方向重評 §第 2 步 opens n-gram only if A–C still needs cross-sentence generalization **after** a product increment, or D breaks.

Current measurements:

- Silent transfer 0/8 (not a reason to train; oneshot already names a cheaper increment).
- Oneshot extra 3, not wired to KeyHandler (product increment still pending).
- 234/234 and 63/63 intact (D not broken).
- `Tools/Training/` contains `bigram_trainer.py` only. `Models/bigram_model.bin` is referenced and absent. There is no `corpus_manifest.json`. The six-stage file remains deferred practice.

### When to open (single experiment, not a ladder)

1. KeyHandler oneshot is dogfooded, **or** the user rejects oneshot UI.
2. Informative transfer misses that remain are **not** fixable by an engine candidate (oneshot offered empty, or accept cannot reach expected).
3. Or saturated 234 / clean 63 regresses.

Then one run: licensed Taiwan Traditional running text from the existing public manifest; character 5-gram + backoff; compare baseline / frozen deterministic / current UOM / n-gram / sum on **frozen** held-out only.

Pass: improved > regressed on that held-out; 234 not worse; p95 < 2 ms or pre-commit only.

Fail: stop learned scorers; keep frozen rules + A–C.

### Explicitly not a prerequisite

MozTW / 法規 extra held-out, ASBC application, KenLM, trigram homework, training on 7307 names.
