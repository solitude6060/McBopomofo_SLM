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

// ScorerDemo — interactive CLI demo for the McBopomofo engine + reranker.
//
// Build:
//   cd Tools/ScorerDemo && mkdir build && cd build && cmake .. && make
//
// Usage:
//   ./scorer_demo <data.txt>                  # interactive mode
//   ./scorer_demo <data.txt> <reading_seq>    # single-shot mode
//
// The reading sequence is dash-separated Bopomofo syllables, e.g.:
//   ./scorer_demo ../../Source/Data/data.txt ㄨㄛˇ-ㄕˋ-ㄒㄩㄝˊ-ㄕㄥ

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

#include "Engine/DeterministicContextualScorer.h"
#include "Engine/McBopomofoLM.h"
#include "Engine/gramambular2/reading_grid.h"

namespace fs = std::filesystem;

// Mirrors applyReranker in evaluator.cpp.
static void applyReranker(
    const std::vector<std::string>& readings,
    Formosa::Gramambular2::ReadingGrid& grid,
    Formosa::Gramambular2::ReadingGrid::WalkResult* walkResult,
    McBopomofo::DeterministicContextualScorer& scorer,
    std::vector<McBopomofo::ScorerCorrection>* outCorrections) {

  McBopomofo::ContextualScoreRequest request;
  request.readings = readings;
  request.cursor = readings.size();

  size_t start = 0;
  for (const auto& node : walkResult->nodes) {
    request.baselinePath.push_back(McBopomofo::CandidateScoreInput{
        node->reading(), node->value(), node->currentUnigram().rawValue(),
        node->score(), start, node->spanningLength()});
    start += node->spanningLength();
  }

  const auto& spans = grid.spans();
  for (size_t loc = 0; loc < spans.size(); ++loc) {
    for (size_t len = 1;
         len <= Formosa::Gramambular2::ReadingGrid::kMaximumSpanLength &&
         loc + len <= readings.size();
         ++len) {
      const auto& node = spans[loc].nodeOf(len);
      if (node == nullptr) {
        continue;
      }
      for (const auto& unigram : node->unigrams()) {
        request.candidates.push_back(McBopomofo::CandidateScoreInput{
            node->reading(), unigram.value(), unigram.rawValue(),
            unigram.score(), loc, node->spanningLength()});
      }
    }
  }

  McBopomofo::ScorerOutput scorerOutput = scorer.suggestCorrections(request);

  std::vector<McBopomofo::ScorerCorrection> selected;
  std::vector<bool> occupied(grid.length(), false);
  for (const auto& correction : scorerOutput.corrections) {
    if (correction.length == 0 ||
        correction.start + correction.length > occupied.size()) {
      continue;
    }
    bool overlaps = false;
    for (size_t i = correction.start; i < correction.start + correction.length;
         ++i) {
      overlaps = overlaps || occupied[i];
    }
    if (overlaps) {
      continue;
    }
    selected.push_back(correction);
    for (size_t i = correction.start; i < correction.start + correction.length;
         ++i) {
      occupied[i] = true;
    }
  }

  std::stable_sort(
      selected.begin(), selected.end(),
      [](const McBopomofo::ScorerCorrection& a,
         const McBopomofo::ScorerCorrection& b) {
        if (a.start != b.start) {
          return a.start < b.start;
        }
        return a.length > b.length;
      });

  bool overridden = false;
  for (const auto& correction : selected) {
    overridden = grid.overrideCandidate(
                     correction.start,
                     Formosa::Gramambular2::ReadingGrid::Candidate(
                         correction.reading, correction.value),
                     Formosa::Gramambular2::ReadingGrid::Node::
                         OverrideType::kOverrideValueWithHighScore) ||
                 overridden;
  }
  if (overridden) {
    *walkResult = grid.walk();
  }

  if (outCorrections) {
    *outCorrections = std::move(selected);
  }
}

// -----------------------------------------------------------------------
// Evaluation
// -----------------------------------------------------------------------
struct Result {
  std::string baselineText;
  std::string rerankedText;
  std::vector<McBopomofo::ScorerCorrection> corrections;
};

