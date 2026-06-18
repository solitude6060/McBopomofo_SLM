# Phase 1 測資審計報告 — Fixture Audit

最後更新：2026-06-18T22:30:00+08:00
作者：Sisyphus
依據：字典詞條比對 + evaluator 實際輸出

## 審計範圍

- `taiwan_ambiguous.jsonl`：60 個臺灣繁中歧義句
- `english_mixed.jsonl`：25 個中英混輸句
- 比對基準：`Source/Data/BPMFMappings.txt`（小麥注音主詞庫）

## 判定類型

| 類型 | 縮寫 | 說明 |
|---|---|---|
| Fixture reading 錯誤 | FR | 該注音在語料庫中對應不同文字，或根本不存在該詞條 |
| 詞庫覆蓋不足 | DK | 該詞條不在主詞庫中（需補詞庫或判斷是否該加） |
| 語境排序不足 | CTX | 注音正確、詞條存在，但 baseline 選錯字，且 scorer 規則沒涵蓋到 |
| Segmentation 瑕疵 | SEG | Readings 正確、詞條都存在，但 engine 選了不同長度的片語 |
| 待確認 | TBD | 需要進一步檢查 |

---

## Taiwan ambiguous — 剩餘 7 個失敗案例

### 第 1 組：Fixture 注音聲調錯誤（FR）

| ID | Readings | Expected | Reranker output | 診斷 | 字典證據 | 修法 |
|---|---|---|---|---|---|---|
| `tw-amb-005` | `...ㄧ ㄙ` | `這是什麼意思` | `這是什麼一絲` | 意思 = ㄧˋ ㄙ，fixture ㄧ 缺少四聲 | `意思 ㄧˋ ㄙ`（BPMFMappings） | 改 fixture 第 5 個 reading：`ㄧ` → `ㄧˋ` |
| `tw-amb-031` | `...ㄆㄧㄣˊ ㄓˊ...` | `空氣品質持續下降` | `空氣頻直持續下降` | 品質 = ㄆㄧㄣˇ ㄓˊ，fixture ㄆㄧㄣˊ 為二聲 | `品質 ㄆㄧㄣˇ ㄓˊ`（BPMFMappings） | 改 fixture 第 3 個 reading：`ㄆㄧㄣˊ` → `ㄆㄧㄣˇ` |
| `tw-amb-033` | `ㄒㄧˋ ㄍㄨㄢˋ...` | `習慣養成不久` | `系慣養成不久` | 習慣 = ㄒㄧˊ ㄍㄨㄢˋ，fixture ㄒㄧˋ 為四聲 | `習慣 ㄒㄧˊ ㄍㄨㄢˋ`（BPMFMappings） | 改 fixture 第 1 個 reading：`ㄒㄧˋ` → `ㄒㄧˊ` |
| `tw-amb-034` | `...ㄓㄨˇ ㄧ...` | `我覺得這個主意非常重要` | `我覺得這個主一非常重要` | 主意 = ㄓㄨˇ ㄧˋ，fixture ㄧ 缺少四聲 | `主意 ㄓㄨˇ ㄧˋ`（BPMFMappings） | 改 fixture 第 7 個 reading：`ㄧ` → `ㄧˋ` |
| `tw-amb-035` | `...ㄓㄥˋ ㄌㄞˊ...` | `這獎金是我辛苦賺來的` | `這獎金是我辛苦政來的` | 賺 = ㄓㄨㄢˋ，fixture ㄓㄥˋ 完全不同音 | `賺 ㄓㄨㄢˋ`（BPMFMappings） | 改 fixture 第 8 個 reading：`ㄓㄥˋ` → `ㄓㄨㄢˋ` |
| `tw-amb-054` | `ㄐㄧ ㄏㄨㄟˋ...` | `會議上有一場演講` | `機會上有一場演講` | 會議 = ㄏㄨㄟˋ ㄧˋ，fixture 用 ㄐㄧ ㄏㄨㄟˋ 完全錯誤 | `會議 ㄏㄨㄟˋ ㄧˋ`（BPMFMappings） | 改 fixture 第 1-2 個 readings：`ㄐㄧ ㄏㄨㄟˋ` → `ㄏㄨㄟˋ ㄧˋ` |

### 第 2 組：True segmentation artifact（SEG）

