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

#include "Engine/DeterministicContextualScorer.h"

#include <algorithm>
#include <initializer_list>

namespace McBopomofo {

namespace {

bool contains(const std::string& haystack, const std::string& needle) {
  return !needle.empty() && haystack.find(needle) != std::string::npos;
}

bool isAnyOf(const std::string& value, std::initializer_list<const char*> list) {
  for (const char* item : list) {
    if (value == item) {
      return true;
    }
  }
  return false;
}

std::vector<std::string> splitUTF8Codepoints(const std::string& s) {
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

}  // namespace

DeterministicContextualScorer::DeterministicContextualScorer() {
  ruleEnabled_["zai-zai"] = true;
  ruleEnabled_["de-de"] = true;
  ruleEnabled_["shi-shi"] = true;
  ruleEnabled_["phase1-homophone"] = true;
  ruleEnabled_["phase1-bigram"] = true;
  ruleEnabled_["phase1-tech-term"] = true;
}

std::vector<double> DeterministicContextualScorer::scoreDeltas(
    const ContextualScoreRequest& request) const {
  std::vector<double> deltas(request.candidates.size(), 0.0);
  if (!enabled_) {
    return deltas;
  }

  for (size_t i = 0; i < request.candidates.size(); ++i) {
    std::string ruleName;
    deltas[i] = ruleDelta(request, request.candidates[i], &ruleName);
  }
  return deltas;
}

ScorerOutput DeterministicContextualScorer::suggestCorrections(
    const ContextualScoreRequest& request) const {
  ScorerOutput output;
  std::vector<double> deltas = scoreDeltas(request);
  for (size_t i = 0; i < deltas.size(); ++i) {
    if (deltas[i] <= 0.0) {
      continue;
    }
    const CandidateScoreInput& candidate = request.candidates[i];
    if (candidate.value == baselineValueAt(request, candidate.start)) {
      continue;
    }

    std::string ruleName;
    ruleDelta(request, candidate, &ruleName);
    output.corrections.push_back(
        ScorerCorrection{i, candidate.start, candidate.length,
                         candidate.reading, candidate.value, deltas[i],
                         ruleName});
  }
  std::stable_sort(output.corrections.begin(), output.corrections.end(),
                   [](const ScorerCorrection& a, const ScorerCorrection& b) {
                     if (a.scoreDelta != b.scoreDelta) {
                       return a.scoreDelta > b.scoreDelta;
                     }
                     return a.candidateIndex < b.candidateIndex;
                   });
  return output;
}

void DeterministicContextualScorer::setRuleEnabled(
    const std::string& ruleName, bool enabled) {
  if (ruleName == "all") {
    enabled_ = enabled;
    return;
  }
  ruleEnabled_[ruleName] = enabled;
}

std::string DeterministicContextualScorer::baselineValueAt(
    const ContextualScoreRequest& request, size_t readingIndex) const {
  for (const CandidateScoreInput& item : request.baselinePath) {
    if (readingIndex >= item.start && readingIndex < item.start + item.length) {
      return item.value;
    }
  }
  return "";
}

std::string DeterministicContextualScorer::baselineValueForSpan(
    const ContextualScoreRequest& request, size_t readingIndex,
    size_t length) const {
  const size_t end = readingIndex + std::max<size_t>(length, 1);
  std::string result;
  for (size_t pos = readingIndex; pos < end;) {
    const CandidateScoreInput* covering = nullptr;
    for (const CandidateScoreInput& item : request.baselinePath) {
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
    const size_t overlapEnd = std::min(end, covering->start + covering->length);
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

std::string DeterministicContextualScorer::baselineValueBefore(
    const ContextualScoreRequest& request, size_t readingIndex) const {
  const CandidateScoreInput* best = nullptr;
  for (const CandidateScoreInput& item : request.baselinePath) {
    if (item.start + item.length <= readingIndex &&
        (best == nullptr || item.start > best->start)) {
      best = &item;
    }
  }
  return best == nullptr ? "" : best->value;
}

std::string DeterministicContextualScorer::baselineValueAfter(
    const ContextualScoreRequest& request, size_t readingIndex) const {
  const CandidateScoreInput* best = nullptr;
  for (const CandidateScoreInput& item : request.baselinePath) {
    if (item.start > readingIndex &&
        (best == nullptr || item.start < best->start)) {
      best = &item;
    }
  }
  return best == nullptr ? "" : best->value;
}

std::string DeterministicContextualScorer::baselineValueAfterSpan(
    const ContextualScoreRequest& request, size_t readingIndex,
    size_t length) const {
  return baselineValueAfter(request, readingIndex + length - 1);
}

bool DeterministicContextualScorer::ruleEnabled(
    const std::string& ruleName) const {
  auto it = ruleEnabled_.find(ruleName);
  return it == ruleEnabled_.end() || it->second;
}

double DeterministicContextualScorer::ruleDelta(
    const ContextualScoreRequest& request, const CandidateScoreInput& candidate,
    std::string* ruleName) const {
  const std::string before = baselineValueBefore(request, candidate.start);
  const std::string after = baselineValueAfterSpan(
      request, candidate.start, std::max<size_t>(candidate.length, 1));
  const std::string current = baselineValueAt(request, candidate.start);
  const std::string currentSpan = baselineValueForSpan(
      request, candidate.start, std::max<size_t>(candidate.length, 1));
  const bool hasProtectedEnglish = !request.protectedEnglishSpans.empty();

  if (ruleEnabled("zai-zai") && candidate.value == "再" &&
      (current == "在" || current.empty()) &&
      (contains(after, "說") || contains(after, "出") ||
       contains(after, "決定") || contains(after, "試") ||
       contains(after, "看") || contains(after, "來"))) {
    if (ruleName != nullptr) {
      *ruleName = "zai-zai";
    }
    return 12.0;
  }

  if (ruleEnabled("de-de") && candidate.value == "得" &&
      (current == "的" || current.empty()) &&
      (contains(after, "很") || contains(after, "快") ||
       contains(after, "好") || contains(after, "多") ||
       contains(before, "覺") || contains(before, "過"))) {
    if (ruleName != nullptr) {
      *ruleName = "de-de";
    }
    return 10.0;
  }

  if (ruleEnabled("shi-shi") && candidate.value == "事" &&
      (current == "是" || current.empty()) &&
      (contains(before, "做") || contains(before, "作") ||
       contains(before, "件") || contains(before, "的") ||
       contains(after, "要") || contains(after, "情"))) {
    if (ruleName != nullptr) {
      *ruleName = "shi-shi";
    }
    return 10.0;
  }

  if (ruleEnabled("phase1-homophone")) {
    if (candidate.value == "做" && (current == "作" || current.empty()) &&
        (contains(after, "事") || contains(after, "是"))) {
      if (ruleName != nullptr) {
        *ruleName = "phase1-homophone";
      }
      return 11.0;
    }

    if (candidate.value == "做" && (current == "作" || current.empty()) &&
        (contains(before, "手") || contains(before, "動手")) &&
        (contains(after, "比") || contains(after, "比較"))) {
      if (ruleName != nullptr) {
        *ruleName = "phase2-context";
      }
      return 11.0;
    }

    if (candidate.value == "遍" && (current == "變" || current.empty()) &&
        (contains(before, "一") || contains(before, "讀"))) {
      if (ruleName != nullptr) {
        *ruleName = "phase1-homophone";
      }
      return 11.0;
    }

    if (candidate.value == "累" && (current == "類" || current.empty()) &&
        (contains(before, "非常") || contains(before, "今天"))) {
      if (ruleName != nullptr) {
        *ruleName = "phase1-homophone";
      }
      return 11.0;
    }

    if (candidate.value == "賺" && (current == "政" || current.empty()) &&
        (contains(before, "辛苦") || contains(after, "來"))) {
      if (ruleName != nullptr) {
        *ruleName = "phase1-homophone";
      }
      return 11.0;
    }

    if (candidate.value == "帶" && (current == "代" || current.empty()) &&
        (contains(before, "忘記") || contains(after, "東西"))) {
      if (ruleName != nullptr) {
        *ruleName = "phase1-homophone";
      }
      return 11.0;
    }

    if (hasProtectedEnglish && candidate.value == "和" && current == "合") {
      if (ruleName != nullptr) {
        *ruleName = "phase1-homophone";
      }
      return 9.0;
    }

    if (candidate.value == "十" &&
        (current == "時" || contains(current, "時") || current.empty()) &&
        contains(after, "個")) {
      if (ruleName != nullptr) {
        *ruleName = "phase2-context";
      }
      return 11.0;
    }

    if (candidate.value == "新" && (current == "心" || current.empty()) &&
        contains(before, "很")) {
      if (ruleName != nullptr) {
        *ruleName = "phase2-context";
      }
      return 11.0;
    }

    if (candidate.value == "畫" && (current == "化" || current.empty()) &&
        (contains(before, "圈") || contains(before, "圓圈")) &&
        (contains(after, "得") || contains(after, "的"))) {
      if (ruleName != nullptr) {
        *ruleName = "phase2-context";
      }
      return 11.0;
    }

    if (candidate.value == "圓" && (current == "員" || current.empty()) &&
        contains(before, "很")) {
      if (ruleName != nullptr) {
        *ruleName = "phase2-context";
      }
      return 11.0;
    }

    if (candidate.value == "煙" && (current == "菸" || current.empty()) &&
        contains(before, "吸")) {
      if (ruleName != nullptr) {
        *ruleName = "phase2-context";
      }
      return 11.0;
    }

    if (candidate.value == "吸煙" &&
        (currentSpan == "吸菸" || currentSpan.empty()) &&
        (contains(before, "止") || contains(before, "禁止") ||
         contains(before, "所"))) {
      if (ruleName != nullptr) {
        *ruleName = "phase2-context";
      }
      return 11.0;
    }
  }

  if (ruleEnabled("phase1-bigram")) {
    if (candidate.value == "意思" &&
        (current == "一絲" || current.empty()) &&
        (contains(before, "什麼") || contains(before, "是"))) {
      if (ruleName != nullptr) {
        *ruleName = "phase1-bigram";
      }
      return 14.0;
    }

    if (candidate.value == "主意" &&
        (current == "主一" || current == "主義" || current.empty()) &&
        (contains(before, "這個") || contains(after, "非常"))) {
      if (ruleName != nullptr) {
        *ruleName = "phase1-bigram";
      }
      return 14.0;
    }

    if (candidate.value == "品質" &&
        (current == "頻直" || current.empty()) &&
        (contains(before, "空氣") || contains(after, "持續"))) {
      if (ruleName != nullptr) {
        *ruleName = "phase1-bigram";
      }
      return 14.0;
    }

    if (candidate.value == "進步" &&
        (current == "躍進" || current == "不" || current.empty()) &&
        (contains(before, "躍進") || contains(before, "讀") ||
         contains(before, "越"))) {
      if (ruleName != nullptr) {
        *ruleName = "phase1-bigram";
      }
      return 14.0;
    }

    if (candidate.value == "正事" && current == "正式" &&
        (after.empty() || contains(after, "完成"))) {
      if (ruleName != nullptr) {
        *ruleName = "phase1-bigram";
      }
      return 14.0;
    }

    if (candidate.value == "習慣" &&
        (current == "系慣" || current.empty()) &&
        (after.empty() || contains(after, "養成"))) {
      if (ruleName != nullptr) {
        *ruleName = "phase1-bigram";
      }
      return 14.0;
    }

    if (candidate.value == "繼承" &&
        (current == "計程" || current.empty()) &&
        (after.empty() || contains(after, "了"))) {
      if (ruleName != nullptr) {
        *ruleName = "phase2-bigram";
      }
      return 14.0;
    }

    if (candidate.value == "程式" &&
        (currentSpan == "成是" || currentSpan.empty()) &&
        (after.empty() || contains(after, "很"))) {
      if (ruleName != nullptr) {
        *ruleName = "phase2-bigram";
      }
      return 14.0;
    }
  }

  if (hasProtectedEnglish && ruleEnabled("phase1-tech-term")) {
    if (isAnyOf(candidate.value,
                {"下載", "參考", "接口", "部署", "鏡像", "代理",
                 "專案", "實例", "檔案", "修改", "登錄", "伺服器",
                 "投資", "市場", "設定", "流程", "程式", "解答"})) {
      if (ruleName != nullptr) {
        *ruleName = "phase1-tech-term";
      }
      return 9.0;
    }
  }

  if (ruleEnabled("phase1-bigram") && candidate.value == "越" &&
      (current == "閱讀" || current == "躍進" || current.empty())) {
    if (ruleName != nullptr) {
      *ruleName = "phase1-bigram";
    }
    return 10.0;
  }

  if (ruleEnabled("phase1-bigram") && candidate.value == "讀" &&
      (current == "閱讀" || current.empty()) &&
      (contains(before, "越") || contains(after, "越") ||
       contains(after, "躍進"))) {
    if (ruleName != nullptr) {
      *ruleName = "phase1-bigram";
    }
    return 10.0;
  }

  return 0.0;
}

}  // namespace McBopomofo
