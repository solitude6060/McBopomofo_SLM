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
#include <cstdio>
#include <functional>

namespace McBopomofo {

BigramContextualScorer::BigramContextualScorer() = default;

BigramContextualScorer::BigramContextualScorer(const std::string& modelPath)
    : modelPath_(modelPath) {
  loadModel(modelPath);
}

std::vector<double> BigramContextualScorer::scoreDeltas(
    const ContextualScoreRequest& request) const {
  if (request.candidates.empty()) {
    return {};
  }
  if (!modelLoaded_) {
    return std::vector<double>(request.candidates.size(), 0.0);
  }

  std::vector<double> deltas;
  deltas.reserve(request.candidates.size());

  for (const auto& candidate : request.candidates) {
    uint32_t contextChar = 0;
    bool hasContext = false;

    if (candidate.start > 0) {
      for (const auto& entry : request.baselinePath) {
        size_t entryEnd = entry.start + entry.length;
        if (entryEnd == candidate.start ||
            (entry.start < candidate.start && entryEnd > candidate.start)) {
          forEachCodepoint(entry.value, [&](uint32_t cp, size_t) {
            contextChar = cp;
          });
          hasContext = true;
          break;
        }
      }
    } else if (candidate.start == 0 &&
               !request.previousCommittedText.empty()) {
      forEachCodepoint(request.previousCommittedText, [&](uint32_t cp, size_t) {
        contextChar = cp;
      });
      hasContext = true;
    }

    if (!hasContext) {
      deltas.push_back(0.0);
      continue;
    }

    double candidateSum = bigramScoreSum(candidate.value, contextChar);

    double baselineSum = 0.0;
    for (const auto& entry : request.baselinePath) {
      if (entry.start == candidate.start) {
        baselineSum = bigramScoreSum(entry.value, contextChar);
        break;
      }
    }

    double delta = candidateSum - baselineSum;
    deltas.push_back(delta);
  }

  return deltas;
}

bool BigramContextualScorer::loadModel(const std::string& path) {
  FILE* f = fopen(path.c_str(), "rb");
  if (!f) {
    modelLoaded_ = false;
    return false;
  }

  uint32_t magic;
  if (fread(&magic, 4, 1, f) != 1 || magic != 0x42494752) {
    fclose(f);
    modelLoaded_ = false;
    return false;
  }

  uint32_t version;
  if (fread(&version, 4, 1, f) != 1 || version != 1) {
    fclose(f);
    modelLoaded_ = false;
    return false;
  }

  uint32_t numUnigrams;
  uint32_t numBigrams;
  if (fread(&numUnigrams, 4, 1, f) != 1 ||
      fread(&numBigrams, 4, 1, f) != 1) {
    fclose(f);
    modelLoaded_ = false;
    return false;
  }

  unigramCounts_.clear();
  bigramProbabilities_.clear();

  for (uint32_t i = 0; i < numUnigrams; ++i) {
    uint32_t cp;
    uint32_t count;
    if (fread(&cp, 4, 1, f) != 1 || fread(&count, 4, 1, f) != 1) {
      fclose(f);
      modelLoaded_ = false;
      return false;
    }
    unigramCounts_[cp] = count;
  }

  for (uint32_t i = 0; i < numBigrams; ++i) {
    uint32_t cp_a;
    uint32_t cp_b;
    uint32_t count;
    float logProb;
    if (fread(&cp_a, 4, 1, f) != 1 || fread(&cp_b, 4, 1, f) != 1 ||
        fread(&count, 4, 1, f) != 1 || fread(&logProb, 4, 1, f) != 1) {
      fclose(f);
      modelLoaded_ = false;
      return false;
    }
    uint64_t key = ((uint64_t)cp_a << 32) | cp_b;
    bigramProbabilities_[key] = logProb;
  }

  fclose(f);

  unigramCount_ = static_cast<size_t>(numUnigrams);
  bigramCount_ = static_cast<size_t>(numBigrams);
  modelPath_ = path;
  modelLoaded_ = true;
  return true;
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

double BigramContextualScorer::bigramScoreSum(
    const std::string& text, uint32_t prevChar) const {
  double sum = 0.0;
  uint32_t prev = prevChar;
  forEachCodepoint(text, [&](uint32_t cp, size_t) {
    sum += lookupBigramScore(prev, cp);
    prev = cp;
  });
  return sum;
}

double BigramContextualScorer::lookupBigramScore(uint32_t cp_a,
                                                 uint32_t cp_b) const {
  uint64_t key = ((uint64_t)cp_a << 32) | cp_b;
  auto it = bigramProbabilities_.find(key);
  if (it != bigramProbabilities_.end()) {
    return std::exp(static_cast<double>(it->second));
  }
  return 0.0;
}

}  // namespace McBopomofo
