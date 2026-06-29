# McBopomofo SLM 專案狀態檢視

檢視日期：2026-06-30T00:00:00+08:00

目前分支：`slm-phase2-learnable`

HEAD：`1ede8a3d4316f56bc6fe470abb73336cf6ddbdf8` (`Record candidate ranker no-regression CI evidence`)

上游：`origin/slm-phase2-learnable`

## 摘要

專案目前處於「Ubuntu-first runtime 可行性與 learned scorer 研究分流」階段。

```text
已完成 Phase 0/1 evaluator 與 deterministic reranker
→ 已完成 Phase 2 bigram / candidate-ranker / prompt-only SLM 反證
→ 已完成 Phase 3 runtime gate 與 Linux CI coverage evidence
→ 目前重點：Ubuntu/Fcitx5 可 dogfood 化 + 自訓 n-gram/ranker 練習路線
```

核心結論：

- Deterministic reranker 是目前唯一適合 runtime 的 scorer 路線。
- Prompt-only Ollama SLM 不適合接同步輸入法 hot path。
- Bigram 與 candidate-ranker-v1 均已被實驗反證，不應直接 promotion。
- 後續 learned scorer 應改走 constrained n-gram / slot ranker / user adaptation。
- Ubuntu 仍是近期優先目標；macOS dogfood 是後續 gate，不是目前主要 blocker。

## 本次新增狀態記錄

本輪整理並準備提交的主要 artifacts：

| Artifact | 狀態 | 說明 |
|---|---|---|
| `Tools/SLMRerankerExperiment/local_llm_scorer.py` | updated | Ollama HTTP payload 預設 `think=false`，避免 Qwen3.5 thinking 模型把答案放進 `thinking` 而讓 `response` 為空。 |
| `docs/reports/experiments/phase2/ollama_slm_smoke_2026_06_24.json` | new | Content-free Ollama SLM smoke report，記錄 Qwen/Gemma prompt-only SLM promotion gate fail。 |
| `docs/reports/experiments/registry.json` | updated | 登錄 Ollama SLM smoke benchmark。 |
| `Models/qwen3_5_0_8b_manifest.json` | new | Ollama Qwen3.5 0.8B local model manifest。 |
| `Models/qwen3_5_2b_manifest.json` | new | Ollama Qwen3.5 2B local model manifest。 |
| `Models/qwen3_5_9b_manifest.json` | new | Ollama Qwen3.5 9B local model manifest。 |
| `Models/gemma4_e2b_manifest.json` | new | Ollama Gemma4 E2B local model manifest。 |
| `Models/gemma4_e4b_manifest.json` | new | Ollama Gemma4 E4B local model manifest。 |
| `docs/台灣繁中注音輸入法_自訓Ngram與Ranker實作評測計畫.md` | new | 使用者手寫 n-gram / ranker 的訓練、eval、gate、agent 分工計畫。 |
| `docs/reports/project_status_2026_06_30.md` | new | 本檔，記錄目前專案狀態。 |

## 程式碼與文件統計

| 指標 | 數值 |
|---|---:|
| `Source/` + `Tools/` + `Linux/` C++/Python/Swift/ObjC 類原始碼檔案 | 214 |
| `Tests/` + `Source/` + `Tools/` + `Linux/` 測試/fixture 類檔案 | 263 |
| `docs/` Markdown 文件 | 34 |
| GitHub Actions workflow | 7 |

## 已驗證能力

### Evaluation / Benchmark

- Contextual evaluator 已可比較 baseline、deterministic、bigram、SLM external scorer。
- Candidate request export 已支援 character granularity 與 candidate validation。
- Heldout clean fixture hygiene 已修復並納入 CI evidence。
- Runtime readiness matrix 與 SLM promotion gate validator 已存在。

### Deterministic Scorer

- Canonical / heldout clean regression gate 已有 CI evidence。
- Clean heldout deterministic gate 已達 `63/63`。
- Runtime hook 與 content-free counters 已有 static gate evidence。

### Learned Scorer 實驗

