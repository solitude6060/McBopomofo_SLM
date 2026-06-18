# Phase 4：Ubuntu 可行性開發步驟

最後更新：2026-06-18

## 目標

確認評測與排序核心能在 Ubuntu 執行，並選定第一條 Linux 桌面整合路線。這一階段先做命令列與架構決策，不直接承諾完整圖形介面。

## 讀檔順序

1. `docs/台灣繁中注音輸入法_產品調查.md`
2. `docs/台灣繁中注音輸入法_法律授權盤點.md`
3. `docs/台灣繁中注音輸入法_技術規格.md`
4. `docs/台灣繁中注音輸入法_Phase0_評測基準開發步驟.md`
5. `docs/台灣繁中注音輸入法_Phase1_輕量重新排序開發步驟.md`

## 開發步驟

1. 抽出平台無關核心。
   - 評測工具不依賴 macOS IMK。
   - scorer 不依賴 Swift UI 或 macOS 設定頁。
2. 建立 Ubuntu build。
   - 先只編譯評測與 scorer。
   - 不先做完整輸入法前端。
3. 跑同一組 Phase 0 / Phase 1 評測。
   - 確認結果與 macOS 差異。
   - 記錄延遲與缺讀音。
4. 研究整合路線。
   - Fcitx5。
   - IBus。
   - Rime。
   - libchewing-adjacent 獨立整合。
5. 寫架構決策紀錄。
   - 選哪一條路線。
   - 拒絕哪些路線。
   - 授權與維護成本。
   - 第一個可交付範圍。
6. 建立命令列 demo。
   - 輸入注音序列。
   - 輸出 baseline 與 scorer 排序結果。

## 輸出檔案建議

- `Tools/ContextualEvaluation/` 的 Linux build 設定。
- `Tools/ScorerDemo/`
- `docs/adr/ADR-002-ubuntu-input-method-path.md`
- `docs/reports/phase4_ubuntu_feasibility_report.md`

## 驗收條件

1. Ubuntu 可編譯並執行評測工具。
2. 同一組測試資料可在 Ubuntu 跑。
3. 命令列 demo 可輸入注音序列並輸出候選排序。
4. 架構決策紀錄清楚選定第一條 Linux 路線。
5. 授權風險已列出，尤其是 LGPL / GPL 元件邊界。

## 停止或轉向條件

- 若 Ubuntu 前端整合需要重寫大量輸入法框架，先維持命令列與核心，不承諾完整前端時程。
- 若選定路線涉及授權衝突，先做替代方案評估。
- 若 Linux 結果與 macOS 差異大，先修正核心可攜性，不做前端。

## 禁止事項

- 不直接複製 GPL 程式碼進 MIT 專案。
- 不假設 macOS Input Method Kit 架構可直接移植。
- 不先做完整 UI 再補評測。
