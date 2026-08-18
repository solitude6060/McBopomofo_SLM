# UserOverrideModel 半衰期量測（2026-08-18）

計畫：`docs/adaptation_halflife_and_ngram_PLAN.md`  
Runner：`Tools/ContextualEvaluation/uom_replay.cpp`  
Validator：`Tools/ContextualEvaluation/validate_uom_replay.py`  
資料：`Source/Data/data.txt`  
Fixture：`Tests/fixtures/contextual_bopomofo/adaptation_replay.jsonl`  
摘要：`docs/reports/experiments/adaptation/uom_halflife_2026_08_18_summary.json`  
各臂摘要列：`docs/reports/experiments/adaptation/uom_halflife_2026_08_18.jsonl`

這次只加 replay 量測旗標。產品半衰期維持 5400。公開 n-gram 未開。未改 `LanguageModelManager.mm` 的 `kObservedOverrideHalflife`。

## 旗標

| 旗標 | 語意 |
|---|---|
| `--halflife=<seconds>` | 只傳給 `UserOverrideModel` 建構式。預設 5400。Persist TSV 存時間戳，不存半衰期。 |
| `--suggest-delay=<seconds>` | 只加在 suggest 時間戳。observe 維持 `kNow = 1657772432.0`。 |

分數公式（`Source/Engine/UserOverrideModel.cpp` 的 `Score`）：

`Score = (count/total) * exp((now-ts)*ln(0.5)/halflife)`

`decay < 1/1048576` 時分數為 0。`UserOverrideModelTest.BasicOperation` 在 `kHalflife * 20` 仍有建議，在 `* 21` 為空。

## RED

在尚未解析旗標的 runner 上：

```text
cd /home/ma/Research/side_project/llm_typing/McBopomofo_SLM-wt-halflife/Tools/ContextualEvaluation
python3 validate_uom_replay.py --halflife=5400 --suggest-delay=108000
# REPLAY FAIL: exit 1: FATAL: unknown argument --halflife=5400
python3 validate_uom_replay.py --suggest-delay=0
# REPLAY FAIL: exit 1: FATAL: unknown argument --suggest-delay=0
./build/uom_replay ../../Source/Data/data.txt ../../Tests/fixtures/contextual_bopomofo/adaptation_replay.jsonl --halflife=5400 --suggest-delay=108000
# FATAL: unknown argument --halflife=5400
```

## GREEN

```text
python3 validate_uom_replay.py --self-test
python3 validate_uom_replay.py --suggest-delay=0
# REPLAY PASS: ... same_key 2/5, transfer 0/8, harmful 0, restart_hits 0, prefix_harms 0, halflife 5400, suggest_delay 0.0
python3 validate_uom_replay.py --halflife=5400 --suggest-delay=108000
# REPLAY PASS: ... same_key 2/5 ... suggest_delay 108000.0
python3 validate_uom_replay.py --halflife=5400 --suggest-delay=113400
# REPLAY PASS: ... same_key 0/5 ... suggest_delay 113400.0
python3 validate_uom_replay.py
python3 validate_uom_replay.py --persist
python3 validate_uom_replay.py --oneshot
# oneshot_transfer_hits 3, oneshot_extra 3, prefix_harms 0
```

`Source/Engine/build/McBopomofoLMLibTest --gtest_filter='UserOverrideModelTest.*'`：6 tests passed。

108000 秒是半衰期 5400 的剛好 20 倍。該點 `decay == 1/1048576`，分數仍非零，`same_key_hits` 仍為 2。113400 秒是 21 倍，`same_key_hits` 為 0。

## 矩陣

工作目錄：`/home/ma/Research/side_project/llm_typing/McBopomofo_SLM-wt-halflife`

```text
Tools/ContextualEvaluation/build/uom_replay \
  Source/Data/data.txt \
  Tests/fixtures/contextual_bopomofo/adaptation_replay.jsonl \
  --halflife=<seconds> --suggest-delay=<seconds>
```

| 實驗設定 | same_key_hits | transfer_hits | prefix_harms | harmful_overrides | 產物 |
|---|---|---|---|---|---|
| delay 0，半衰期 5400 | 2 | 0 | 0 | 0 | `docs/reports/experiments/adaptation/uom_halflife_d0_hl5400_2026_08_18.jsonl` |
| delay 28800（8 小時），半衰期 5400 | 2 | 0 | 0 | 0 | `docs/reports/experiments/adaptation/uom_halflife_d28800_hl5400_2026_08_18.jsonl` |
| delay 108000（20 個半衰期），半衰期 5400 | 2 | 0 | 0 | 0 | `docs/reports/experiments/adaptation/uom_halflife_d108000_hl5400_2026_08_18.jsonl` |
| delay 28800，半衰期 86400 | 2 | 0 | 0 | 0 | `docs/reports/experiments/adaptation/uom_halflife_d28800_hl86400_2026_08_18.jsonl` |
| delay 28800，半衰期 604800 | 2 | 0 | 0 | 0 | `docs/reports/experiments/adaptation/uom_halflife_d28800_hl604800_2026_08_18.jsonl` |

門檻核對（不列入上表五臂）：

| 實驗設定 | same_key_hits | transfer_hits | prefix_harms | harmful_overrides | 產物 |
|---|---|---|---|---|---|
| delay 113400（21 個半衰期），半衰期 5400 | 0 | 0 | 0 | 0 | `docs/reports/experiments/adaptation/uom_halflife_d113400_hl5400_2026_08_18.jsonl` |

五臂的 `harmful_overrides` 與 `prefix_harms` 皆為 0。未建議改產品半衰期。

## 產品常數

`Source/LanguageModelManager.mm` 第 34 行仍為：

```text
static const double kObservedOverrideHalflife = 5400.0; // 1.5 hr.
```

倉庫內沒有論文推出 5400。註解只有 `// 1.5 hr.`

## 結論範圍

Replay 現在可以用 `--suggest-delay` 移動 suggest 時間。預設記憶體上，delay 0 維持 same-key 2／transfer 0／restart 0。剛好 20 個半衰期仍維持 same-key 2。超過 20 個半衰期後 same-key 降為 0。

未做 macOS 隔夜實機。未改產品 5400。未訓公開 n-gram。改 `LanguageModelManager.mm` 仍要使用者閘門。