| ID | Readings | Expected | Reranker output | 診斷 | 修法 |
|---|---|---|---|---|---|
| `tw-amb-042` | `ㄨㄛˇ ㄩㄝˋ ㄉㄨˊ ㄩㄝˋ ㄐㄧㄣˋ ㄅㄨˋ` | `我越讀越進步` | `我閱讀躍進不` | 5 readings 分別有意義，但 engine 偏好合成 bigram：閱讀(ㄩㄝˋ-ㄉㄨˊ) + 躍進(ㄩㄝˋ-ㄐㄧㄣˋ) + 不(ㄅㄨˋ)。Scorer 有 越/讀 規則但未能成功 override。 | True reranker 限制。需確認 override 在 1-char 校正後 walk 是否能改變 segmentation。保留至 Phase 1 後續優化。 |

---

## English mixed — 剩餘 16 個失敗案例

### 第 1 組：Fixture 注音聲調錯誤（FR）

| ID | Readings | Expected | Reranker output | 診斷 | 字典證據 | 修法 |
|---|---|---|---|---|---|---|
| `en-mix-001` | `ㄩㄥˋ Docker ㄅㄨˋ ㄕㄨˇ` | `用 Docker 部署` | `用 Docker 部屬` | 署在 部署 中為 ㄕㄨˋ，fixture 用ㄕㄨˇ | `部署 ㄅㄨˋ ㄕㄨˋ`（BPMFMappings） | 改 `ㄕㄨˇ` → `ㄕㄨˋ` |
| `en-mix-002` | `ㄒㄧㄚˋ ㄗㄞˋ GitHub...` | `下載 GitHub 上的程式` | `下在 GitHub 上的程式` | 下載 = ㄒㄧㄚˋ ㄗㄞˇ，fixture ㄗㄞˋ 為四聲（在） | `下載 ㄒㄧㄚˋ ㄗㄞˇ`（BPMFMappings） | 改 `ㄗㄞˋ` → `ㄗㄞˇ` |
| `en-mix-007` | `...nginx ㄉㄞˋ ㄌㄧˊ` | `配置 nginx 代理` | `配置 nginx 帶離` | 代理 = ㄉㄞˋ ㄌㄧˇ，fixture ㄌㄧˊ 為二聲（離） | `代理 ㄉㄞˋ ㄌㄧˇ`（BPMFMappings） | 改 `ㄌㄧˊ` → `ㄌㄧˇ` |
| `en-mix-009` | `ㄔㄨㄤˋ ㄐㄧㄢˋ React ㄓㄨㄢˋ ㄢˋ` | `元件 React 專案` | `創建 React 賺案` | ① 元 = ㄩㄢˊ，fixture ㄔㄨㄤˋ 為創 ② 專 = ㄓㄨㄢ，fixture ㄓㄨㄢˋ 為賺 | `元件 ㄩㄢˊ ㄐㄧㄢˋ`，`專案 ㄓㄨㄢ ㄢˋ` | 改 `ㄔㄨㄤˋ` → `ㄩㄢˊ`，改 `ㄓㄨㄢˋ` → `ㄓㄨㄢ` |
| `en-mix-013` | `...ㄗˋ ㄉㄤˇ` | `JSON 格式的檔案` | `JSON 格式的字檔` | 檔案 = ㄉㄤˇ ㄢˋ，fixture ㄗˋ 對應 字 非 檔，且缺少 ㄢˋ | `檔案 ㄉㄤˇ ㄢˋ`（BPMFMappings） | 改 `ㄗˋ` → `ㄉㄤˇ`，`ㄉㄤˇ` → `ㄢˋ` |
| `en-mix-014` | `ㄒㄧㄡ ㄍㄞˋ /etc/hosts ㄨㄣˊ ㄐㄧㄢˋ` | `修改 /etc/hosts 檔案` | `修概 /etc/hosts 文件` | ① 改 = ㄍㄞˇ，fixture ㄍㄞˋ 為概 ② 檔案 = ㄉㄤˇ ㄢˋ，fixture ㄨㄣˊ ㄐㄧㄢˋ 對應 文件 | `修改 ㄒㄧㄡ ㄍㄞˇ`，`檔案 ㄉㄤˇ ㄢˋ` | 改 `ㄍㄞˋ` → `ㄍㄞˇ`；改 `ㄨㄣˊㄐㄧㄢˋ` → `ㄉㄤˇㄢˋ` |
| `en-mix-018` | `ㄒㄧㄚˋ ㄗㄞˋ https://...` | `下載 https://... 這個 URL` | `下在 https://... 這個 URL` | 同 en-mix-002：載為 ㄗㄞˇ 非 ㄗㄞˋ | `下載 ㄒㄧㄚˋ ㄗㄞˇ` | 改 `ㄗㄞˋ` → `ㄗㄞˇ` |
| `en-mix-021` | `...ㄈㄨˊ ㄨˋ ㄑㄧˋ` | `用 SSH 登錄伺服器` | `用 SSH 登錄服務氣` | ① 伺服 = ㄙˋ ㄈㄨˊ，fixture ㄈㄨˊ ㄨˋ 為服務 ② 器 = ㄑㄧˋ與氣同音但應為器 | `伺服器 ㄙˋ ㄈㄨˊ ㄑㄧˋ`（BPMFMappings）；`服務器` 無此詞條 | 改 `ㄈㄨˊ ㄨˋ` → `ㄙˋ ㄈㄨˊ` |
| `en-mix-024` | `ㄊㄡ ㄗ CNSX ㄕˋ ㄔㄤˇ` | `投資 CNSX 市場` | `偷資 CNSX 市場` | 投 = ㄊㄡˊ（二聲），fixture ㄊㄡ 為一聲（偷） | `投資 ㄊㄡˊ ㄗ`（BPMFMappings） | 改 `ㄊㄡ` → `ㄊㄡˊ` |

