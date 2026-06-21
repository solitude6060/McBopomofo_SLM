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

// Phase 0 baseline evaluator.
// readings from JSONL test fixtures, records accuracy, candidate rank,
// latency, and missing readings.
//   ./evaluator /path/to/data.txt < test_cases.jsonl
//   ./evaluator /path/to/data.txt /path/to/test_cases.jsonl

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "Engine/DeterministicContextualScorer.h"
#include "Engine/McBopomofoLM.h"
#include "Engine/gramambular2/reading_grid.h"
#include "Engine/BigramContextualScorer.h"

namespace fs = std::filesystem;

// No dependency on nlohmann/json.

static std::string trim(const std::string& s) {
  size_t start = 0;
  while (start < s.size() && (s[start] == ' ' || s[start] == '\t')) ++start;
  size_t end = s.size();
  while (end > start && (s[end - 1] == ' ' || s[end - 1] == '\t')) --end;
  return s.substr(start, end - start);
}

static std::vector<std::string> splitUTF8Codepoints(const std::string& s) {
  std::vector<std::string> result;
  for (size_t i = 0; i < s.size();) {
    unsigned char c = static_cast<unsigned char>(s[i]);
    size_t len = 1;
    if ((c & 0x80) == 0x00) {
      len = 1;
    } else if ((c & 0xE0) == 0xC0) {
      len = 2;
    } else if ((c & 0xF0) == 0xE0) {
      len = 3;
    } else if ((c & 0xF8) == 0xF0) {
      len = 4;
    }
    if (i + len > s.size()) {
      len = 1;
    }
    result.push_back(s.substr(i, len));
    i += len;
  }
  return result;
}

static std::string unescapeJSON(const std::string& s) {
  std::string out;
  out.reserve(s.size());
  for (size_t i = 0; i < s.size(); ++i) {
    if (s[i] == '\\' && i + 1 < s.size()) {
      switch (s[i + 1]) {
        case '"':  out.push_back('"'); ++i; break;
        case '\\': out.push_back('\\'); ++i; break;
        case '/':  out.push_back('/'); ++i; break;
        case 'n':  out.push_back('\n'); ++i; break;
        case 't':  out.push_back('\t'); ++i; break;
        case 'u': {
          // Simplified: skip 4 hex digits for uXXXX
          if (i + 5 < s.size()) {
            // We don't fully decode; treat as raw for now
            out.push_back('?');
            i += 5;
          }
          break;
        }
        default: out.push_back(s[i + 1]); ++i; break;
      }
    } else {
      out.push_back(s[i]);
    }
  }
  return out;
}

// Handles both "key": "value" and "key":"value"
static std::string extractJSONString(const std::string& json, const std::string& key) {
  std::string search = "\"" + key + "\":";
  size_t pos = json.find(search);
  if (pos == std::string::npos) return "";
  pos = json.find('"', pos + search.size());
  if (pos == std::string::npos) return "";
  size_t end = pos + 1;
  while (end < json.size()) {
    if (json[end] == '"' && json[end - 1] != '\\') break;
    ++end;
  }
  if (end >= json.size()) return "";
  return unescapeJSON(json.substr(pos + 1, end - pos - 1));
}

static std::vector<std::string> extractJSONStringArray(const std::string& json,
                                                       const std::string& key) {
  std::vector<std::string> result;
  std::string search = "\"" + key + "\":";
  size_t pos = json.find(search);
  if (pos == std::string::npos) return result;
  pos += search.size();
  // Skip whitespace between : and [
  while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) ++pos;
  if (pos >= json.size() || json[pos] != '[') return result;
  ++pos; // skip '['
  // Skip whitespace after [
  while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) ++pos;
  if (pos >= json.size() || json[pos] != '"') {
    // Might be empty array
    if (json[pos] == ']') return result;
    return result;
  }
  // Parse string elements
  while (pos < json.size()) {
    // Find opening quote
    while (pos < json.size() && json[pos] != '"') {
      if (json[pos] == ']') return result; // end of array
      ++pos;
    }
    if (pos >= json.size()) break;
    size_t start = pos + 1;
    size_t end = start;
    while (end < json.size()) {
      if (json[end] == '\\') { end += 2; continue; }
      if (json[end] == '"') break;
      ++end;
    }
    if (end >= json.size()) break;
    result.push_back(unescapeJSON(json.substr(start, end - start)));
    pos = end + 1;
    // Skip to next element or ']'
    while (pos < json.size() && json[pos] != ',' && json[pos] != ']') ++pos;
    if (pos < json.size() && json[pos] == ',') ++pos;
  }
  return result;
}

static bool extractJSONBool(const std::string& json, const std::string& key,
                            bool defaultVal = false) {
  std::string search = "\"" + key + "\":";
  size_t pos = json.find(search);
  if (pos == std::string::npos) return defaultVal;
  pos += search.size();
  while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) ++pos;
  if (pos + 4 <= json.size() && json.substr(pos, 4) == "true") return true;
  if (pos + 5 <= json.size() && json.substr(pos, 5) == "false") return false;
  return defaultVal;
}

