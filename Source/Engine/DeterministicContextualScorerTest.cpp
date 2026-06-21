// Copyright (c) 2026 McBopomofo SLM Authors
//
// Permission is hereby granted, free of charge, to any person
// obtaining a copy of this software and associated documentation
// files (the "Software"), to deal in the Software without
// restriction, including without limitation the rights to use,
// copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the
// Software is furnished to do so, subject to the following
// conditions:
//
// The above copyright notice and this permission notice shall be
// included in all copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
// EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
// OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
// NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
// HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
// WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
// FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
// OTHER DEALINGS IN THE SOFTWARE.

#include <string>
#include <vector>

#include "ContextualScorer.h"
#include "DeterministicContextualScorer.h"
#include "gtest/gtest.h"

namespace McBopomofo {

using CandidateInput = CandidateScoreInput;

static ContextualScoreRequest makeRequest(
    const std::vector<std::string>& readings,
    const std::vector<CandidateInput>& baselinePath,
    const std::vector<CandidateInput>& candidates,
    const std::vector<std::string>& protectedEnglishSpans = {}) {
  ContextualScoreRequest req;
  req.readings = readings;
  req.baselinePath = baselinePath;
  req.candidates = candidates;
  req.protectedEnglishSpans = protectedEnglishSpans;
  req.cursor = readings.size();
  return req;
}

TEST(DeterministicScorerTest, ScoreDeltasSizeMatchesCandidates) {
  DeterministicContextualScorer scorer;
  ContextualScoreRequest req;
  req.candidates.resize(5);
  std::vector<double> deltas = scorer.scoreDeltas(req);
  EXPECT_EQ(deltas.size(), 5u);
}

TEST(DeterministicScorerTest, ScoreDeltasAllZeroWhenDisabled) {
  DeterministicContextualScorer scorer;
  scorer.setRuleEnabled("all", false);
  ContextualScoreRequest req;
  req.candidates.resize(3);
  std::vector<double> deltas = scorer.scoreDeltas(req);
  for (size_t i = 0; i < deltas.size(); ++i) {
    EXPECT_EQ(deltas[i], 0.0);
  }
}

TEST(DeterministicScorerTest, SuggestCorrectionsEmptyWhenNoDeltas) {
  DeterministicContextualScorer scorer;
  scorer.setRuleEnabled("all", false);
  ContextualScoreRequest req;
  req.candidates.push_back(CandidateInput{"", "a", "", 0.0, 0, 1});
  req.candidates.push_back(CandidateInput{"", "b", "", 0.0, 1, 1});
  req.baselinePath.push_back(CandidateInput{"", "a", "", 0.0, 0, 1});
  req.baselinePath.push_back(CandidateInput{"", "b", "", 0.0, 1, 1});
  ScorerOutput out = scorer.suggestCorrections(req);
  EXPECT_TRUE(out.corrections.empty());
}

TEST(DeterministicScorerTest, MultiCharCandidateGetsDeltaWithTechTerm) {
  DeterministicContextualScorer scorer;
  ContextualScoreRequest req;
  req.readings = {"ㄑㄧㄥˇ", "ㄘㄢ", "ㄎㄠˇ"};
  req.protectedEnglishSpans = {"README"};
  // baseline: 請 參 靠
  req.baselinePath.push_back(CandidateInput{"ㄑㄧㄥˇ", "請", "", -3.0, 0, 1});
  req.baselinePath.push_back(CandidateInput{"ㄘㄢ", "參", "", -3.0, 1, 1});
  req.baselinePath.push_back(CandidateInput{"ㄎㄠˇ", "靠", "", -3.0, 2, 1});
  // candidates include the bigram 參考
  req.candidates.push_back(CandidateInput{"ㄑㄧㄥˇ", "請", "", -3.0, 0, 1});
  req.candidates.push_back(CandidateInput{"ㄘㄢ", "參", "", -3.0, 1, 1});
  req.candidates.push_back(CandidateInput{"ㄎㄠˇ", "靠", "", -3.0, 2, 1});
  req.candidates.push_back(
      CandidateInput{"ㄘㄢ-ㄎㄠˇ", "參考", "", -4.1, 1, 2});

  ScorerOutput out = scorer.suggestCorrections(req);
  bool foundRef = false;
  for (const auto& c : out.corrections) {
    if (c.value == "參考") {
      foundRef = true;
      EXPECT_EQ(c.start, 1u);
      EXPECT_EQ(c.length, 2u);
      EXPECT_GT(c.scoreDelta, 0.0);
      break;
    }
  }
  EXPECT_TRUE(foundRef);
}

TEST(DeterministicScorerTest, NoTechTermWithoutProtectedEnglish) {
  DeterministicContextualScorer scorer;
  ContextualScoreRequest req;
  req.readings = {"ㄑㄧㄥˇ", "ㄘㄢ", "ㄎㄠˇ"};
  req.protectedEnglishSpans = {};  // no protected spans
  req.baselinePath.push_back(CandidateInput{"ㄑㄧㄥˇ", "請", "", -3.0, 0, 1});
  req.baselinePath.push_back(CandidateInput{"ㄘㄢ", "參", "", -3.0, 1, 1});
  req.baselinePath.push_back(CandidateInput{"ㄎㄠˇ", "靠", "", -3.0, 2, 1});
  req.candidates.push_back(CandidateInput{"ㄑㄧㄥˇ", "請", "", -3.0, 0, 1});
  req.candidates.push_back(CandidateInput{"ㄘㄢ", "參", "", -3.0, 1, 1});
  req.candidates.push_back(CandidateInput{"ㄎㄠˇ", "靠", "", -3.0, 2, 1});
  req.candidates.push_back(
      CandidateInput{"ㄘㄢ-ㄎㄠˇ", "參考", "", -4.1, 1, 2});

  ScorerOutput out = scorer.suggestCorrections(req);
  for (const auto& c : out.corrections) {
    EXPECT_NE(c.value, "參考") << "tech-term should NOT fire without protected English";
  }
}

TEST(DeterministicScorerTest, NoCorrectionForBaselineValue) {
  DeterministicContextualScorer scorer;
  ContextualScoreRequest req;
  req.readings = {"ㄩㄝˋ"};
  req.protectedEnglishSpans = {"README"};
  // baseline already has "越" at position 0
  req.baselinePath.push_back(CandidateInput{"ㄩㄝˋ", "越", "", -3.6, 0, 1});
  // candidate also has "越"
  req.candidates.push_back(CandidateInput{"ㄩㄝˋ", "越", "", -3.6, 0, 1});
  // "越" is NOT in the tech-term list, so no delta from tech-term
  // And the value matches baseline → no correction
  ScorerOutput out = scorer.suggestCorrections(req);
  EXPECT_TRUE(out.corrections.empty());
}

TEST(DeterministicScorerTest, NoCorrectionForBaselineSpanPrefix) {
  DeterministicContextualScorer scorer;
  ContextualScoreRequest req;
  req.readings = {"ㄕㄜˋ", "ㄉㄧㄥˋ", "ㄉㄤˇ"};
  req.protectedEnglishSpans = {"YAML"};
  req.baselinePath.push_back(
      CandidateInput{"ㄕㄜˋ-ㄉㄧㄥˋ-ㄉㄤˇ", "設定檔", "", -5.7, 0, 3});
  req.candidates.push_back(
      CandidateInput{"ㄕㄜˋ-ㄉㄧㄥˋ", "設定", "", -4.2, 0, 2});

  ScorerOutput out = scorer.suggestCorrections(req);
  for (const auto& c : out.corrections) {
    EXPECT_NE(c.value, "設定")
        << "baseline span prefix must not override 設定檔";
  }
}

TEST(DeterministicScorerTest, ProtectedDockerContextSelectsImageTerms) {
  DeterministicContextualScorer scorer;
  ContextualScoreRequest req;
  req.readings = {"ㄢ", "ㄓㄨㄤ", "ㄗㄨㄛˋ", "ㄐㄧㄥˋ", "ㄒㄧㄤˋ"};
  req.protectedEnglishSpans = {"Dockerfile"};
  req.baselinePath.push_back(
      CandidateInput{"ㄢ-ㄓㄨㄤ", "安裝", "", -4.4, 0, 2});
  req.baselinePath.push_back(CandidateInput{"ㄗㄨㄛˋ", "作", "", -2.7, 2, 1});
  req.baselinePath.push_back(CandidateInput{"ㄐㄧㄥˋ", "境", "", -3.4, 3, 1});
  req.baselinePath.push_back(CandidateInput{"ㄒㄧㄤˋ", "相", "", -3.0, 4, 1});
  req.candidates.push_back(CandidateInput{"ㄗㄨㄛˋ", "做", "", -3.0, 2, 1});
  req.candidates.push_back(CandidateInput{"ㄐㄧㄥˋ", "鏡", "", -4.1, 3, 1});
  req.candidates.push_back(CandidateInput{"ㄒㄧㄤˋ", "像", "", -3.1, 4, 1});

  ScorerOutput out = scorer.suggestCorrections(req);
  bool foundDo = false;
  bool foundMirror = false;
  bool foundImage = false;
  for (const auto& c : out.corrections) {
    foundDo = foundDo || c.value == "做";
    foundMirror = foundMirror || c.value == "鏡";
    foundImage = foundImage || c.value == "像";
  }
  EXPECT_TRUE(foundDo);
  EXPECT_TRUE(foundMirror);
  EXPECT_TRUE(foundImage);
}

TEST(DeterministicScorerTest, ProtectedSshContextSelectsKeyTerms) {
  DeterministicContextualScorer scorer;
  ContextualScoreRequest req;
  req.readings = {"ㄌㄧㄢˊ", "ㄒㄧㄢˋ", "ㄧㄠˋ", "ㄕㄜˋ", "ㄐㄧㄣ", "ㄧㄠˋ"};
  req.protectedEnglishSpans = {"SSH"};
  req.baselinePath.push_back(
      CandidateInput{"ㄌㄧㄢˊ-ㄒㄧㄢˋ", "連線", "", -4.5, 0, 2});
  req.baselinePath.push_back(CandidateInput{"ㄧㄠˋ", "要", "", -2.4, 2, 1});
  req.baselinePath.push_back(CandidateInput{"ㄕㄜˋ", "社", "", -3.1, 3, 1});
  req.baselinePath.push_back(CandidateInput{"ㄐㄧㄣ", "今", "", -3.1, 4, 1});
  req.baselinePath.push_back(CandidateInput{"ㄧㄠˋ", "要", "", -2.4, 5, 1});
  req.candidates.push_back(CandidateInput{"ㄕㄜˋ", "設", "", -3.2, 3, 1});
  req.candidates.push_back(CandidateInput{"ㄐㄧㄣ-ㄧㄠˋ", "金鑰", "", -6.0, 4, 2});

  ScorerOutput out = scorer.suggestCorrections(req);
  bool foundSet = false;
  bool foundKey = false;
  for (const auto& c : out.corrections) {
    foundSet = foundSet || c.value == "設";
    foundKey = foundKey || c.value == "金鑰";
  }
  EXPECT_TRUE(foundSet);
  EXPECT_TRUE(foundKey);
}

TEST(DeterministicScorerTest, ProtectedYamlContextSelectsAlignment) {
  DeterministicContextualScorer scorer;
  ContextualScoreRequest req;
  req.readings = {"ㄕㄜˋ", "ㄉㄧㄥˋ", "ㄉㄤˇ", "ㄍㄜˊ", "ㄕˋ", "ㄧㄠˋ", "ㄉㄨㄟˋ", "ㄑㄧˊ"};
  req.protectedEnglishSpans = {"YAML"};
  req.baselinePath.push_back(
      CandidateInput{"ㄕㄜˋ-ㄉㄧㄥˋ-ㄉㄤˇ", "設定檔", "", -5.7, 0, 3});
  req.baselinePath.push_back(
      CandidateInput{"ㄍㄜˊ-ㄕˋ", "格式", "", -4.6, 3, 2});
  req.baselinePath.push_back(CandidateInput{"ㄧㄠˋ", "要", "", -2.4, 5, 1});
  req.baselinePath.push_back(CandidateInput{"ㄉㄨㄟˋ", "對", "", -2.6, 6, 1});
  req.baselinePath.push_back(CandidateInput{"ㄑㄧˊ", "其", "", -2.9, 7, 1});
  req.candidates.push_back(
      CandidateInput{"ㄕㄜˋ-ㄉㄧㄥˋ", "設定", "", -4.2, 0, 2});
  req.candidates.push_back(
      CandidateInput{"ㄉㄨㄟˋ-ㄑㄧˊ", "對齊", "", -6.3, 6, 2});

  ScorerOutput out = scorer.suggestCorrections(req);
  bool foundAlignment = false;
  for (const auto& c : out.corrections) {
    EXPECT_NE(c.value, "設定");
    foundAlignment = foundAlignment || c.value == "對齊";
  }
  EXPECT_TRUE(foundAlignment);
}

TEST(DeterministicScorerTest, ZaiZaiRuleFires) {
  DeterministicContextualScorer scorer;
  ContextualScoreRequest req;
  req.readings = {"ㄗㄞˋ", "ㄕㄨㄛ"};
  // baseline: "在" "說"
  req.baselinePath.push_back(CandidateInput{"ㄗㄞˋ", "在", "", -3.0, 0, 1});
  req.baselinePath.push_back(CandidateInput{"ㄕㄨㄛ", "說", "", -3.0, 1, 1});
  // "再" as alternative candidate
  req.candidates.push_back(CandidateInput{"ㄗㄞˋ", "在", "", -3.0, 0, 1});
  req.candidates.push_back(CandidateInput{"ㄕㄨㄛ", "說", "", -3.0, 1, 1});
  req.candidates.push_back(CandidateInput{"ㄗㄞˋ", "再", "", -4.0, 0, 1});

  ScorerOutput out = scorer.suggestCorrections(req);
  bool foundZai = false;
  for (const auto& c : out.corrections) {
    if (c.value == "再") {
      foundZai = true;
      EXPECT_EQ(c.start, 0u);
      EXPECT_EQ(c.length, 1u);
      EXPECT_GT(c.scoreDelta, 0.0);
      break;
    }
  }
  EXPECT_TRUE(foundZai);
}

TEST(DeterministicScorerTest, SuggestCorrectionsSkipsZeroDelta) {
  DeterministicContextualScorer scorer;
  ContextualScoreRequest req;
  req.readings = {"ㄘㄢ", "ㄎㄠˇ"};
  req.baselinePath.push_back(CandidateInput{"ㄘㄢ", "參", "", -3.0, 0, 1});
  req.baselinePath.push_back(CandidateInput{"ㄎㄠˇ", "考", "", -3.3, 1, 1});
  req.candidates.push_back(CandidateInput{"ㄘㄢ", "參", "", -3.0, 0, 1});
  req.candidates.push_back(CandidateInput{"ㄎㄠˇ", "考", "", -3.3, 1, 1});
  req.candidates.push_back(CandidateInput{"ㄎㄠˇ", "烤", "", -4.7, 1, 1});
  // 烤 has no rule → delta 0 → no correction
  ScorerOutput out = scorer.suggestCorrections(req);
  for (const auto& c : out.corrections) {
    EXPECT_NE(c.value, "烤");
  }
}

TEST(DeterministicScorerTest, RuleCanBeIndividuallyDisabled) {
  DeterministicContextualScorer scorer;
  scorer.setRuleEnabled("zai-zai", false);
  ContextualScoreRequest req;
  req.readings = {"ㄗㄞˋ", "ㄕㄨㄛ"};
  req.baselinePath.push_back(CandidateInput{"ㄗㄞˋ", "在", "", -3.0, 0, 1});
  req.baselinePath.push_back(CandidateInput{"ㄕㄨㄛ", "說", "", -3.0, 1, 1});
  req.candidates.push_back(CandidateInput{"ㄗㄞˋ", "在", "", -3.0, 0, 1});
  req.candidates.push_back(CandidateInput{"ㄕㄨㄛ", "說", "", -3.0, 1, 1});
  req.candidates.push_back(CandidateInput{"ㄗㄞˋ", "再", "", -4.0, 0, 1});
  ScorerOutput out = scorer.suggestCorrections(req);
  for (const auto& c : out.corrections) {
    EXPECT_NE(c.value, "再") << "zai-zai rule disabled";
  }
}

TEST(DeterministicScorerTest, TechTermListIncludesCommonTerms) {
  DeterministicContextualScorer scorer;
  ContextualScoreRequest req;
  req.readings = {"ㄒㄧㄚˋ", "ㄗㄞˇ"};
  req.protectedEnglishSpans = {"GitHub"};
  req.baselinePath.push_back(CandidateInput{"ㄒㄧㄚˋ", "下", "", -3.0, 0, 1});
  req.baselinePath.push_back(CandidateInput{"ㄗㄞˇ", "宰", "", -2.9, 1, 1});
  // bigram "下載"
  req.candidates.push_back(CandidateInput{"ㄒㄧㄚˋ-ㄗㄞˇ", "下載", "", -3.5, 0, 2});

  ScorerOutput out = scorer.suggestCorrections(req);
  bool found = false;
  for (const auto& c : out.corrections) {
    if (c.value == "下載") {
      found = true;
      break;
    }
  }
  EXPECT_TRUE(found);
}

TEST(DeterministicScorerTest, Phase2TaiwanAmbiguousRulesFire) {
  DeterministicContextualScorer scorer;
  ContextualScoreRequest req;
  req.readings = {"ㄧㄡˇ", "ㄕˊ", "ㄍㄜ˙"};
  req.baselinePath.push_back(CandidateInput{"ㄧㄡˇ", "有", "", -3.0, 0, 1});
  req.baselinePath.push_back(CandidateInput{"ㄕˊ", "時", "", -3.0, 1, 1});
  req.baselinePath.push_back(CandidateInput{"ㄍㄜ˙", "個", "", -3.0, 2, 1});
  req.candidates.push_back(CandidateInput{"ㄕˊ", "時", "", -3.0, 1, 1});
  req.candidates.push_back(CandidateInput{"ㄕˊ", "十", "", -4.0, 1, 1});

  ScorerOutput out = scorer.suggestCorrections(req);
  bool foundTen = false;
  for (const auto& c : out.corrections) {
    if (c.value == "十") {
      foundTen = true;
      EXPECT_EQ(c.start, 1u);
      EXPECT_GT(c.scoreDelta, 0.0);
      break;
    }
  }
  EXPECT_TRUE(foundTen);
}

TEST(DeterministicScorerTest, Phase2PhraseRulesFire) {
  DeterministicContextualScorer scorer;
  ContextualScoreRequest req;
  req.readings = {"ㄗˋ", "ㄐㄧˇ", "ㄉㄨㄥˋ", "ㄕㄡˇ", "ㄗㄨㄛˋ", "ㄅㄧˇ"};
  req.baselinePath.push_back(CandidateInput{"ㄗˋ", "自", "", -3.0, 0, 1});
  req.baselinePath.push_back(CandidateInput{"ㄐㄧˇ", "己", "", -3.0, 1, 1});
  req.baselinePath.push_back(CandidateInput{"ㄉㄨㄥˋ", "動", "", -3.0, 2, 1});
  req.baselinePath.push_back(CandidateInput{"ㄕㄡˇ", "手", "", -3.0, 3, 1});
  req.baselinePath.push_back(CandidateInput{"ㄗㄨㄛˋ", "作", "", -3.0, 4, 1});
  req.baselinePath.push_back(CandidateInput{"ㄅㄧˇ", "比", "", -3.0, 5, 1});
  req.candidates.push_back(CandidateInput{"ㄗㄨㄛˋ", "作", "", -3.0, 4, 1});
  req.candidates.push_back(CandidateInput{"ㄗㄨㄛˋ", "做", "", -4.0, 4, 1});

  ScorerOutput out = scorer.suggestCorrections(req);
  bool foundDo = false;
  for (const auto& c : out.corrections) {
    if (c.value == "做") {
      foundDo = true;
      EXPECT_EQ(c.start, 4u);
      EXPECT_GT(c.scoreDelta, 0.0);
      break;
    }
  }
  EXPECT_TRUE(foundDo);
}

TEST(DeterministicScorerTest, Phase2AdjectiveRulesFire) {
  DeterministicContextualScorer scorer;
  ContextualScoreRequest req;
  req.readings = {"ㄏㄣˇ", "ㄒㄧㄣ"};
  req.baselinePath.push_back(CandidateInput{"ㄏㄣˇ", "很", "", -3.0, 0, 1});
  req.baselinePath.push_back(CandidateInput{"ㄒㄧㄣ", "心", "", -3.0, 1, 1});
  req.candidates.push_back(CandidateInput{"ㄒㄧㄣ", "心", "", -3.0, 1, 1});
  req.candidates.push_back(CandidateInput{"ㄒㄧㄣ", "新", "", -4.0, 1, 1});

  ScorerOutput out = scorer.suggestCorrections(req);
  bool foundNew = false;
  for (const auto& c : out.corrections) {
    if (c.value == "新") {
      foundNew = true;
      EXPECT_EQ(c.start, 1u);
      EXPECT_GT(c.scoreDelta, 0.0);
      break;
    }
  }
  EXPECT_TRUE(foundNew);
}

TEST(DeterministicScorerTest, Phase2VariantRulesFire) {
  DeterministicContextualScorer scorer;
  ContextualScoreRequest req;
  req.readings = {"ㄐㄧㄣˋ", "ㄓˇ", "ㄒㄧ", "ㄧㄢ"};
  req.baselinePath.push_back(CandidateInput{"ㄐㄧㄣˋ", "禁", "", -3.0, 0, 1});
  req.baselinePath.push_back(CandidateInput{"ㄓˇ", "止", "", -3.0, 1, 1});
  req.baselinePath.push_back(CandidateInput{"ㄒㄧ-ㄧㄢ", "吸菸", "", -3.0, 2, 2});
  req.candidates.push_back(CandidateInput{"ㄒㄧ-ㄧㄢ", "吸菸", "", -3.0, 2, 2});
  req.candidates.push_back(CandidateInput{"ㄒㄧ-ㄧㄢ", "吸煙", "", -4.0, 2, 2});

  ScorerOutput out = scorer.suggestCorrections(req);
  bool foundSmoke = false;
  for (const auto& c : out.corrections) {
    if (c.value == "吸煙") {
      foundSmoke = true;
      EXPECT_EQ(c.start, 2u);
      EXPECT_EQ(c.length, 2u);
      EXPECT_GT(c.scoreDelta, 0.0);
      break;
    }
  }
  EXPECT_TRUE(foundSmoke);
}

TEST(DeterministicScorerTest, Phase2ProgramPhraseRulesFireInsideBaselineSpan) {
  DeterministicContextualScorer scorer;
  ContextualScoreRequest req;
  req.readings = {"ㄅㄧㄢ", "ㄒㄧㄝˇ", "ㄔㄥˊ", "ㄕˋ", "ㄏㄣˇ"};
  req.baselinePath.push_back(
      CandidateInput{"ㄅㄧㄢ-ㄒㄧㄝˇ-ㄔㄥˊ", "編寫成", "", -3.0, 0, 3});
  req.baselinePath.push_back(CandidateInput{"ㄕˋ", "是", "", -3.0, 3, 1});
  req.baselinePath.push_back(CandidateInput{"ㄏㄣˇ", "很", "", -3.0, 4, 1});
  req.candidates.push_back(CandidateInput{"ㄔㄥˊ-ㄕˋ", "成事", "", -3.0, 2, 2});
  req.candidates.push_back(CandidateInput{"ㄔㄥˊ-ㄕˋ", "程式", "", -4.0, 2, 2});

  ScorerOutput out = scorer.suggestCorrections(req);
  bool foundProgram = false;
  for (const auto& c : out.corrections) {
    if (c.value == "程式") {
      foundProgram = true;
      EXPECT_EQ(c.start, 2u);
      EXPECT_EQ(c.length, 2u);
      EXPECT_GT(c.scoreDelta, 0.0);
      break;
    }
  }
  EXPECT_TRUE(foundProgram);
}

}  // namespace McBopomofo