### 第 2 組：Fixture readings 數量／順序錯誤

| ID | Readings | Expected | Reranker output | 診斷 | 修法 |
|---|---|---|---|---|---|
| `en-mix-016` | `ㄐㄧㄡˋ ㄐㄧˋ ㄕˊ 用 JavaScript ㄍㄞˇ ㄒㄧㄝˇ` | `就用 JavaScript 改寫` | `救濟時 用 JavaScript 改寫` | 多了 2 個 readings（ㄐㄧˋ、ㄕˊ），對應到 濟時 而非 就。應改為 `ㄐㄧㄡˋ ㄩㄥˋ JavaScript ㄍㄞˇ ㄒㄧㄝˇ`（將 用 改為 Bopomofo ㄩㄥˋ 走 LM 避免 spacing 問題） | 移除 `ㄐㄧˋ`、`ㄕˊ`；`用` → `ㄩㄥˋ` |
| `en-mix-017` | `ㄔㄨㄤˋ ㄎㄣˋ GitHub Actions ㄌㄧㄡˊ ㄔㄥˊ` | `設定 GitHub Actions 流程` | `創掯 GitHub Actions 流程` | 前 2 個 readings 完全錯誤（創掯 vs 設定）。應改為 `ㄕㄜˋ ㄉㄧㄥˋ` | `ㄔㄨㄤˋ` → `ㄕㄜˋ`，`ㄎㄣˋ` → `ㄉㄧㄥˋ` |
| `en-mix-020` | `ㄗㄨㄟˋ ㄐㄧㄚˋ macOS Sequoia 15.4` | `在 macOS Sequoia 15.4 上測試` | `最價 macOS Sequoia 15.4` | 完全缺少 `在`、`上`、`測試` 的 readings。只有 5 個 readings 但需要 7 個。應改為 `ㄗㄞˋ macOS Sequoia 15.4 ㄕㄤˋ ㄘㄜˋ ㄕˋ` | 新增 readings：`["ㄗㄞˋ","macOS","Sequoia","15.4","ㄕㄤˋ","ㄘㄜˋ","ㄕˋ"]` |
| `en-mix-022` | `ㄐㄧㄢˋ MongoDB ㄗㄞˋ Docker ㄓㄨㄥ ㄩㄣˋ ㄒㄧㄥˊ` | `MongoDB 在 Docker 中運行` | `建 MongoDB 在 Docker 中運行` | 首個 reading `ㄐㄧㄢˋ`（建）不應存在，句子以 MongoDB 開頭 | 移除 `ㄐㄧㄢˋ` |

### 第 3 組：True reranker 限制 — 詞串校正未生效

