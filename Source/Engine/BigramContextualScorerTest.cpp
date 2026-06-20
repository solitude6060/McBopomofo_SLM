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

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

#include "Engine/BigramContextualScorer.h"
#include "gtest/gtest.h"

namespace McBopomofo {
namespace {

// Writes a minimal valid BIGR model with 2 unigrams and 1 bigram.
// The model encodes: P(好|很) = log(0.8)
// Unigrams: 很 (count=100), 好 (count=80)
static void writeMinimalModel(const std::string& path) {
  FILE* f = fopen(path.c_str(), "wb");
  ASSERT_NE(f, nullptr);

  // magic "BIGR"
  uint32_t magic = 0x42494752;
  fwrite(&magic, 4, 1, f);

  // version
  uint32_t version = 1;
  fwrite(&version, 4, 1, f);

  // num_unigrams, num_bigrams
  uint32_t numUnigrams = 2;
  uint32_t numBigrams = 1;
  fwrite(&numUnigrams, 4, 1, f);
  fwrite(&numBigrams, 4, 1, f);

  // unigrams: 很 (U+5F88), 好 (U+597D)
  uint32_t cp = 0x5F88;
  uint32_t count = 100;
  fwrite(&cp, 4, 1, f);
  fwrite(&count, 4, 1, f);
  cp = 0x597D;
  count = 80;
  fwrite(&cp, 4, 1, f);
  fwrite(&count, 4, 1, f);

  // bigrams: 很→好 (count=64, log_prob=log(0.8)≈-0.2231)
  float logProb = -0.22314355f;  // logf(0.8f)
  cp = 0x5F88;  // cp_a = 很
  fwrite(&cp, 4, 1, f);
  cp = 0x597D;  // cp_b = 好
  fwrite(&cp, 4, 1, f);
  count = 64;
  fwrite(&count, 4, 1, f);
  fwrite(&logProb, 4, 1, f);

  fclose(f);
}

// Writes a model with invalid magic bytes.
static void writeInvalidMagicModel(const std::string& path) {
  FILE* f = fopen(path.c_str(), "wb");
  ASSERT_NE(f, nullptr);
  uint32_t badMagic = 0xDEADBEEF;
  fwrite(&badMagic, 4, 1, f);
  fclose(f);
}

// Writes a model with unsupported version.
static void writeBadVersionModel(const std::string& path) {
  FILE* f = fopen(path.c_str(), "wb");
  ASSERT_NE(f, nullptr);
  uint32_t magic = 0x42494752;
  uint32_t version = 999;
  fwrite(&magic, 4, 1, f);
  fwrite(&version, 4, 1, f);
  fclose(f);
}

// Writes a model truncated in the middle of header.
static void writeTruncatedModel(const std::string& path) {
  FILE* f = fopen(path.c_str(), "wb");
  ASSERT_NE(f, nullptr);
  uint32_t magic = 0x42494752;
  fwrite(&magic, 4, 1, f);
  // File ends here — no version field
  fclose(f);
}

TEST(BigramContextualScorerTest, ModelNotLoaded_ReturnsAllZeros) {
  BigramContextualScorer scorer("/nonexistent/path.model");
  EXPECT_FALSE(scorer.isModelLoaded());

  ContextualScoreRequest req;
  req.readings = {"ㄗㄞˋ"};
  req.candidates.push_back(
      CandidateScoreInput{"ㄗㄞˋ", "在", "在", 1.0, 0, 1});
  std::vector<double> deltas = scorer.scoreDeltas(req);
  ASSERT_EQ(deltas.size(), 1);
  EXPECT_DOUBLE_EQ(deltas[0], 0.0);
}

TEST(BigramContextualScorerTest, InvalidMagic_FailsClosed) {
  std::string tmpPath = "/tmp/test_bigram_invalid_magic.bin";
  writeInvalidMagicModel(tmpPath);
  BigramContextualScorer scorer(tmpPath);
  EXPECT_FALSE(scorer.isModelLoaded());
  std::remove(tmpPath.c_str());
}

TEST(BigramContextualScorerTest, BadVersion_FailsClosed) {
  std::string tmpPath = "/tmp/test_bigram_bad_version.bin";
  writeBadVersionModel(tmpPath);
  BigramContextualScorer scorer(tmpPath);
  EXPECT_FALSE(scorer.isModelLoaded());
  std::remove(tmpPath.c_str());
}

TEST(BigramContextualScorerTest, TruncatedModel_FailsClosed) {
  std::string tmpPath = "/tmp/test_bigram_truncated.bin";
  writeTruncatedModel(tmpPath);
  BigramContextualScorer scorer(tmpPath);
  EXPECT_FALSE(scorer.isModelLoaded());
  std::remove(tmpPath.c_str());
}

TEST(BigramContextualScorerTest, ScoreDeltas_SizeMatchesCandidates) {
  std::string tmpPath = "/tmp/test_bigram_size_check.bin";
  writeMinimalModel(tmpPath);
  BigramContextualScorer scorer(tmpPath);
  EXPECT_TRUE(scorer.isModelLoaded());

  ContextualScoreRequest req;
  req.readings = {"ㄏㄣˇ", "ㄏㄠˇ"};
  // Two candidates at position 1
  req.candidates.push_back(
      CandidateScoreInput{"ㄏㄠˇ", "好", "好", 2.0, 1, 1});
  req.candidates.push_back(
      CandidateScoreInput{"ㄏㄠˇ", "號", "號", 1.5, 1, 1});
  // Baseline path has "很" at position 0
  req.baselinePath.push_back(
      CandidateScoreInput{"ㄏㄣˇ", "很", "很", 3.0, 0, 1});

  std::vector<double> deltas = scorer.scoreDeltas(req);
  ASSERT_EQ(deltas.size(), 2);
  // Both deltas should be set (not NaN, not inf)
  for (size_t i = 0; i < deltas.size(); ++i) {
    EXPECT_TRUE(std::isfinite(deltas[i]));
  }
  std::remove(tmpPath.c_str());
}

TEST(BigramContextualScorerTest, KnownBigram_BoostsCandidate) {
  std::string tmpPath = "/tmp/test_bigram_known_boost.bin";
  writeMinimalModel(tmpPath);
  BigramContextualScorer scorer(tmpPath);
  EXPECT_TRUE(scorer.isModelLoaded());

  // Build a request where:
  // - The previous committed text is "很" (U+5F88)
  // - Position 1 has candidates "好" and "號"
  // - "很→好" is a known bigram with positive score
  ContextualScoreRequest req;
  req.readings = {"ㄏㄣˇ", "ㄏㄠˇ"};
  req.previousCommittedText = "很";
  req.candidates.push_back(
      CandidateScoreInput{"ㄏㄠˇ", "好", "好", 2.0, 1, 1});
  req.candidates.push_back(
      CandidateScoreInput{"ㄏㄠˇ", "號", "號", 1.5, 1, 1});
  // Baseline at position 1 is "號" (wrong choice)
  req.baselinePath.push_back(
      CandidateScoreInput{"ㄏㄣˇ", "很", "很", 3.0, 0, 1});
  req.baselinePath.push_back(
      CandidateScoreInput{"ㄏㄠˇ", "號", "號", 1.5, 1, 1});

  std::vector<double> deltas = scorer.scoreDeltas(req);
  ASSERT_EQ(deltas.size(), 2);

  // The first candidate "好" should have a positive delta
  // (known bigram "很→好" supports it)
  EXPECT_GT(deltas[0], 0.0);

  // The second candidate "號" should have a lower or zero delta
  // (unknown bigram "很→號" → 0 contribution)
  EXPECT_GE(deltas[1], 0.0);

  // The "好" delta should be higher than "號" delta
  EXPECT_GT(deltas[0], deltas[1]);

  std::remove(tmpPath.c_str());
}

TEST(BigramContextualScorerTest, UnknownBigram_ContributesZero) {
  std::string tmpPath = "/tmp/test_bigram_unknown.bin";
  writeMinimalModel(tmpPath);
  BigramContextualScorer scorer(tmpPath);
  EXPECT_TRUE(scorer.isModelLoaded());

  ContextualScoreRequest req;
  // No context, unknown pair
  req.readings = {"ㄑㄧㄥˊ"};
  req.candidates.push_back(
      CandidateScoreInput{"ㄑㄧㄥˊ", "情", "情", 1.0, 0, 1});
  req.candidates.push_back(
      CandidateScoreInput{"ㄑㄧㄥˊ", "晴", "晴", 0.5, 0, 1});

  std::vector<double> deltas = scorer.scoreDeltas(req);
  ASSERT_EQ(deltas.size(), 2);
  // Both should be 0 since there's no preceding context
  EXPECT_DOUBLE_EQ(deltas[0], 0.0);
  EXPECT_DOUBLE_EQ(deltas[1], 0.0);

  std::remove(tmpPath.c_str());
}

TEST(BigramContextualScorerTest, LoadedModel_MetadataCorrect) {
  std::string tmpPath = "/tmp/test_bigram_metadata.bin";
  writeMinimalModel(tmpPath);
  BigramContextualScorer scorer(tmpPath);
  EXPECT_TRUE(scorer.isModelLoaded());
  EXPECT_EQ(scorer.unigramCount(), 2);
  EXPECT_EQ(scorer.bigramCount(), 1);
  EXPECT_EQ(scorer.modelPath(), tmpPath);
  std::remove(tmpPath.c_str());
}

TEST(BigramContextualScorerTest, EmptyRequest_ReturnsEmpty) {
  BigramContextualScorer scorer;
  ContextualScoreRequest req;
  std::vector<double> deltas = scorer.scoreDeltas(req);
  EXPECT_TRUE(deltas.empty());
}

}  // namespace
}  // namespace McBopomofo
