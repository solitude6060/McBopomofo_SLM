# One-shot macOS composing suggestion Implementation Plan

> **For agentic workers:** Execute task-by-task with TDD. Do not wire silent per-key re-suggest. Do not commit unless the user asks.

**Goal:** On macOS McBopomofo, show at most one engine multi-character candidate before commit; apply it only if the user accepts.

**Architecture:** Extract `applyOneshot` from `uom_replay.cpp` into the engine. KeyHandler keeps the three-node suggest-on-insert path. On the first commit key (Enter, or Space-at-end that would commit), if the picker offers a value, push a one-candidate immutable `InputState`. Accept runs a high-score `overrideCandidate` and returns to `Inputting`. Dismiss commits the original buffer.

**Tech Stack:** C++17 engine, Objective-C++ `KeyHandler.mm`, Swift `InputState` / CandidateUI, existing `uom_replay --oneshot`.

**Spec:** `docs/adaptation_persist_and_suggestion_PLAN.md`, `docs/adaptation_oneshot_suggestion_PLAN.md`, `../../docs/survey/2026-08-18_oneshot_ui_commit_halflife_ngram.md`

## Global Constraints

- Do not re-suggest earlier nodes after each insert.
- Do not invent text outside `ReadingGrid::candidatesAt`.
- Do not offer `別再說` as a whole phrase.
- Do not add an NSTimer in the first slice.
- Do not reuse `handleAssociatedPhraseWithState` to pick the candidate (that path appends associations).
- Do not change half-life or train n-gram.
- Linux tests: `uom_replay --oneshot` must stay green after the extract.
- macOS UI tests require Xcode; they are a later dogfood gate.

---

### Task 1: Extract picker (RED then GREEN)

**Files:**

- Create: `Source/Engine/OneShotOverride.h`, `Source/Engine/OneShotOverride.cpp`
- Modify: `Source/Engine/CMakeLists.txt`, `Tools/ContextualEvaluation/uom_replay.cpp`
- Test: `Source/Engine/OneShotOverrideTest.cpp` (string-key UOM + a tiny in-grid fixture if a test language model already exists; otherwise a focused test that the function returns empty on a null UOM / empty grid) plus `python3 Tools/ContextualEvaluation/validate_uom_replay.py --oneshot`

**Interfaces:**

- Consumes: `UserOverrideModel::suggest(const std::string&, double)`, `ReadingGrid::candidatesAt`, `syllableKey` / `head_next` construction now in `uom_replay.cpp`
- Produces: `McBopomofo::PickOneShotOverride(grid, uom, timestamp) -> {loc, value}` empty if none

- [ ] Move `applyOneshot` / `syllableKey` helpers used by oneshot into the engine without changing replay numbers.
- [ ] Run `validate_uom_replay.py --oneshot`. Expect the same summary: `oneshot_transfer_hits` 3, `prefix_harms` 0.
- [ ] Run `UserOverrideModelTest.*` and the new test.

---

### Task 2: Dual observe in KeyHandler (after extract)

**Files:**

- Modify: `Source/KeyHandler.mm` around `fixNodeWithReading:` (observe at 302)

**Behavior:** After the existing walk `observe`, also store the `head_next` string key the replay uses (first differing reading, next syllable, top unigram before override). Then `saveUserOverrideModel`. Without this, the picker has nothing to look up after `請再說一次`.

- [ ] Add a failing engine or replay-adjacent test that KeyHandler-shaped observe stores both keys (if that cannot be expressed without `.mm`, document that replay already stores both and keep this task as a KeyHandler-only change verified on Mac).
- [ ] Implement the extra `observe(key, candidate, timestamp)` call. Do not change the insert-time three-node `suggest`.

---

### Task 3: InputState and commit intercept

**Files:**

- Modify: `Source/InputState.swift` (new `InputState.OneShotSuggestion: NotEmpty, CandidateProvider`)
- Modify: `Source/KeyHandler.mm` `_handleEnterWithState:` (1339), Space-at-end commit (706–718)
- Modify: `Source/InputMethodController+CandidateControllerDelegate.swift` `didSelectCandidateAtIndex`
- Modify: `Source/KeyHandler.mm` Esc / associated-phrase dismiss patterns (530–536) so Esc on oneshot returns to `Inputting` without applying

**Behavior:**

1. Compute the offer only when the reading buffer is empty and a commit key is about to fire.
2. If offer empty, existing commit.
3. If offer present, `stateCallback` a `OneShotSuggestion` with exactly one `Candidate` (`reading` + `value` from the engine candidate). Composing buffer unchanged.
4. Accept: `overrideCandidate(loc, value, kOverrideValueWithHighScore)`, walk, `buildInputtingState`. Do not commit in the same key.
5. Second Enter from `Inputting` commits as today.
6. On the oneshot state: Enter accepts (this is a commit-intercept, not associated-phrase autoTrigger). Esc or keep-typing dismisses without applying. A second explicit “commit original” path (Enter after dismiss, or force-commit) must not apply the offer.
7. Do not copy associated-phrase Shift+Enter-only accept unless the state is marked `autoTriggered`. That convention exists for after-insert associations (`KeyHandler.mm` 1509–1511) and would surprise a user who just pressed Enter to commit.
8. `handleForceCommitWithStateCallback:` must commit the original buffer.
9. If `Preferences.associatedPhrasesEnabled` would also fire on insert, leave that path alone (`associatedPhrasesEnabled` defaults to false).

- [ ] Write the Swift state as an immutable snapshot. Do not mutate `InputState` instances.
- [ ] Do not replace AppKit candidate UI with SwiftUI.

---

### Task 4: Preference (optional, same PR if small)

**Files:** `Source/Preferences.swift`, `zh-Hant.lproj/Localizable.strings`, `en.lproj/Localizable.strings`

Default on. Toggle off disables the intercept only. Persist file and three-node suggest stay on.

---

### Task 5: Record and dogfood gate

- [ ] Update `docs/adaptation_oneshot_suggestion_PLAN.md` with the KeyHandler protocol.
- [ ] macOS dogfood: teach `請再說一次`, type `別在說`, press Enter once, expect `再說` in the one-candidate window, accept, expect composing `別再說`, Enter again to commit.
- [ ] Confirm `在吃飯` does not flip mid-input (existing three-node path).

Ubuntu official fcitx5 is a separate repo and is out of this plan.