static std::optional<uint32_t> nextCodepoint(const std::string& s, size_t* offset) {
  if (offset == nullptr || *offset >= s.size()) {
    return std::nullopt;
  }
  const unsigned char c = static_cast<unsigned char>(s[*offset]);
  if (c < 0x80) {
    ++(*offset);
    return c;
  }
  if ((c & 0xE0) == 0xC0 && *offset + 1 < s.size()) {
    uint32_t cp = ((c & 0x1F) << 6) |
                  (static_cast<unsigned char>(s[*offset + 1]) & 0x3F);
    *offset += 2;
    return cp;
  }
  if ((c & 0xF0) == 0xE0 && *offset + 2 < s.size()) {
    uint32_t cp = ((c & 0x0F) << 12) |
                  ((static_cast<unsigned char>(s[*offset + 1]) & 0x3F) << 6) |
                  (static_cast<unsigned char>(s[*offset + 2]) & 0x3F);
    *offset += 3;
    return cp;
  }
  if ((c & 0xF8) == 0xF0 && *offset + 3 < s.size()) {
    uint32_t cp = ((c & 0x07) << 18) |
                  ((static_cast<unsigned char>(s[*offset + 1]) & 0x3F) << 12) |
                  ((static_cast<unsigned char>(s[*offset + 2]) & 0x3F) << 6) |
                  (static_cast<unsigned char>(s[*offset + 3]) & 0x3F);
    *offset += 4;
    return cp;
  }
  ++(*offset);
  return std::nullopt;
}

static bool isBopomofoCodepoint(uint32_t cp) {
  return (cp >= 0x3100 && cp <= 0x312F) ||  // Bopomofo
         (cp >= 0x31A0 && cp <= 0x31BF) ||  // Extended Bopomofo
         cp == 0x02CA || cp == 0x02C7 || cp == 0x02CB || cp == 0x02D9;
}

static bool isBopomofoReading(const std::string& token) {
  if (token.empty()) {
    return false;
  }
  bool sawBopomofo = false;
  size_t offset = 0;
  while (offset < token.size()) {
    std::optional<uint32_t> cp = nextCodepoint(token, &offset);
    if (!cp.has_value() || !isBopomofoCodepoint(cp.value())) {
      return false;
    }
    sawBopomofo = true;
  }
  return sawBopomofo;
}

struct TestCase {
  std::string id;
  std::vector<std::string> readings;
  std::string expected;
  std::vector<std::string> protectedEnglishSpans;
  bool redistributable;
};

static TestCase parseTestCase(const std::string& line) {
  TestCase tc;
  tc.id = extractJSONString(line, "id");
  tc.readings = extractJSONStringArray(line, "readings");
  tc.expected = extractJSONString(line, "expected");
  tc.protectedEnglishSpans = extractJSONStringArray(line, "protected_english_spans");
  tc.redistributable = extractJSONBool(line, "redistributable", true);
  return tc;
}

struct CandidateInfo {
  std::string value;
  std::string reading;
  double score;
  size_t spanIndex;
  size_t length;
};

struct PerCaseResult {
  std::string id;
  bool exactMatch = false;
  size_t totalCJKChars = 0;
  size_t matchedCJKChars = 0;
  int targetRank = -1;        // 1-based rank of expected in all candidates; 0 = not found
  int bestCandidateRank = -1; // rank of best candidate matching ANY expected token
  uint64_t elapsedMicroseconds = 0;
  bool missingReading = false;
  size_t missingReadingIndex = 0;
  std::string engineOutput;
};

static size_t countCJK(const std::string& s) {
  size_t count = 0;
  for (unsigned char c : s) {
    // CJK Unified Ideographs range: U+4E00 to U+9FFF
    // In UTF-8: 4E00 = E4 B8 80, 9FFF = E9 BF BF
    // We detect 3-byte UTF-8 sequences in this range
    if ((c & 0xF0) == 0xE0) {
      // Start of 3-byte sequence
      count++;
    }
  }
  return count;
}

static void debugUTF8(const std::string& label, const std::string& s) {
  fprintf(stderr, "[%s] bytes (%zu): ", label.c_str(), s.size());
  for (unsigned char c : s) {
    fprintf(stderr, "%02x ", c);
  }
  fprintf(stderr, "\n");
}

static double nodeTopScore(const Formosa::Gramambular2::ReadingGrid::NodePtr& node) {
  auto unigrams = node->unigrams();
  if (unigrams.empty()) return 0.0;
  double best = unigrams[0].score();
  for (const auto& u : unigrams) {
    if (u.score() > best) best = u.score();
  }
  return best;
}

// Forward declaration used by Evaluator.
static std::string escapeJSON(const std::string& s);

class Evaluator {
 public:
   enum class ScorerType {
     Baseline,
     Deterministic,
     Bigram
   };

   enum class SlmCandidateGranularity {
     Node,
     Character
   };

