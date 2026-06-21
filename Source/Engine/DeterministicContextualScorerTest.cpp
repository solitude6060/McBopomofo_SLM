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

static bool hasCorrectionValue(const DeterministicContextualScorer& scorer,
                               const ContextualScoreRequest& req,
                               const std::string& value) {
  ScorerOutput out = scorer.suggestCorrections(req);
  for (const auto& c : out.corrections) {
    if (c.value == value) {
      return true;
    }
  }
  return false;
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

TEST(DeterministicScorerTest, TaiwanSpecificFoodRulesFire) {
  DeterministicContextualScorer scorer;
  ContextualScoreRequest req;
  req.readings = {"ㄓㄜˋ", "ㄐㄧㄚ", "ㄌㄨˇ", "ㄖㄡˋ", "ㄈㄢˋ",
                  "ㄧㄠˋ", "ㄐㄧㄚ", "ㄊㄧㄢˊ", "ㄌㄚˋ"};
  req.baselinePath.push_back(CandidateInput{"ㄓㄜˋ", "這", "", -3.0, 0, 1});
  req.baselinePath.push_back(CandidateInput{"ㄐㄧㄚ", "家", "", -3.0, 1, 1});
  req.baselinePath.push_back(
      CandidateInput{"ㄌㄨˇ-ㄖㄡˋ-ㄈㄢˋ", "魯肉飯", "", -5.9, 2, 3});
  req.baselinePath.push_back(CandidateInput{"ㄧㄠˋ", "要", "", -3.0, 5, 1});
  req.baselinePath.push_back(CandidateInput{"ㄐㄧㄚ", "家", "", -3.0, 6, 1});
  req.baselinePath.push_back(CandidateInput{"ㄊㄧㄢˊ", "田", "", -3.0, 7, 1});
  req.baselinePath.push_back(CandidateInput{"ㄌㄚˋ", "辣", "", -3.0, 8, 1});
  req.candidates.push_back(
      CandidateInput{"ㄌㄨˇ-ㄖㄡˋ-ㄈㄢˋ", "滷肉飯", "", -6.2, 2, 3});
  req.candidates.push_back(CandidateInput{"ㄐㄧㄚ", "加", "", -4.0, 6, 1});
  req.candidates.push_back(CandidateInput{"ㄊㄧㄢˊ", "甜", "", -4.0, 7, 1});

  ScorerOutput out = scorer.suggestCorrections(req);
  bool foundBraised = false;
  bool foundAdd = false;
  bool foundSweet = false;
  for (const auto& c : out.corrections) {
    foundBraised = foundBraised || c.value == "滷肉飯";
    foundAdd = foundAdd || c.value == "加";
    foundSweet = foundSweet || c.value == "甜";
  }
  EXPECT_TRUE(foundBraised);
  EXPECT_TRUE(foundAdd);
  EXPECT_TRUE(foundSweet);
}

TEST(DeterministicScorerTest, TaiwanSpecificDailyLifeRulesFire) {
  DeterministicContextualScorer scorer;
  ContextualScoreRequest req;
  req.readings = {"ㄐㄧ", "ㄔㄜ", "ㄧㄠˋ", "ㄊㄧㄥˊ", "ㄗㄞˋ",
                  "ㄍㄜˊ", "ㄗ˙", "ㄌㄧˇ", "ㄎㄨㄞˋ", "ㄉㄧㄢˇ",
                  "ㄉㄠˇ"};
  req.baselinePath.push_back(CandidateInput{"ㄐㄧ-ㄔㄜ", "機車", "", -3.0, 0, 2});
  req.baselinePath.push_back(CandidateInput{"ㄧㄠˋ", "要", "", -3.0, 2, 1});
  req.baselinePath.push_back(CandidateInput{"ㄊㄧㄥˊ", "停", "", -3.0, 3, 1});
  req.baselinePath.push_back(CandidateInput{"ㄗㄞˋ", "在", "", -3.0, 4, 1});
  req.baselinePath.push_back(CandidateInput{"ㄍㄜˊ", "格", "", -3.0, 5, 1});
  req.baselinePath.push_back(CandidateInput{"ㄗ˙", "子", "", -3.0, 6, 1});
  req.baselinePath.push_back(CandidateInput{"ㄌㄧˇ", "理", "", -3.0, 7, 1});
  req.baselinePath.push_back(CandidateInput{"ㄎㄨㄞˋ", "快", "", -3.0, 8, 1});
  req.baselinePath.push_back(CandidateInput{"ㄉㄧㄢˇ", "點", "", -3.0, 9, 1});
  req.baselinePath.push_back(CandidateInput{"ㄉㄠˇ", "導", "", -3.0, 10, 1});
  req.candidates.push_back(CandidateInput{"ㄌㄧˇ", "裡", "", -4.0, 7, 1});
  req.candidates.push_back(CandidateInput{"ㄉㄠˇ", "倒", "", -4.0, 10, 1});

  ScorerOutput out = scorer.suggestCorrections(req);
  bool foundInside = false;
  bool foundPour = false;
  for (const auto& c : out.corrections) {
    foundInside = foundInside || c.value == "裡";
    foundPour = foundPour || c.value == "倒";
  }
  EXPECT_TRUE(foundInside);
  EXPECT_TRUE(foundPour);
}

TEST(DeterministicScorerTest, TaiwanSpecificProtectedBrandRulesFire) {
  DeterministicContextualScorer scorer;
  ContextualScoreRequest req;
  req.readings = {"ㄓㄢˋ", "ㄉㄧㄢˇ", "ㄏㄣˇ", "ㄉㄨㄛ",
                  "ㄓˊ", "ㄏㄣˇ", "ㄍㄠ", "ㄉㄧㄢˋ", "ㄏㄣˇ"};
  req.protectedEnglishSpans = {"YouBike", "CP", "chill"};
  req.baselinePath.push_back(CandidateInput{"ㄓㄢˋ", "戰", "", -3.0, 0, 1});
  req.baselinePath.push_back(CandidateInput{"ㄉㄧㄢˇ", "點", "", -3.0, 1, 1});
  req.baselinePath.push_back(CandidateInput{"ㄏㄣˇ", "很", "", -3.0, 2, 1});
  req.baselinePath.push_back(CandidateInput{"ㄉㄨㄛ", "多", "", -3.0, 3, 1});
  req.baselinePath.push_back(CandidateInput{"ㄓˊ", "直", "", -3.0, 4, 1});
  req.baselinePath.push_back(CandidateInput{"ㄏㄣˇ", "很", "", -3.0, 5, 1});
  req.baselinePath.push_back(CandidateInput{"ㄍㄠ", "高", "", -3.0, 6, 1});
  req.baselinePath.push_back(CandidateInput{"ㄉㄧㄢˋ", "電", "", -3.0, 7, 1});
  req.baselinePath.push_back(CandidateInput{"ㄏㄣˇ", "很", "", -3.0, 8, 1});
  req.candidates.push_back(CandidateInput{"ㄓㄢˋ", "站", "", -4.0, 0, 1});
  req.candidates.push_back(CandidateInput{"ㄓˊ", "值", "", -4.0, 4, 1});
  req.candidates.push_back(CandidateInput{"ㄉㄧㄢˋ", "店", "", -4.0, 7, 1});

  ScorerOutput out = scorer.suggestCorrections(req);
  bool foundStation = false;
  bool foundValue = false;
  bool foundShop = false;
  for (const auto& c : out.corrections) {
    foundStation = foundStation || c.value == "站";
    foundValue = foundValue || c.value == "值";
    foundShop = foundShop || c.value == "店";
  }
  EXPECT_TRUE(foundStation);
  EXPECT_TRUE(foundValue);
  EXPECT_TRUE(foundShop);
}

TEST(DeterministicScorerTest, TaiwanSpecificColloquialRulesFire) {
  DeterministicContextualScorer scorer;
  ContextualScoreRequest req;
  req.readings = {"ㄕˋ", "ㄚ", "ㄅㄟˇ", "ㄌㄨㄛˋ", "ㄓㄣˇ",
                  "ㄌㄜ˙", "ㄅㄚ"};
  req.baselinePath.push_back(CandidateInput{"ㄕˋ", "是", "", -3.0, 0, 1});
  req.baselinePath.push_back(CandidateInput{"ㄚ", "啊", "", -3.0, 1, 1});
  req.baselinePath.push_back(CandidateInput{"ㄅㄟˇ", "北", "", -3.0, 2, 1});
  req.baselinePath.push_back(CandidateInput{"ㄌㄨㄛˋ", "落", "", -3.0, 3, 1});
  req.baselinePath.push_back(CandidateInput{"ㄓㄣˇ", "診", "", -3.0, 4, 1});
  req.baselinePath.push_back(CandidateInput{"ㄌㄜ˙", "了", "", -3.0, 5, 1});
  req.baselinePath.push_back(CandidateInput{"ㄅㄚ", "八", "", -3.0, 6, 1});
  req.candidates.push_back(CandidateInput{"ㄚ", "阿", "", -4.0, 1, 1});
  req.candidates.push_back(CandidateInput{"ㄓㄣˇ", "枕", "", -4.0, 4, 1});
  req.candidates.push_back(CandidateInput{"ㄅㄚ", "吧", "", -4.0, 6, 1});

  ScorerOutput out = scorer.suggestCorrections(req);
  bool foundPrefix = false;
  bool foundPillow = false;
  bool foundParticle = false;
  for (const auto& c : out.corrections) {
    foundPrefix = foundPrefix || c.value == "阿";
    foundPillow = foundPillow || c.value == "枕";
    foundParticle = foundParticle || c.value == "吧";
  }
  EXPECT_TRUE(foundPrefix);
  EXPECT_TRUE(foundPillow);
  EXPECT_TRUE(foundParticle);
}

TEST(DeterministicScorerTest, Phase2GeneralizationHomophoneAndTaiwanRulesFire) {
  DeterministicContextualScorer scorer;

  EXPECT_TRUE(hasCorrectionValue(
      scorer,
      makeRequest({"ㄨㄛˇ", "ㄏㄜˊ", "ㄊㄚ", "ㄕˋ", "ㄆㄥˊ", "ㄧㄡˇ"},
                  {CandidateInput{"ㄨㄛˇ", "我", "", -3.0, 0, 1},
                   CandidateInput{"ㄏㄜˊ", "合", "", -3.0, 1, 1},
                   CandidateInput{"ㄊㄚ", "他", "", -3.0, 2, 1},
                   CandidateInput{"ㄕˋ", "是", "", -3.0, 3, 1},
                   CandidateInput{"ㄆㄥˊ-ㄧㄡˇ", "朋友", "", -3.0, 4, 2}},
                  {CandidateInput{"ㄏㄜˊ", "和", "", -4.0, 1, 1}}),
      "和"));

  EXPECT_TRUE(hasCorrectionValue(
      scorer,
      makeRequest({"ㄒㄧㄤˋ", "ㄋㄧˇ", "ㄓㄜˋ", "ㄧㄤˋ"},
                  {CandidateInput{"ㄒㄧㄤˋ", "相", "", -3.0, 0, 1},
                   CandidateInput{"ㄋㄧˇ", "你", "", -3.0, 1, 1},
                   CandidateInput{"ㄓㄜˋ-ㄧㄤˋ", "這樣", "", -3.0, 2, 2}},
                  {CandidateInput{"ㄒㄧㄤˋ", "像", "", -4.0, 0, 1}}),
      "像"));

  EXPECT_TRUE(hasCorrectionValue(
      scorer,
      makeRequest({"ㄩㄥˋ", "ㄉㄧㄢˋ", "ㄍㄨㄛ", "ㄓㄨˇ"},
                  {CandidateInput{"ㄩㄥˋ-ㄉㄧㄢˋ", "用電", "", -3.0, 0, 2},
                   CandidateInput{"ㄍㄨㄛ", "郭", "", -3.0, 2, 1},
                   CandidateInput{"ㄓㄨˇ", "煮", "", -3.0, 3, 1}},
                  {CandidateInput{"ㄍㄨㄛ", "鍋", "", -4.0, 2, 1}}),
      "鍋"));

  EXPECT_TRUE(hasCorrectionValue(
      scorer,
      makeRequest({"ㄈㄥ", "ㄕㄢˋ", "ㄏㄠˇ", "ㄌㄧㄤˊ"},
                  {CandidateInput{"ㄈㄥ-ㄕㄢˋ", "風扇", "", -3.0, 0, 2},
                   CandidateInput{"ㄏㄠˇ", "好", "", -3.0, 2, 1},
                   CandidateInput{"ㄌㄧㄤˊ", "量", "", -3.0, 3, 1}},
                  {CandidateInput{"ㄌㄧㄤˊ", "涼", "", -4.0, 3, 1}}),
      "涼"));

  EXPECT_TRUE(hasCorrectionValue(
      scorer,
      makeRequest({"ㄅㄠˇ", "ㄒㄧㄢ", "ㄏㄜˊ"},
                  {CandidateInput{"ㄅㄠˇ", "保", "", -3.0, 0, 1},
                   CandidateInput{"ㄒㄧㄢ", "先", "", -3.0, 1, 1},
                   CandidateInput{"ㄏㄜˊ", "盒", "", -3.0, 2, 1}},
                  {CandidateInput{"ㄒㄧㄢ", "鮮", "", -4.0, 1, 1}}),
      "鮮"));
}

TEST(DeterministicScorerTest, Phase2GeneralizationEnglishSlangAndBigramRulesFire) {
  DeterministicContextualScorer scorer;

  EXPECT_TRUE(hasCorrectionValue(
      scorer,
      makeRequest({"ㄆㄠˇ", "ML", "pipeline", "ㄗㄞˋ", "ㄒㄧㄚˋ", "ㄅㄢ"},
                  {CandidateInput{"ㄆㄠˇ", "跑", "", -3.0, 0, 1},
                   CandidateInput{"ML", "ML", "", -3.0, 1, 1},
                   CandidateInput{"pipeline", "pipeline", "", -3.0, 2, 1},
                   CandidateInput{"ㄗㄞˋ", "在", "", -3.0, 3, 1},
                   CandidateInput{"ㄒㄧㄚˋ-ㄅㄢ", "下班", "", -3.0, 4, 2}},
                  {CandidateInput{"ㄗㄞˋ", "再", "", -4.0, 3, 1}},
                  {"ML", "pipeline"}),
      "再"));

  EXPECT_TRUE(hasCorrectionValue(
      scorer,
      makeRequest({"SSL", "ㄆㄧㄥˊ", "ㄓㄥˋ", "ㄎㄨㄞˋ", "ㄉㄠˋ", "ㄑㄧˊ"},
                  {CandidateInput{"SSL", "SSL", "", -3.0, 0, 1},
                   CandidateInput{"ㄆㄧㄥˊ-ㄓㄥˋ", "憑證", "", -3.0, 1, 2},
                   CandidateInput{"ㄎㄨㄞˋ-ㄉㄠˋ", "快到", "", -3.0, 3, 2},
                   CandidateInput{"ㄑㄧˊ", "其", "", -3.0, 5, 1}},
                  {CandidateInput{"ㄑㄧˊ", "期", "", -4.0, 5, 1}},
                  {"SSL"}),
      "期"));

  EXPECT_TRUE(hasCorrectionValue(
      scorer,
      makeRequest({"ㄓㄜˋ", "ㄕㄡˇ", "ㄍㄜ"},
                  {CandidateInput{"ㄓㄜˋ", "這", "", -3.0, 0, 1},
                   CandidateInput{"ㄕㄡˇ", "手", "", -3.0, 1, 1},
                   CandidateInput{"ㄍㄜ", "歌", "", -3.0, 2, 1}},
                  {CandidateInput{"ㄕㄡˇ", "首", "", -4.0, 1, 1}}),
      "首"));

  EXPECT_TRUE(hasCorrectionValue(
      scorer,
      makeRequest({"ㄒㄧㄠˋ", "ㄙˇ"},
                  {CandidateInput{"ㄒㄧㄠˋ", "校", "", -3.0, 0, 1},
                   CandidateInput{"ㄙˇ", "死", "", -3.0, 1, 1}},
                  {CandidateInput{"ㄒㄧㄠˋ", "笑", "", -4.0, 0, 1}}),
      "笑"));

  EXPECT_TRUE(hasCorrectionValue(
      scorer,
      makeRequest({"ㄕㄣˊ", "ㄇㄜ˙", "ㄌㄚ"},
                  {CandidateInput{"ㄕㄣˊ-ㄇㄜ˙", "什麼", "", -3.0, 0, 2},
                   CandidateInput{"ㄌㄚ", "拉", "", -3.0, 2, 1}},
                  {CandidateInput{"ㄌㄚ", "啦", "", -4.0, 2, 1}}),
      "啦"));

  EXPECT_TRUE(hasCorrectionValue(
      scorer,
      makeRequest({"ㄐㄧㄚˇ", "ㄉㄜ˙", "ㄌㄚ"},
                  {CandidateInput{"ㄐㄧㄚˇ-ㄉㄜ˙", "假的", "", -3.0, 0, 2},
                   CandidateInput{"ㄌㄚ", "拉", "", -3.0, 2, 1}},
                  {CandidateInput{"ㄌㄚ", "啦", "", -4.0, 2, 1}}),
      "啦"));

  EXPECT_TRUE(hasCorrectionValue(
      scorer,
      makeRequest({"ㄏㄨㄟˋ", "ㄔㄨ", "CSV"},
                  {CandidateInput{"ㄏㄨㄟˋ-ㄔㄨ", "會出", "", -3.0, 0, 2},
                   CandidateInput{"CSV", "CSV", "", -3.0, 2, 1}},
                  {CandidateInput{"ㄏㄨㄟˋ-ㄔㄨ", "匯出", "", -4.0, 0, 2}},
                  {"CSV"}),
      "匯出"));

  EXPECT_TRUE(hasCorrectionValue(
      scorer,
      makeRequest({"ㄊㄚ", "ㄧㄡˋ", "ㄗㄞˋ", "ㄑㄧㄤˊ", "ㄉㄧㄠˋ"},
                  {CandidateInput{"ㄊㄚ", "他", "", -3.0, 0, 1},
                   CandidateInput{"ㄧㄡˋ-ㄗㄞˋ", "又在", "", -3.0, 1, 2},
                   CandidateInput{"ㄑㄧㄤˊ-ㄉㄧㄠˋ", "強調", "", -3.0, 3, 2}},
                  {CandidateInput{"ㄧㄡˋ-ㄗㄞˋ", "又再", "", -4.0, 1, 2}}),
      "又再"));
}

TEST(DeterministicScorerTest, Phase2GeneralizationRulesCanBeDisabled) {
  DeterministicContextualScorer scorer;
  scorer.setRuleEnabled("phase2-generalization", false);

  ContextualScoreRequest req = makeRequest(
      {"ㄨㄛˇ", "ㄏㄜˊ", "ㄊㄚ"},
      {CandidateInput{"ㄨㄛˇ", "我", "", -3.0, 0, 1},
       CandidateInput{"ㄏㄜˊ", "合", "", -3.0, 1, 1},
       CandidateInput{"ㄊㄚ", "他", "", -3.0, 2, 1}},
      {CandidateInput{"ㄏㄜˊ", "和", "", -4.0, 1, 1}});

  EXPECT_FALSE(hasCorrectionValue(scorer, req, "和"));
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