- Dictionary bigram：promotion gate fail，效果等同 baseline。
- Candidate-ranker-v1：canonical 有改善但 heldout generalization 失敗，exact feature matching 不足。
- Prompt-only Ollama SLM：
  - `qwen2.5:0.5b` 63-case heldout clean limit4：15/63 exact，40 fallback，p50 0.41s。
  - `qwen3.5:0.8b` 63-case heldout clean limit4：10/63 exact，46 fallback，p50 1.62s。
  - `qwen3.5:2b` 10-case sample：3/10 exact，4 fallback，p50 2.49s。
  - `qwen3.5:9b` / `gemma4:e2b` / `gemma4:e4b` 單筆 smoke 皆秒級到十秒級且未命中。
  - 結論：不可接 hot path，只能暫作離線分析或 batch labeling。

### Ubuntu / Linux

- `slm-phase4-ubuntu` 已併入目前分支歷史。
- Linux evaluator、CLI demo、Engine GTest CI evidence 已存在。
- Fcitx5 addon MVP 存在於 `Linux/Fcitx5Addon/`。
- 尚未完成 `.deb` packaging、真實 Ubuntu 桌面 dogfood、Fcitx5 addon CI/release gate。

## 目前開口與 Blockers

| 優先級 | 項目 | 狀態 | 建議 |
|---|---|---|---|
| P0 | Ubuntu/Fcitx5 dogfood | open | 先做 feature-flagged deterministic path、content-free counters、real desktop smoke。 |
| P0 | SLM runtime promotion | blocked | Prompt-only Ollama fail；改做 constrained n-gram / slot ranker，不接 runtime。 |
| P1 | `.deb` packaging | open | 建立可安裝、可移除、可回退的 Ubuntu package。 |
| P1 | Fcitx5 addon CI | open | 將 Linux addon build / smoke 加入 CI 或可重現 local gate。 |
| P1 | 自訓 n-gram/ranker 練習路線 | planned | 依新文件逐步從 bigram → trigram → 5-gram → KenLM → ranker v2。 |
| P2 | macOS manual IMK dogfood | open | 在 Ubuntu 優先事項穩定後再回來補。 |

## Gate 調整建議

因 clean heldout deterministic 已滿分，後續 learned scorer gate 應從「打贏 deterministic clean heldout」改為：

- clean heldout：不退化 deterministic。
- OOD / dogfood：`improved_cases > regressed_cases`。
- latency：hot path p95 < 2ms；commit-time p95 < 20ms。
- candidate validity：non-candidate violation = 0。
- privacy：content-free report。

## 本次未納入 commit 的工作樹項目

以下項目目前保留為未追蹤暫存物，不納入本次 commit：

| Path | 原因 |
|---|---|
| `.omo/` | 本機工具/狀態暫存，非專案交付 artifact。 |
| `.sisyphus/` | 本機工具/狀態暫存，非專案交付 artifact。 |
| `Tools/ContextualEvaluation/build_fcitx_original/` | build output，不應提交。 |
| `task_plan.md` | 暫存計畫檔，未確認為正式 docs artifact。 |

## 建議下一步

1. **提交本輪 Ollama 反證與自訓計畫**：保留研究證據，避免後續重複嘗試 prompt-only SLM。
2. **啟動 Ubuntu dogfood lane**：Fcitx5 deterministic mode + content-free counters + local install/uninstall flow。
3. **讓使用者手寫 Bigram 練習開始**：agent 只做 review、測試、benchmark、content-free report。
4. **修正 learned scorer gate**：避免 deterministic clean heldout 滿分時造成不合理 promotion 判準。
5. **暫停 SLM hot path wiring**：直到 constrained n-gram / ranker 路線通過 gate。

## 驗證建議

本次 commit 前應至少執行：

- `python3 Tools/SLMRerankerExperiment/local_llm_scorer.py --self-test`
- `python3 -m py_compile Tools/SLMRerankerExperiment/local_llm_scorer.py`
- `python3 -m json.tool` for model manifests, registry, and Ollama smoke report
- `git diff --check`

完整 runtime / CI gate 可在後續 Ubuntu lane 中重新跑。