   explicit Evaluator(const char* dataPath, ScorerType scorerType,
                      const std::string& modelPath = "")
       : scorerType_(scorerType), modelPath_(modelPath) {
     lm_ = std::make_shared<McBopomofo::McBopomofoLM>();
     lm_->loadLanguageModel(dataPath);
     if (!lm_->isDataModelLoaded()) {
       fprintf(stderr, "FATAL: failed to load language model from %s\n", dataPath);
       exit(1);
     }

     switch (scorerType_) {
       case ScorerType::Baseline:
         scorer_ = nullptr;
         break;
       case ScorerType::Deterministic:
         scorer_ = std::make_unique<McBopomofo::DeterministicContextualScorer>();
         break;
       case ScorerType::Bigram:
         scorer_ = std::make_unique<McBopomofo::BigramContextualScorer>(modelPath_);
         break;
     }
   }

   PerCaseResult evaluate(const TestCase& tc) {
     PerCaseResult r = evaluateGeneric(tc);
     if (slmOutput_) {
       writeSlmRequest(tc);
     }
     return r;
   }

   void setSlmOutput(FILE* f) { slmOutput_ = f; }
   void setSlmCandidateLimit(size_t limit) { slmCandidateLimit_ = limit; }
   void setSlmCandidateGranularity(SlmCandidateGranularity granularity) {
     slmCandidateGranularity_ = granularity;
   }

 private:
   struct OutputSegment {
     std::string text;
     bool protectedText = false;
   };

   struct Correction {
     size_t candidateIndex = 0;
     size_t start = 0;
     size_t length = 0;
     std::string reading;
     std::string value;
     double scoreDelta = 0.0;
   };

   PerCaseResult evaluateGeneric(const TestCase& tc) {
     PerCaseResult result;
     result.id = tc.id;

     std::vector<OutputSegment> segments;
     std::vector<std::string> bopomofoChunk;
     bool pureBopomofo = true;

     auto flushChunk = [&]() -> bool {
       if (bopomofoChunk.empty()) {
         return true;
       }
       std::string chunkOutput;
       uint64_t chunkElapsed = 0;
       bool ok = evaluateBopomofoChunk(bopomofoChunk, tc, &chunkOutput,
                                       &chunkElapsed,
                                       pureBopomofo ? &result : nullptr);
       bopomofoChunk.clear();
       if (!ok) {
         result.missingReading = true;
         return false;
       }
       result.elapsedMicroseconds += chunkElapsed;
       segments.push_back(OutputSegment{chunkOutput, false});
       return true;
     };

     for (size_t i = 0; i < tc.readings.size(); ++i) {
       if (isBopomofoReading(tc.readings[i])) {
         bopomofoChunk.push_back(tc.readings[i]);
         continue;
       }

       pureBopomofo = false;
       if (!flushChunk()) {
         result.missingReadingIndex = i;
         return result;
       }
       segments.push_back(OutputSegment{tc.readings[i], true});
     }

     if (!flushChunk()) {
       result.missingReadingIndex = tc.readings.size();
       return result;
     }

     result.engineOutput = joinSegments(segments);
     finishAccuracy(tc, &result);
     return result;
   }

   bool evaluateBopomofoChunk(const std::vector<std::string>& readings,
                              const TestCase& tc, std::string* output,
                              uint64_t* elapsedMicroseconds,
                              PerCaseResult* rankResult) {
     Formosa::Gramambular2::ReadingGrid grid(
         std::make_shared<Formosa::Gramambular2::ReadingGrid::ScoreRankedLanguageModel>(lm_));

     for (const std::string& reading : readings) {
       if (!grid.insertReading(reading)) {
         return false;
       }
     }

     struct timespec ts;
     clock_gettime(CLOCK_MONOTONIC, &ts);
     const uint64_t start = ts.tv_sec * 1000000ULL + ts.tv_nsec / 1000;

     Formosa::Gramambular2::ReadingGrid::WalkResult walkResult = grid.walk();
     if (scorer_ != nullptr) {
       applyReranker(readings, tc.protectedEnglishSpans, grid, &walkResult);
     }

     clock_gettime(CLOCK_MONOTONIC, &ts);
     const uint64_t end = ts.tv_sec * 1000000ULL + ts.tv_nsec / 1000;
     *elapsedMicroseconds += end - start;

     auto values = walkResult.valuesAsStrings();
     for (const auto& v : values) {
       *output += v;
     }

     if (rankResult != nullptr) {
       rankResult->targetRank = findTargetRank(grid, tc);
       rankResult->bestCandidateRank = findBestCandidateRank(grid, tc);
     }
     return true;
   }

