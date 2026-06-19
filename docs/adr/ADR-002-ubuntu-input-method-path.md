# ADR-002: Ubuntu Input Method Integration Path

## Status

Proposed

## Context

The McBopomofo contextual reranker project has completed Phase 0 (baseline evaluation), Phase 1 (deterministic reranker), and Phase 3 (macOS IMK integration steps 1-3). Phase 4 investigates Ubuntu feasibility. While the C++ engine compiles and runs on Linux (verified in Phase 4 benchmarks — 123/123 engine tests pass, evaluator and CLI demo both build and run), there is no existing Linux desktop integration for the McBopomofo engine.

The engine is a pure C++17 library licensed under MIT. It provides:
- `McBopomofoLM` — unigram language model with phrase replacement, user phrases, associated phrases
- `ReadingGrid` — DAG-based text segmentation with candidate management
- `DeterministicContextualScorer` — pattern-matching reranker for homophone disambiguation

The macOS integration uses Input Method Kit (IMK) via an Objective-C++ bridge and Swift state machine. This architecture cannot port to Linux.

**Constraint**: The engine must remain platform-neutral C++17. Integration layers must not introduce license conflicts with the MIT core.

### Project Health Reference Data (2026-06)

| Project | Stars | Last Push | License | Status |
|---------|-------|-----------|---------|--------|
| Fcitx5 | 2,341 | 2026-05 | LGPL-2.1+ | Active, 60 contributors, release 5.1.19 |
| IBus | 972 | 2026-03 | LGPL-2.1+ | Stable but slowing, GNOME-driven |
| librime | 4,287 | 2026-03 | BSD-3-Clause | Active, 70 contributors, 1.16.1 |
| libchewing | 414 | ~2026-04 | LGPL-2.1 | Slowing, migrating to Codeberg |

Ubuntu 24.04 packages: `fcitx5 5.1.7`, `fcitx5-chewing 5.1.1`, `ibus 1.5.29`, `librime1` all available via apt.

## Options Considered

### Option A: Fcitx5 Addon

Fcitx5 is a modern C++ input method framework for Linux/BSD supporting X11 and Wayland. It uses a modular addon system where each input method is a shared library loaded by the fcitx5 process. (2,341 stars, 60 contributors, last push 2026-05, LGPL-2.1+.)

**Architecture reference**: fcitx5-chewing wraps libchewing as a Fcitx5 addon in ~700 lines of C++. The addon implements `fcitx::InputMethodEngine` and handles key events, candidate display, and commit text. The engine (`libchewing`) is a separate shared library. The addon class hierarchy is:

```
ChewingEngine : InputMethodEngine          // keyEvent(), activate(), etc.
ChewingEngineFactory : AddonFactory        // FCITX_ADDON_FACTORY() macro
```

CMake uses `find_package(Fcitx5Core)` and `target_link_libraries(... Fcitx5::Core)`. The addon `.so` installs to `$prefix/lib/fcitx5/` with corresponding `.conf` files in `addon/` and `inputmethod/` subdirectories.

**License boundary strategy**: Build the engine as a **separate shared library** (`libmbengine.so`, MIT) and the addon as a thin LGPL wrapper (`mcbopomofo.so`) that dynamically links to both Fcitx5 (LGPL) and the engine (MIT). This keeps the engine as a "separate work" under LGPL terms — the same model fcitx5-chewing uses with libchewing. See License Boundaries section below.

**Evaluation**:

1. **Integration effort**: 4-8 weeks for a single developer. Need to implement `InputMethodEngine` subclass, key event mapping (Bopomofo keyboard layouts already exist in engine), candidate window integration, and preferences. The fcitx5-chewing codebase (~700 lines of C++) provides a directly applicable reference architecture.

2. **License compatibility**: ✅ MIT engine stays MIT. The addon `.so` that interfaces with Fcitx5's LGPL API must be LGPL-compatible (following fcitx5-chewing's `SPDX-License-Identifier: LGPL-2.1-or-later` precedent). The engine `.so` remains MIT. Two separate binaries, clearly documented.

