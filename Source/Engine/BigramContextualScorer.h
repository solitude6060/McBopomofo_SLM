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

#ifndef SRC_ENGINE_BIGRAMCONTEXTUALSCORER_H_
#define SRC_ENGINE_BIGRAMCONTEXTUALSCORER_H_

#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

#include "Engine/ContextualScorer.h"

namespace McBopomofo {

// Character bigram contextual scorer for Phase 2 experiments.
//
// Loads a BIGR-format binary model (see bigram_trainer.py for format spec)
// and computes score deltas based on bigram language model probabilities.
// The scorer adjusts candidate scores when the bigram context supports the
// candidate over the baseline, using the formula:
//
//   delta(candidate) = sum(log P(c_i|c_{i-1})) for all adjacent char pairs
//                      - sum(log P(b_i|b_{i-1})) for baseline at same position
//
// Missing bigrams contribute 0 to the delta (no opinion).
// If the model fails to load, all deltas are 0.0 (fail-closed).
class BigramContextualScorer : public ContextualScorer {
 public:
  // Loads a BIGR-format model from the given path.
  // Returns true if loading succeeded.
  // After construction, call isModelLoaded() to check validity.
  BigramContextualScorer();
  explicit BigramContextualScorer(const std::string& modelPath);

  std::vector<double> scoreDeltas(
      const ContextualScoreRequest& request) const override;

  bool isModelLoaded() const { return modelLoaded_; }
  const std::string& modelPath() const { return modelPath_; }

  // Exposed for testing: total bigram entries in loaded model.
  size_t bigramCount() const { return bigramCount_; }

  // Exposed for testing: total unigram entries in loaded model.
  size_t unigramCount() const { return unigramCount_; }

 private:
  bool loadModel(const std::string& path);

  // Iterates characters in a UTF-8 string and calls f(cp, i) for each.
  // Returns the number of codepoints iterated.
  template <typename Fn>
  size_t forEachCodepoint(const std::string& s, Fn fn) const;

  // Computes the sum of bigram log-probabilities for all adjacent character
  // pairs in the given UTF-8 string, given the preceding character (0 if none).
  double bigramLogProbSum(const std::string& text,
                          uint32_t prevChar) const;

  // Looks up log P(cp_b | cp_a). Returns 0.0 if the bigram is unknown.
  double lookupBigram(uint32_t cp_a, uint32_t cp_b) const;

  std::string modelPath_;
  bool modelLoaded_ = false;

  // bigram key = (cp_a << 32) | cp_b
  std::unordered_map<uint64_t, float> bigramProbabilities_;

  // unigram codepoint -> count (for metadata/reporting)
  std::unordered_map<uint32_t, uint32_t> unigramCounts_;
  size_t unigramCount_ = 0;
  size_t bigramCount_ = 0;
};

}  // namespace McBopomofo

#endif  // SRC_ENGINE_BIGRAMCONTEXTUALSCORER_H_
