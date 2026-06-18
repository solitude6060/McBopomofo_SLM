# Phase 2：小型語言模型實驗開發步驟

最後更新：2026-06-18

## 目標

在輸入法 live path 外部比較本機小型語言模型與 Phase 1 輕量重新排序器。只有當模型在台灣繁中與英文混輸保留測試集明確勝出，且延遲符合預算，才允許進入 macOS 實驗 runtime。

## 讀檔順序

1. `docs/台灣繁中注音輸入法_Phase1_輕量重新排序開發步驟.md`
2. `docs/reports/phase1_reranker_report.md`
3. `docs/台灣繁中注音輸入法_法律授權盤點.md`
4. `docs/台灣繁中注音輸入法_技術規格.md`
5. `docs/台灣繁中注音輸入法_速度需求.md`
6. `docs/台灣繁中注音輸入法_台灣語料路線.md`

## 開發步驟

1. 建立語料 manifest。
   - 來源。
   - 授權。
   - 是否可散布。
   - 台灣繁中相關性。
   - 前處理方式。
   - 是否允許 benchmark。
   - 是否允許訓練。
   - 是否只能作本機 adapter。
   - 是否含 CC BY-ND、CC BY-SA 或政府資料開放授權義務。
2. 建立候選受限的模型任務。
   - 輸入：上下文、注音、候選清單。
   - 輸出：候選排名或分數。
   - 禁止模型輸出候選集外文字。
3. 建立離線 scorer。
   - 不接入輸入法主行程。
   - 可設定逾時。
   - 可輸出每案耗時與是否回退。
4. 至少評估一種本機 runtime。
   - llama.cpp 優先評估，因為 C/C++ 與跨平台路線較直接。
   - Core ML 與 ONNX Runtime 只在有明確收益時比較。
5. 分開評測。
   - 台灣繁中歧義案例。
   - 英文混輸案例。
   - 泛繁中案例。
   - 政府開放資料命名實體案例。
   - 教育部 / 萌典歧義讀音案例。
6. 建立失敗分析。
   - 模型慢。
   - 模型產生非候選答案。
   - 台灣用語退化。
   - 英文片段干擾。
   - 授權不允許散布。

## 輸出檔案建議

- `Data/manifests/taiwan_corpus_manifest.json`
- `Tools/SLMRerankerExperiment/`
- `docs/reports/phase2_slm_experiment_report.md`
- `docs/reports/phase2_slm_experiment_report.json`
- `docs/adr/ADR-001-local-slm-runtime.md`

## 驗收條件

1. 小型語言模型相對 Phase 1 額外錯誤率下降至少 5%。
2. 台灣繁中保留測試集不退化。
3. 英文混輸保留測試集不退化。
4. 送出前重新排序 p95 小於 20 ms。
5. 超過 30 ms 可回退。
6. 模型權重、runtime、語料 manifest 的授權狀態清楚。
7. 實驗工具不記錄原始輸入、候選文字、送出文字。
8. 訓練資料不得包含 Phase 0 benchmark 測試集。

## 停止或轉向條件

- 若模型沒有明顯優於 Phase 1，不導入 runtime。
- 若模型延遲不符合預算，不導入 runtime。
- 若模型權重或語料授權不清楚，不散布模型。
- 若英文混輸退化，先修正任務設計與保護規則。
- 若可用訓練語料不足，改做 P1 deterministic scorer 與本機 adapter，不訓練可散布模型。

## 禁止事項

- 不把模型接到每次按鍵同步路徑。
- 不讓模型自由生成送出文字。
- 不把授權不明語料放進 repo。
- 不把使用者私人文字放進紀錄、commit、發佈包。
- 不把 CC BY-ND 釋義全文當作可改作訓練語料。
- 不把 CC BY-SA 內容訓練成可散布模型，除非已完成 share-alike 義務評估。
