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

#ifndef SRC_ENGINE_ONESHOTOVERRIDE_H_
#define SRC_ENGINE_ONESHOTOVERRIDE_H_

#include <string>

#include "UserOverrideModel.h"
#include "gramambular2/reading_grid.h"

namespace McBopomofo {

// Longest engine multi-character candidate that contains a head_next
// suggestion. Empty if none. Does not mutate the grid.
struct OneShotOverride {
  size_t loc = 0;
  std::string value;
  std::string reading;

  [[nodiscard]] bool empty() const { return value.empty(); }
};

OneShotOverride PickOneShotOverride(
    Formosa::Gramambular2::ReadingGrid& grid, UserOverrideModel* uom,
    double timestamp);

// KeyHandler-shaped second observe: first differing reading, next syllable,
// top unigram before override. Candidate is the after-walk phrase if it
// starts at that reading, otherwise the differing character.
struct HeadNextObservation {
  std::string key;
  std::string candidate;
  bool forceHighScoreOverride = false;

  [[nodiscard]] bool empty() const {
    return key.empty() || candidate.empty();
  }
};

HeadNextObservation FormHeadNextObservation(
    Formosa::Gramambular2::ReadingGrid& grid,
    const Formosa::Gramambular2::ReadingGrid::WalkResult& walkBefore,
    const Formosa::Gramambular2::ReadingGrid::WalkResult& walkAfter);

}  // namespace McBopomofo

#endif  // SRC_ENGINE_ONESHOTOVERRIDE_H_
