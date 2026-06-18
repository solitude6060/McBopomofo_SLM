# Agent 任務提示

最後更新：2026-06-18

## 共通系統提示

你正在維護一個基於小麥注音 fork 的台灣繁中注音輸入法專案。目標是降低連續注音輸入的選字修正成本，支援台灣用語、注音、英文混輸、macOS 與 Ubuntu 使用者。

不可把「導入小型語言模型」視為預設解。必須先建立評測，再做輕量上下文重新排序，最後才評估本機小型語言模型。每次按鍵同步路徑不可等待模型。模型只能重新排序候選，不可自由產生送出文字。預設不連網、不上傳、不記錄輸入原文。

開始前必讀：

1. `docs/台灣繁中注音輸入法_規劃索引.md`
2. `docs/台灣繁中注音輸入法_產品需求.md`
3. `docs/台灣繁中注音輸入法_技術規格.md`
4. `docs/台灣繁中注音輸入法_速度需求.md`
5. `docs/台灣繁中注音輸入法_法律授權盤點.md`
6. `docs/台灣繁中注音輸入法_本機習慣收集與Adapter訓練.md`
7. `docs/台灣繁中注音輸入法_台灣語料路線.md`

## Phase 0 Agent Prompt

任務：建立台灣繁中注音評測基準。

請執行：

1. 閱讀 `docs/台灣繁中注音輸入法_Phase0_評測基準開發步驟.md`。
2. 盤點目前引擎可重用的測試入口。
3. 定義 JSONL 評測格式與授權 manifest。
4. 建立至少 50 句台灣繁中歧義案例與 20 句英文混輸案例。
5. 實作重播工具，輸出正確率、候選排名、缺讀音與延遲。
6. 產出 `docs/reports/phase0_baseline_report.md`。
7. 使用 `docs/台灣繁中注音輸入法_台灣語料路線.md` 分類資料來源；教育部 / 萌典只作讀音與歧義種子，政府開放資料可作台灣命名實體來源。

驗收：

- 評測命令可重跑。
- 報告可重現。
- 沒有授權不明測試資料被 commit。
- 不修改候選排序。
- benchmark 與 training 資料已分離。

## Phase 1 Agent Prompt

任務：建立低延遲輕量上下文重新排序器。

請執行：

1. 閱讀 `docs/台灣繁中注音輸入法_Phase1_輕量重新排序開發步驟.md`。
2. 先寫測試，鎖定停用時與 baseline 一致。
3. 新增 `ContextualScorer` 介面。
4. 新增 `DeterministicContextualScorer`，只回傳 score delta。
5. 保護英文片段與使用者覆寫。
6. 用 Phase 0 評測比較 baseline 與 P1。
7. 產出 `docs/reports/phase1_reranker_report.md`。

驗收：

- 台灣繁中歧義錯誤率相對下降至少 10%。
- 英文混輸不退化。
- p95 新增延遲小於 2 ms。
- 停用後行為與小麥注音一致。

## Phase 2 Agent Prompt

任務：離線評估本機小型語言模型是否值得導入。

請執行：

1. 閱讀 `docs/台灣繁中注音輸入法_Phase2_SLM實驗開發步驟.md`。
2. 建立語料 manifest。
3. 設計候選受限的模型任務。
4. 建立離線 scorer，不接入輸入法主行程。
5. 至少評估一個本機小型語言模型 runtime。
6. 與 Phase 1 報告比較。
7. 產出 `docs/reports/phase2_slm_experiment_report.md` 與 runtime ADR。
8. 只使用 manifest 中 `train_allowed=true` 的資料訓練。

驗收：

- 相對 P1 額外錯誤率下降至少 5%。
- 台灣繁中與英文混輸不退化。
- p95 小於 20 ms，超過 30 ms 可回退。
- 授權可確認。
- 訓練資料不包含 Phase 0 benchmark。

## Phase 2.5 Agent Prompt

任務：建立本機自訓、修正事件收集、adapter 重新訓練與刪除流程。

請執行：

1. 僅在 Phase 2 達標後開始。
2. 閱讀 `docs/台灣繁中注音輸入法_Phase2_5_本機自訓開發步驟.md`。
3. 閱讀 `docs/台灣繁中注音輸入法_本機習慣收集與Adapter訓練.md`。
4. 建立本機文字匯入、訓練、評測、manifest、刪除流程。
5. 建立明確選擇加入的 L1 修正事件收集。
6. 建立 adapter 重新訓練觸發器。
7. 建立 promotion gate，未通過不得啟用新 adapter。
8. 加入防誤打包檢查。
9. 產出隱私 runbook。

驗收：

- 使用者可離線訓練。
- 使用者開啟本機個人化後，修正事件可觸發 adapter 訓練。
- 可啟用、停用、刪除自訓模型與 adapter。
- 新 adapter 未通過 gate 不啟用。
- 私有資料不進一般紀錄、commit、發佈包。

## Phase 3 Agent Prompt

任務：macOS 實驗整合。

請執行：

1. 僅在 Phase 1 或 Phase 2 達標後開始。
2. 閱讀 `docs/台灣繁中注音輸入法_Phase3_macOS實驗整合開發步驟.md`。
3. 新增實驗設定，預設關閉。
4. 整合 scorer 與回退路徑。
5. 加入非內容型觀測。
6. 完成實際使用檢查表。

驗收：

- 可啟用、停用、切換 scorer。
- 停用後與原本小麥注音一致。
- 快速打字不等待模型。
- 紀錄中沒有輸入原文。

## Phase 4 Agent Prompt

任務：Ubuntu 可行性與第一條 Linux 路線。

請執行：

1. 閱讀 `docs/台灣繁中注音輸入法_Phase4_Ubuntu可行性開發步驟.md`。
2. 抽出平台無關評測與 scorer。
3. 建立 Ubuntu build。
4. 跑 Phase 0 / Phase 1 評測。
5. 比較 Fcitx5、IBus、Rime、libchewing-adjacent 路線。
6. 寫 ADR 並建立命令列 demo。

驗收：

- Ubuntu 可執行評測。
- 命令列 demo 可輸出候選排序。
- ADR 選定第一條 Linux 路線。
- 授權風險已列出。

## 絕對禁止

1. 每次按鍵同步等待小型語言模型。
2. 模型自由產生候選集外文字。
3. 上傳使用者輸入內容。
4. 記錄原始注音、候選文字、送出文字、使用者詞庫內容。
5. 複製 GPL 程式碼進 MIT 發佈路線。
6. 使用授權不明語料訓練可散布模型。
7. 未經使用者明確開啟就保存本機修正事件。
8. 把 CC BY-ND 釋義全文當作可改作訓練語料。
9. 把 CC BY-SA 內容訓練成可散布模型而未先完成授權義務評估。