   void applyReranker(
       const std::vector<std::string>& readings,
       const std::vector<std::string>& protectedEnglishSpans,
       Formosa::Gramambular2::ReadingGrid& grid,
       Formosa::Gramambular2::ReadingGrid::WalkResult* walkResult) {
     McBopomofo::ContextualScoreRequest request;
     request.readings = readings;
     request.protectedEnglishSpans = protectedEnglishSpans;
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

     std::vector<double> deltas = scorer_->scoreDeltas(request);
     std::vector<Correction> viable;

     for (size_t i = 0; i < deltas.size(); ++i) {
       if (deltas[i] <= 0.0) continue;

       const auto& candidate = request.candidates[i];
       size_t start = candidate.start;
       size_t length = candidate.length;

       if (length == 0 || start + length > grid.length()) {
         continue;
       }

       if (candidate.value == baselineValueAt(request, start)) {
         continue;
       }
       if (candidate.value == baselineValueForSpan(request, start, length)) {
         continue;
       }

       viable.push_back(Correction{
           i, start, length, candidate.reading, candidate.value, deltas[i]});
     }

     std::stable_sort(
         viable.begin(), viable.end(),
         [](const Correction& a, const Correction& b) {
           if (a.scoreDelta != b.scoreDelta) {
             return a.scoreDelta > b.scoreDelta;
           }
           if (a.length != b.length) {
             return a.length > b.length;
           }
           return a.candidateIndex < b.candidateIndex;
         });

     std::vector<Correction> selected;
     std::vector<bool> occupied(grid.length(), false);
     for (const auto& correction : viable) {
       bool overlaps = false;
       for (size_t j = correction.start;
            j < correction.start + correction.length; ++j) {
         overlaps = overlaps || occupied[j];
       }
       if (overlaps) {
         continue;
       }

       selected.push_back(correction);

       for (size_t j = correction.start;
            j < correction.start + correction.length; ++j) {
         occupied[j] = true;
       }
     }

     std::stable_sort(
         selected.begin(), selected.end(),
         [](const Correction& a, const Correction& b) {
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
                        Formosa::Gramambular2::ReadingGrid::Node::OverrideType::
                            kOverrideValueWithHighScore) ||
                    overridden;
     }
     if (overridden) {
       *walkResult = grid.walk();
     }
   }

  std::string baselineValueAt(
      const McBopomofo::ContextualScoreRequest& request,
      size_t readingIndex) const {
    for (const auto& item : request.baselinePath) {
      if (readingIndex >= item.start &&
          readingIndex < item.start + item.length) {
        return item.value;
      }
    }
    return "";
  }

  std::string baselineValueForSpan(
      const McBopomofo::ContextualScoreRequest& request,
      size_t readingIndex, size_t length) const {
    const size_t end = readingIndex + std::max<size_t>(length, 1);
    std::string result;
    for (size_t pos = readingIndex; pos < end;) {
      const McBopomofo::CandidateScoreInput* covering = nullptr;
      for (const auto& item : request.baselinePath) {
        if (pos >= item.start && pos < item.start + item.length) {
          covering = &item;
          break;
        }
      }
      if (covering == nullptr) {
        ++pos;
        continue;
      }

      const size_t overlapStart = std::max(pos, covering->start);
      const size_t overlapEnd =
          std::min(end, covering->start + covering->length);
      std::vector<std::string> chars = splitUTF8Codepoints(covering->value);
      if (chars.size() == covering->length) {
        for (size_t i = overlapStart - covering->start;
             i < overlapEnd - covering->start; ++i) {
          result += chars[i];
        }
      } else if (overlapStart == covering->start &&
                 overlapEnd == covering->start + covering->length) {
        result += covering->value;
      }

      size_t next = covering->start + covering->length;
      pos = next > pos ? next : pos + 1;
    }
    return result;
  }

  static std::string joinSegments(const std::vector<OutputSegment>& segments) {
    std::string output;
    for (size_t i = 0; i < segments.size(); ++i) {
      if (segments[i].text.empty()) {
        continue;
      }
      if (!output.empty() &&
          (segments[i].protectedText || segments[i - 1].protectedText)) {
        output += " ";
      }
      output += segments[i].text;
    }
    return output;
  }

  static void finishAccuracy(const TestCase& tc, PerCaseResult* result) {
    result->exactMatch = (result->engineOutput == tc.expected);

    std::string engineCJK;
    std::string expectedCJK;
    for (size_t i = 0; i < result->engineOutput.size(); ) {
      unsigned char c = static_cast<unsigned char>(result->engineOutput[i]);
      if ((c & 0xF0) == 0xE0) {
        engineCJK += result->engineOutput.substr(i, 3);
        i += 3;
      } else {
        ++i;
      }
    }
    for (size_t i = 0; i < tc.expected.size(); ) {
      unsigned char c = static_cast<unsigned char>(tc.expected[i]);
      if ((c & 0xF0) == 0xE0) {
        expectedCJK += tc.expected.substr(i, 3);
        i += 3;
      } else {
        ++i;
      }
    }

    result->totalCJKChars = expectedCJK.size() / 3;
    size_t matched = 0;
    for (size_t ei = 0; ei + 3 <= engineCJK.size(); ei += 3) {
      for (size_t xi = 0; xi + 3 <= expectedCJK.size(); xi += 3) {
        if (engineCJK.substr(ei, 3) == expectedCJK.substr(xi, 3)) {
          matched++;
          break;
        }
      }
    }
    result->matchedCJKChars = matched;
  }