3. **Installation**: Ubuntu 24.04+ has `fcitx5 5.1.7` and `fcitx5-chewing 5.1.1` in universe. Users install fcitx5, then our `.deb` or PPA. Setup: `im-config` → select fcitx5 → relogin. No environment variables needed.

4. **Wayland support**: ✅ Fcitx5 has first-class Wayland support via `text-input-v3` protocol. KWin Wayland 5.24+ integration uses "Virtual Keyboard" setting. Both X11 and Wayland supported without workarounds.

5. **Maintenance burden**: Low. Fcitx5 is actively maintained (2-3 releases/year, Jenkins CI), its addon API is stable, and the maintainer (wengxt) is responsive.

6. **Scorer integration**: ✅ The scorer operates at the `ReadingGrid` level inside the engine. The Fcitx5 addon calls engine APIs the same way the macOS KeyHandler.mm does — insert readings, walk, apply scorer, update results. No design changes needed.

### Option B: IBus Engine

IBus is an older input method framework that uses a bus daemon and per-engine processes communicating via D-Bus. (972 stars, last push 2026-03, LGPL-2.1+, 140 contributors primarily from Red Hat/GNOME.)

**Architecture reference**: ibus-chewing (~77 stars, GPL-2.0) wraps libchewing as a separate IBus engine process. The engine communicates with IBus via D-Bus, making the license boundary the cleanest of all options — our engine runs as a completely separate process.

**Evaluation**:

1. **Integration effort**: 4-8 weeks. The separate process model avoids shared library linking but requires D-Bus IPC boilerplate and process lifecycle management.

2. **License compatibility**: ✅ Cleanest. Our engine is a separate process. IBus is a separate process. No library linking at all.

3. **Installation**: Available in apt. IBus is the default on GNOME (`ibus 1.5.29` on 24.04). However, non-GNOME desktops require additional configuration.

4. **Wayland support**: ⚠️ Moderate. IBus supports `input-method-v2` (since 1.5.32), but ecosystem momentum favors Fcitx5 for new Wayland IME development. GNOME Wayland works well; KDE Wayland is less polished.

5. **Maintenance burden**: Medium. IBus development has slowed relative to Fcitx5. The chewing project itself is migrating to Codeberg, suggesting waning GitHub activity. ibus-chewing has 3× fewer stars than fcitx5-chewing.

6. **Scorer integration**: ✅ Engine runs independently, scorer is inside the engine.

### Option C: Rime Integration

Rime (librime) is a cross-platform C++ input method engine with a BSD-3-Clause license. It supports customizable schemas and has desktop frontends via Squirrel (macOS), ibus-rime, and fcitx5-rime. (4,287 stars, 70 contributors, last release 1.16.1 2026-01, BSD-3-Clause.)

**Sub-options evaluated**:

- **C1**: Replace Rime's engine with McBopomofo's engine. This would require implementing a new Rime "grammar" component — a deep integration into Rime's `Grammar` system which is architecturally completely different from Gramambular2. This is a rewrite, not a plugin.
- **C2**: Write our scorer as a Rime filter plugin. Rime's pipeline supports pluggable processors, segmentors, translators, and filters. librime-lua (BSD-3-Clause, 460 stars) allows writing filters in Lua, but our `DeterministicContextualScorer` is C++ code tightly coupled to our `LanguageModel` and `ReadingGrid` data structures. Porting it to operate on Rime's candidate pipeline would be essentially rewriting it for a different engine.

**Evaluation**:

1. **Integration effort**: C1: 12+ weeks (reimplementing Gramambular2 inside Rime). C2: 2-3 weeks for a filter that operates on Rime's candidates, but this defeats the purpose — we want to validate OUR engine's output, not Rime's.

