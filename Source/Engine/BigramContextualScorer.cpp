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

#include "Engine/BigramContextualScorer.h"

#include <cmath>
#include <functional>

namespace McBopomofo {

// RED phase stub: compiles but scoreDeltas returns all zeros
// and model loading always fails.

BigramContextualScorer::BigramContextualScorer() = default;

BigramContextualScorer::BigramContextualScorer(const std::string& modelPath)
    : modelPath_(modelPath) {
  loadModel(modelPath);
}

std::vector<double> BigramContextualScorer::scoreDeltas(
    const ContextualScoreRequest& request) const {
  // RED stub: return all zeros
  return std::vector<double>(request.candidates.size(), 0.0);
}

bool BigramContextualScorer::loadModel(const std::string& path) {
  // RED stub: always fail to load
  (void)path;
  modelLoaded_ = false;
  return false;
}

template <typename Fn>
size_t BigramContextualScorer::forEachCodepoint(const std::string& s,
                                                 Fn fn) const {
  size_t count = 0;
  size_t offset = 0;
  while (offset < s.size()) {
    unsigned char c = static_cast<unsigned char>(s[offset]);
    uint32_t cp;
    size_t advance;
    if (c < 0x80) {
      cp = c;
      advance = 1;
    } else if ((c & 0xE0) == 0xC0 && offset + 1 < s.size()) {
      cp = ((c & 0x1F) << 6) |
           (static_cast<unsigned char>(s[offset + 1]) & 0x3F);
      advance = 2;
    } else if ((c & 0xF0) == 0xE0 && offset + 2 < s.size()) {
      cp = ((c & 0x0F) << 12) |
           ((static_cast<unsigned char>(s[offset + 1]) & 0x3F) << 6) |
           (static_cast<unsigned char>(s[offset + 2]) & 0x3F);
      advance = 3;
    } else if ((c & 0xF8) == 0xF0 && offset + 3 < s.size()) {
      cp = ((c & 0x07) << 18) |
           ((static_cast<unsigned char>(s[offset + 1]) & 0x3F) << 12) |
           ((static_cast<unsigned char>(s[offset + 2]) & 0x3F) << 6) |
           (static_cast<unsigned char>(s[offset + 3]) & 0x3F);
      advance = 4;
    } else {
      ++offset;
      continue;
    }
    fn(cp, count);
    offset += advance;
    ++count;
  }
  return count;
}

double BigramContextualScorer::bigramLogProbSum(
    const std::string& text, uint32_t prevChar) const {
  // RED stub
  (void)text;
  (void)prevChar;
  return 0.0;
}

double BigramContextualScorer::lookupBigram(uint32_t cp_a,
                                             uint32_t cp_b) const {
  // RED stub
  (void)cp_a;
  (void)cp_b;
  return 0.0;
}

}  // namespace McBopomofo
