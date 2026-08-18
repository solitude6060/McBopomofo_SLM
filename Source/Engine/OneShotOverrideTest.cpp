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

#include <map>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

#include "OneShotOverride.h"
#include "UserOverrideModel.h"
#include "gramambular2/language_model.h"
#include "gramambular2/reading_grid.h"
#include "gtest/gtest.h"

namespace McBopomofo {

namespace {

constexpr double kFakeNow = 1657772432;
constexpr int kCapacity = 8;
constexpr double kHalflife = 5400.0;

// Tiny Traditional Chinese fixture: walk prefers 別在說; engine has 再說.
constexpr char kOneshotLm[] = R"(
ㄅㄧㄝˊ 別 -2.0
ㄗㄞˋ 在 -2.0
ㄗㄞˋ 再 -4.0
ㄕㄨㄛ 說 -2.0
ㄗㄞˋ-ㄕㄨㄛ 再說 -3.0
ㄅㄧㄝˊ-ㄗㄞˋ 別在 -1.2
)";

class SimpleLM : public Formosa::Gramambular2::LanguageModel {
 public:
  explicit SimpleLM(const char* input) {
    std::stringstream stream(input);
    while (stream.good()) {
      std::string line;
      std::getline(stream, line);
      if (line.empty() || line[0] == '#') {
        continue;
      }
      std::stringstream lineStream(line);
      std::string reading;
      std::string value;
      std::string scoreText;
      lineStream >> reading >> value >> scoreText;
      db_[reading].emplace_back(value, std::stod(scoreText));
    }
  }

  std::vector<Unigram> getUnigrams(const std::string& reading) override {
    const auto found = db_.find(reading);
    return found == db_.end() ? std::vector<Unigram>() : found->second;
  }

  bool hasUnigrams(const std::string& reading) override {
    return db_.find(reading) != db_.end();
  }

 private:
  std::map<std::string, std::vector<Unigram>> db_;
};

std::string JoinWalk(
    const Formosa::Gramambular2::ReadingGrid::WalkResult& walk) {
  std::string out;
  for (const auto& value : walk.valuesAsStrings()) {
    out += value;
  }
  return out;
}

Formosa::Gramambular2::ReadingGrid MakeGrid() {
  Formosa::Gramambular2::ReadingGrid grid(std::make_shared<SimpleLM>(kOneshotLm));
  grid.setReadingSeparator("-");
  EXPECT_TRUE(grid.insertReading("ㄅㄧㄝˊ"));
  EXPECT_TRUE(grid.insertReading("ㄗㄞˋ"));
  EXPECT_TRUE(grid.insertReading("ㄕㄨㄛ"));
  return grid;
}

}  // namespace

TEST(OneShotOverrideTest, ReturnsEmptyWhenUomMissing) {
  auto grid = MakeGrid();
  const OneShotOverride pick = PickOneShotOverride(grid, nullptr, kFakeNow);
  EXPECT_TRUE(pick.empty());
}

TEST(OneShotOverrideTest, ReturnsEmptyOnEmptyGrid) {
  UserOverrideModel uom(kCapacity, kHalflife);
  uom.observe("ㄕㄨㄛ-(ㄗㄞˋ,在)", "再", kFakeNow);
  Formosa::Gramambular2::ReadingGrid grid(std::make_shared<SimpleLM>(kOneshotLm));
  const OneShotOverride pick = PickOneShotOverride(grid, &uom, kFakeNow);
  EXPECT_TRUE(pick.empty());
}

TEST(OneShotOverrideTest, PicksLongestEngineCandidateContainingSuggestion) {
  auto grid = MakeGrid();
  ASSERT_EQ(JoinWalk(grid.walk()), "別在說");

  UserOverrideModel uom(kCapacity, kHalflife);
  uom.observe("ㄕㄨㄛ-(ㄗㄞˋ,在)", "再", kFakeNow);

  const OneShotOverride pick = PickOneShotOverride(grid, &uom, kFakeNow);
  ASSERT_FALSE(pick.empty());
  EXPECT_EQ(pick.value, "再說");
  EXPECT_EQ(JoinWalk(grid.walk()), "別在說");

  bool sawOffered = false;
  bool sawInvented = false;
  for (size_t loc = 0; loc < grid.length(); ++loc) {
    for (const auto& candidate : grid.candidatesAt(loc)) {
      if (candidate.value == pick.value) {
        sawOffered = true;
      }
      if (candidate.value == "別再說") {
        sawInvented = true;
      }
    }
  }
  EXPECT_TRUE(sawOffered);
  EXPECT_FALSE(sawInvented);
}

TEST(OneShotOverrideTest, DualObserveStoresHeadNextKey) {
  auto grid = MakeGrid();
  const auto before = grid.walk();
  ASSERT_EQ(JoinWalk(before), "別在說");
  ASSERT_TRUE(grid.overrideCandidate(1, "再"));
  const auto after = grid.walk();

  const HeadNextObservation observed =
      FormHeadNextObservation(grid, before, after);
  ASSERT_FALSE(observed.empty());
  EXPECT_EQ(observed.key, "ㄕㄨㄛ-(ㄗㄞˋ,在)");
  EXPECT_FALSE(observed.candidate.empty());

  UserOverrideModel uom(kCapacity, kHalflife);
  uom.observe(before, after, 1, kFakeNow);
  uom.observe(observed.key, observed.candidate, kFakeNow,
              observed.forceHighScoreOverride);

  auto probe = MakeGrid();
  ASSERT_EQ(JoinWalk(probe.walk()), "別在說");
  const OneShotOverride pick = PickOneShotOverride(probe, &uom, kFakeNow);
  ASSERT_FALSE(pick.empty());
  EXPECT_EQ(pick.value, "再說");
}

}  // namespace McBopomofo