2. **License compatibility**: ✅ Rime is BSD-3-Clause, compatible with MIT.

3. **Installation**: Requires installing librime + Rime frontend (fcitx5-rime or ibus-rime) + schema + plugin. More steps than a native addon.

4. **Wayland support**: Depends on frontend — through fcitx5-rime (good) or ibus-rime (moderate).

5. **Maintenance burden**: Moderate. Rime is actively maintained but the plugin API surface is larger than Fcitx5's addon API.

6. **Scorer integration**: ⚠️ Partial at best. Rime has its own segmentation engine (Grammar system) that is completely different from Gramambular2. C2 uses Rime's engine, not ours — our research is about enhancing McBopomofo, not Rime. This is a fundamental architectural mismatch.

### Option D: Standalone IME

Build a standalone input method process with direct Wayland/X11 text-input protocol handling.

**Evaluation**:

1. **Integration effort**: 6+ months. Must implement Wayland `text-input-v3` protocol, XIM fallback, candidate window rendering, input context management per application, autostart, configuration UI, and compositor-specific behavior. This is building a new IME framework from scratch.

2. **License compatibility**: ✅ Full control. No third-party license concerns.

3. **Installation**: Manual setup. No distro packaging. No standard configuration mechanism.

4. **Wayland support**: Must be built from scratch. Wayland input method protocols are complex and compositor-specific behavior varies widely.

5. **Maintenance burden**: Very high. We become the framework maintainers. Every new desktop environment or Wayland compositor quirk is ours to fix.

6. **Scorer integration**: ✅ Full control, but the cost of achieving this control is disproportionate for a research project.

## Decision

**Selected: Option A (Fcitx5 addon)**, with Option B (IBus) as a documented secondary path if Fcitx5 proves unsuitable for specific environments.

### Rationale

1. **Fcitx5 is the modern standard** for Linux IME development (2,341 stars, 60 contributors, release 5.1.19 in 2026-03). It has active maintenance, first-class Wayland support, and a stable C++ addon API. The community has standardized on Fcitx5 over IBus for new IME development.

2. **Proven reference architecture**: fcitx5-chewing demonstrates the exact pattern we need — a C++ IME engine wrapped as a Fcitx5 addon in ~700 lines of C++. The class hierarchy (`ChewingEngine : InputMethodEngine`, `ChewingEngineFactory : AddonFactory`) is directly applicable.

3. **License boundary is manageable via separate `.so` strategy**: The engine builds as a standalone `libmbengine.so` (MIT). The addon builds as a separate `mcbopomofo.so` (LGPL-2.1+) that dynamically links to both Fcitx5's public API and the engine. This keeps the engine as a "separate work" under LGPL terms — the same model fcitx5-chewing uses with libchewing.

4. **Scorer integration path is identical to macOS**: The Fcitx5 addon calls engine APIs (insert readings → walk → apply scorer → update candidates) the same way the macOS KeyHandler.mm does. No design changes needed.

5. **IBus remains a documented fallback**: The engine `.so` is framework-agnostic. Writing an IBus engine later would reuse the same engine binary with a different wrapper process.

### Rejected Options

- **Rime (C1 — engine replacement)**: Rime has its own segmentation engine (Grammar system) that is architecturally completely different from Gramambular2. Replacing it would require maintaining a librime fork — disproportionate effort for a research project.
- **Rime (C2 — scorer as filter)**: A Rime filter operates on Rime's candidate pipeline, not our engine's `ReadingGrid`. Our scorer is tightly coupled to our `LanguageModel` data structures. Porting it to Rime means rewriting it for a different engine — defeating the purpose of validating our engine on Linux. **This is a fundamental architectural mismatch.**
- **Standalone (D)**: 6+ months of effort for what existing frameworks provide. Unjustifiable for a single-developer research project.

### Escalation Triggers

