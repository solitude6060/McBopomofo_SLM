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

#ifndef SRC_ENGINE_DETERMINISTICCONTEXTUALSCORER_H_
#define SRC_ENGINE_DETERMINISTICCONTEXTUALSCORER_H_

#include <cstddef>
#include <string>
#include <unordered_map>
#include <vector>

#include "Engine/ContextualScorer.h"

namespace McBopomofo {

struct ScorerCorrection {
  size_t candidateIndex = 0;
  size_t start = 0;
  size_t length = 0;
  std::string reading;
  std::string value;
  double scoreDelta = 0.0;
  std::string ruleName;
};

struct ScorerOutput {
  std::vector<ScorerCorrection> corrections;
};

// Deterministic contextual reranker for Phase 1.
//
// Applies pattern-matching rules to adjust existing candidates. It does not
// create text, read files, call a model, or decide English passthrough.
class DeterministicContextualScorer : public ContextualScorer {
 public:
  DeterministicContextualScorer();

  std::vector<double> scoreDeltas(
      const ContextualScoreRequest& request) const override;

  ScorerOutput suggestCorrections(
      const ContextualScoreRequest& request) const;

  void setRuleEnabled(const std::string& ruleName, bool enabled);

 private:
  std::string baselineValueAt(const ContextualScoreRequest& request,
                              size_t readingIndex) const;
  std::string baselineValueBefore(const ContextualScoreRequest& request,
                                  size_t readingIndex) const;
  std::string baselineValueAfter(const ContextualScoreRequest& request,
                                 size_t readingIndex) const;
  std::string baselineValueAfterSpan(const ContextualScoreRequest& request,
                                     size_t readingIndex,
                                     size_t length) const;
  bool ruleEnabled(const std::string& ruleName) const;
  double ruleDelta(const ContextualScoreRequest& request,
                   const CandidateScoreInput& candidate,
                   std::string* ruleName) const;

  bool enabled_ = true;
  std::unordered_map<std::string, bool> ruleEnabled_;
};

}  // namespace McBopomofo

#endif  // SRC_ENGINE_DETERMINISTICCONTEXTUALSCORER_H_