  int findTargetRank(Formosa::Gramambular2::ReadingGrid& grid,
                     const TestCase& tc) {
    std::string firstExpectedChar;
    for (size_t i = 0; i < tc.expected.size(); ) {
      unsigned char c = static_cast<unsigned char>(tc.expected[i]);
      if ((c & 0xF0) == 0xE0) {
        firstExpectedChar = tc.expected.substr(i, 3);
        break;
      }
      ++i;
    }
    if (firstExpectedChar.empty()) return 0;

    for (size_t loc = 0; loc < grid.length(); ++loc) {
      auto candidates = grid.candidatesAt(loc);
      for (int rank = 0; rank < static_cast<int>(candidates.size()); ++rank) {
        if (candidates[rank].value == firstExpectedChar) {
          return rank + 1; // 1-based
        }
        for (size_t i = 0; i + 3 <= candidates[rank].value.size(); i += 3) {
          if (candidates[rank].value.substr(i, 3) == firstExpectedChar) {
            return rank + 1;
          }
        }
      }
    }
    return 0;
  }

  int findBestCandidateRank(Formosa::Gramambular2::ReadingGrid& grid,
                            const TestCase& tc) {
    int bestRank = 999;
    for (size_t loc = 0; loc < grid.length(); ++loc) {
      auto candidates = grid.candidatesAt(loc);
      for (int rank = 0; rank < static_cast<int>(candidates.size()); ++rank) {
        for (size_t ei = 0; ei + 3 <= tc.expected.size(); ei += 3) {
          std::string expChar = tc.expected.substr(ei, 3);
          for (size_t ci = 0; ci + 3 <= candidates[rank].value.size(); ci += 3) {
            if (candidates[rank].value.substr(ci, 3) == expChar) {
              if (rank + 1 < bestRank) bestRank = rank + 1;
            }
          }
        }
      }
    }
    return bestRank == 999 ? 0 : bestRank;
  }

  struct SlmSlotResult {
    std::string text;
    std::vector<std::vector<std::string>> slots;
    bool ok = true;
  };

  SlmSlotResult processBopomofoChunkForSlm(
      const std::vector<std::string>& readings) {
    SlmSlotResult result;
    Formosa::Gramambular2::ReadingGrid grid(
        std::make_shared<
            Formosa::Gramambular2::ReadingGrid::ScoreRankedLanguageModel>(
            lm_));
    for (const auto& r : readings) {
      if (!grid.insertReading(r)) {
        result.ok = false;
        return result;
      }
    }
    Formosa::Gramambular2::ReadingGrid::WalkResult walkResult = grid.walk();
    auto values = walkResult.valuesAsStrings();
    for (const auto& v : values) {
      result.text += v;
    }

    size_t readingOffset = 0;
    for (const auto& node : walkResult.nodes) {
      size_t length = node->spanningLength();
      const auto& spanNode = grid.spans()[readingOffset].nodeOf(length);
      std::vector<std::string> candidates;
      if (spanNode != nullptr) {
        std::unordered_set<std::string> seen;
        for (const auto& u : spanNode->unigrams()) {
          if (seen.insert(u.value()).second) {
            candidates.push_back(u.value());
          }
        }
      }
      // Cap at limit, ensuring baseline value is always included.
      if (candidates.size() > slmCandidateLimit_) {
        std::string baselineVal = node->value();
        auto it = std::find(candidates.begin(),
                            candidates.begin() + slmCandidateLimit_,
                            baselineVal);
        if (it == candidates.begin() + slmCandidateLimit_) {
          candidates.resize(slmCandidateLimit_);
          candidates.back() = baselineVal;
        } else {
          candidates.resize(slmCandidateLimit_);
        }
      }
      if (slmCandidateGranularity_ == SlmCandidateGranularity::Character) {
        addCharacterSlotsForSlm(node->value(), candidates, &result.slots);
      } else {
        result.slots.push_back(std::move(candidates));
      }
      readingOffset += length;
    }
    return result;
  }

  void addCharacterSlotsForSlm(
      const std::string& baselineValue,
      const std::vector<std::string>& nodeCandidates,
      std::vector<std::vector<std::string>>* slots) const {
    std::vector<std::string> baselineChars = splitUTF8Codepoints(baselineValue);
    if (baselineChars.empty()) {
      slots->push_back(nodeCandidates);
      return;
    }

    std::vector<std::vector<std::string>> charSlots;
    std::vector<std::unordered_set<std::string>> seen;
    charSlots.reserve(baselineChars.size());
    seen.reserve(baselineChars.size());

    for (const auto& ch : baselineChars) {
      charSlots.push_back({ch});
      std::unordered_set<std::string> slotSeen;
      slotSeen.insert(ch);
      seen.push_back(std::move(slotSeen));
    }

    for (const auto& candidate : nodeCandidates) {
      std::vector<std::string> candidateChars = splitUTF8Codepoints(candidate);
      if (candidateChars.size() != baselineChars.size()) {
        continue;
      }
      for (size_t i = 0; i < candidateChars.size(); ++i) {
        if (charSlots[i].size() >= slmCandidateLimit_) {
          continue;
        }
        if (seen[i].insert(candidateChars[i]).second) {
          charSlots[i].push_back(candidateChars[i]);
        }
      }
    }

    for (auto& slot : charSlots) {
      slots->push_back(std::move(slot));
    }
  }

