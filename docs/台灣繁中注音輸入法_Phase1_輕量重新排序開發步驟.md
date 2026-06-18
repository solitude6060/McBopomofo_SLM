# Phase 1：輕量重新排序開發步驟

最後更新：2026-06-18

## 目標

在不加入模型 runtime 的前提下，建立可量測、可回退、低延遲的上下文重新排序器。這一階段驗證「簡單透明特徵是否已足夠降低修正成本」。

## 讀檔順序

1. `docs/台灣繁中注音輸入法_Phase0_評測基準開發步驟.md`
2. `docs/reports/phase0_baseline_report.md`
3. `docs/台灣繁中注音輸入法_技術規格.md`
4. `docs/台灣繁中注音輸入法_速度需求.md`
5. `Source/Engine/McBopomofoLM.cpp`
6. `Source/Engine/gramambular2/reading_grid.h`
7. `Source/Engine/gramambular2/reading_grid.cpp`

## 開發步驟

1. 新增 `ContextualScorer` 介面。
   - 回傳 score delta。
   - 不回傳任意候選文字。
   - 輸入資料長度需有上限。
2. 新增 `DeterministicContextualScorer`。
   - 詞長特徵。
   - 相鄰詞相容性。
   - 台灣詞彙加權。
   - 使用者覆寫保護。
   - 英文片段保護。
3. 加入 feature flag。
   - 評測工具可啟用。
   - 輸入法 runtime 預設關閉。
4. 串接評測工具。
   - 同一批 Phase 0 案例可比較 baseline 與 P1。
5. 加入測試。
   - score delta 尺寸與候選數一致。
   - 英文片段不被轉換或移位。
   - 使用者覆寫結果不被覆蓋。
   - 停用 flag 時輸出與 baseline 一致。
6. 產出 Phase 1 報告。
   - 正確率差異。
   - 英文混輸差異。
   - 延遲差異。
   - 失敗案例清單。

## 輸出檔案建議

- `Source/Engine/ContextualScorer.h`
- `Source/Engine/DeterministicContextualScorer.h`
- `Source/Engine/DeterministicContextualScorer.cpp`
- `Tests/Engine/DeterministicContextualScorerTest.cpp`
- `docs/reports/phase1_reranker_report.md`
- `docs/reports/phase1_reranker_report.json`

## 驗收條件

1. Phase 0 評測案例可同時跑 baseline 與 P1。
2. 台灣繁中歧義句錯誤率相對下降至少 10%。
3. 英文混輸案例不退化。
4. 按鍵同步重新排序 p95 小於 2 ms，p99 小於 5 ms。
5. 停用重新排序時，輸出與現有小麥注音一致。
6. 現有 C++ 引擎測試通過。
7. 紀錄中沒有原始注音、候選文字、送出文字或使用者詞庫內容。

## 停止或轉向條件

- 若 P1 已達主要需求，延後小型語言模型。
- 若 P1 改善不足但錯誤仍是上下文問題，進入 Phase 2。
- 若 P1 破壞使用者覆寫或英文混輸，先修正保護規則，不進入 Phase 2。

## 禁止事項

- 不加入模型 runtime。
- 不改寫候選介面。
- 不讓排序器新增候選集外文字。
- 不把偵錯案例換成真實使用者輸入。
