# 台灣繁中注音輸入法自訓 N-gram 與 Ranker 實作評測計畫

最後更新：2026-06-25T00:00:00+08:00

## 目的

這份文件是給「自己練習模型訓練」用的工程任務書。目標不是一開始做出最強模型，而是完整走過資料、訓練、scoring、評測、gate、錯誤分析與 runtime 決策。

最終希望建立一條可掌控、可驗證、可回退的本機模型路線：

```text
手寫 Bigram
→ Trigram
→ generic 5-gram + backoff
→ KenLM 對照
→ candidate slot ranker
→ local user adaptation
```

所有模型都必須符合：

- 預設本機執行，不連網。
- 不記錄原始輸入、候選文字、送出文字到 committed report。
- 不直接產生文字，只能重排既有候選或輸出分數。
- 未通過 promotion gate 前，不接 Ubuntu/Fcitx5 或 macOS hot path。
- 按鍵同步路徑只允許微秒到低毫秒級計算。

## 現況與約束

### 已知結果

目前專案已驗證：

- Dictionary-data bigram 幾乎沒有鑑別力，Phase 2 bigram 等同 baseline。
- Prompt-only Ollama/Qwen/Gemma SLM 不適合即時輸入法：
  - 小模型常輸出 invalid index。
  - 大模型單筆 latency 達秒級到十秒級。
  - 即使用 `think:false` 修掉 response 空輸出問題，也無法達到 promotion gate。
- Deterministic reranker 在 clean heldout 已可達 `63/63`，所以 SLM 或 learned scorer 的 gate 不能再寫成「必須打贏 clean deterministic」，否則 gate 不合理。

### 延遲預算

| 路徑 | 目標 | 硬性上限 | 說明 |
|---|---:|---:|---|
| 每次按鍵同步 rerank | p95 < 2ms | p99 < 5ms | 只允許 deterministic、n-gram、small ranker |
| 送出前 SLM / heavier rerank | p95 < 20ms | >30ms 直接回退 | 僅空白、Enter、標點或停頓後 |
| 背景模型載入 / 訓練 | 不阻塞輸入 | 可取消 | 只能 idle 或使用者明確啟動 |

### Promotion Gate 建議修正版

因 deterministic clean heldout 已滿分，後續 learned scorer 應採用：

| Gate | 要求 |
|---|---|
| clean heldout | 不退化 deterministic |
| OOD / dogfood fixture | improved cases > regressed cases |
| candidate validity | non-candidate violation = 0 |
| fallback | deterministic/n-gram/ranker 不應 fallback；LLM fallback 必須可回退 |
| latency | hot path p95 < 2ms；commit-time p95 < 20ms |
| privacy | report content-free，不含 raw text/candidates |
| runtime | 未通過 gate 不接預設 runtime |

## Phase 0：資料與評測場地

### 目標

建立可重現的 corpus pipeline 與 contamination audit，避免訓練資料偷看到 benchmark fixture。

### 建議檔案

```text
Tools/Training/prepare_corpus.py
Tools/Training/audit_fixture_contamination.py
Tools/Training/corpus_stats.py
data/corpus/train.txt
data/corpus/valid.txt
data/corpus/test_heldout.txt
docs/reports/experiments/phase2_6/corpus_manifest.json
```

### Corpus 規則

- UTF-8，一行一句。
- 保留台灣繁中用字。
- 保留標點，但訓練時要能選擇 normalize。
- 英文片段保留；初期 scoring 可跳過或降權。
- 排除所有 benchmark fixture 的 expected/baseline/output 文字。
- 每個來源記錄 license、來源日期、處理方式與可 redistributable 狀態。

### Contamination Audit

至少檢查：

- 完整 fixture sentence 是否出現在 train。
- 去標點後 sentence 是否出現在 train。
- CJK-only sentence 是否出現在 train。
- 任意長度 `n >= 8` 的連續字串是否大量重疊。

報告只記 aggregate：

```json
{
  "corpus": "train",
  "lines": 123456,
  "cjk_chars": 9876543,
  "fixture_cases_checked": 297,
  "exact_sentence_hits": 0,
  "normalized_sentence_hits": 0,
  "long_ngram_overlap_cases": 0,
  "gate_result": "PASS"
}
```

