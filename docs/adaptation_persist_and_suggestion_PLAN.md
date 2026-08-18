# Persist and suggestion plan

Date: 2026-08-18  
Parent: `docs/台灣繁中注音輸入法_2026_08_方向重評.md`  
User decision this session: no silent per-key re-suggest; persist the override memory; treat later training as a separate local store.

## Need

The user does not want the composing buffer to flip earlier characters as later syllables arrive. A single, meaningful suggestion that changes several characters at once is acceptable. Override memory must survive restart. That file is not automatically a public n-gram or SLM corpus.

## Two stores

| Store | Purpose | Default | Contains |
|---|---|---|---|
| UserOverrideModel persist | Product recall after restart (A–C) | On, local, deletable | Observation keys, chosen candidates, counts, timestamps |
| L1 habit events | Later local adapter / ranker training | Off until the user opts in (`docs/台灣繁中注音輸入法_本機習慣收集與Adapter訓練.md`) | Short context, readings, top vs chosen candidate |

Public n-gram training still uses the existing manifest only. It does not read either store.

## Suggestion protocol (not K2 silent re-suggest)

Do not change KeyHandler to re-suggest every earlier node after each insert. That is the path that shows `再` in the middle of `在吃飯`.

Allowed later: after a pause or before commit, if a multi-character candidate already in the engine list is a meaningful correction, show it once for the user to accept. One accept may change several characters. The model still may not invent text outside engine candidates.

2026-08-18 candidate probe (`docs/reports/experiments/adaptation/uom_candidates_2026_08_18.md`): `別再說` is not an engine candidate. The four transfer misses have `別再`, `再說`, `再說`, and `做事`. A later UI may offer those. It may not synthesize `別再說`.

2026-08-18 oneshot replay (`docs/reports/experiments/adaptation/uom_oneshot_2026_08_18.md`): accepting one engine candidate after the full probe fixed three transfer misses (`別再說`, `不要再說`, `別做事`). The offer on `別在說` was `再說`, not `別再`. `再說一遍` stayed `再說一變`. `prefix_harms` 0. KeyHandler still unchanged.

## Persist slice (implemented 2026-08-18)

1. Engine test `SaveLoadRoundTrip` is green. `save` / `load` reject `/tmp` and `/var/tmp`.
2. File format: `# McBopomofo-UserOverrideModel 1` then TSV rows `key`, `candidate`, `override_count`, `timestamp`, `force`, `observation_count`. Write is atomic (`*.writing` then rename).
3. Replay `--persist=path`: default path still has `restart_hits 0`; persist path has `restart_hits 2` on `adaptation_replay.jsonl` (same two same-key hits). Report: `docs/reports/experiments/adaptation/uom_persist_2026_08_18.md`.
4. Runtime: `LanguageModelManager.userOverrideModelDataPath` is `user-override-model.txt` next to `data.txt`. Load runs with user phrases. `KeyHandler` saves after `observe`. The file is created on the first override, not at install. Deleting it clears memory after the next restart. macOS / Ubuntu dogfood still needs the user.

Out of scope in this slice: silent K2 wiring, n-gram / SLM training, uploading events, changing half-life, menu item to open the file.
