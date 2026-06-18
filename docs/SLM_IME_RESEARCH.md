# SLM IME Research Brief

Last updated: 2026-06-18T18:20:30+08:00

## Scope

This brief evaluates whether a small language model should be added to this
McBopomofo fork to improve continuous Bopomofo-to-Traditional-Chinese
conversion for macOS and Ubuntu users.

The product target is not a general writing assistant. The target is a local
input method that reduces wrong candidate choices while preserving low latency,
privacy, deterministic fallback behavior, and user override semantics.

The primary language market is Taiwan Traditional Chinese:

- Traditional Chinese orthography used in Taiwan, not Simplified Chinese and not
  Hong Kong written conventions by default.
- Taiwan vocabulary, institutions, named entities, colloquial function words,
  and common professional writing patterns.
- Bopomofo-first input, with English mixed into ordinary Taiwanese technical,
  work, and messaging text.
- Taiwanese users on macOS and Ubuntu first; other Chinese-language markets are
  secondary compatibility concerns.

## First-Principles Audit

### 1. Actual Need

The stated solution is to add a small language model. The underlying need is to
reduce correction work during continuous Bopomofo input, especially when the
current unigram scoring chooses locally frequent words that are wrong in the
sentence context.

### 2. Load-Bearing Assumption

The load-bearing assumption is that Taiwan-focused contextual reranking can
improve top-1 conversion accuracy enough to justify model runtime cost,
training cost, and packaging complexity.

This assumption is only partially verified:

- The local code and `algorithm.md` state that the current conversion uses a
  unigram model and does not consider context.
- Rime has separate language-model and next-word-prediction plugin directions,
  showing that advanced IME engines treat language-modeling as a distinct
  extension point.
- Gboard research and HUOZIIME show that keyboard language models and on-device
  IME models are active product and research directions.

It is not yet verified that an SLM beats a simpler contextual reranker on this
Taiwan Traditional Chinese Bopomofo task. The MVP must compare both.

### 3. What Changes if the Assumption Is Wrong

If an SLM does not beat lighter methods under the latency budget, the product
should ship a deterministic contextual reranker first: Taiwan phrase transition
features, user override learning, English-mixed text handling, and domain
lexicon adaptation. The SLM then becomes an optional offline trainer, distilled
reranker source, or advanced runtime reranker, not a required runtime dependency.

### 4. Root-Cause Versus Workaround

The root cause is missing context in the scoring function. Replacing the IME
with a generative chat-style model would be a workaround because it would hide
candidate ranking behind a slow, hard-to-debug component. The root-cause fix is
to add a bounded contextual scoring layer that can be disabled, benchmarked, and
compared against the existing unigram path.

### 5. Risk Review

The risky decision is runtime model integration inside an input method process.
An IME sees sensitive text. The default architecture must be local-only, must
not log typed content, and must preserve the existing no-model fallback path.

## Current Local Baseline

The project is a macOS Input Method Kit application with Swift UI/state code,
Objective-C++ bridging, and a C++ engine. The current key path is:

- `Source/Engine/gramambular2/reading_grid.h`: `ReadingGrid` stores Bopomofo
  readings, candidate nodes, and walk results.
- `Source/Engine/McBopomofoLM.cpp`: `getUnigrams()` merges excluded phrases,
  user phrases, main dictionary entries, replacement rules, macros, conversion,
  and deduplication.
- `algorithm.md`: states that McBopomofo currently uses unigrams; each word or
  phrase has an independent score and context is not modeled.

Observed local constraints:

- Existing candidate walk is deterministic and fast.
- User phrase behavior already includes special score handling for single-
  syllable versus multi-syllable entries.
- The model insertion point should not bypass `ReadingGrid`, user overrides, or
  `McBopomofoLM::getUnigrams()`.

## External Evidence

