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

#ifndef SRC_ENGINE_CONTEXTUALSCORER_H_
#define SRC_ENGINE_CONTEXTUALSCORER_H_

#include <cstddef>
#include <string>
#include <vector>

namespace McBopomofo {

struct CandidateScoreInput {
  std::string reading;
  std::string value;
  std::string rawValue;
  double baseScore = 0.0;
  size_t start = 0;
  size_t length = 0;
};

struct ContextualScoreRequest {
  std::vector<std::string> readings;
  std::vector<CandidateScoreInput> candidates;
  std::vector<CandidateScoreInput> baselinePath;
  std::string previousCommittedText;
  std::vector<std::string> protectedEnglishSpans;
  size_t cursor = 0;
};

class ContextualScorer {
 public:
  virtual ~ContextualScorer() = default;

  // Returns one score delta per request.candidates entry. Implementations must
  // not create candidate text that is absent from the request.
  virtual std::vector<double> scoreDeltas(
      const ContextualScoreRequest& request) const = 0;
};

}  // namespace McBopomofo

#endif  // SRC_ENGINE_CONTEXTUALSCORER_H_
