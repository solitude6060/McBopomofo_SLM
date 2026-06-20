// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (C) 2026 McBopomofo contributors

#pragma once

#include <fcitx/addonfactory.h>
#include <fcitx/inputmethodengine.h>
#include <fcitx-config/configuration.h>
#include <fcitx/candidatelist.h>
#include <fcitx/text.h>
#include <fcitx/inputpanel.h>
#include <fcitx/event.h>
#include <fcitx/inputcontext.h>

#include "Engine/McBopomofoLM.h"
#include "Engine/gramambular2/reading_grid.h"
#include "Engine/ContextualScorer.h"
#include "Engine/DeterministicContextualScorer.h"
#include "Engine/Mandarin/Mandarin.h"

namespace fcitx {
class Instance;
}

namespace McBopomofo {

FCITX_CONFIGURATION(McBopomofoEngineConfig,
    fcitx::Option<std::string> dataModelPath{this, "DataModelPath", "Data model path", "${prefix}/share/fcitx5/mcbopomofo/data.txt"};
    fcitx::Option<bool> contextualRerankerEnabled{this, "ContextualRerankerEnabled", "Contextual reranker", false};
)

struct InputState {
    Formosa::Mandarin::BopomofoReadingBuffer readingBuffer;
    std::unique_ptr<Formosa::Gramambular2::ReadingGrid> grid;
    Formosa::Gramambular2::ReadingGrid::WalkResult latestWalk;
    bool candidatesShowing = false;
    size_t candidateGridCursor = 0;
    int candidateCursorGlobal = -1;

    explicit InputState()
        : readingBuffer(Formosa::Mandarin::BopomofoKeyboardLayout::StandardLayout()) {}
};

class McBopomofoEngine final : public fcitx::InputMethodEngine {
public:
    explicit McBopomofoEngine(fcitx::Instance* instance);
    ~McBopomofoEngine() override = default;

    void keyEvent(const fcitx::InputMethodEntry& entry, fcitx::KeyEvent& event) override;
    void activate(const fcitx::InputMethodEntry& entry, fcitx::InputContextEvent& event) override;
    void deactivate(const fcitx::InputMethodEntry& entry, fcitx::InputContextEvent& event) override;
    void reset(const fcitx::InputMethodEntry& entry, fcitx::InputContextEvent& event) override;

    const fcitx::Configuration* getConfig() const override;
    void setConfig(const fcitx::RawConfig& config) override;

private:
    InputState* ensureState(fcitx::InputContext* ic);
    void commitComposition(fcitx::InputContext* ic, InputState& state);
    void updatePreedit(fcitx::InputContext* ic, InputState& state);
    void updateCandidates(fcitx::InputContext* ic, InputState& state);
    void applyContextualReranker(InputState& state);
    bool loadLanguageModel();

    fcitx::Instance* instance_;
    McBopomofoEngineConfig config_;
    std::shared_ptr<McBopomofoLM> lm_;
    std::unique_ptr<DeterministicContextualScorer> scorer_;
    bool lmLoaded_ = false;
    std::string dataPath_;
};

// Factory class — FCITX_ADDON_FACTORY uses static storage so it must be
// default-constructible (no arguments).
class McBopomofoEngineFactory : public fcitx::AddonFactory {
public:
    fcitx::AddonInstance* create(fcitx::AddonManager* manager) override;
};

}

FCITX_ADDON_FACTORY(McBopomofo::McBopomofoEngineFactory)
