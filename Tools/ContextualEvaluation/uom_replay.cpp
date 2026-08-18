// Copyright (c) 2026 McBopomofo SLM Authors
//
// Walk-level UserOverrideModel replay.
// Default: capacity 500, half-life 5400 s, three-node key, isolated memory.
// --key/--memory are replay-only experimental arms. KeyHandler is unchanged.
// --persist=path writes after observe and loads into the restart instance.
// --oneshot accepts one engine multi-character candidate after the full probe.
// --halflife=<seconds> is replay-only (default 5400). Production stays 5400.
// --suggest-delay=<seconds> is added to suggest timestamps only.

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <memory>
#include <string>
#include <vector>

#include "Engine/McBopomofoLM.h"
#include "Engine/OneShotOverride.h"
#include "Engine/UserOverrideModel.h"
#include "Engine/gramambular2/reading_grid.h"

namespace fs = std::filesystem;

namespace {

constexpr int kCapacity = 500;
constexpr double kHalfLife = 5400.0;
constexpr double kNow = 1657772432.0;

static bool debugReplay() {
  const char* flag = std::getenv("UOM_REPLAY_DEBUG");
  return flag != nullptr && flag[0] != '\0';
}

static std::string unescapeJSON(const std::string& s) {
  std::string out;
  out.reserve(s.size());
  for (size_t i = 0; i < s.size(); ++i) {
    if (s[i] == '\\' && i + 1 < s.size()) {
      switch (s[i + 1]) {
        case '"':
        case '\\':
        case '/':
          out.push_back(s[i + 1]);
          ++i;
          break;
        case 'n':
          out.push_back('\n');
          ++i;
          break;
        case 't':
          out.push_back('\t');
          ++i;
          break;
        default:
          out.push_back(s[i + 1]);
          ++i;
          break;
      }
    } else {
      out.push_back(s[i]);
    }
  }
  return out;
}

static std::string extractJSONString(const std::string& json,
                                     const std::string& key) {
  const std::string search = "\"" + key + "\":";
  size_t pos = json.find(search);
  if (pos == std::string::npos) {
    return "";
  }
  pos = json.find('"', pos + search.size());
  if (pos == std::string::npos) {
    return "";
  }
  size_t end = pos + 1;
  while (end < json.size()) {
    if (json[end] == '"' && json[end - 1] != '\\') {
      break;
    }
    ++end;
  }
  if (end >= json.size()) {
    return "";
  }
  return unescapeJSON(json.substr(pos + 1, end - pos - 1));
}

static std::vector<std::string> extractJSONStringArray(const std::string& json,
                                                       const std::string& key) {
  std::vector<std::string> result;
  const std::string search = "\"" + key + "\":";
  size_t pos = json.find(search);
  if (pos == std::string::npos) {
    return result;
  }
  pos += search.size();
  while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) {
    ++pos;
  }
  if (pos >= json.size() || json[pos] != '[') {
    return result;
  }
  ++pos;
  while (pos < json.size()) {
    while (pos < json.size() && json[pos] != '"' && json[pos] != ']') {
      ++pos;
    }
    if (pos >= json.size() || json[pos] == ']') {
      return result;
    }
    size_t start = pos + 1;
    size_t end = start;
    while (end < json.size()) {
      if (json[end] == '\\') {
        end += 2;
        continue;
      }
      if (json[end] == '"') {
        break;
      }
      ++end;
    }
    if (end >= json.size()) {
      break;
    }
    result.push_back(unescapeJSON(json.substr(start, end - start)));
    pos = end + 1;
  }
  return result;
}

static bool extractJSONBool(const std::string& json, const std::string& key,
                            bool defaultVal) {
  const std::string search = "\"" + key + "\":";
  size_t pos = json.find(search);
  if (pos == std::string::npos) {
    return defaultVal;
  }
  pos += search.size();
  while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) {
    ++pos;
  }
  if (pos + 4 <= json.size() && json.substr(pos, 4) == "true") {
    return true;
  }
  if (pos + 5 <= json.size() && json.substr(pos, 5) == "false") {
    return false;
  }
  return defaultVal;
}