### 驗收

- `corpus_manifest.json` 可 parse。
- contamination = 0。
- corpus split 可重現。
- report 不含原始句子。

## Phase 1：手寫 Character Bigram

### 目標

用最簡單模型練完整 pipeline。這一階段不要求打贏 deterministic。

### 模型

```text
P(c_i | c_{i-1})
score(sentence) = sum log P(c_i | c_{i-1})
```

Add-k smoothing：

```text
P(next | prev) = (count(prev,next) + k) / (count(prev) + k * V)
```

建議 sweep：

```text
k = 0.1, 0.01, 0.001
```

### 建議檔案

```text
Tools/Training/train_char_bigram.py
Tools/Training/eval_char_bigram.py
Tools/Training/ngram_model.py
Models/char_bigram.json
docs/reports/experiments/phase2_6/char_bigram_benchmark.json
```

### 實作建議

先用 JSON，之後再做 binary：

```json
{
  "model_type": "char-ngram",
  "order": 2,
  "smoothing": {"type": "add-k", "k": 0.01},
  "vocab_size": 12345,
  "unigrams": {"我": 100},
  "ngrams": {"我\t和": 42}
}
```

必要 API：

```python
class CharNgramModel:
    def score_sentence(self, text: str) -> float: ...
    def score_candidate(self, left: str, candidate: str, right: str) -> float: ...
```

Candidate scoring 初期只看局部：

```text
left = 我
candidate = 和
right = 他

score = log P(和 | 我) + log P(他 | 和)
```

### Unit Tests

必測：

- 空 corpus fail closed。
- unknown char 不 crash。
- add-k smoothing 不產生 `-inf`。
- 同一 corpus 下常見 bigram 分數高於 unseen bigram。
- `score_candidate()` 只重算局部 window。

### Eval

Bigram evaluation 分四層：

1. Intrinsic：
   - valid set average negative log likelihood
   - unknown char rate
   - model size
2. Synthetic sanity：
   - 人工 10-20 個 homophone examples
   - 只檢查分數方向是否合理
3. Fixture benchmark：
   - baseline
   - deterministic
   - char-bigram
4. Latency：
   - p50/p95/p99 candidate scoring time

### 預期

Bigram 可能改善少數例子，但很可能不贏 deterministic。這是正常結果。

## Phase 2：Character Trigram

### 目標

讓模型看到短上下文，開始理解 `左二 + 左一 + candidate + 右一`。

### 模型

```text
P(c_i | c_{i-2}, c_{i-1})
```

Backoff：

```text
if trigram exists:
    use trigram
elif bigram exists:
    use bigram
else:
    use unigram
```

### 建議檔案

```text
Tools/Training/train_char_trigram.py
Models/char_trigram.json
docs/reports/experiments/phase2_6/char_trigram_benchmark.json
```

### 實作建議

不要複製 bigram trainer。把 Phase 1 重構成 generic order：

```python
class NgramCounter:
    def observe_sentence(self, chars: list[str]) -> None: ...
    def count_ngram(self, history: tuple[str, ...], token: str) -> int: ...

class BackoffScorer:
    def logprob(self, history: tuple[str, ...], token: str) -> float: ...
```

Backoff 報告要記：

```json
{
  "backoff_usage": {
    "order_3": 1234,
    "order_2": 456,
    "order_1": 78,
    "unknown": 9
  }
}
```

### Eval

和 Bigram 同樣四層，但新增：

- trigram coverage
- backoff distribution
- changed/improved/regressed cases
- 對 Bigram 的 delta

### Gate

- 不得比 Bigram 明顯退化。
- latency p95 應仍小於 2ms。
- 若 improved <= regressed，不能 promotion。

## Phase 3：Generic 5-gram + Backoff

### 目標

建立真正值得比較的統計 LM baseline。

### 模型

```text
P(c_i | c_{i-4}, c_{i-3}, c_{i-2}, c_{i-1})
5-gram → 4-gram → trigram → bigram → unigram
```

### 建議檔案

