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

#include "OneShotOverride.h"

#include <string>
#include <vector>

#include "UTF8Helper.h"

namespace McBopomofo {

namespace {

constexpr char kEmptyNodeString[] = "()";

size_t readingSpan(const std::string& reading) {
  if (reading.empty()) {
    return 1;
  }
  size_t span = 1;
  for (char c : reading) {
    if (c == '-') {
      ++span;
    }
  }
  return span;
}

std::string combineReadingValue(const std::string& reading,
                                const std::string& value) {
  return std::string("(") + reading + "," + value + ")";
}

std::string topOneReadingValue(Formosa::Gramambular2::ReadingGrid& grid,
                               size_t loc) {
  auto candidates = grid.candidatesAt(loc);
  for (const auto& candidate : candidates) {
    if (readingSpan(candidate.reading) == 1 && !candidate.value.empty()) {
      return candidate.value;
    }
  }
  return "";
}

std::string headNextKey(Formosa::Gramambular2::ReadingGrid& grid, size_t loc) {
  const auto& readings = grid.readings();
  if (loc >= readings.size()) {
    return "";
  }
  const std::string top = topOneReadingValue(grid, loc);
  if (top.empty()) {
    return "";
  }
  const std::string head = combineReadingValue(readings[loc], top);
  const std::string next = loc + 1 < readings.size()
                               ? readings[loc + 1]
                               : std::string(kEmptyNodeString);
  return next + "-" + head;
}

std::string walkValueCovering(
    const Formosa::Gramambular2::ReadingGrid::WalkResult& walk, size_t loc) {
  size_t covered = 0;
  for (const auto& node : walk.nodes) {
    const size_t start = covered;
    covered += node->spanningLength();
    if (loc >= start && loc < covered) {
      return node->value();
    }
  }
  return "";
}

std::string joinWalk(
    const Formosa::Gramambular2::ReadingGrid::WalkResult& walk) {
  std::string out;
  for (const auto& value : walk.valuesAsStrings()) {
    out += value;
  }
  return out;
}

std::vector<std::string> charsByReading(
    const Formosa::Gramambular2::ReadingGrid::WalkResult& walk) {
  std::vector<std::string> out;
  for (const auto& node : walk.nodes) {
    const auto chars = Split(node->value());
    if (chars.size() == node->spanningLength()) {
      out.insert(out.end(), chars.begin(), chars.end());
      continue;
    }
    for (size_t i = 0; i < node->spanningLength(); ++i) {
      out.push_back(i == 0 ? node->value() : "");
    }
  }
  return out;
}

}  // namespace

OneShotOverride PickOneShotOverride(
    Formosa::Gramambular2::ReadingGrid& grid, UserOverrideModel* uom,
    double timestamp) {
  OneShotOverride best;
  if (uom == nullptr || grid.length() == 0) {
    return best;
  }
  const auto walk = grid.walk();
  size_t bestSize = 0;
  for (size_t loc = 0; loc < grid.length(); ++loc) {
    const std::string key = headNextKey(grid, loc);
    if (key.empty()) {
      continue;
    }
    const auto suggestion = uom->suggest(key, timestamp);
    if (suggestion.empty()) {
      continue;
    }
    const std::string current = walkValueCovering(walk, loc);
    if (current.find(suggestion.candidate) != std::string::npos) {
      continue;
    }
    std::vector<size_t> locs = {loc};
    if (loc > 0) {
      locs.push_back(loc - 1);
    }
    for (size_t candLoc : locs) {
      for (const auto& candidate : grid.candidatesAt(candLoc)) {
        if (readingSpan(candidate.reading) < 2 || candidate.value.empty()) {
          continue;
        }
        if (candidate.value.find(suggestion.candidate) == std::string::npos) {
          continue;
        }
        if (walkValueCovering(walk, candLoc) == candidate.value) {
          continue;
        }
        if (candidate.value.size() > bestSize) {
          bestSize = candidate.value.size();
          best.loc = candLoc;
          best.value = candidate.value;
          best.reading = candidate.reading;
        }
      }
    }
  }
  return best;
}

HeadNextObservation FormHeadNextObservation(
    Formosa::Gramambular2::ReadingGrid& grid,
    const Formosa::Gramambular2::ReadingGrid::WalkResult& walkBefore,
    const Formosa::Gramambular2::ReadingGrid::WalkResult& walkAfter) {
  HeadNextObservation observed;
  const auto& readings = grid.readings();
  if (readings.empty()) {
    return observed;
  }
  const auto beforeChars = charsByReading(walkBefore);
  const auto afterChars = Split(joinWalk(walkAfter));
  size_t diff = static_cast<size_t>(-1);
  const size_t n = beforeChars.size() < afterChars.size() ? beforeChars.size()
                                                          : afterChars.size();
  for (size_t i = 0; i < n; ++i) {
    if (beforeChars[i] != afterChars[i]) {
      diff = i;
      break;
    }
  }
  if (diff == static_cast<size_t>(-1) || diff >= readings.size()) {
    return observed;
  }
  const std::string top = topOneReadingValue(grid, diff);
  if (top.empty()) {
    return observed;
  }
  const std::string head = combineReadingValue(readings[diff], top);
  const std::string next = diff + 1 < readings.size()
                               ? readings[diff + 1]
                               : std::string(kEmptyNodeString);
  observed.key = next + "-" + head;

  size_t past = 0;
  auto afterNode = walkAfter.findNodeAt(diff, &past);
  if (afterNode == walkAfter.nodes.cend()) {
    return HeadNextObservation{};
  }
  const size_t nodeStart = past - (*afterNode)->spanningLength();
  const bool phraseAtDiff =
      nodeStart == diff && (*afterNode)->spanningLength() > 1;
  observed.forceHighScoreOverride = phraseAtDiff;
  if (phraseAtDiff) {
    observed.candidate = (*afterNode)->currentUnigram().value();
  } else if (diff < afterChars.size()) {
    observed.candidate = afterChars[diff];
  }
  return observed;
}

}  // namespace McBopomofo
