# macOS Experimental Reranker Dogfood Runbook

## Goal

Validate that the experimental contextual reranker preference can be enabled,
disabled, and evaluated without changing privacy boundaries or disrupting
ordinary typing.

This runbook is content-free by design. Do not collect raw typed text,
Bopomofo readings, candidate strings, committed text, screenshots containing
private text, or user phrase files.

## Preconditions

- Build and install a macOS development build from the active branch.
- Confirm `.github/workflows/continuous-integration-workflow-xcode-latest.yml`
  passes for the active branch before dogfooding runtime behavior.
- Confirm the input menu exposes `Experimental Contextual Reranker`.
- Confirm the default mode is `Off` after a clean preferences reset.
- Confirm the current branch has passing evaluator benchmarks for the intended
  scorer mode.
- Keep a rollback build or installer available.

## Modes

| Mode | Purpose | Expected Behavior |
| --- | --- | --- |
| Off | Baseline dogfood control | Same behavior as existing McBopomofo |
| Deterministic | Phase 3 synchronous scorer path | Low-latency deterministic corrections only |
| SLM Prototype | Future async/pre-commit prototype | Must not block rapid typing |

Do not dogfood `SLM Prototype` until a separate runtime implementation has
content-free counters, timeout handling, and fail-closed behavior.

## Checklist

Record pass/fail and a non-content note for each item.

| Area | Check |
| --- | --- |
| Toggle | Switch Off -> Deterministic -> Off without reinstalling |
| Baseline | Off mode matches normal typing behavior |
| Long composition | Long composing buffer remains responsive |
| Candidate UI | Candidate window ordering and selection keys remain predictable |
| English mixed | Protected English spans do not cause spacing regressions |
| User phrases | User phrase and excluded phrase behavior remains intact |
| Phrase replacement | Existing phrase replacement behavior remains intact |
| Rapid typing | Fast consecutive keystrokes do not stall or drop input |
| Input method switching | Switching away and back preserves safe state |
| Error handling | Invalid/missing scorer state falls back without losing text |
| Privacy | Logs and reports contain no typed content |

## Metrics To Record

Use buckets or counts only.

- Mode under test.
- Build identifier.
- Session duration bucket.
- Number of fallback events.
- Number of visible candidate-order surprises.
- Latency bucket counts: `<2ms`, `2-20ms`, `20-100ms`, `>100ms`.
- Crash or hang count.
- User-disabled-due-to-latency count.

## Issue Template

```
Mode:
Build:
Environment:
Category: latency | candidate-order | fallback | crash | privacy | other
Severity: low | medium | high | blocker
Synthetic reproduction:
Expected behavior:
Actual behavior summary:
Observed latency bucket:
Fallback observed: yes | no | unknown
Private content included: no
```

If an issue cannot be reproduced without private text, summarize the behavior
and create a synthetic fixture separately. Do not attach the private text.

## Stop Conditions

- Any log, report, crash artifact, or issue contains raw typed content.
- The reranker causes committed text loss.
- Rapid typing visibly stalls in normal writing.
- Users disable the feature because latency or candidate ordering is surprising.
- Candidate behavior cannot be explained with a synthetic reproduction.

## Exit Criteria

- Off mode remains unchanged.
- Deterministic mode can be toggled without reinstalling.
- No typed content appears in collected artifacts.
- No blocker issues remain open.
- All issues have content-free categories and synthetic reproduction paths.