  void writeSlmRequest(const TestCase& tc) {
    if (!slmOutput_) return;

    std::vector<std::vector<std::string>> allSlots;
    std::string baselineOutput;
    std::vector<std::string> bopomofoChunk;
    bool allOk = true;
    bool prevWasProtected = false;

    auto addSlotsWithSpacing =
        [&](std::vector<std::vector<std::string>>& newSlots,
            const std::string& text, bool isProtected) {
          bool needSpace = !baselineOutput.empty();
          if (needSpace && (isProtected || prevWasProtected)) {
            allSlots.push_back({" "});
            baselineOutput += " ";
          }
          for (auto& slot : newSlots) {
            allSlots.push_back(std::move(slot));
          }
          baselineOutput += text;
          prevWasProtected = isProtected;
        };

    for (size_t i = 0; i < tc.readings.size(); ++i) {
      if (isBopomofoReading(tc.readings[i])) {
        bopomofoChunk.push_back(tc.readings[i]);
        continue;
      }

      if (!bopomofoChunk.empty()) {
        auto chunkResult = processBopomofoChunkForSlm(bopomofoChunk);
        bopomofoChunk.clear();
        if (chunkResult.ok) {
          addSlotsWithSpacing(chunkResult.slots, chunkResult.text, false);
        } else {
          allOk = false;
        }
      }

      std::vector<std::vector<std::string>> tokenSlots = {{tc.readings[i]}};
      addSlotsWithSpacing(tokenSlots, tc.readings[i], true);
    }

    if (!bopomofoChunk.empty()) {
      auto chunkResult = processBopomofoChunkForSlm(bopomofoChunk);
      bopomofoChunk.clear();
      if (chunkResult.ok) {
        addSlotsWithSpacing(chunkResult.slots, chunkResult.text, false);
      } else {
        allOk = false;
      }
    }

    fprintf(slmOutput_, "{\"id\":\"%s\"", escapeJSON(tc.id).c_str());

    fprintf(slmOutput_, ",\"readings\":[");
    for (size_t i = 0; i < tc.readings.size(); ++i) {
      if (i > 0) fprintf(slmOutput_, ",");
      fprintf(slmOutput_, "\"%s\"", escapeJSON(tc.readings[i]).c_str());
    }
    fprintf(slmOutput_, "]");

    fprintf(slmOutput_, ",\"baseline_output\":\"%s\"",
            escapeJSON(baselineOutput).c_str());

    if (!tc.expected.empty()) {
      fprintf(slmOutput_, ",\"expected\":\"%s\"",
              escapeJSON(tc.expected).c_str());
    }

    if (!tc.protectedEnglishSpans.empty()) {
      fprintf(slmOutput_, ",\"protected_english_spans\":[");
      for (size_t i = 0; i < tc.protectedEnglishSpans.size(); ++i) {
        if (i > 0) fprintf(slmOutput_, ",");
        fprintf(slmOutput_, "\"%s\"",
                escapeJSON(tc.protectedEnglishSpans[i]).c_str());
      }
      fprintf(slmOutput_, "]");
    }

    if (!allSlots.empty() && allOk) {
      fprintf(slmOutput_, ",\"candidates\":[");
      for (size_t i = 0; i < allSlots.size(); ++i) {
        if (i > 0) fprintf(slmOutput_, ",");
        fprintf(slmOutput_, "[");
        for (size_t j = 0; j < allSlots[i].size(); ++j) {
          if (j > 0) fprintf(slmOutput_, ",");
          fprintf(slmOutput_, "\"%s\"",
                  escapeJSON(allSlots[i][j]).c_str());
        }
        fprintf(slmOutput_, "]");
      }
      fprintf(slmOutput_, "]");
    }

    fprintf(slmOutput_, "}\n");
  }

  std::shared_ptr<McBopomofo::McBopomofoLM> lm_;
  Evaluator::ScorerType scorerType_;
  std::string modelPath_;
  std::unique_ptr<McBopomofo::ContextualScorer> scorer_;
  FILE* slmOutput_ = nullptr;
  size_t slmCandidateLimit_ = 16;
  SlmCandidateGranularity slmCandidateGranularity_ =
      SlmCandidateGranularity::Node;
};

static std::string escapeJSON(const std::string& s) {
  std::string out;
  out.reserve(s.size());
  for (char c : s) {
    switch (c) {
      case '"': out += "\\\""; break;
      case '\\': out += "\\\\"; break;
      case '\n': out += "\\n"; break;
      case '\t': out += "\\t"; break;
      default: out += c;
    }
  }
  return out;
}

static void printResultJSON(const PerCaseResult& r) {
  printf("{\"id\":\"%s\",\"exact_match\":%s,\"total_cjk_chars\":%zu,"
         "\"matched_cjk_chars\":%zu,\"target_rank\":%d,"
         "\"best_candidate_rank\":%d,\"elapsed_us\":%llu,"
         "\"missing_reading\":%s,\"engine_output\":\"%s\"}\n",
         r.id.c_str(),
         r.exactMatch ? "true" : "false",
         r.totalCJKChars,
         r.matchedCJKChars,
         r.targetRank,
         r.bestCandidateRank,
         static_cast<unsigned long long>(r.elapsedMicroseconds),
         r.missingReading ? "true" : "false",
         escapeJSON(r.engineOutput).c_str());
}