static int extractJSONInt(const std::string& json, const std::string& key,
                          int defaultVal) {
  const std::string search = "\"" + key + "\":";
  size_t pos = json.find(search);
  if (pos == std::string::npos) {
    return defaultVal;
  }
  pos += search.size();
  while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) {
    ++pos;
  }
  if (pos >= json.size() ||
      !(json[pos] == '-' || (json[pos] >= '0' && json[pos] <= '9'))) {
    return defaultVal;
  }
  return std::atoi(json.c_str() + pos);
}

static std::string extractObject(const std::string& json,
                                 const std::string& key) {
  const std::string search = "\"" + key + "\"";
  size_t pos = json.find(search);
  if (pos == std::string::npos) {
    return "";
  }
  pos = json.find('{', pos + search.size());
  if (pos == std::string::npos) {
    return "";
  }
  int depth = 0;
  for (size_t i = pos; i < json.size(); ++i) {
    if (json[i] == '{') {
      ++depth;
    } else if (json[i] == '}') {
      --depth;
      if (depth == 0) {
        return json.substr(pos, i - pos + 1);
      }
    }
  }
  return "";
}

static std::string jsonEscape(const std::string& s) {
  std::string out;
  out.reserve(s.size());
  for (char c : s) {
    if (c == '"' || c == '\\') {
      out.push_back('\\');
    }
    out.push_back(c);
  }
  return out;
}

static std::string joinWalk(
    const Formosa::Gramambular2::ReadingGrid::WalkResult& walk) {
  std::string out;
  for (const auto& value : walk.valuesAsStrings()) {
    out += value;
  }
  return out;
}