| Evidence | What It Means For This Project |
|---|---|
| McBopomofo upstream is a macOS Traditional Chinese Bopomofo IME, MIT licensed, with a 3.0 release on 2026-03-08. Source: https://github.com/openvanilla/McBopomofo | The fork has a narrow but credible macOS base. Ubuntu support cannot be assumed from upstream. |
| libchewing is a Bopomofo/Zhuyin engine used through input frameworks such as IBus and Fcitx; the GitHub mirror points to Codeberg and reports v0.12.0 on 2026-04-06. Sources: https://github.com/chewing/libchewing and https://codeberg.org/chewing/libchewing | Ubuntu support should likely use input-framework integration or a reusable core library rather than porting macOS IMK code directly. |
| Rime is a modular C++ input method engine with Linux, macOS, and Windows frontends; its README lists language-model and next-word-prediction plugins. Source: https://github.com/rime/librime | Rime is the strongest open-source architecture reference for schema/plugin separation and multi-platform deployment. |
| HuoziIME is a 2026 on-device LLM-enhanced IME demo with Android source and llama.cpp/Qwen acknowledgements. Sources: https://arxiv.org/abs/2604.14159 and https://github.com/Shan-HIT/HuoziIME | The category is real, but the project is early and Android-focused. Treat it as evidence for feasibility, not as a mature desktop product benchmark. |
| Gboard research shows mobile keyboard next-word prediction with on-device/federated training and later differential privacy guarantees. Sources: https://arxiv.org/abs/1811.03604 and https://arxiv.org/abs/2305.18465 | Privacy-preserving keyboard modeling is a known production pattern. This project should start with local-only inference and explicit privacy constraints. |
| A 2024 Gboard paper reports 19.0% and 22.8% relative improvement in next-word prediction accuracy from public-LLM-synthesized pretraining data. Source: https://arxiv.org/abs/2404.04360 | Synthetic data can be useful before collecting private user text, but the MVP still needs task-specific Taiwan Bopomofo evaluation. |
| Apple describes on-device processing as a privacy cornerstone and sets strict cloud AI privacy requirements. Source: https://security.apple.com/blog/private-cloud-compute/ | If this product ever adds cloud inference, it needs a separate privacy design. It is out of scope for the MVP. |
| llama.cpp is a C/C++ local inference runtime with Apple Silicon support, Metal, CPU features, and quantization. Source: https://github.com/ggml-org/llama.cpp | llama.cpp is a plausible runtime candidate for a later optional SLM backend, but it is still a new dependency and must not be added before baseline evaluation. |
| StatCounter reports Taiwan desktop OS share in May 2026 as Windows 68.66%, Unknown 17.96%, OS X 7.7%, Linux 2.97%, macOS 2.63%, Chrome OS 0.08%. Source: https://gs.statcounter.com/os-market-share/desktop/taiwan | macOS plus Linux is a meaningful niche but not a mass-market desktop default. The product should target Taiwan power users, developers, writers, and privacy-sensitive users first. |

## Competitor Map

| Product / Project | Platform | Strength | Gap This Project Can Target |
|---|---:|---|---|
| Apple built-in Traditional Chinese input methods | macOS | Preinstalled, familiar, integrated | Closed behavior, limited transparency, no Ubuntu path |
| McBopomofo | macOS | Open source, local, clean Traditional Chinese focus | Current unigram scoring struggles with sentence context |
| libchewing / IBus / Fcitx frontends | Linux, Unix-like, some Windows/macOS paths | Mature Bopomofo ecosystem and input-framework integration | User experience and contextual prediction can feel dated |
| Rime / Squirrel / ibus-rime / fcitx-rime | macOS, Linux, Windows | Highly configurable, schema/plugin architecture | Configuration burden; not focused on SLM-assisted Bopomofo ranking by default |
| HuoziIME | Android | Recent on-device LLM IME proof of concept | Mobile-only, early maturity, GPL constraints |
| Gboard / SwiftKey / iOS keyboard | Mobile | Strong prediction and personalization | Closed source, cloud/federated privacy trust questions, not desktop Bopomofo-first |

## Market Value Hypothesis

The likely initial market is not the general Taiwanese desktop population. It is
users who:

- type Traditional Chinese frequently on macOS and Ubuntu;
- use Taiwan vocabulary and Bopomofo rather than Simplified Chinese Pinyin;
- mix English identifiers, product names, code terms, and acronyms into
  Traditional Chinese text;
- notice context errors in long Bopomofo sequences;
- prefer local and inspectable software over closed prediction systems;
- are willing to install and tune an input method if correction effort falls.

Value is measured by reduced correction work, not by model novelty.

Primary value metric:

- Top-1 sentence conversion accuracy on a held-out Traditional Chinese
  Bopomofo corpus focused on Taiwan usage.

Secondary value metrics:

- Mean and p95 reranking latency per keystroke and per committed segment.
- Candidate page changes per 100 characters.
- Manual corrections per 100 characters in dogfood sessions.
- Memory footprint of the model and reranker.
- User-visible fallback rate.

## Strategic Verdict

Build this as a staged contextual IME project:

1. Establish a reproducible Bopomofo conversion benchmark.
2. Add a deterministic contextual reranker that can be tested without new model
   runtime dependencies.
3. Build a Taiwan Traditional Chinese data and training pipeline, including
   public corpus curation, synthetic ambiguous cases, and private local-only
   adaptation rules.
4. Add an optional local SLM reranker only if it beats the deterministic baseline
   under strict accuracy, latency, privacy, and package-size budgets.
5. Split reusable C++ scoring/evaluation logic from macOS IMK concerns so Ubuntu
   can later use an IBus or Fcitx frontend.

The MVP should not promise open-ended generation, cloud personalization, or a
chat assistant inside the IME.