static void printSummaryJSON(const std::vector<PerCaseResult>& results,
                             uint64_t totalElapsed,
                             const char* engineName) {
  size_t total = results.size();
  size_t exactMatch = 0;
  size_t missingReading = 0;
  size_t totalCJK = 0;
  size_t matchedCJK = 0;
  int totalRank = 0;
  int rankCount = 0;
  std::vector<uint64_t> latencies;

  for (const auto& r : results) {
    if (r.exactMatch) exactMatch++;
    if (r.missingReading) missingReading++;
    totalCJK += r.totalCJKChars;
    matchedCJK += r.matchedCJKChars;

    if (r.targetRank > 0) {
      totalRank += r.targetRank;
      rankCount++;
    }

    if (!r.missingReading) {
      latencies.push_back(r.elapsedMicroseconds);
    }
  }

  std::sort(latencies.begin(), latencies.end());

  double p50 = latencies.empty() ? 0 : latencies[latencies.size() * 50 / 100];
  double p95 = latencies.empty() ? 0 : latencies[latencies.size() * 95 / 100];
  double p99 = latencies.empty() ? 0 : latencies[latencies.size() * 99 / 100];

  double sentenceAcc = total > 0 ? (100.0 * exactMatch / total) : 0.0;
  double tokenAcc = totalCJK > 0 ? (100.0 * matchedCJK / totalCJK) : 0.0;
  double meanRank = rankCount > 0 ? (1.0 * totalRank / rankCount) : 0.0;

  // We classify by checking which cases failed
  size_t contextAmbiguity = 0;
  size_t unknown = 0;
  for (const auto& r : results) {
    if (!r.exactMatch && !r.missingReading) {
      contextAmbiguity++;
    }
  }

  printf("{\"engine\":\"%s\","
         "\"data_version\":\"2026-06-18\","
         "\"total_cases\":%zu,"
         "\"exact_sentence_accuracy\":%.4f,"
         "\"token_accuracy\":%.4f,"
         "\"exact_match_count\":%zu,"
         "\"candidate_rank_mean\":%.2f,"
         "\"missing_reading_cases\":%zu,"
         "\"latency_microseconds_p50\":%.0f,"
         "\"latency_microseconds_p95\":%.0f,"
         "\"latency_microseconds_p99\":%.0f,"
         "\"total_elapsed_seconds\":%.3f,"
         "\"context_ambiguity_errors\":%zu,"
         "\"unknown_errors\":%zu}\n",
         engineName,
         total,
         sentenceAcc,
         tokenAcc,
         exactMatch,
         meanRank,
         missingReading,
         p50, p95, p99,
         totalElapsed / 1000000.0,
         contextAmbiguity,
         unknown);
}