| ID | Readings | Expected | Reranker output | 診斷 | 說明 |
|---|---|---|---|---|---|
| `en-mix-003` | `ㄑㄧㄥˇ ㄘㄢ ㄎㄠˋ README ㄕㄨㄛ ㄇㄧㄥˊ` | `請參考 README 說明` | `請參靠 README 說明` | Readings 正確（ㄘㄢ ㄎㄠˋ），engine 把 ㄎㄠˋ 選成 靠。tech-term rule 有 參考 但 bigram override 可能未生效 | 待確認 override 是否支援 multi-char 校正 |
| `en-mix-006` | `ㄢ ㄓㄨㄤ Dockerfile ㄗㄨㄛˋ ㄐㄧㄥˋ ㄒㄧㄤˋ` | `安裝 Dockerfile 做鏡像` | `安裝 Dockerfile 作境相` | ① 做 vs 作：homophone rule 未涵蓋此語境（後方無 事/是）② 鏡像 vs 境相：tech-term rule 有 鏡像 但 bigram override 可能未生效 | 同上 |
| `en-mix-011` | `ㄘㄢ ㄎㄠˋ StackOverflow...` | `參考 StackOverflow 上的解答` | `參靠 StackOverflow 上的解答` | 同 en-mix-003：ㄎㄠˋ 被選為 靠 | 同上 |

### 第 4 組：待確認（待修完 FR 後重跑再判）

| ID | Readings | Expected | 狀態 |
|---|---|---|---|
| `en-mix-007`(FR 修後) | `...ㄉㄞˋ ㄌㄧˇ` | `配置 nginx 代理` | 改完讀音後需重跑看 engine 是否選 代理 |
| `en-mix-024`(FR 修後) | `ㄊㄡˊ ㄗ CNSX...` | `投資 CNSX 市場` | 改完讀音後需重跑看 engine 是否選 投資 |

---

## 修復策略

### Tw-ambiguous（全修）

全部 6 個 FR 案例**(005/031/033/034/035/054)** 都有明確字典證據，readings 與 dictionary 不一致。直接改 fixture。

### English-mixed

依明確度分三批：

**第一批 — 明確 FR 聲調錯誤（優先修）：**
- `en-mix-001`（署 ㄕㄨˇ→ㄕㄨˋ）
- `en-mix-002`（載 ㄗㄞˋ→ㄗㄞˇ）
- `en-mix-007`（理 ㄌㄧˊ→ㄌㄧˇ）
- `en-mix-009`（元 ㄔㄨㄤˋ→ㄩㄢˊ，專 ㄓㄨㄢˋ→ㄓㄨㄢ）
- `en-mix-013`（檔案 ㄗˋㄉㄤˇ→ㄉㄤˇㄢˋ）
- `en-mix-014`（改 ㄍㄞˋ→ㄍㄞˇ，檔案 ㄨㄣˊㄐㄧㄢˋ→ㄉㄤˇㄢˋ）
- `en-mix-018`（載 ㄗㄞˋ→ㄗㄞˇ）
- `en-mix-021`（伺服 ㄈㄨˊㄨˋ→ㄙˋㄈㄨˊ）
- `en-mix-024`（投 ㄊㄡ→ㄊㄡˊ）

**第二批 — readings 數量／順序（必須修）：**
- `en-mix-016`（移除多餘 2 readings）
- `en-mix-017`（前 2 個 reading 全錯）
- `en-mix-020`（缺後半句子 readings）
- `en-mix-022`（移除前綴 reading）

**第三批 — 不修（留到 Phase 1 scorer 優化）：**
- `en-mix-003`（參考：bigram override 問題）
- `en-mix-006`（做/作 與 鏡像：新語境 + bigram override 問題）
- `en-mix-011`（參考：同 en-mix-003）

---

## Gate 影響評估

### Taiwan
| Case | 類型 | 是否阻擋 gate | 修後預期 |
|---|---|---|---|
| tw-amb-005 ~ 054(6 cases) | FR | 是 (錯誤 fixture 導致 reranker 無法改善) | 全部進入 exact match |
| tw-amb-042 | SEG | 是 (需 scorer 改善) | 仍無法通過 |

預期修後 TW reranker 正確率：**59~60/60（98.33%~100%）**

### English mixed
| 修復 | 影響 |
|---|---|
| 修 9 個 FR（第一批） | 預期增 4~6 個 exact match |
| 修 4 個 readings 錯誤（第二批） | 預期增 4 個 exact match |
| 剩 3 個 bigram override 限制 | 需優化 scorer 後才能過 |

預期修後 EN reranker 正確率：**17~19/25（68%~76%）**，另有 3 個需 scorer 優化。

---

## 避免事項

- 不要新增注音不存在的文字進 fixture
- 不要用規則蓋掉 dictionary 已存在的詞條
- 不要修改 `tw-amb-042` 的 readings（它是有效的 segmentation 測試）
- 不要修改 `en-mix-003/006/011` 的 readings 去迎合 engine output（它們是有效的中文同音選擇題）
