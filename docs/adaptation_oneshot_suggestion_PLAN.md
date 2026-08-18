# One-shot multi-character suggestion Implementation Plan

> Replay-only slice. KeyHandler is unchanged until this measurement is green.

**Goal:** After the user has taught an override, measure whether accepting one engine multi-character candidate (not invented text) can fix a transfer miss without mid-input flips.

**Architecture:** Keep the production three-node key during insert. Also store a `head_next` key at observe time. After the probe has all readings, look up `head_next` at each cursor, find the longest engine candidate that contains that suggestion and is not already selected, and apply it once with a high-score override. That apply is the replay stand-in for "user accepts once".

**Tech Stack:** C++17 `uom_replay`, Python validator, existing `UserOverrideModel` and `ReadingGrid`.

**Spec:** `docs/adaptation_persist_and_suggestion_PLAN.md`, `docs/台灣繁中注音輸入法_2026_08_方向重評.md`

## Global Constraints

- Do not re-suggest earlier nodes after each insert.
- Do not invent text outside `candidatesAt`.
- Do not offer `別再說` as a whole phrase; it is not a candidate.
- Do not change production half-life or the default three-node key used while typing.
- Do not train n-gram or SLM.
- Do not write new rows into frozen 234/63 fixtures.
- Do not commit unless the user asks.
- Persist files stay out of `/tmp`.

## First principles

1. Need: fewer repeated corrections on transfer sentences.
2. Assumption: a `head_next` memory of `再` / `做事` plus a two-character engine candidate can beat `別在` / `作是`, which a soft single-character override cannot.
3. That assumption is verified for candidate existence (`uom_candidates_2026_08_18.md`) and for K2 losing `別在說` to `別在`.
4. If wrong, `oneshot_transfer_hits` stays 0 and this slice stops.
5. This addresses the transfer miss, not mid-input flicker.

## Result (2026-08-18)

`--oneshot` on `adaptation_replay.jsonl`: `oneshot_transfer_hits` 3, `oneshot_extra` 3, `prefix_harms` 0. Offered `再說` / `再說` / `再說` / `做事`. `別在說` became `別再說` after accepting `再說`. `再說一遍` became `再說一變`. KeyHandler not wired.

## Exit

On `adaptation_replay.jsonl` with `--oneshot`:

- `oneshot_transfer_hits >= 1`
- `prefix_harms == 0`
- `harmful_overrides == 0`
- default path without `--oneshot` unchanged (`restart_hits 0`, transfer 0/8)

## Tasks

### Task 1: Failing validator (RED)

Add `--oneshot` to `uom_replay` that reports `oneshot_offered`, `oneshot_hits`, `oneshot_transfer_hits`, `oneshot_extra` as zeros without applying a candidate. Validator `--oneshot` requires `oneshot_transfer_hits >= 1`.

### Task 2: Apply one candidate (GREEN)

When `--oneshot`: observe `head_next` in addition to the typing key; after the full probe walk, apply at most one high-score multi-character override chosen from engine candidates that contain the `head_next` suggestion.

### Task 3: Record

Write `docs/reports/experiments/adaptation/uom_oneshot_2026_08_18.md` and update the persist/suggestion plan, 方向重評, 規劃索引, and the three management files. Do not wire KeyHandler.