```text
Tools/Training/train_char_ngram.py
Tools/Training/ngram_binary.py
Tools/Training/eval_char_ngram.py
Models/char_5gram.json
Models/char_5gram.bin
docs/reports/experiments/phase2_6/char_5gram_benchmark.json
```

### 實作建議

訓練 flags：

```text
--order 5
--min-count 2
--smoothing add-k
--k 0.01
--max-vocab 50000
--exclude-fixtures Tests/fixtures/contextual_bopomofo
--manifest-output docs/reports/experiments/phase2_6/char_5gram_manifest.json
```

Pruning：

- order 1-2 可保留完整。
- order 3-5 可先 `min_count >= 2`。
- 記錄被 prune 的 ngram 數。

Runtime scoring 不要整句重算：

```text
只重算 candidate 影響範圍：
left_context up to order-1
candidate chars
right_context up to order-1
```

### Binary Format 建議

JSON 便於練習，但 runtime 應轉 binary：

```text
magic: "CNLM"
version: uint32
order: uint32
vocab_count: uint32
ngram_count: uint64
entries: sorted hash/history/token/logprob/backoff
endianness: little-endian
```

### Eval

新增 model-level 指標：

- model size
- load time
- memory RSS
- ngram hit rate by order
- scoring latency by slot count

Benchmark 指標：

```json
{
  "exact_accuracy_pct": 0.0,
  "changed_cases": 0,
  "improved_cases": 0,
  "regressed_cases": 0,
  "latency_us": {"p50": 0, "p95": 0, "p99": 0},
  "ngram_hit_rate": {"order_5": 0.0, "order_4": 0.0},
  "gate_result": "PASS|FAIL"
}
```

### Gate

- clean heldout 不退化 deterministic。
- OOD/dogfood improved > regressed。
- p95 < 2ms 才可考慮 hot path。
- model size 初期目標 < 50MB。

## Phase 4：KenLM 對照

### 目標

用成熟 n-gram 工具驗證自己手寫模型的上限與差距。

### 訓練

先把 corpus 轉成字級 token：

```text
我 和 他 是 朋 友
```

KenLM 指令：

```bash
lmplz -o 5 < train.char.txt > char_5gram.arpa
build_binary char_5gram.arpa char_5gram.klm
```

### 建議檔案

```text
Tools/Training/export_kenlm_corpus.py
Tools/Training/train_kenlm_char5.sh
Tools/Training/eval_kenlm_scorer.py
Models/char_5gram.klm
docs/reports/experiments/phase2_6/kenlm_char5_benchmark.json
```

### Eval

比較：

| 模型 | accuracy | improved | regressed | p95 latency | size | load time |
|---|---:|---:|---:|---:|---:|---:|
| hand 5-gram | | | | | | |
| KenLM 5-gram | | | | | | |

### 決策

- KenLM 明顯更快或更準：runtime 優先接 KenLM。
- 手寫版接近 KenLM：保留手寫版，方便 C++ 深度整合。
- 兩者都沒改善：轉向 candidate ranker。

## Phase 5：Candidate Slot Ranker v2

### 目標

從「整句 LM」改為真正符合輸入法的「候選 slot 排序」。

### 資料格式

一個 slot 生成多筆 pair/classification examples：

```json
{
  "fixture_id": "content-free-id",
  "slot_index": 2,
  "reading": "ㄏㄜˊ",
  "baseline_rank": 1,
  "candidate_rank": 3,
  "candidate_is_baseline": false,
  "label": 1,
  "features": {
    "left_len": 2,
    "right_len": 3,
    "ngram_score_delta": 1.23,
    "candidate_frequency_bucket": 4
  }
}
```

Committed report 不存 raw candidate text。訓練中本機可用 raw text，但不得寫入 docs report。

### Features

初版：

```text
reading
candidate char id / hash
baseline char id / hash
candidate == baseline
candidate original rank
left char 1/2/3 hashed
right char 1/2/3 hashed
left+candidate ngram score
candidate+right ngram score
candidate frequency bucket
baseline frequency bucket
protected English span flag
punctuation context flag
```

不要再用 exact full-window string 當唯一依據。前一版 candidate-ranker-v1 失敗原因就是 exact feature matching 無法 generalize。

### 模型順序