Reconsider this decision if:
- Ubuntu stops shipping the XIM bridge on Wayland with GNOME 46+ and Fcitx5's `text-input-v3` fails in a specific desktop environment.
- A major Linux distribution mandates IBus as the only supported IME framework (no current distribution does this — even GNOME Ubuntu allows Fcitx5).

## Consequences

1. **Phase 5 scope**: Build a minimal Fcitx5 addon wrapping the existing C++ engine. Target: Bopomofo input with contextual reranker toggleable via Fcitx5's configuration system.

2. **Repository layout**:
   - `Source/Engine/` — MIT, platform-neutral C++17 (unchanged)
   - `Tools/Fcitx5Addon/` — LGPL-2.1+, thin wrapper with `CMakeLists.txt` using `find_package(Fcitx5Core)`
   - Engine builds as `libmbengine.so` (MIT), addon builds as `mcbopomofo.so` (LGPL)

3. **Implementation order**:
   - Week 1: Addon skeleton (`InputMethodEngine` + `AddonFactory`), engine `.so` build target
   - Week 2-3: Key event handling, state machine, candidate display
   - Week 4: Configuration (keyboard layout, reranker toggle)
   - Week 5: Packaging (`.deb`), documentation
   - Week 6: Testing on clean Ubuntu 24.04 system

4. **Testing**: Requires either an Ubuntu desktop environment with Fcitx5 installed (physical or VM) or headless testing via Fcitx5's test utilities.

5. **IBus contingency**: The engine `.so` is framework-agnostic. Writing an IBus engine later would reuse `libmbengine.so` with a different wrapper process. Estimated 4-6 weeks if needed.

## License Boundaries

```
┌──────────────────────────────────────┐
│  Fcitx5 Framework (LGPL-2.1+)        │  ← system package, dynamic link
└────────────┬─────────────────────────┘
             │ public API (Fcitx5::Core)
┌────────────▼─────────────────────────┐
│  mcbopomofo.so — addon (LGPL-2.1+)   │  ← thin wrapper InputMethodEngine
│  dynamically links Fcitx5::Core      │      follows fcitx5-chewing pattern
│  dynamically links libmbengine.so    │
└────────────┬─────────────────────────┘
             │ C API / ABI-stable interface
┌────────────▼─────────────────────────┐
│  libmbengine.so — engine (MIT)        │  ← separate shared library
│  McBopomofoLM, ReadingGrid,           │      no Fcitx5 dependency
│  DeterministicContextualScorer        │      can be used by any app
└──────────────────────────────────────┘
```

**Key principle**: Two separate shared libraries. The engine `.so` has zero knowledge of Fcitx5 — it is a standalone C++ library that any application could use. The addon `.so` is a thin integration layer that happens to use both Fcitx5 (for input method services) and the engine (for Bopomofo processing). Under LGPL-2.1 Section 6, the engine qualifies as a "separate work" that the addon "uses" — its MIT license is unaffected.

**Why NOT static linking**: If the engine were statically linked into `mcbopomofo.so`, the combined binary would need LGPL-compatible licensing because it incorporates Fcitx5's API calls. Building two `.so` files eliminates this ambiguity entirely.

**Precedent**: fcitx5-chewing wraps libchewing (LGPL-2.1+) in an LGPL-2.1+ addon (its `SPDX-License-Identifier: LGPL-2.1-or-later`). libchewing's license is unaffected by the wrapper. Our situation is analogous with MIT instead of LGPL for the engine.

## References

- Fcitx5: https://github.com/fcitx/fcitx5 (LGPL-2.1+)
- fcitx5-chewing: https://github.com/fcitx/fcitx5-chewing (GPL-2.0+)
- IBus: https://github.com/ibus/ibus (LGPL-2.1+)
- librime: https://github.com/rime/librime (BSD-3-Clause)
- libchewing: https://github.com/chewing/libchewing (LGPL-2.1+)
- Project license analysis: `docs/台灣繁中注音輸入法_法律授權盤點.md`
