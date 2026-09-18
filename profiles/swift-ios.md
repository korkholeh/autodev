# Profile: native iOS app in Swift

## Layout

```
Package.swift or <App>.xcodeproj / .xcworkspace
Sources/<AppCore>/        logic, networking, persistence — platform-independent SwiftPM target
<App>/                    SwiftUI/UIKit screens, App entry point, Info.plist, entitlements
Tests/<AppCore>Tests/     unit tests
<App>UITests/             XCUITest specs — the e2e layer
docs/dev, docs/user
```

## Commands

Pin one simulator destination and use it everywhere; a run that picks "any iOS device" is not reproducible.

| Key | Command |
|---|---|
| install | `xcodebuild -resolvePackageDependencies` |
| build | `xcodebuild -scheme <App> -destination 'platform=iOS Simulator,name=iPhone 16' build` |
| run | `xcrun simctl boot 'iPhone 16'` then install and launch the built `.app` |
| test | `swift test` for the core package, `xcodebuild -scheme <App> -destination 'platform=iOS Simulator,name=iPhone 16' test` |
| lint | `swiftlint` |
| format | `swift-format format -i -r Sources Tests` or `swiftformat .` |
| e2e up | `xcrun simctl boot 'iPhone 16'` (idempotent; ignore "already booted") |
| e2e | `xcodebuild -scheme <App>UITests -destination 'platform=iOS Simulator,name=iPhone 16' test` |
| e2e down | `xcrun simctl shutdown 'iPhone 16'` (optional) |
| screenshot | `xcrun simctl io booted screenshot <path>.png` with the app launched on the booted simulator |

## End-to-end with XCUITest

- Reset per test: `xcrun simctl uninstall` or a launch argument that clears the app's container. A simulator that
  carries state between runs produces a suite that passes only the second time.
- Accessibility identifiers on every control an e2e case touches; never match localized labels.
- Cover the parts only the device shows: permission prompts (camera, location, notifications) and both answers to
  each, deep links / universal links, background and foreground, rotation, Dynamic Type at the largest size, and
  what happens with no network.
- Stub the network at the app boundary under a launch argument rather than hitting a live backend from a UI test.
- Attach a screenshot on failure.

## Documentation

`docs/dev/operations.md`: bundle id, provisioning and signing, the build/archive command, TestFlight or App Store
submission steps, and the minimum supported iOS version with the reason. `docs/user/`: install, first run, every
permission the app asks for and why, and offline behaviour.

## Pitfalls

- App Review rejects surprises: a permission with no user-visible purpose string, or data collected without a
  privacy manifest. Treat both as spec items, not as afterthoughts.
- Local persistence needs a migration path from every shipped schema version.
- Simulator-only verification is not device verification — say which one a claim came from.
- Long-running work must survive suspension; a task killed in the background is a normal case, not an edge case.

## Screenshots

- `xcrun simctl io booted screenshot <path>.png` on the simulator the e2e destination already boots; drive the
  app to each state with the UI test target first, or capture `XCUIScreen.main.screenshot()` from inside it.
- One device for the whole run (the e2e destination), status bar overridden with `xcrun simctl status_bar booted
  override --time 9:41 --batteryLevel 100` so the chrome stops changing between phases.
- Seed through a launch argument the app honours (`-uitest-seed`), never by tapping through onboarding.
- Light appearance unless the phase is about dark mode.
