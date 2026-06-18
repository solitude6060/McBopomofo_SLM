# Phase 0：評測基準開發步驟

最後更新：2026-06-18

## 目標

建立可重現的台灣繁中注音評測基準，用現有小麥注音引擎證明目前錯誤類型、候選排名與延遲。這一階段不導入模型，也不改候選排序。

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

1. 評測命令可在本機執行並產出 JSON 與 Markdown 報告。
2. 同一台機器連跑兩次，案例數、正確率、缺讀音數一致。
3. 至少 50 句台灣繁中歧義案例與 20 句英文混輸案例通過格式檢查。
4. 報告列出句子完全正確率、字詞正確率、目標候選平均排名、p50 / p95 / p99 延遲。
5. 報告列出前三大錯誤類型。
6. 沒有授權不明的語料被 commit。
7. 所有 benchmark 來源均在 corpus manifest 中有授權與用途分類。

## 停止或轉向條件

- 若主要錯誤是詞庫缺漏，先建立台灣詞庫補強工作，不進入模型實驗。
- 若主要錯誤是上下文選字，進入 Phase 1。
- 若評測資料授權不清楚，先修正資料來源與 manifest，不寫排序器。
- 若 benchmark 與訓練資料無法分離，先修正資料切分，不進入 Phase 1。

## 禁止事項

- 不導入小型語言模型。
- 不改候選排序。
- 不加入雲端服務。
- 不記錄使用者真實輸入內容。