int main(int argc, char* argv[]) {
  if (argc < 2) {
    fprintf(stderr, "Usage: %s <data.txt> [--scorer baseline|deterministic|bigram] [--model <path>] [--reranker] [--slm-request-output <path>] [--slm-candidate-limit <N>] [--slm-candidate-granularity node|character] [test_cases.jsonl]\n", argv[0]);
    fprintf(stderr, "  If test_cases.jsonl is omitted, reads from stdin.\n");
    fprintf(stderr, "  --slm-request-output <path>   Write candidate-constrained SLM request JSONL to <path>\n");
    fprintf(stderr, "  --slm-candidate-limit <N>     Max candidates per slot (default 16, always includes baseline)\n");
    fprintf(stderr, "  --slm-candidate-granularity   Candidate slot export granularity (default node)\n");
    return 1;
  }

  const char* dataPath = argv[1];
  if (!fs::exists(dataPath)) {
    fprintf(stderr, "FATAL: data.txt not found at %s\n", dataPath);
    return 1;
  }

  Evaluator::ScorerType scorerType = Evaluator::ScorerType::Baseline;
  std::string modelPath = "";
  const char* testCasesPath = nullptr;
  const char* slmRequestOutputPath = nullptr;
  size_t slmCandidateLimit = 16;
  Evaluator::SlmCandidateGranularity slmCandidateGranularity =
      Evaluator::SlmCandidateGranularity::Node;

  for (int i = 2; i < argc; ++i) {
    if (std::strcmp(argv[i], "--scorer") == 0) {
      if (i + 1 >= argc) {
        fprintf(stderr, "FATAL: --scorer requires a value (baseline|deterministic|bigram)\n");
        return 1;
      }
      const char* scorerArg = argv[++i];
      if (std::strcmp(scorerArg, "baseline") == 0) {
        scorerType = Evaluator::ScorerType::Baseline;
      } else if (std::strcmp(scorerArg, "deterministic") == 0) {
        scorerType = Evaluator::ScorerType::Deterministic;
      } else if (std::strcmp(scorerArg, "bigram") == 0) {
        scorerType = Evaluator::ScorerType::Bigram;
      } else {
        fprintf(stderr, "FATAL: unknown scorer type '%s' (expected baseline|deterministic|bigram)\n", scorerArg);
        return 1;
      }
      continue;
    }
    if (std::strcmp(argv[i], "--model") == 0) {
      if (i + 1 >= argc) {
        fprintf(stderr, "FATAL: --model requires a path\n");
        return 1;
      }
      modelPath = argv[++i];
      continue;
    }
    if (std::strcmp(argv[i], "--reranker") == 0) {
      scorerType = Evaluator::ScorerType::Deterministic;
      continue;
    }
    if (std::strcmp(argv[i], "--slm-request-output") == 0) {
      if (i + 1 >= argc) {
        fprintf(stderr, "FATAL: --slm-request-output requires a path\n");
        return 1;
      }
      slmRequestOutputPath = argv[++i];
      continue;
    }
    if (std::strcmp(argv[i], "--slm-candidate-limit") == 0) {
      if (i + 1 >= argc) {
        fprintf(stderr, "FATAL: --slm-candidate-limit requires a value\n");
        return 1;
      }
      int val = std::atoi(argv[++i]);
      if (val <= 0) {
        fprintf(stderr, "FATAL: --slm-candidate-limit must be positive, got %d\n", val);
        return 1;
      }
      slmCandidateLimit = static_cast<size_t>(val);
      continue;
    }
    if (std::strcmp(argv[i], "--slm-candidate-granularity") == 0) {
      if (i + 1 >= argc) {
        fprintf(stderr, "FATAL: --slm-candidate-granularity requires a value\n");
        return 1;
      }
      const char* granularityArg = argv[++i];
      if (std::strcmp(granularityArg, "node") == 0) {
        slmCandidateGranularity = Evaluator::SlmCandidateGranularity::Node;
      } else if (std::strcmp(granularityArg, "character") == 0) {
        slmCandidateGranularity =
            Evaluator::SlmCandidateGranularity::Character;
      } else {
        fprintf(stderr, "FATAL: unknown --slm-candidate-granularity '%s' (expected node|character)\n",
                granularityArg);
        return 1;
      }
      continue;
    }
    testCasesPath = argv[i];
  }

  Evaluator evaluator(dataPath, scorerType, modelPath);
  evaluator.setSlmCandidateLimit(slmCandidateLimit);
  evaluator.setSlmCandidateGranularity(slmCandidateGranularity);

  FILE* slmOutput = nullptr;
  if (slmRequestOutputPath != nullptr) {
    slmOutput = fopen(slmRequestOutputPath, "w");
    if (!slmOutput) {
      fprintf(stderr, "FATAL: cannot open SLM request output %s\n",
              slmRequestOutputPath);
      return 1;
    }
    fprintf(stderr, "Writing SLM requests to %s\n", slmRequestOutputPath);
    evaluator.setSlmOutput(slmOutput);
  }

  FILE* input = stdin;
  bool closeInput = false;
  if (testCasesPath != nullptr) {
    input = fopen(testCasesPath, "r");
    if (!input) {
      fprintf(stderr, "FATAL: cannot open %s\n", testCasesPath);
      if (slmOutput) fclose(slmOutput);
      return 1;
    }
    closeInput = true;
  }

  std::vector<PerCaseResult> results;
  char buffer[65536];
  uint64_t totalStart = 0;

  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  totalStart = ts.tv_sec * 1000000ULL + ts.tv_nsec / 1000;

  size_t lineNum = 0;
  while (fgets(buffer, sizeof(buffer), input)) {
    lineNum++;
    std::string line(buffer);
    while (!line.empty() && (line.back() == '\n' || line.back() == '\r')) {
      line.pop_back();
    }
    if (line.empty()) continue;

    TestCase tc;
    try {
      tc = parseTestCase(line);
    } catch (const std::exception& e) {
      fprintf(stderr, "WARN: parse error at line %zu: %s\n", lineNum, e.what());
      continue;
    }
    if (tc.id.empty()) {
      fprintf(stderr, "WARN: empty id at line %zu, skipping\n", lineNum);
      continue;
    }

    PerCaseResult r = evaluator.evaluate(tc);
    results.push_back(r);
    printResultJSON(r);
  }

  clock_gettime(CLOCK_MONOTONIC, &ts);
  uint64_t totalEnd = ts.tv_sec * 1000000ULL + ts.tv_nsec / 1000;

  const char* engineName = "baseline-mcbopomofo";
  switch (scorerType) {
    case Evaluator::ScorerType::Baseline:
      engineName = "baseline-mcbopomofo";
      break;
    case Evaluator::ScorerType::Deterministic:
      engineName = "deterministic-reranker";
      break;
    case Evaluator::ScorerType::Bigram:
      engineName = "bigram-reranker";
      break;
  }

  printSummaryJSON(results, totalEnd - totalStart, engineName);

  if (closeInput) {
    fclose(input);
  }
  if (slmOutput) {
    fclose(slmOutput);
  }

  return 0;
}
