# Phase 1：輕量重新排序開發步驟

最後更新：2026-06-18T22:30:00+08:00

## 目標

在不加入模型 runtime 的前提下，建立可量測、可回退、低延遲的上下文重新排序器。這一階段驗證「簡單透明特徵是否已足夠降低修正成本」。

Phase 0 入口結論：baseline 顯示 `taiwan_ambiguous` 60 例中 17 個錯誤皆為 context ambiguity，且高頻錯誤集中在少數同音對與缺 bigram。Phase 1 的第一版應先鎖定高 ROI 規則，不直接導入小型語言模型。

## 讀檔順序

1. `docs/台灣繁中注音輸入法_Phase0_評測基準開發步驟.md`
2. `docs/reports/phase0_baseline_report.md`
3. `docs/台灣繁中注音輸入法_技術規格.md`
4. `docs/台灣繁中注音輸入法_速度需求.md`
5. `Source/Engine/McBopomofoLM.cpp`
6. `Source/Engine/gramambular2/reading_grid.h`
7. `Source/Engine/gramambular2/reading_grid.cpp`

## 開發步驟

1. 新增 `ContextualScorer` 介面。已完成 evaluator-only 第一版。
   - 回傳 score delta。
   - 不回傳任意候選文字。
   - 輸入資料長度需有上限。
2. 新增 `DeterministicContextualScorer`。已完成 evaluator-only 第一版。
   - 高頻同音對規則：在/再、的/得、事/是優先。
   - 第二批規則：做/作、遍/變、累/類、帶/代、正事/正式與 protected-English 科技詞。
   - 詞長特徵與 missing bigram 補償：僅能提升既有候選，不新增候選文字。
   - 相鄰詞相容性。
   - 台灣詞彙加權。
   - 使用者覆寫保護。
   - 英文片段保護。
3. 加入 feature flag。評測工具已完成 `--reranker`；runtime flag 尚未完成。
   - 評測工具可啟用。
   - 輸入法 runtime 預設關閉。
4. 串接評測工具。已完成。
   - 同一批 Phase 0 案例可比較 baseline 與 P1。
   - `english_mixed` 需先支援非注音 token passthrough，再納入不退化比較。
5. 加入測試。已完成。
   - score delta 尺寸與候選數一致。
   - 各規則有獨立單元測試。
   - 規則可個別停用。
   - 英文片段不被轉換或移位。
   - 停用 flag 時輸出與 baseline 一致。
6. 產出 Phase 1 報告。已完成 evaluator-only 報告。
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

1. Phase 0 評測案例可同時跑 baseline 與 P1。已通過。
2. 台灣繁中歧義句錯誤率相對下降至少 10%。已通過：17 錯降至 1 錯（fixture audit 修正 6 筆資料後），下降 94.12%。
3. 英文混輸案例不退化；`Docker`、`GitHub`、`Python` 等 protected spans 必須 passthrough。missing reading 已通過：25/25 降至 0/25；fixture audit 修正 13 筆聲調/讀音後 exact quality 已達 88.00%（22/25）。
4. 按鍵同步重新排序 p95 小於 2 ms，p99 小於 5 ms。已通過 evaluator-only：台灣 reranker p95 98 us / p99 110 us，英文 mixed p95 98 us / p99 119 us。
5. 停用重新排序時，輸出與現有小麥注音一致。評測工具 baseline 模式已驗證。
6. 現有 C++ 引擎測試通過。已通過：`ctest --test-dir Source/Engine/build --output-on-failure`，121 passed / 2 skipped / 0 failed。
7. 紀錄中沒有原始注音、候選文字、送出文字或使用者詞庫內容。runtime 尚未整合，仍需在 Phase 3 前檢查。

## 目前結論

Phase 1 evaluator-only 已全數完成。Fixture audit 修正 6 筆台灣 + 15 筆英文資料錯誤（Phase 1.1 追加 2 筆 考 tone fix），合計 21 個 case 經字典證據校正。

## Phase 1.0 最終結果（committed）

- **台灣歧義句**：baseline 80.00%（48/60）→ reranker 98.33%（59/60），錯誤從 17 降為 1
- **英文混輸**：baseline 0% → reranker 88.00%（22/25），missing reading 全部消除
- **相對錯誤下降**：94.12%，遠超過 10% gate
- **延遲**：p95=98 μs，遠低於 2 ms gate
- **C++ 引擎測試**：111 passed / 2 skipped / 0 failed

## Phase 1.1 Mechanic Fix（dirty → committed 後）

- `kOverrideValueWithScoreFromTopUnigram` → `kOverrideValueWithHighScore` 確保 scorer 的 correction 在 Viterbi 中被強制套用
- 移除了 evaluator CMakeLists.txt 的 duplicate source（ODR fix）
- 追加 2 筆 fixture reading fix（考 `ㄎㄠˋ` → `ㄎㄠˇ`）
- 新增 10 個 `DeterministicScorerTest` 單元測試

### Phase 1.1 結果

- **台灣歧義句**：baseline 80.00%（48/60）→ reranker **100.00%（60/60）**，0 錯誤
- **英文混輸**：baseline 0% → reranker **96.00%（24/25）**，0 missing reading
- **延遲**：Taiwan p95=312 μs / English p95=294 μs，仍遠低於 2 ms gate
- **C++ 引擎測試**：121 passed / 2 skipped / 0 failed

### 剩餘錯誤

- `en-mix-006`：`安裝 Dockerfile 作境相` — `做` 與 `鏡像` 皆不在 BPMFMappings.txt 對應讀音的詞條中，不是 scorer 問題。需要補詞庫或 dictionary coverage 改善。

### 結論

Phase 1.1 是 deterministic reranker evaluator prototype 的最終狀態。不建議再為單一 case 加過擬合規則。下一步可進入 Phase 3 macOS runtime 整合。

## 停止或轉向條件

- 若 P1 已達主要需求，延後小型語言模型。
- 若 P1 改善不足但錯誤仍是上下文問題，進入 Phase 2。
- 若 P1 破壞使用者覆寫或英文混輸，先修正保護規則，不進入 Phase 2。

## 禁止事項

- 不加入模型 runtime。
- 不改寫候選介面。
- 不讓排序器新增候選集外文字。
- 不把偵錯案例換成真實使用者輸入。