static size_t readingSpan(const std::string& reading) {
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

static size_t actualCursorAtEnd(size_t length) {
  if (length == 0) {
    return 0;
  }
  return length - 1;
}

enum class KeyStyle { ThreeNode, HeadReading, HeadNext };

static constexpr char kEmptyNodeString[] = "()";

static std::string combineReadingValue(const std::string& reading,
                                       const std::string& value) {
  return std::string("(") + reading + "," + value + ")";
}

static bool isPunctuation(
    const Formosa::Gramambular2::ReadingGrid::NodePtr& node) {
  const std::string& reading = node->reading();
  return !reading.empty() && reading[0] == '_';
}

static std::string threeNodeKey(
    const Formosa::Gramambular2::ReadingGrid::WalkResult& walk,
    size_t cursor) {
  auto head = walk.findNodeAt(cursor);
  auto end = walk.nodes.begin();
  if (head == walk.nodes.cend() || (*head)->unigrams().empty()) {
    return "";
  }
  std::string headStr = combineReadingValue((*head)->reading(),
                                            (*head)->unigrams()[0].value());
  std::string prevStr;
  bool prevIsPunctuation = false;
  if (head != end) {
    --head;
    prevIsPunctuation = isPunctuation(*head);
    if (prevIsPunctuation) {
      prevStr = kEmptyNodeString;
    } else {
      prevStr = combineReadingValue((*head)->reading(),
                                    (*head)->currentUnigram().value());
    }
  } else {
    prevStr = kEmptyNodeString;
  }
  std::string anteriorStr;
  if (head != end && !prevIsPunctuation) {
    --head;
    if (isPunctuation(*head)) {
      anteriorStr = kEmptyNodeString;
    } else {
      anteriorStr = combineReadingValue((*head)->reading(),
                                        (*head)->currentUnigram().value());
    }
  } else {
    anteriorStr = kEmptyNodeString;
  }
  return anteriorStr + "-" + prevStr + "-" + headStr;
}

static std::string keyFromHead(
    std::vector<Formosa::Gramambular2::ReadingGrid::NodePtr>::const_iterator
        head,
    const Formosa::Gramambular2::ReadingGrid::WalkResult& walk,
    KeyStyle style) {
  if (head == walk.nodes.cend() || (*head)->unigrams().empty()) {
    return "";
  }
  const std::string headStr = combineReadingValue(
      (*head)->reading(), (*head)->unigrams()[0].value());
  if (style == KeyStyle::HeadReading) {
    return headStr;
  }
  std::string nextReading = kEmptyNodeString;
  auto next = head;
  ++next;
  if (next != walk.nodes.cend()) {
    nextReading = (*next)->reading();
  }
  return nextReading + "-" + headStr;
}

static std::string experimentalKey(
    const Formosa::Gramambular2::ReadingGrid::WalkResult& walk, size_t cursor,
    KeyStyle style) {
  if (style == KeyStyle::ThreeNode) {
    return threeNodeKey(walk, cursor);
  }
  return keyFromHead(walk.findNodeAt(cursor), walk, style);
}

static std::vector<std::string> splitUtf8(const std::string& s) {
  std::vector<std::string> chars;
  for (size_t i = 0; i < s.size();) {
    unsigned char c = static_cast<unsigned char>(s[i]);
    size_t len = 1;
    if ((c & 0x80) == 0) {
      len = 1;
    } else if ((c & 0xE0) == 0xC0) {
      len = 2;
    } else if ((c & 0xF0) == 0xE0) {
      len = 3;
    } else if ((c & 0xF8) == 0xF0) {
      len = 4;
    }
    if (i + len > s.size()) {
      break;
    }
    chars.push_back(s.substr(i, len));
    i += len;
  }
  return chars;
}

static std::vector<std::string> charsByReading(
    const Formosa::Gramambular2::ReadingGrid::WalkResult& walk) {
  std::vector<std::string> out;
  for (const auto& node : walk.nodes) {
    const auto chars = splitUtf8(node->value());
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

static std::string topOneReadingValue(
    Formosa::Gramambular2::ReadingGrid* grid, size_t loc) {
  auto candidates = grid->candidatesAt(loc);
  for (const auto& candidate : candidates) {
    if (readingSpan(candidate.reading) == 1 && !candidate.value.empty()) {
      return candidate.value;
    }
  }
  return "";
}

static std::string syllableKey(Formosa::Gramambular2::ReadingGrid* grid,
                               size_t loc, KeyStyle style) {
  const auto& readings = grid->readings();
  if (loc >= readings.size()) {
    return "";
  }
  const std::string top = topOneReadingValue(grid, loc);
  if (top.empty()) {
    return "";
  }
  const std::string head = combineReadingValue(readings[loc], top);
  if (style == KeyStyle::HeadReading) {
    return head;
  }
  const std::string next = loc + 1 < readings.size() ? readings[loc + 1]
                                                     : std::string(kEmptyNodeString);
  return next + "-" + head;
}

static void applySuggestions(
    Formosa::Gramambular2::ReadingGrid* grid,
    McBopomofo::UserOverrideModel* uom, KeyStyle style, bool resuggest,
    double timestamp) {
  if (uom == nullptr) {
    return;
  }
  std::vector<size_t> cursors;
  if (resuggest) {
    for (size_t i = 0; i < grid->length(); ++i) {
      cursors.push_back(i);
    }
  } else if (grid->length() > 0) {
    cursors.push_back(actualCursorAtEnd(grid->length()));
  }
  for (size_t cursor : cursors) {
    auto walk = grid->walk();
    McBopomofo::UserOverrideModel::Suggestion suggestion;
    if (style == KeyStyle::ThreeNode) {
      suggestion = uom->suggest(walk, cursor, timestamp);
      if (debugReplay()) {
        fprintf(stderr, "suggest three_node cursor=%zu cand='%s'\n", cursor,
                suggestion.candidate.c_str());
      }
    } else {
      const std::string key = syllableKey(grid, cursor, style);
      if (key.empty()) {
        continue;
      }
      suggestion = uom->suggest(key, timestamp);
      if (debugReplay()) {
        fprintf(stderr, "suggest key='%s' cursor=%zu cand='%s'\n", key.c_str(),
                cursor, suggestion.candidate.c_str());
      }
    }
    if (suggestion.empty()) {
      continue;
    }
    const auto type =
        suggestion.forceHighScoreOverride
            ? Formosa::Gramambular2::ReadingGrid::Node::OverrideType::
                  kOverrideValueWithHighScore
            : Formosa::Gramambular2::ReadingGrid::Node::OverrideType::
                  kOverrideValueWithScoreFromTopUnigram;
    const bool overridden =
        grid->overrideCandidate(cursor, suggestion.candidate, type);
    if (debugReplay()) {
      fprintf(stderr, "override cursor=%zu cand='%s' ok=%d walk='%s'\n", cursor,
              suggestion.candidate.c_str(), overridden ? 1 : 0,
              joinWalk(grid->walk()).c_str());
    }
  }
}

struct ReplayRow {
  std::string id;
  std::vector<std::string> observeReadings;
  std::string committed;
  std::vector<std::string> probeReadings;
  std::string expected;
  bool sameKeyExpected = false;
  int prefixAfter = -1;
  std::string prefixExpected;
};

static ReplayRow parseRow(const std::string& line) {
  ReplayRow row;
  row.id = extractJSONString(line, "id");
  const std::string observe = extractObject(line, "observe");
  const std::string probe = extractObject(line, "probe");
  row.observeReadings = extractJSONStringArray(observe, "readings");
  row.committed = extractJSONString(observe, "committed");
  row.probeReadings = extractJSONStringArray(probe, "readings");
  row.expected = extractJSONString(probe, "expected");
  row.sameKeyExpected = extractJSONBool(line, "same_key_expected", false);
  row.prefixAfter = extractJSONInt(probe, "prefix_after", -1);
  row.prefixExpected = extractJSONString(probe, "prefix_expected");
  return row;
}

static bool insertReadings(
    Formosa::Gramambular2::ReadingGrid* grid,
    const std::vector<std::string>& readings) {
  for (const auto& reading : readings) {
    if (!grid->insertReading(reading)) {
      return false;
    }
  }
  return true;
}

struct CandidateProbe {
  bool expectedInCandidates = false;
  std::string longestMultichar;
};

static CandidateProbe probeCandidates(
    const std::shared_ptr<McBopomofo::McBopomofoLM>& lm,
    const std::vector<std::string>& readings, const std::string& expected) {
  CandidateProbe probe;
  Formosa::Gramambular2::ReadingGrid grid(
      std::make_shared<
          Formosa::Gramambular2::ReadingGrid::ScoreRankedLanguageModel>(lm));
  if (!insertReadings(&grid, readings)) {
    return probe;
  }
  for (size_t loc = 0; loc < grid.length(); ++loc) {
    for (const auto& candidate : grid.candidatesAt(loc)) {
      if (candidate.value == expected) {
        probe.expectedInCandidates = true;
      }
      if (readingSpan(candidate.reading) < 2 || candidate.value.empty()) {
        continue;
      }
      if (expected.find(candidate.value) == std::string::npos) {
        continue;
      }
      if (candidate.value.size() > probe.longestMultichar.size()) {
        probe.longestMultichar = candidate.value;
      }
    }
  }
  return probe;
}

static std::string applyOneshot(
    Formosa::Gramambular2::ReadingGrid* grid,
    McBopomofo::UserOverrideModel* uom, double timestamp) {
  const McBopomofo::OneShotOverride pick =
      McBopomofo::PickOneShotOverride(*grid, uom, timestamp);
  if (pick.empty()) {
    return "";
  }
  const bool ok = grid->overrideCandidate(
      pick.loc, pick.value,
      Formosa::Gramambular2::ReadingGrid::Node::OverrideType::
          kOverrideValueWithHighScore);
  if (!ok) {
    return "";
  }
  if (debugReplay()) {
    fprintf(stderr, "oneshot loc=%zu value='%s' walk='%s'\n", pick.loc,
            pick.value.c_str(), joinWalk(grid->walk()).c_str());
  }
  return pick.value;
}

static std::string convertWithUom(
    const std::shared_ptr<McBopomofo::McBopomofoLM>& lm,
    McBopomofo::UserOverrideModel* uom,
    const std::vector<std::string>& readings, double timestamp, KeyStyle style,
    bool resuggest, int prefixAfter, std::string* prefixOut,
    bool oneshotApply = false, std::string* oneshotValue = nullptr) {
  Formosa::Gramambular2::ReadingGrid grid(
      std::make_shared<
          Formosa::Gramambular2::ReadingGrid::ScoreRankedLanguageModel>(lm));
  for (const auto& reading : readings) {
    if (!grid.insertReading(reading)) {
      return "";
    }
    applySuggestions(&grid, uom, style, resuggest, timestamp);
    if (prefixOut != nullptr && prefixAfter >= 0 &&
        static_cast<int>(grid.length()) == prefixAfter) {
      *prefixOut = joinWalk(grid.walk());
    }
  }
  if (oneshotApply) {
    const std::string offered = applyOneshot(&grid, uom, timestamp);
    if (oneshotValue != nullptr) {
      *oneshotValue = offered;
    }
  }
  return joinWalk(grid.walk());
}

static bool applyCommitted(
    Formosa::Gramambular2::ReadingGrid* grid, const std::string& committed,
    size_t* firstOverrideLoc) {
  *firstOverrideLoc = static_cast<size_t>(-1);
  if (joinWalk(grid->walk()) == committed) {
    return true;
  }
  std::string remaining = committed;
  size_t loc = 0;
  while (loc < grid->length() && !remaining.empty()) {
    auto candidates = grid->candidatesAt(loc);
    const Formosa::Gramambular2::ReadingGrid::Candidate* best = nullptr;
    for (const auto& candidate : candidates) {
      if (candidate.value.empty()) {
        continue;
      }
      if (remaining.compare(0, candidate.value.size(), candidate.value) != 0) {
        continue;
      }
      const size_t span = readingSpan(candidate.reading);
      if (span == 0 || loc + span > grid->length()) {
        continue;
      }
      if (best == nullptr || candidate.value.size() > best->value.size()) {
        best = &candidate;
      }
    }
    if (best == nullptr) {
      return false;
    }
    const size_t span = readingSpan(best->reading);
    auto walk = grid->walk();
    std::string current;
    size_t covered = 0;
    for (const auto& node : walk.nodes) {
      if (covered == loc) {
        current = node->value();
        break;
      }
      covered += node->spanningLength();
      if (covered > loc) {
        current = node->value();
        break;
      }
    }
    if (current != best->value) {
      if (!grid->overrideCandidate(loc, *best)) {
        return false;
      }
      if (*firstOverrideLoc == static_cast<size_t>(-1)) {
        *firstOverrideLoc = loc;
      }
    }
    remaining.erase(0, best->value.size());
    loc += span;
  }
  return remaining.empty();
}

static bool observeCommitted(
    const std::shared_ptr<McBopomofo::McBopomofoLM>& lm,
    McBopomofo::UserOverrideModel* uom,
    const std::vector<std::string>& readings, const std::string& committed,
    double timestamp, KeyStyle style) {
  Formosa::Gramambular2::ReadingGrid grid(
      std::make_shared<
          Formosa::Gramambular2::ReadingGrid::ScoreRankedLanguageModel>(lm));
  if (!insertReadings(&grid, readings)) {
    return false;
  }
  auto before = grid.walk();
  const auto beforeChars = charsByReading(before);
  const std::string beforeText = joinWalk(before);
  size_t firstOverrideLoc = static_cast<size_t>(-1);
  if (!applyCommitted(&grid, committed, &firstOverrideLoc)) {
    return false;
  }
  auto after = grid.walk();
  if (joinWalk(after) != committed) {
    return false;
  }
  if (firstOverrideLoc == static_cast<size_t>(-1)) {
    return true;
  }
  if (style == KeyStyle::ThreeNode) {
    if (debugReplay()) {
      fprintf(stderr, "observe three_node loc=%zu before='%s' after='%s'\n",
              firstOverrideLoc, beforeText.c_str(), joinWalk(after).c_str());
    }
    uom->observe(before, after, firstOverrideLoc, timestamp);
    return true;
  }
  const auto committedChars = splitUtf8(committed);
  size_t diff = static_cast<size_t>(-1);
  const size_t n =
      beforeChars.size() < committedChars.size() ? beforeChars.size()
                                                 : committedChars.size();
  for (size_t i = 0; i < n; ++i) {
    if (beforeChars[i] != committedChars[i]) {
      diff = i;
      break;
    }
  }
  if (diff == static_cast<size_t>(-1) || diff >= readings.size()) {
    return true;
  }
  auto unigrams = lm->getUnigrams(readings[diff]);
  if (unigrams.empty()) {
    return false;
  }
  const std::string head =
      combineReadingValue(readings[diff], unigrams[0].value());
  std::string key = head;
  if (style == KeyStyle::HeadNext) {
    const std::string next = diff + 1 < readings.size()
                                 ? readings[diff + 1]
                                 : std::string(kEmptyNodeString);
    key = next + "-" + head;
  }
  size_t past = 0;
  auto afterNode = after.findNodeAt(diff, &past);
  if (afterNode == after.nodes.cend()) {
    return false;
  }
  const size_t nodeStart = past - (*afterNode)->spanningLength();
  const bool phraseAtDiff = nodeStart == diff &&
                            (*afterNode)->spanningLength() > 1;
  const std::string candidate = phraseAtDiff
                                    ? (*afterNode)->currentUnigram().value()
                                    : committedChars[diff];
  if (debugReplay()) {
    fprintf(stderr,
            "observe key='%s' candidate='%s' diff=%zu before='%s' after='%s' "
            "force_high=%d\n",
            key.c_str(), candidate.c_str(), diff, beforeText.c_str(),
            joinWalk(after).c_str(), phraseAtDiff ? 1 : 0);
  }
  uom->observe(key, candidate, timestamp, phraseAtDiff);
  return true;
}

}  // namespace

int main(int argc, char* argv[]) {
  if (argc < 3) {
    fprintf(stderr,
            "Usage: %s <data.txt> <fixture.jsonl> "
            "[--key=three_node|head_reading|head_next] "
            "[--memory=isolated|shared] "
            "[--persist=path] [--candidates] [--oneshot] "
            "[--halflife=<seconds>] [--suggest-delay=<seconds>]\n",
            argv[0]);
    return 1;
  }
  if (!fs::exists(argv[1])) {
    fprintf(stderr, "FATAL: data.txt not found at %s\n", argv[1]);
    return 1;
  }
  if (!fs::exists(argv[2])) {
    fprintf(stderr, "FATAL: fixture not found at %s\n", argv[2]);
    return 1;
  }

  KeyStyle style = KeyStyle::ThreeNode;
  bool shared = false;
  std::string persistPath;
  bool dumpCandidates = false;
  bool oneshot = false;
  double halfLife = kHalfLife;
  double suggestDelay = 0.0;
  for (int i = 3; i < argc; ++i) {
    if (std::strncmp(argv[i], "--key=", 6) == 0) {
      const char* value = argv[i] + 6;
      if (std::strcmp(value, "three_node") == 0) {
        style = KeyStyle::ThreeNode;
      } else if (std::strcmp(value, "head_reading") == 0) {
        style = KeyStyle::HeadReading;
      } else if (std::strcmp(value, "head_next") == 0) {
        style = KeyStyle::HeadNext;
      } else {
        fprintf(stderr, "FATAL: unknown --key=%s\n", value);
        return 1;
      }
    } else if (std::strncmp(argv[i], "--memory=", 9) == 0) {
      const char* value = argv[i] + 9;
      if (std::strcmp(value, "isolated") == 0) {
        shared = false;
      } else if (std::strcmp(value, "shared") == 0) {
        shared = true;
      } else {
        fprintf(stderr, "FATAL: unknown --memory=%s\n", value);
        return 1;
      }
    } else if (std::strncmp(argv[i], "--persist=", 10) == 0) {
      persistPath = argv[i] + 10;
      if (persistPath.empty()) {
        fprintf(stderr, "FATAL: --persist= requires a path\n");
        return 1;
      }
    } else if (std::strcmp(argv[i], "--candidates") == 0) {
      dumpCandidates = true;
    } else if (std::strcmp(argv[i], "--oneshot") == 0) {
      oneshot = true;
    } else if (std::strncmp(argv[i], "--halflife=", 11) == 0) {
      halfLife = std::atof(argv[i] + 11);
      if (!(halfLife > 0.0)) {
        fprintf(stderr, "FATAL: --halflife= must be > 0\n");
        return 1;
      }
    } else if (std::strncmp(argv[i], "--suggest-delay=", 16) == 0) {
      suggestDelay = std::atof(argv[i] + 16);
      if (suggestDelay < 0.0) {
        fprintf(stderr, "FATAL: --suggest-delay= must be >= 0\n");
        return 1;
      }
    } else {
      fprintf(stderr, "FATAL: unknown argument %s\n", argv[i]);
      return 1;
    }
  }
  const bool resuggest = style == KeyStyle::HeadNext;
  const double suggestNow = kNow + suggestDelay;

  auto lm = std::make_shared<McBopomofo::McBopomofoLM>();
  lm->loadLanguageModel(argv[1]);
  if (!lm->isDataModelLoaded()) {
    fprintf(stderr, "FATAL: failed to load language model\n");
    return 1;
  }

  std::ifstream in(argv[2]);
  if (!in) {
    fprintf(stderr, "FATAL: cannot open fixture\n");
    return 1;
  }

  int total = 0;
  int sameKeyRows = 0;
  int sameKeyHits = 0;
  int sameKeyBaselineExact = 0;
  int sameKeyAfterExact = 0;
  int transferRows = 0;
  int transferHits = 0;
  int transferBaselineExact = 0;
  int transferAfterExact = 0;
  int harmful = 0;
  int prefixHarms = 0;
  int restartHits = 0;
  int expectedInCandidates = 0;
  int transferMissesWithMultichar = 0;
  int oneshotOffered = 0;
  int oneshotHits = 0;
  int oneshotTransferHits = 0;
  int oneshotExtra = 0;
  McBopomofo::UserOverrideModel sharedUom(kCapacity, halfLife);

  const char* keyName = "three_node";
  if (style == KeyStyle::HeadReading) {
    keyName = "head_reading";
  } else if (style == KeyStyle::HeadNext) {
    keyName = "head_next";
  }
  const char* memoryName = shared ? "shared" : "isolated";

  std::string line;
  while (std::getline(in, line)) {
    if (line.empty()) {
      continue;
    }
    ReplayRow row = parseRow(line);
    if (row.id.empty() || row.observeReadings.empty() ||
        row.probeReadings.empty()) {
      fprintf(stderr, "FATAL: bad row: %s\n", line.c_str());
      return 1;
    }
    if (debugReplay()) {
      fprintf(stderr, "\n== row %s ==\n", row.id.c_str());
    }

    std::string baselinePrefix;
    const std::string baseline =
        convertWithUom(lm, nullptr, row.probeReadings, kNow, style, resuggest,
                       row.prefixAfter, &baselinePrefix);
    const bool baselineExact = baseline == row.expected;

    McBopomofo::UserOverrideModel isolated(kCapacity, halfLife);
    McBopomofo::UserOverrideModel* uom = shared ? &sharedUom : &isolated;
    const bool observed = observeCommitted(lm, uom, row.observeReadings,
                                           row.committed, kNow, style);
    if (oneshot && style != KeyStyle::HeadNext) {
      observeCommitted(lm, uom, row.observeReadings, row.committed, kNow,
                       KeyStyle::HeadNext);
    }
    if (!persistPath.empty()) {
      if (!uom->save(persistPath)) {
        fprintf(stderr, "FATAL: persist save failed: %s\n",
                persistPath.c_str());
        return 1;
      }
    }
    std::string afterPrefix;
    const std::string after =
        convertWithUom(lm, uom, row.probeReadings, suggestNow, style, resuggest,
                       row.prefixAfter, &afterPrefix);
    const bool afterExact = after == row.expected;
    std::string oneshotValue;
    std::string oneshotOut = after;
    bool oneshotOfferedRow = false;
    bool oneshotExact = false;
    bool oneshotHit = false;
    bool oneshotExtraRow = false;
    if (oneshot) {
      oneshotOut = convertWithUom(lm, uom, row.probeReadings, suggestNow,
                                  KeyStyle::ThreeNode, false, -1, nullptr, true,
                                  &oneshotValue);
      oneshotOfferedRow = !oneshotValue.empty();
      oneshotExact = oneshotOut == row.expected;
      oneshotHit = oneshotExact && !baselineExact;
      oneshotExtraRow = oneshotExact && !afterExact;
    }
    const bool hit = afterExact && !baselineExact;
    const bool harmfulRow = baselineExact && !afterExact;
    const bool prefixHarmful =
        row.prefixAfter >= 0 && !row.prefixExpected.empty() &&
        baselinePrefix == row.prefixExpected &&
        afterPrefix != row.prefixExpected;

    McBopomofo::UserOverrideModel restarted(kCapacity, halfLife);
    if (!persistPath.empty()) {
      if (!restarted.load(persistPath)) {
        fprintf(stderr, "FATAL: persist load failed: %s\n",
                persistPath.c_str());
        return 1;
      }
    }
    const std::string restartOut =
        convertWithUom(lm, &restarted, row.probeReadings, suggestNow, style,
                       resuggest, -1, nullptr);
    const bool restartExact = restartOut == row.expected && !baselineExact;

    ++total;
    if (row.sameKeyExpected) {
      ++sameKeyRows;
      if (baselineExact) {
        ++sameKeyBaselineExact;
      }
      if (afterExact) {
        ++sameKeyAfterExact;
      }
      if (hit) {
        ++sameKeyHits;
      }
    } else {
      ++transferRows;
      if (baselineExact) {
        ++transferBaselineExact;
      }
      if (afterExact) {
        ++transferAfterExact;
      }
      if (hit) {
        ++transferHits;
      }
    }
    if (harmfulRow) {
      ++harmful;
    }
    if (prefixHarmful) {
      ++prefixHarms;
    }
    if (restartExact) {
      ++restartHits;
    }
    if (oneshotOfferedRow) {
      ++oneshotOffered;
    }
    if (oneshotHit) {
      ++oneshotHits;
      if (!row.sameKeyExpected) {
        ++oneshotTransferHits;
      }
    }
    if (oneshotExtraRow) {
      ++oneshotExtra;
    }
    CandidateProbe cand;
    if (dumpCandidates) {
      cand = probeCandidates(lm, row.probeReadings, row.expected);
      if (cand.expectedInCandidates) {
        ++expectedInCandidates;
      }
      if (!row.sameKeyExpected && !afterExact &&
          !cand.longestMultichar.empty()) {
        ++transferMissesWithMultichar;
      }
    }

    printf(
        "{\"id\":\"%s\",\"observed\":%s,\"baseline_exact\":%s,"
        "\"after_exact\":%s,\"hit\":%s,\"harmful\":%s,"
        "\"prefix_harmful\":%s,\"same_key_expected\":%s,\"restart_exact\":%s,"
        "\"baseline\":\"%s\",\"after\":\"%s\","
        "\"prefix_baseline\":\"%s\",\"prefix_after\":\"%s\"",
        jsonEscape(row.id).c_str(), observed ? "true" : "false",
        baselineExact ? "true" : "false", afterExact ? "true" : "false",
        hit ? "true" : "false", harmfulRow ? "true" : "false",
        prefixHarmful ? "true" : "false",
        row.sameKeyExpected ? "true" : "false",
        restartExact ? "true" : "false", jsonEscape(baseline).c_str(),
        jsonEscape(after).c_str(), jsonEscape(baselinePrefix).c_str(),
        jsonEscape(afterPrefix).c_str());
    if (dumpCandidates) {
      printf(
          ",\"expected_in_candidates\":%s,\"longest_multichar\":\"%s\"",
          cand.expectedInCandidates ? "true" : "false",
          jsonEscape(cand.longestMultichar).c_str());
    }
    if (oneshot) {
      printf(
          ",\"oneshot_offered\":%s,\"oneshot_value\":\"%s\","
          "\"oneshot_after\":\"%s\",\"oneshot_exact\":%s,"
          "\"oneshot_hit\":%s,\"oneshot_extra\":%s",
          oneshotOfferedRow ? "true" : "false",
          jsonEscape(oneshotValue).c_str(), jsonEscape(oneshotOut).c_str(),
          oneshotExact ? "true" : "false", oneshotHit ? "true" : "false",
          oneshotExtraRow ? "true" : "false");
    }
    printf("}\n");
  }

  printf(
      "{\"total_rows\":%d,\"same_key_rows\":%d,\"same_key_hits\":%d,"
      "\"same_key_baseline_exact\":%d,\"same_key_after_exact\":%d,"
      "\"transfer_rows\":%d,\"transfer_hits\":%d,"
      "\"transfer_baseline_exact\":%d,\"transfer_after_exact\":%d,"
      "\"harmful_overrides\":%d,\"prefix_harms\":%d,\"restart_hits\":%d,"
      "\"key\":\"%s\",\"memory\":\"%s\",\"persist\":%s,"
      "\"halflife\":%.17g,\"suggest_delay\":%.17g",
      total, sameKeyRows, sameKeyHits, sameKeyBaselineExact, sameKeyAfterExact,
      transferRows, transferHits, transferBaselineExact, transferAfterExact,
      harmful, prefixHarms, restartHits, keyName, memoryName,
      persistPath.empty() ? "false" : "true", halfLife, suggestDelay);
  if (dumpCandidates) {
    printf(
        ",\"expected_in_candidates\":%d,"
        "\"transfer_misses_with_multichar\":%d",
        expectedInCandidates, transferMissesWithMultichar);
  }
  if (oneshot) {
    printf(
        ",\"oneshot\":true,\"oneshot_offered\":%d,\"oneshot_hits\":%d,"
        "\"oneshot_transfer_hits\":%d,\"oneshot_extra\":%d",
        oneshotOffered, oneshotHits, oneshotTransferHits, oneshotExtra);
  }
  printf("}\n");
  return 0;
}
