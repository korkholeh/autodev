# Profile: native macOS app in Swift

## Layout

```
Package.swift or <App>.xcodeproj / .xcworkspace
Sources/<AppCore>/        platform-independent logic, as a SwiftPM target
<App>/                    the app target: SwiftUI/AppKit views, App entry point, Info.plist, entitlements
Tests/<AppCore>Tests/     unit tests (Swift Testing or XCTest)
<App>UITests/             XCUITest specs — the e2e layer
docs/dev, docs/user
```

Keep the logic in a SwiftPM target the app depends on: it builds and tests in seconds without a simulator or a
signing identity, and it is what most of the suite should exercise.

## Commands

Prefer `xcodebuild` with an explicit scheme; it is the only form that works unattended.

| Key | Command |
|---|---|
| install | `xcodebuild -resolvePackageDependencies` |
| build | `xcodebuild -scheme <App> -destination 'platform=macOS' build` |
| run | `open -a <App>.app` after a build, or `swift run` for a core-only executable |
| test | `swift test` for the core package, `xcodebuild -scheme <App> -destination 'platform=macOS' test` for the app |
| lint | `swiftlint` (config committed) |
| format | `swift-format format -i -r Sources Tests` or `swiftformat .` |
| e2e up | `-` (XCUITest launches the app itself) |
| e2e | `xcodebuild -scheme <App>UITests -destination 'platform=macOS' test` |
| e2e down | `-` |
| screenshot | `XCUIScreen.main.screenshot()` written to a file from a UI test, or `screencapture -x -o -l<window-id> <path>.png` |

Add `-quiet` or pipe through `xcbeautify` when the raw output floods the log. Never rely on an interactive
Xcode action; everything must run from the command line.

## End-to-end with XCUITest

- The app launches per test via `XCUIApplication()`. Pass fixture state through `app.launchArguments` /
  `launchEnvironment` (for example `-uiTestSeed reset`) and branch on it at startup — never mutate the user's real
  Application Support directory from a test.
- Address elements by accessibility identifier. Set them explicitly on every control an e2e case touches; do not
  match on visible labels that localization will change.
- Wait with `waitForExistence(timeout:)` / `expectation(for:)`. Never `sleep`.
- Cover what only the real app shows: window restoration, menu bar commands, keyboard shortcuts, the sandbox's
  file-access prompts, multi-window, and the launch path itself.
- Attach a screenshot on failure (`XCTAttachment(screenshot:)`, lifetime `.deleteOnSuccess`).

## Documentation

Record in `docs/dev/operations.md`: the bundle identifier, signing and notarization steps, the entitlements and why
each one is needed, where user data lives (`~/Library/Application Support/<bundle-id>`), and how a release is built.
`docs/user/` covers install, first launch, permissions the user will be asked for, and every keyboard shortcut.

## Pitfalls

- Sandbox entitlements are a design decision: what the app may read, write, or reach has to be stated before the UI
  assumes it.
- A schema change in the local store needs a migration, not a wipe. Users cannot re-create their data.
- Keychain access, notifications, and file prompts do not work without the right entitlement and a code signature.
- `xcodebuild` fails silently in odd ways when the scheme is not shared: mark schemes shared and commit them.

## Screenshots

- From a UI test: `XCUIScreen.main.screenshot()` (or `app.windows.firstMatch.screenshot()` for the window
  alone), written to the phase's `screenshots/` directory with `try png.write(to:)`.
- Outside the test target, `screencapture -x -o -l<window-id>` photographs one window without the desktop; the
  window id comes from `CGWindowListCopyWindowInfo`, not from a guess.
- Fix the window size in the test before capturing, and keep it for the whole run.
- Seed with a launch argument the app honours, and capture in light appearance unless the phase is about theming.