1. Logistic regression / linear model
2. fastText supervised
3. tiny MLP
4. ONNX runtime scorer

### 建議檔案

```text
Tools/Training/export_ranker_features.py
Tools/Training/train_candidate_ranker_v2.py
Tools/Training/eval_candidate_ranker_v2.py
Models/candidate_ranker_v2.json
Models/candidate_ranker_v2.onnx
docs/reports/experiments/phase2_6/candidate_ranker_v2_benchmark.json
```

### Eval

分兩種：

#### Slot-level

- top-1 candidate accuracy
- MRR
- expected candidate rank before/after
- non-candidate violation 必須為 0

#### Sentence-level

- exact sentence accuracy
- changed cases
- improved cases
- regressed cases
- protected English regression
- punctuation regression
- p50/p95/p99 latency

### Gate

```text
clean heldout:
  exact >= deterministic
  regressions = 0

OOD/dogfood:
  improved > regressed

latency:
  p95 < 2ms for hot path candidate ranker

privacy:
  content-free report only
```

## Phase 6：Local User Adaptation

### 目標

讓模型學使用者自己的選字習慣，優先做簡單可控的 local-only adaptation。

### 事件

只在本機保存：

```text
reading + selected candidate count
previous char hash + selected candidate count
selected candidate + next char hash count
phrase override count
manual correction count
```

### 儲存

```text
~/.local/share/mcbopomofo-slm/user_adaptation.bin
```

### Scoring

```text
final_score =
  engine_score
  + deterministic_delta
  + ngram_delta
  + ranker_delta
  + user_adaptation_delta
```

### Eval

Synthetic user profile：

- 建 3 組不同習慣 profile。
- replay 同一批 fixture。
- 確認 profile A 的偏好不污染 profile B。

Dogfood content-free counters：

```json
{
  "user_adaptation_enabled": true,
  "events_recorded": 123,
  "adaptation_hits": 45,
  "adaptation_overrides": 6,
  "user_reverted_after_override": 0,
  "latency_bucket_counts": {
    "lt_1ms": 100,
    "1_2ms": 20,
    "gt_2ms": 3
  }
}
```

### Gate

- 可停用。
- 可清除。
- 無 user data 時行為等同 baseline。
- 不寫 raw text 到 report。
- user correction 後不應提高後續 revert 率。

## 統一 Eval Matrix

每個模型都跑同一張矩陣：

| Eval | Bigram | Trigram | 5-gram | KenLM | Ranker v2 | User adaptation |
|---|---|---|---|---|---|---|
| unit tests | required | required | required | required | required | required |
| corpus contamination | required | required | required | required | required | required |
| intrinsic valid loss | required | required | required | required | optional | optional |
| synthetic sanity | required | required | required | required | required | required |
| canonical 234 | required | required | required | required | required | required |
| heldout clean 63 | required | required | required | required | required | required |
| OOD fixture | optional initially | required | required | required | required | required |
| latency p50/p95/p99 | required | required | required | required | required | required |
| content-free report | required | required | required | required | required | required |
| runtime gate | no | no | maybe | maybe | maybe | maybe |

## Eval Report Schema

每次 benchmark 產生：

```json
{
  "id": "phase2_6-char-5gram-benchmark",
  "date": "2026-06-25T00:00:00+08:00",
  "branch": "slm-phase2-learnable",
  "model": {
    "type": "char-ngram",
    "order": 5,
    "path": "Models/char_5gram.bin",
    "size_bytes": 0
  },
  "privacy": {
    "content_free": true,
    "raw_text_recorded": false,
    "candidate_text_recorded": false
  },
  "fixtures": {
    "canonical_total": 234,
    "heldout_clean_total": 63
  },
  "metrics": {
    "exact_accuracy_pct": 0.0,
    "changed_cases": 0,
    "improved_cases": 0,
    "regressed_cases": 0,
    "fallbacks": 0,
    "candidate_violations": 0,
    "latency_us": {"p50": 0, "p95": 0, "p99": 0}
  },
  "gate": {
    "result": "PASS|FAIL",
    "reasons": []
  },
  "verification": []
}
```

## Error Analysis

每次 eval 後都要分類，不要只看總 accuracy。

分類：