static Result evaluate(const std::vector<std::string>& readings,
                       std::shared_ptr<McBopomofo::McBopomofoLM> lm) {
  Result result;

  Formosa::Gramambular2::ReadingGrid grid(
      std::make_shared<Formosa::Gramambular2::ReadingGrid::ScoreRankedLanguageModel>(lm));

  for (const auto& r : readings) {
    grid.insertReading(r);
  }

  auto walkResult = grid.walk();
  {
    auto parts = walkResult.valuesAsStrings();
    for (const auto& p : parts) result.baselineText += p;
  }

  {
    McBopomofo::DeterministicContextualScorer scorer;
    applyReranker(readings, grid, &walkResult, scorer, &result.corrections);
  }
  {
    auto parts = walkResult.valuesAsStrings();
    for (const auto& p : parts) result.rerankedText += p;
  }

  return result;
}

// -----------------------------------------------------------------------
// String splitting
// -----------------------------------------------------------------------
static std::vector<std::string> split(const std::string& s, char delim) {
  std::vector<std::string> parts;
  size_t start = 0, end;
  while ((end = s.find(delim, start)) != std::string::npos) {
    parts.push_back(s.substr(start, end - start));
    start = end + 1;
  }
  parts.push_back(s.substr(start));
  return parts;
}

// -----------------------------------------------------------------------
// Main
// -----------------------------------------------------------------------
static void printUsage(const char* prog) {
  std::fprintf(stderr,
      "Usage: %s <data.txt> [reading_sequence]\n"
      "\n"
      "  data.txt        Path to language model dictionary\n"
      "  reading_sequence Dash-separated Bopomofo syllables\n"
      "                   (e.g. 'ㄨㄛˇ-ㄕˋ-ㄒㄩㄝˊ-ㄕㄥ')\n"
      "\n"
      "  If reading_sequence is omitted, enters interactive mode\n"
      "  where each line is a reading sequence.\n",
      prog);
}

int main(int argc, char* argv[]) {
  if (argc < 2) {
    printUsage(argv[0]);
    return 1;
  }

  const char* dataPath = argv[1];
  if (!fs::exists(dataPath)) {
    std::fprintf(stderr, "FATAL: data.txt not found at %s\n", dataPath);
    return 1;
  }

  // Load language model
  auto lm = std::make_shared<McBopomofo::McBopomofoLM>();
  lm->loadLanguageModel(dataPath);
  if (!lm->isDataModelLoaded()) {
    std::fprintf(stderr, "FATAL: failed to load language model from %s\n", dataPath);
    return 1;
  }

  if (argc >= 3) {
    // Single-shot mode
    std::string readingSeq = argv[2];
    auto readings = split(readingSeq, '-');
    auto result = evaluate(readings, lm);

    std::printf("Input:   %s\n", readingSeq.c_str());
    std::printf("Base:    %s\n", result.baselineText.c_str());
    std::printf("Scored:  %s\n", result.rerankedText.c_str());

    if (result.corrections.empty()) {
      std::printf("Corrections: (none)\n");
    } else {
      std::printf("Corrections:\n");
      for (const auto& c : result.corrections) {
        std::printf("  [%zu:%zu] %s -> %s  (%.1f, rule: %s)\n",
                    c.start, c.length,
                    c.reading.c_str(), c.value.c_str(),
                    c.scoreDelta, c.ruleName.c_str());
      }
    }
  } else {
    // Interactive mode
    std::printf("McBopomofo Scorer Demo (interactive mode)\n");
    std::printf("Enter dash-separated Bopomofo sequences, or empty line to quit.\n");
    std::printf("Example: ㄨㄛˇ-ㄕˋ-ㄒㄩㄝˊ-ㄕㄥ\n\n");

    std::string line;
    while (true) {
      std::printf("> ");
      std::fflush(stdout);
      if (!std::getline(std::cin, line) || line.empty()) {
        break;
      }

      auto readings = split(line, '-');
      auto result = evaluate(readings, lm);

      std::printf("Input:   %s\n", line.c_str());
      std::printf("Base:    %s\n", result.baselineText.c_str());
      std::printf("Scored:  %s\n", result.rerankedText.c_str());
      if (result.corrections.empty()) {
        std::printf("Corrections: (none)\n");
      } else {
        std::printf("Corrections:\n");
        for (const auto& c : result.corrections) {
          std::printf("  [%zu:%zu] %s -> %s  (%.1f, rule: %s)\n",
                      c.start, c.length,
                      c.reading.c_str(), c.value.c_str(),
                      c.scoreDelta, c.ruleName.c_str());
        }
      }
      std::printf("\n");
    }
  }

  return 0;
}
