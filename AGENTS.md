# AGENTS.md

Cicada (知了, formerly Live Subs): a macOS app, run from the menu bar, that turns what the Mac plays into live translated subtitles and meeting notes, keeps each meeting as a bilingual record, and speaks what you say back into the room in their language.

## Scope

- Surfaces: menu bar panel, live notes window (default) or subtitle bar while listening, main window (meeting records), settings, four-step onboarding (system audio, sample meeting, Ling key, speaking if wanted). A request that fits none of them gets pushed back before any UI is added.
- Nothing the user does needs the Terminal.
- Listening: Core Audio process tap → on-device language detection and `SpeechAnalyzer` → translation. Experimental voices: a bundled Core ML voiceprint model (`SpeakerID.swift`), compiled on first use. Speaking: hold right ⌥ or a shortcut → mic → Ming (with a Ling key) or on-device + translation → voice → BlackHole 2ch virtual mic.

## Hard rules

- The Ling key lives only in the 0600 `ling-api-key` file (`AIKey`): never UserDefaults, logs or exports.
- Every Ling call goes through `LingClient` (rate gate, priorities, `thinking: disabled`, content in the system message). Partial text is translated by Google, never Ling.
- Never speak untranslated text into the room. Never bundle the GPL BlackHole driver; download it and check its pinned SHA-256.
- The notes window is a non-activating panel with `sharingType = .none`: it must never take focus, and stays out of screen captures unless the user turns on 共享屏幕时让对方看到 (then it shows a badge).
- UI and engine state are `@MainActor`; audio callbacks hand buffers to `AudioRouter`'s queue.
- Don't change the release bundle id `com.wquguru.cicada` or the ad-hoc designated requirement: permissions are tied to them.
- macOS targets: no third-party dependencies, no `.xcodeproj`; Command Line Tools only. Ubuntu lives under `ubuntu/` with its own Python dependencies; see `ubuntu/README.md` for boundaries and checks.

## Design

- Ground `#F3F4F6`, white cards (the main window is one white sheet, no cards), ink `#15171C`, one accent `#E8552B` for "live", greys `#5A5F6B` / `#6B7080`. Design canvases on claude.ai and the app itself are the source of truth.
- Copy is Chinese and short, at most one grey helper line. Chinese text is the localization key; `Resources/{en,ja,ko}.lproj` translate it. SwiftUI literals localize themselves; other UI strings use `L("…")`; never `L()` prompts, logs or stored values. After changing UI text run `python3 scripts/strings.py` (`--write` adds TODOs), and check the English UI, which runs wider.
- The logo geometry is kept in step in `CicadaLogo` (`Onboarding.swift`), `Sources/LiveSubsIcon` and `site/icon.svg`; then rerun `scripts/site-images.sh`.

## Layout

- `Sources/LiveSubs`: the app, one concern per file. Engines are UI-free (`ListenEngine`, `SpeakEngine`, `SpeakTest`, `Notes`, `Translator`, `Ling`, `VirtualMic`, `SessionStore`, `Updates`…); `AppModel` wires them and holds the debug commands. Settings keys: `AppSettings` in `Settings.swift`.
- `Sources/LiveSubsIcon`: renders the icon set. `site/`: the website, built by `scripts/site.py`.
- The site is Chinese at `/`, English / Japanese / Korean under `/en/` `/ja/` `/ko/`; every `{{t.key}}` comes from `site/i18n/<lang>.json`. `start.html` is the setup page; its `img/start/` screenshots come from the app in each language. `tools/`: test helpers. `Tests/LiveSubsTests`: unit tests for the pure parts.

## Commands

```bash
scripts/test.sh                        # AGENTS.md check + unit tests
scripts/build.sh && open build/Cicada.app   # dev build: own bundle id, settings, log
RELEASE=1 scripts/build.sh             # release build
scripts/package.sh                     # DMG + zip + checksums
scripts/release.sh <x.y.z>             # writes the CHANGELOG section from commits; CI publishes the tag
scripts/deploy-site.sh                 # build the site, wrangler deploy to the cicada-site Worker (cicada.indaloop.app)
```

## Verifying

- Run the app and check the behaviour, not just the build; check the English UI too.
- Drive the dev build with `tools/lsctl` (commands and testing tips in `tools/README.md`; the source of truth is `AppModel.debugCommand`). Use `afplay Resources/sample/sample.m4a` or `say -o` clips as input and read `/tmp/livesubs-dev-debug.log`.
- A real voice, the BlackHole install, Input Monitoring and a Mac without permissions need a person.

## Conventions

- Match the existing naming and comment density; comments say why.
- Commit messages are English only and follow Conventional Commits (`feat:`, `fix:`, `docs:`, `build:`, `refactor:`, `test:`, `chore:`). `feat:` and `fix:` subjects are the release notes (`scripts/changelog.py`), one line each linked to the commit: say what the user gets in one plain sentence, one change per commit; website changes use `feat(site):` / `fix(site):`.
- Every user-visible change also gets a Chinese item in `site/changelog.json`, the website's changelog; keep `README.md` (Chinese, the default) and `README.en.md` in step.
- Versions are semver from 1.0.0: patch for fixes only, minor for features, major only when users must grant permissions again.
- This file stays under 6 KB with these sections; `scripts/check-agents.py` enforces it in `scripts/test.sh`, CI and the pre-commit hook. Implementation detail belongs in code comments, not here.