```text
homophone
taiwan-specific
english-mixed
slang
punctuation
stress
candidate-missing
model-latency
format/fallback
```

Report 只記 count：

```json
{
  "error_categories": {
    "homophone": {"remaining": 10, "improved": 2, "regressed": 1},
    "english_mixed": {"remaining": 2, "improved": 0, "regressed": 0}
  }
}
```

## Runtime 接入順序

不要一邊訓練一邊直接接 Fcitx5 runtime。順序應該是：

1. Python trainer + evaluator proof。
2. C++ scorer loader + unit tests。
3. ContextualEvaluation benchmark。
4. Linux CLI demo。
5. Fcitx5 feature flag shadow mode。
6. Content-free dogfood counters。
7. Gate pass 才能預設啟用。

Feature flag：

```text
Off
Deterministic
NgramPrototype
RankerPrototype
UserAdaptationPrototype
```

預設仍應是 `Off` 或 `Deterministic`，直到 dogfood 通過。

## 你自己與 Agent 的分工

### 你自己實作

- corpus preparation
- bigram trainer
- trigram / n-gram backoff
- score_candidate
- small ranker first version
- 手動讀錯誤分析，決定下一輪 features

### Agent 驗證

- code review
- 補 unit tests
- 跑 contamination audit
- 跑 benchmark
- 產生 content-free report
- 檢查 latency gate
- 檢查 registry/report schema

### Agent Prompt

所有 opencode / implement agent prompt 都要以 `ultrawork` 開頭：

```text
ultrawork User is manually implementing the n-gram/ranker training exercises. Act as verifier and reviewer. Inspect the new trainer/scorer, add focused tests only where needed, run contamination audit, run canonical/heldout/OOD benchmarks, produce content-free reports, and recommend the smallest next correction. Do not replace the user's implementation unless it is broken, unsafe, or violates privacy/runtime gates.
```

## Milestone Checklist

### M1 Bigram Practice

- [ ] `prepare_corpus.py`
- [ ] `audit_fixture_contamination.py`
- [ ] `train_char_bigram.py`
- [ ] `score_candidate()`
- [ ] unit tests
- [ ] synthetic sanity eval
- [ ] canonical + heldout benchmark
- [ ] content-free report

### M2 Trigram

- [ ] generic `NgramCounter`
- [ ] backoff scorer
- [ ] backoff usage report
- [ ] benchmark vs Bigram
- [ ] latency report

### M3 5-gram

- [ ] `--order 5`
- [ ] pruning
- [ ] binary model draft
- [ ] model load-time benchmark
- [ ] benchmark vs deterministic

### M4 KenLM

- [ ] char-tokenized corpus export
- [ ] KenLM train script
- [ ] KenLM scorer adapter
- [ ] comparison report

### M5 Candidate Ranker v2

- [ ] feature exporter
- [ ] train classifier
- [ ] slot-level eval
- [ ] sentence-level eval
- [ ] no-regression gate

### M6 User Adaptation

- [ ] local-only event store
- [ ] clear/disable controls
- [ ] synthetic user replay
- [ ] dogfood content-free counters

## 停止或轉向條件

立即停止某路線：

- clean heldout 退化且無明確修復方向。
- p95 latency 超過預算 5 倍以上。
- report 需要 raw text 才能解釋結果。
- candidate violation 不可消除。
- improved cases 長期小於或等於 regressed cases。

轉向建議：

- Bigram/Trigram 無改善：升 5-gram 或 KenLM。
- 5-gram 仍無改善：轉 candidate ranker。
- Ranker v2 overfit：增加 OOD、改 features、降低模型複雜度。
- 所有 learned scorer 都不穩：保留 deterministic + user adaptation，先把 Ubuntu/Fcitx5 做穩。

## 最重要的學習目標

這條路線的價值不是 Bigram 本身，而是讓你練會：

- 怎麼避免 training/eval contamination。
- 怎麼把模型輸出限制在候選集合內。
- 怎麼用 latency 和 regression gate 決定是否接 runtime。
- 怎麼分辨「模型看起來聰明」和「輸入法真的少修字」。
- 怎麼讓本機個人化改善你的輸入，而不犧牲隱私與穩定性。
