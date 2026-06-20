// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (C) 2026 McBopomofo contributors

#include "McBopomofoEngine.h"

#include <algorithm>
#include <cctype>
#include <filesystem>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include <fcitx/inputcontext.h>
#include <fcitx/addonmanager.h>
#include <fcitx/instance.h>

namespace fs = std::filesystem;

namespace {

using StateMap =
    std::unordered_map<const fcitx::InputContext*, McBopomofo::InputState>;

StateMap& globalStateMap() {
  static StateMap map;
  return map;
}

inline char normalizeBopomofoKey(int sym) {
  char c = static_cast<char>(sym);
  if (c >= 'A' && c <= 'Z') {
    return c - 'A' + 'a';
  }
  return c;
}

class SelectCandidateWord final : public fcitx::CandidateWord {
 public:
  using SelectCallback = std::function<void()>;

  SelectCandidateWord(fcitx::Text text,
                      size_t gridCursor,
                      Formosa::Gramambular2::ReadingGrid::Candidate candidate,
                      Formosa::Gramambular2::ReadingGrid* grid,
                      SelectCallback afterSelect)
      : fcitx::CandidateWord(std::move(text)),
        gridCursor_(gridCursor),
        candidate_(std::move(candidate)),
        grid_(grid),
        afterSelect_(std::move(afterSelect)) {}

  void select(fcitx::InputContext* /*inputContext*/) const override {
    grid_->overrideCandidate(
        gridCursor_, candidate_,
        Formosa::Gramambular2::ReadingGrid::Node::OverrideType::
            kOverrideValueWithHighScore);
    if (afterSelect_) {
      afterSelect_();
    }
  }

