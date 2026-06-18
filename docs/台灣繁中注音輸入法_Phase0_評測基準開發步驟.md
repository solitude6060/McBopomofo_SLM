# Phase 0：評測基準開發步驟

最後更新：2026-06-18

## 目標

建立可重現的台灣繁中注音評測基準，用現有小麥注音引擎證明目前錯誤類型、候選排名與延遲。這一階段不導入模型，也不改候選排序。

狀態：已完成，完成日期 2026-06-18。基準報告位於 `docs/reports/phase0_baseline_report.md` 與 `docs/reports/phase0_baseline_report.json`。

## 讀檔順序

1. `docs/台灣繁中注音輸入法_規劃索引.md`
2. `docs/台灣繁中注音輸入法_產品需求.md`
3. `docs/台灣繁中注音輸入法_技術規格.md`
4. `docs/台灣繁中注音輸入法_速度需求.md`
5. `docs/台灣繁中注音輸入法_台灣語料路線.md`
6. `algorithm.md`
7. `Source/Engine/gramambular2/reading_grid.h`
8. `Source/Engine/McBopomofoLM.cpp`

## 開發步驟

1. 定義評測資料格式。
   - 欄位至少包含 `id`、`readings`、`expected`、`domain`、`source`、`license`、`redistributable`、`protected_english_spans`。
   - `redistributable` 必須明確標示是否可放入公開 repo。
   - 必須能對應 `docs/台灣繁中注音輸入法_台灣語料路線.md` 的來源分類。
2. 建立手寫測試集。
   - 至少 50 句台灣繁中歧義句。
   - 至少 20 句英文混輸句。
   - 每句都要能追溯來源；授權不清楚者只能作本機私有測試，不能 commit。
   - 教育部 / 萌典資料只能作讀音與歧義詞種子；公開句子應由專案手寫或來自允許改作的來源。
   - 政府開放資料可作機關名、地名、法規名等命名實體來源，需保存顯名資訊。
3. 建立重播工具。
   - 輸入注音序列。
   - 呼叫現有小麥注音引擎。
   - 輸出最佳候選、目標候選排名、缺讀音、耗時。
4. 使用 `ReadingGrid::WalkResult::elapsedMicroseconds` 取得基準延遲。
5. 產出報告。
   - JSON 報告供程式讀取。
   - Markdown 摘要供人閱讀。
6. 將錯誤分類。
   - 詞庫缺漏。
   - 上下文選字錯誤。
   - 英文混輸干擾。
   - 使用者詞或排除詞相關。
   - 讀音缺漏。

## 輸出檔案建議

- `Tests/fixtures/contextual_bopomofo/taiwan_ambiguous.jsonl`
- `Tests/fixtures/contextual_bopomofo/english_mixed.jsonl`
- `Tools/ContextualEvaluation/`
- `docs/reports/phase0_baseline_report.md`
- `docs/reports/phase0_baseline_report.json`

## 驗收條件

1. 已通過：評測命令可在本機執行並產出 JSON 與 Markdown 報告。
2. 已通過：同一台機器連跑兩次，案例數、正確率、缺讀音數一致。
3. 已通過：60 句台灣繁中歧義案例與 25 句英文混輸案例存在。
4. 已通過：報告列出句子完全正確率、CJK token accuracy、目標候選平均排名、p50 / p95 / p99 延遲。
5. 已通過：報告列出錯誤類型與高頻模式。
6. 待持續維護：新增 benchmark 前必須確認來源與授權。
7. 待持續維護：所有 benchmark 來源均需在 corpus manifest 中有授權與用途分類。

完成摘要：

| 指標 | 數值 |
|---|---:|
| `taiwan_ambiguous` 案例 | 60 |
| 完全正確 | 43 |
| 句子完全正確率 | 71.67% |
| CJK token accuracy | 94.95% |
| 目標候選平均排名 | 1.00 |
| missing reading | 0 |
| context ambiguity error | 17 |
| 延遲 p50 / p95 / p99 | 1 / 2 / 2 μs |

錯誤結論：

1. 17 個錯誤皆為 context ambiguity。
2. 高頻錯誤集中在同音替換，例如在/再、累/類、帶/代、遍/變、尚/上。
3. 部分錯誤是 missing bigram，例如 `意思`、`主意`。
4. 部分錯誤是 segmentation artifact，例如 `品質`、`進步` 相關輸出。
5. `english_mixed` 25 例目前全部是 missing reading，原因是非注音 token 被送進 LM；Phase 1 要先補 passthrough。

## 停止或轉向條件

- 若主要錯誤是詞庫缺漏，先建立台灣詞庫補強工作，不進入模型實驗。
- 已判定主要錯誤是上下文選字，進入 Phase 1。
- 若評測資料授權不清楚，先修正資料來源與 manifest，不寫排序器。
- 若 benchmark 與訓練資料無法分離，先修正資料切分，不進入 Phase 1。

## 禁止事項

- 不導入小型語言模型。
- 不改候選排序。
- 不加入雲端服務。
- 不記錄使用者真實輸入內容。