 private:
  size_t gridCursor_;
  Formosa::Gramambular2::ReadingGrid::Candidate candidate_;
  Formosa::Gramambular2::ReadingGrid* grid_;
  SelectCallback afterSelect_;
};

void applyReranker(
    const std::vector<std::string>& readings,
    Formosa::Gramambular2::ReadingGrid& grid,
    Formosa::Gramambular2::ReadingGrid::WalkResult* walkResult,
    McBopomofo::DeterministicContextualScorer& scorer) {
  if (readings.empty() || walkResult->nodes.empty()) {
    return;
  }

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
        if (a.start != b.start) return a.start < b.start;
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

}  // namespace

namespace McBopomofo {

// -----------------------------------------------------------------------
// Construction / initialization
// -----------------------------------------------------------------------

McBopomofoEngine::McBopomofoEngine(fcitx::Instance* instance)
    : instance_(instance) {
  dataPath_ = config_.dataModelPath.value();
  if (dataPath_.find("${prefix}") != std::string::npos) {
    auto pos = dataPath_.find("${prefix}");
    dataPath_.replace(pos, 9, FCITX5_INSTALL_PREFIX);
  }
}

bool McBopomofoEngine::loadLanguageModel() {
  if (lmLoaded_) {
    return true;
  }
  if (!fs::exists(dataPath_)) {
    return false;
  }
  auto lm = std::make_shared<McBopomofoLM>();
  lm->loadLanguageModel(dataPath_.c_str());
  if (!lm->isDataModelLoaded()) {
    return false;
  }
  lm_ = std::move(lm);
  scorer_ = std::make_unique<DeterministicContextualScorer>();
  lmLoaded_ = true;
  return true;
}

// -----------------------------------------------------------------------
// Per-context state
// -----------------------------------------------------------------------

InputState* McBopomofoEngine::ensureState(fcitx::InputContext* ic) {
  if (!lmLoaded_ || !lm_) {
    return nullptr;
  }
  auto& map = globalStateMap();
  auto& state = map[ic];
  if (!state.grid) {
    state.grid = std::make_unique<Formosa::Gramambular2::ReadingGrid>(
        std::make_shared<
            Formosa::Gramambular2::ReadingGrid::ScoreRankedLanguageModel>(lm_));
    state.readingBuffer.setKeyboardLayout(
        Formosa::Mandarin::BopomofoKeyboardLayout::StandardLayout());
  }
  return &state;
}

// -----------------------------------------------------------------------
// Fcitx5 lifecycle
// -----------------------------------------------------------------------

void McBopomofoEngine::activate(const fcitx::InputMethodEntry& /*entry*/,
                                 fcitx::InputContextEvent& event) {
  if (!lmLoaded_) {
    loadLanguageModel();
  }
  if (!lmLoaded_) {
    return;
  }
  auto* ic = event.inputContext();
  auto* state = ensureState(ic);
  if (!state) {
    return;
  }
  state->readingBuffer.clear();
  state->candidatesShowing = false;
  state->candidateGridCursor = 0;
  state->candidateCursorGlobal = -1;
  if (state->grid) {
    state->grid->clear();
  }
}

void McBopomofoEngine::deactivate(const fcitx::InputMethodEntry& entry,
                                   fcitx::InputContextEvent& event) {
  reset(entry, event);
  globalStateMap().erase(event.inputContext());
}

void McBopomofoEngine::reset(const fcitx::InputMethodEntry& /*entry*/,
                              fcitx::InputContextEvent& event) {
  auto* ic = event.inputContext();
  auto* state = ensureState(ic);
  if (!state) {
    ic->inputPanel().reset();
    ic->updatePreedit();
    return;
  }
  state->readingBuffer.clear();
  state->candidatesShowing = false;
  state->candidateGridCursor = 0;
  state->candidateCursorGlobal = -1;
  if (state->grid) {
    state->grid->clear();
  }
  ic->inputPanel().reset();
  ic->updatePreedit();
}

// -----------------------------------------------------------------------
// Key event handling
// -----------------------------------------------------------------------

void McBopomofoEngine::keyEvent(const fcitx::InputMethodEntry& /*entry*/,
                                 fcitx::KeyEvent& event) {
  if (event.isRelease()) {
    return;
  }

  auto* ic = event.inputContext();
  if (!ic) {
    return;
  }

  if (!lmLoaded_ && !loadLanguageModel()) {
    return;
  }

  auto* state = ensureState(ic);
  if (!state) {
    return;
  }
  auto& buf = state->readingBuffer;
  auto& grid = state->grid;
  auto key = event.key();

  // --- Escape ---
  if (key.check(FcitxKey_Escape)) {
    if (!buf.isEmpty()) {
      buf.clear();
      updatePreedit(ic, *state);
      event.filterAndAccept();
      return;
    }
    if (!state->candidatesShowing && grid->length() > 0) {
      grid->clear();
      state->candidatesShowing = false;
      updatePreedit(ic, *state);
      event.filterAndAccept();
      return;
    }
    if (state->candidatesShowing) {
      state->candidatesShowing = false;
      ic->inputPanel().reset();
      ic->updatePreedit();
      event.filterAndAccept();
      return;
    }
    return;
  }

  // --- Backspace ---
  if (key.check(FcitxKey_BackSpace)) {
    if (state->candidatesShowing) {
      state->candidatesShowing = false;
      updateCandidates(ic, *state);
      updatePreedit(ic, *state);
      event.filterAndAccept();
      return;
    }
    if (!buf.isEmpty()) {
      buf.backspace();
      updatePreedit(ic, *state);
      event.filterAndAccept();
      return;
    }
    if (grid->length() > 0 && grid->deleteReadingBeforeCursor()) {
      state->latestWalk = grid->walk();
      if (config_.contextualRerankerEnabled.value() && scorer_) {
        applyContextualReranker(*state);
      }
      updatePreedit(ic, *state);
      event.filterAndAccept();
      return;
    }
    return;
  }

  // --- Enter ---
  if (key.check(FcitxKey_Return) || key.check(FcitxKey_KP_Enter)) {
    if (state->candidatesShowing) {
      state->candidatesShowing = false;
      ic->inputPanel().reset();
    }
    // If reading buffer is non-empty, Enter composes the syllable first
    // (tone-1: no tone marker). If the reading is valid, insert and commit.
    // If invalid, consume the key and update preedit (M1 fix).
    if (!buf.isEmpty()) {
      std::string reading = buf.syllable().composedString();
      if (!reading.empty() && lm_->hasUnigrams(reading)) {
        grid->insertReading(reading);
        state->latestWalk = grid->walk();
        if (config_.contextualRerankerEnabled.value() && scorer_) {
          applyContextualReranker(*state);
        }
        buf.clear();
        commitComposition(ic, *state);
        event.filterAndAccept();
        return;
      }
      // M1: invalid reading — consume the key and update preedit
      buf.clear();
      updatePreedit(ic, *state);
      event.filterAndAccept();
      return;
    }
    if (grid->length() > 0) {
      commitComposition(ic, *state);
      event.filterAndAccept();
      return;
    }
    return;
  }

  // --- Space ---
  if (key.check(FcitxKey_space)) {
    if (state->candidatesShowing) {
      state->candidatesShowing = false;
      ic->inputPanel().reset();
      ic->updatePreedit();
      event.filterAndAccept();
      return;
    }
    // If reading buffer is non-empty, Space composes the current syllable
    // (tone-1: no tone marker). Mirrors KeyHandler.mm line 504.
    if (!buf.isEmpty()) {
      std::string reading = buf.syllable().composedString();
      if (!reading.empty() && lm_->hasUnigrams(reading)) {
        grid->insertReading(reading);
        state->latestWalk = grid->walk();
        if (config_.contextualRerankerEnabled.value() && scorer_) {
          applyContextualReranker(*state);
        }
      }
      buf.clear();
      state->candidatesShowing = false;
      updatePreedit(ic, *state);
      event.filterAndAccept();
      return;
    }
    if (grid->length() > 0) {
      state->candidateGridCursor = grid->cursor();
      state->candidatesShowing = true;
      state->candidateCursorGlobal = -1;
      updateCandidates(ic, *state);
      event.filterAndAccept();
      return;
    }
    return;
  }

  // --- Left arrow ---
  if (key.check(FcitxKey_Left)) {
    if (state->candidatesShowing) {
      state->candidatesShowing = false;
      ic->inputPanel().reset();
    }
    if (grid->cursor() > 0) {
      grid->setCursor(grid->cursor() - 1);
      updatePreedit(ic, *state);
    }
    event.filterAndAccept();
    return;
  }

  // --- Right arrow ---
  if (key.check(FcitxKey_Right)) {
    if (state->candidatesShowing) {
      state->candidatesShowing = false;
      ic->inputPanel().reset();
    }
    if (grid->cursor() < grid->length()) {
      grid->setCursor(grid->cursor() + 1);
      updatePreedit(ic, *state);
    }
    event.filterAndAccept();
    return;
  }

  // --- Number keys 1-9 for candidate selection ---
  if (state->candidatesShowing) {
    auto sym = key.sym();
    if (sym >= FcitxKey_1 && sym <= FcitxKey_9) {
      int idx = static_cast<int>(sym - FcitxKey_1);
      auto candidates = grid->candidatesAt(state->candidateGridCursor);
      if (idx >= 0 && idx < static_cast<int>(candidates.size())) {
        const auto& cand = candidates[static_cast<size_t>(idx)];
        grid->overrideCandidate(
            state->candidateGridCursor,
            Formosa::Gramambular2::ReadingGrid::Candidate(cand.reading,
                                                           cand.value),
            Formosa::Gramambular2::ReadingGrid::Node::OverrideType::
                kOverrideValueWithHighScore);
        state->latestWalk = grid->walk();
        if (config_.contextualRerankerEnabled.value() && scorer_) {
          applyContextualReranker(*state);
        }
        state->candidatesShowing = false;
        updatePreedit(ic, *state);
      }
      event.filterAndAccept();
      return;
    }
  }

  // --- Bopomofo key handling ---
  auto sym = event.key().sym();

  if (sym >= 0x20 && sym <= 0x7e) {
    char c = normalizeBopomofoKey(static_cast<int>(sym));

    if (buf.isValidKey(c)) {
      buf.combineKey(c);

      if (buf.syllable().hasToneMarker() && !buf.hasToneMarkerOnly()) {
        std::string reading = buf.syllable().composedString();
        if (!reading.empty()) {
          grid->insertReading(reading);
          state->latestWalk = grid->walk();
          if (config_.contextualRerankerEnabled.value() && scorer_) {
            applyContextualReranker(*state);
          }
        }
        buf.clear();
        state->candidatesShowing = false;
      }

      updatePreedit(ic, *state);
      event.filterAndAccept();
      return;
    }
  }

}

// -----------------------------------------------------------------------
// Commit / preedit / candidates
// -----------------------------------------------------------------------

void McBopomofoEngine::commitComposition(fcitx::InputContext* ic,
                                          InputState& state) {
  if (state.grid->length() == 0) {
    return;
  }

  std::string committed;
  auto parts = state.latestWalk.valuesAsStrings();
  for (const auto& p : parts) {
    committed += p;
  }

  ic->commitString(committed);
  state.grid->clear();
  state.candidatesShowing = false;
  state.candidateGridCursor = 0;
  state.candidateCursorGlobal = -1;
  state.readingBuffer.clear();
  state.latestWalk = {};
  ic->inputPanel().reset();
  ic->updatePreedit();
}

void McBopomofoEngine::updatePreedit(fcitx::InputContext* ic,
                                      InputState& state) {
  auto& grid = state.grid;
  auto& buf = state.readingBuffer;

  if (grid->length() == 0 && buf.isEmpty()) {
    ic->inputPanel().reset();
    ic->updatePreedit();
    return;
  }

  size_t gridCursor = grid->cursor();
  size_t readingPos = 0;
  size_t bytePos = 0;

  fcitx::Text preedit;
  for (const auto& node : state.latestWalk.nodes) {
    std::string value = node->value();
    if (readingPos + node->spanningLength() <= gridCursor) {
      bytePos += value.size();
      readingPos += node->spanningLength();
    } else if (readingPos < gridCursor) {
      bytePos += std::min((gridCursor - readingPos) * 3, value.size());
      readingPos = gridCursor;
    }
    preedit.append(value);
  }

  if (!buf.isEmpty()) {
    std::string pending = buf.composedString();
    preedit.append(pending);
  }

  preedit.setCursor(static_cast<int>(bytePos));
  ic->inputPanel().setPreedit(preedit);
  ic->updatePreedit();
}

void McBopomofoEngine::updateCandidates(fcitx::InputContext* ic,
                                         InputState& state) {
  if (!state.candidatesShowing) {
    ic->inputPanel().setCandidateList(nullptr);
    return;
  }

  auto candidates = state.grid->candidatesAt(state.candidateGridCursor);
  if (candidates.empty()) {
    state.candidatesShowing = false;
    ic->inputPanel().setCandidateList(nullptr);
    return;
  }

  auto candidateList = std::make_unique<fcitx::CommonCandidateList>();
  candidateList->setPageSize(9);
  candidateList->setLayoutHint(fcitx::CandidateLayoutHint::Vertical);

  for (const auto& cand : candidates) {
    auto afterSelect = [this, ic]() {
      auto* s = ensureState(ic);
      if (!s || !s->grid) {
        return;
      }
      s->latestWalk = s->grid->walk();
      if (config_.contextualRerankerEnabled.value() && scorer_) {
        applyContextualReranker(*s);
      }
      s->candidatesShowing = false;
      updatePreedit(ic, *s);
    };
    auto word = std::make_unique<SelectCandidateWord>(
        fcitx::Text(cand.value), state.candidateGridCursor,
        Formosa::Gramambular2::ReadingGrid::Candidate(cand.reading, cand.value),
        state.grid.get(), std::move(afterSelect));
    candidateList->append(std::move(word));
  }

  ic->inputPanel().setCandidateList(std::move(candidateList));
}

// -----------------------------------------------------------------------
// Contextual reranker
// -----------------------------------------------------------------------

void McBopomofoEngine::applyContextualReranker(InputState& state) {
  if (!scorer_ || state.grid->length() == 0) {
    return;
  }

  ::applyReranker(state.grid->readings(), *state.grid, &state.latestWalk,
                  *scorer_);
}

// -----------------------------------------------------------------------
// Configuration
// -----------------------------------------------------------------------

const fcitx::Configuration* McBopomofoEngine::getConfig() const {
  return &config_;
}

void McBopomofoEngine::setConfig(const fcitx::RawConfig& config) {
  config_.load(config, true);
  std::string newPath = config_.dataModelPath.value();
  if (newPath.find("${prefix}") != std::string::npos) {
    auto pos = newPath.find("${prefix}");
    newPath.replace(pos, 9, FCITX5_INSTALL_PREFIX);
  }
  if (newPath != dataPath_) {
    dataPath_ = newPath;
    lmLoaded_ = false;
    lm_.reset();
    scorer_.reset();
    globalStateMap().clear();
  }
}

// -----------------------------------------------------------------------
// Factory
// -----------------------------------------------------------------------

fcitx::AddonInstance* McBopomofoEngineFactory::create(
    fcitx::AddonManager* manager) {
  return new McBopomofoEngine(manager->instance());
}

}  // namespace McBopomofo
