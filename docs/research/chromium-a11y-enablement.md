# Chromium/Electron AT-SPI enablement on Linux — primary-source findings

Research date: 2026-08-05. All Chromium code cited at `main` (HEAD) on
`chromium.googlesource.com` / github mirror `chromium/chromium` unless a commit is
given. Electron code cited at `master` on `github.com/electron/electron`.
Primary sources only, except where a source is explicitly labelled **secondary**.

---

## Verdict (read this first)

The empty `application → frame shell` tree that Heimdall sees is caused by **two
independent gates**, and the ones that matter are different from what the lore
implies:

| Mechanism | Real? | What it actually does | Persists across restarts? |
|---|---|---|---|
| `ACCESSIBILITY_ENABLED=1` env var | **REAL** — read by Chromium (`ui/accessibility/platform/atk_util_auralinux.cc`) | Gate 1 only: registers the app's ATK util with the AT-SPI bus, so at-spi sees the *application root and native-window "frame" shell*. It does **not** enable the web-contents tree. | **Yes** — it's read at process start from the environment; survives restarts via `~/.config/environment.d/*.conf` (applied at login). |
| `--force-renderer-accessibility` launch arg | **REAL** — switch defined in `ui/accessibility/accessibility_switches.cc`, parsed in `content/browser/accessibility/browser_accessibility_state_impl.cc` | Gate 2: forces a Chromium `AXMode` (entire DOM/ATK tree, incl. document + text nodes) at process start. This is the flag that actually populates the tree. With a value (`=complete` etc.) the mode is locked for the process lifetime. | **Yes** — only if the flag is baked into the launch entry (.desktop `Exec=`, wrapper script, `app.commandLine.appendSwitch`). |
| `chrome://accessibility` "global flags" toggles | **Real** | Runtime-only: sets `kNativeAPIs`/`kWebContents`/… via a `ScopedAccessibilityMode` bound to the `chrome://accessibility` tab. | **No** — reverted when the tab is closed and on every browser restart. |
| CDP `Accessibility.enable` | **Real** | **Renderer-only** Blink tree (`AXContext(…, kAXModeComplete)`), per DevTools session. Does **not** enable the platform/AT-SPI bridge. | **No** — per-session; resets when the DevTools session ends. |
| DBus `org.a11y.Bus` / GSettings `toolkit-accessibility` | Real (checked in the same file) | Equivalents of Gate 1. Merely turning on the bus makes Chromium show the shell, exactly what Heimdall already observes — never the content. | Toggling the bus is pre-existing/however you start at-spi; it never sets AXMode. |

**The `BOTH` claim on the Arch wiki is correct but for reasons the wiki gets half
wrong.** The env var is NOT Electron-only and NOT lore — it is genuinely read by
Chromium, and it *is* necessary for the app to be visible on the at-spi bus at
all in a bare session. But it only satisfies Gate 1. The env var alone **cannot**
produce document nodes; `--force-renderer-accessibility` (or an equivalent
AXMode force at startup) is what produces them. Heimdall already has Gate 1
satisfied (it sees the frame shell — almost certainly because it brings up the
a11y bus itself), so **the missing piece is Gate 2: nothing forces the
browser-process `AXMode`**.

> Bottom line for the tool: there is **no persistent, out-of-process,
> runtime-only mechanism** that populates the tree. The only options that
> persist across restarts are the launch-time ones (flag in the launch entry,
> env var for gate 1). A per-boot programmatic toggle cannot work for AT-SPI:
> `chrome://accessibility` and CDP are both in-process/session-scoped and
> neither reaches the AT-SPI bridge persistently.

---

## 1. Does Chromium read `ACCESSIBILITY_ENABLED`? — YES (since 2016, current HEAD)

**Current code.** `ui/accessibility/platform/atk_util_auralinux.cc` at HEAD:

- `kAccessibilityEnabledVariables = {"ACCESSIBILITY_ENABLED", "GNOME_ACCESSIBILITY", "QT_ACCESSIBILITY"}`.
- `AtkUtilAuraLinux::ShouldEnableAccessibility()` reads each variable via
  `base::Environment::GetVar(...)`; value `"1"` → enable, `"0"` → disable; then
  falls back to a DBus query of `org.a11y.Bus` / `org.a11y.Status.IsEnabled`,
  then GSettings `org.gnome.desktop.interface` → `toolkit-accessibility`.
- `AtkUtilAuraLinux::InitializeAsync()` **early-returns unless
  `ShouldEnableAccessibility()` is true**, i.e. it only registers
  `ATK_UTIL_AURALINUX_TYPE` (the ATK util whose `get_root` feeds
  `AXPlatformNodeAuraLinux::application()`) when one of those signals says "AT
  should be served". That registration is exactly what makes at-spi able to see
  the application at all.

Cited: <https://chromium.googlesource.com/chromium/src.git/+/HEAD/ui/accessibility/platform/atk_util_auralinux.cc>
(function names + the env-var array above are verbatim from that file).

**History.** The `getenv("ACCESSIBILITY_ENABLED")` check dates to 2016, visible
in the (re)landed CLs "Fix hanging on browser shutdown"
(<https://codereview.chromium.org/1990453002>) and its revert/re-land
(<https://codereview.chromium.org/1988213002>); same variable, same GConf
(now GSettings/DBus) fallbacks.

**Scope.** `ACCESSIBILITY_ENABLED` is read **only** in that one file. It gates
ATK-util registration — the bus/layer-1 gate. It sets **no** `AXMode`, so it
never builds the web-contents tree by itself. It is a Chromium mechanism that
Electron inherits (see §4); it is not an Electron invention and not lore.

---

## 2. `--force-renderer-accessibility`: parsing, mode, and what gets exported

**Switch definition.** `ui/accessibility/accessibility_switches.cc`:
`kForceRendererAccessibility = "force-renderer-accessibility"`, with the doc
comment: *"Force renderer accessibility to be on instead of enabling it on
demand… optional parameter that forces an AXMode bundle… 'basic',
'form-controls', 'complete'. If the bundle argument is invalid, then the forced
AXMode will default to 'complete'. If the bundle argument is missing, then the
initial AXMode will default to complete but allow changes."*
<https://github.com/chromium/chromium/blob/main/ui/accessibility/accessibility_switches.cc>

**Parsing.** `content/browser/accessibility/browser_accessibility_state_impl.cc`,
constructor `BrowserAccessibilityStateImpl::BrowserAccessibilityStateImpl()`:

```
if (command_line.HasSwitch(switches::kDisableRendererAccessibility)) {
  disallow_changes = true;
} else if (command_line.HasSwitch(switches::kForceRendererAccessibility)) {
  std::string ax_mode_bundle = GetSwitchValueNative(...);
  if (ax_mode_bundle.empty()) {
    // backwards-compat: no-arg -> screen reader bundle, allow changes
    initial_mode = ui::kAXModeComplete | ui::AXMode::kScreenReader;
  } else {
    // =basic / =form-controls / =complete / =on-screen; 'screen-reader' or
    // invalid -> kAXModeComplete | kScreenReader
    ...
    disallow_changes = true;   // mode locked for the whole run
  }
}
...
forced_accessibility_mode_ = CreateScopedModeForProcess(initial_mode);
...
SetAXModeChangeAllowed(!disallow_changes);
```
<https://github.com/chromium/chromium/blob/main/content/browser/accessibility/browser_accessibility_state_impl.cc>
(`BrowserAccessibilityStateImpl` caches it as
`force_renderer_accessibility_` per the header
`content/browser/accessibility/browser_accessibility_state_impl.h`.)

**What mode it forces.** Bundles in `ui/accessibility/ax_mode.h`:
- `kNativeAPIs` (1<<0): "Native accessibility APIs… enabled. … unless one of the
  modes below is set, the contents of web pages will not be accessible."
- `kWebContents` (1<<1): renderer builds the DOM accessibility tree; "the
  minimum mode required in order for web contents to be accessible".
- `kAXModeBasic = kNativeAPIs | kWebContents`
- `kAXModeComplete = kNativeAPIs | kWebContents | kInlineTextBoxes | kExtendedProperties`
- `kAXModeFormControls = (kNativeAPIs | kWebContents) filtering forms/labels only`
<https://github.com/chromium/chromium/blob/main/ui/accessibility/ax_mode.h>

**Answer to "does forcing native APIs export the full tree?":** `kNativeAPIs`
 alone only creates platform nodes for the browser UI ("native accessibility"),
 and — as the comment in `ax_mode.h` stresses — **not** web content. The DOM
 tree requires `kWebContents`, and richer text requires
 `kInlineTextBoxes`/`kExtendedProperties`. Because every bundle that
 `--force-renderer-accessibility` accepts (`basic`, `form-controls`, `complete`,
 no-arg) **includes `kWebContents`**, any valid form of the flag exports the
 full page tree (document → text) over ATK/AT-SPI on Linux — provided Gate 1 is
 also satisfied (app registered on the bus). The ATK wrappers themselves are
 built by the browser-process manager:
 `ui/accessibility/platform/browser_accessibility_manager_auralinux.cc`
 (`BrowserAccessibilityManager::Create` → `BrowserAccessibilityManagerAuraLinux`);
 each node is wrapped as an `AXPlatformNodeAuraLinux` ATK object
 (`ui/accessibility/platform/ax_platform_node_auralinux.cc`).

**No-arg vs with-arg caveat:** with an argument the AXMode is *locked*
(`SetAXModeChangeAllowed(false)`) for the whole process — no runtime changes,
fine for a deterministic tool. Without an argument it starts
`complete|screen-reader` but can still change later.

Official docs: `docs/accessibility/overview.md`, section "Accessibility features
… off by default and enabled automatically on-demand … Command Line Options",
and "Linux: ATK".
<https://github.com/chromium/chromium/blob/main/docs/accessibility/overview.md>

---

## 3. `chrome://accessibility` and every runtime enable mechanism

Backing store: `chrome/browser/ui/webui/accessibility/accessibility_ui.cc`.
- The "global flags" section (Native / Web / Text / ExtendedProperties / HTML /
  isolate / locked) is handled by
  `AccessibilityUIMessageHandler::HandleSetGlobalFlag`, which maps flag names to
  `AXMode` bits (`kNative` → `kNativeAPIs`, `kWeb` → `kWebContents`, …) and
  applies them through `AccessibilityUiModes::SetModeForProcess` →
  `content::BrowserAccessibilityState::CreateScopedModeForProcess(mode)`.
- All modes (process-wide *and* per-tab) are held in `AccessibilityUiModes`, a
  `WebContentsUserData` attached to the `chrome://accessibility` tab, owning
  `ScopedAccessibilityMode`s. When the tab is destroyed or the browser exits,
  the scopers die and the mode reverts. There is a save/restore only for
  in-page navigation away/back to the same tab — **explicitly not persisted to
  any pref or Local State**. Toggling "Enable global accessibility mode" here
  will **not** survive a browser restart (and not even closing the tab).
<https://github.com/chromium/chromium/blob/main/chrome/browser/ui/webui/accessibility/accessibility_ui.cc>

Can it be triggered from *outside* the browser?
- **CDP `Accessibility.enable` — no (for AT-SPI).** The protocol method is
  implemented renderer-side in
  `third_party/blink/renderer/modules/accessibility/inspector_accessibility_agent.cc`:
  `enable()` → `EnableAndReset()` (per-agent `enabled_` flip) and
  `AttachToAXObjectCache()` creates an `AXContext(document, ui::kAXModeComplete)`
  **inside the renderer/Blink only**. It builds/serializes the Blink AX tree for
  the DevTools frontend and never sets the browser-process `AXMode`, never sets
  `kNativeAPIs`, and never touches the at-spi bridge. It is also scoped to the
  DevTools session. So it "turns on accessibility for the page" *in the renderer*
  but cannot make a populated tree appear over AT-SPI and does not persist.
  Protocol spec (the enable/disable semantics):
  <https://chromedevtools.github.io/devtools-protocol/tot/Accessibility/>;
  origin commit "DevTools: Accessibility.enable and disable protocol methods"
  (crbug 887173), hash `24961c1e`.
- **`chrome://flags` — no relevant entry.** Flags are mapped to Chromium
  switches/`--enable-features` (per Electron's command-line-switches doc below);
  there is no standard flag that forces `kNativeAPIs`/`kWebContents`. The only
  documented ways to reach the two gates are the env var, the launch switch
  `--force-renderer-accessibility`, and the (ephemeral) `chrome://accessibility`
  toggles.
- **DBus / GSettings — only Gate 1.** `org.a11y` bus enabled / GNOME
  `toolkit-accessibility` merely make Chromium register its ATK util; they don't
  set an AXMode (§1). That is precisely why Heimdall already sees the shell.
  Toggling them at login changes nothing about content.

**Related subtlety — "progressive" platform enable can't self-heal the content.**
There is a path (`AXPlatform::OnPropertiesUsedInWebContent` →
`BrowserAccessibilityStateImpl::EnableAXModeFromPlatform(kAXModeBasic)`) that
auto-adds `kNativeAPIs|kWebContents` when assistive tech reads *web* properties;
but it only fires once web nodes exist — and it is additionally subject to
`SetActivationFromPlatformEnabled()` / `SetAXModeChangeAllowed()` gates
(`browser_accessibility_state_impl.cc` `FilterModeFlags`, `kFromPlatform` bit).
So an at-spi client that starts from the empty frame shell never gets to query a
web node, nothing fires, and the tree stays empty. This is the chicken-and-egg
the command-line flag breaks.
Sources: `ui/accessibility/platform/ax_platform.h` (delegate callbacks),
`content/browser/accessibility/browser_accessibility_state_impl.cc`
(`EnableAXModeFromPlatform`, `FilterModeFlags`).

---

## 4. Electron: what Electron itself does, and the minimal enablement

Electron has **no separate env-var handling** — it embeds Chromium's `//ui/accessibility`,
so the *same* `atk_util_auralinux.cc` (and thus `ACCESSIBILITY_ENABLED`) runs in
its browser process. Everything in §1–§2 applies identically.

Electron-specific plumbing (all in `shell/browser/api/electron_api_app.cc`):
- `App::SetAccessibilitySupportEnabled(bool)` →
  `content::BrowserAccessibilityState::GetInstance()->CreateScopedModeForProcess(ui::kAXModeComplete)`
  — programmatic equivalent of `--force-renderer-accessibility=complete`
  (kNativeAPIs|kWebContents|kInlineTextBoxes|kExtendedProperties).
- `app.setAccessibilitySupportFeatures([...])` / `app.getAccessibilitySupportFeatures()`
  — granular bits (added in PR <https://github.com/electron/electron/pull/48042>).
- `App::IsAccessibilitySupportEnabled()` returns `mode.has_mode(kAXModeComplete)`;
  the `'accessibility-support-changed'` app event wraps
  `Browser::Get()->OnAccessibilitySupportChanged()`.
- CLI: Electron forwards Chromium switches verbatim; the
  `docs/api/command-line-switches.md` page documents
  `app.commandLine.appendSwitch(switch, value)` as the in-app hook, and notes
  Chromium switches aren't exposed via `about://flags`.
<https://github.com/electron/electron/blob/master/shell/browser/api/electron_api_app.cc>
<https://github.com/electron/electron/blob/main/docs/api/command-line-switches.md>

**Minimal way to get Electron apps (Discord, `code`, Brave, Sidra) to expose a
populated tree**, per primary code + official Electron issue #48268 (maintainer
instructions: "set the ACCESSIBILITY_ENABLED environment variable to 1, and if
it doesn't help, also use --force-renderer-accessibility flag"):
1. `ACCESSIBILITY_ENABLED=1` in the environment (Gate 1, needed in bare
   sessions; possibly already satisfied if the a11y bus is on), and
2. `--force-renderer-accessibility` on the process command line (Gate 2 — the
   flag that populates content).
For a *distributed/user-facing* app you can't relaunch, the app should call
`app.commandLine.appendSwitch('force-renderer-accessibility')` in `main` before
`ready`, or `app.setAccessibilitySupportEnabled(true)`.

Per-app caveats (secondary but widely confirmed, useful for planning):
- **VS Code (`code`/`code-insiders`):** accepts `--force-renderer-accessibility`
  explicitly (added to its accepted args) and when
  `"editor.accessibilitySupport": "on"` is set it reboots and forwards the flag
  itself — issue microsoft/vscode#84833. It also needs the env var in some
  setups; on Linux combine both.
- **Discord / Brave / Sidra:** plain Electron/Chromium apps; put the flag in the
  `.desktop` `Exec=` line (or its own wrapper) rather than a terminal alias, so
  autostart/launchers also get it.
- Adding the flag with a value locks the mode for the process — safe and
  desirable for this use case.

---

## 5. Persistence across restarts (the decision table)

| Candidate | Applies via | Restart behavior on Linux |
|---|---|---|
| (a) `--force-renderer-accessibility` in the launch entry (`.desktop` `Exec=`, wrapper script, or `app.commandLine.appendSwitch`) | per-app process launch | **Persists** — re-applied on every launch of that app; the only mechanism that reliably gives Gate 2 (content). |
| (b) `ACCESSIBILITY_ENABLED=1` in `~/.config/environment.d/*.conf` (also `/etc/environment`, `~/.profile`) | systemd user environment, applied at login | **Persists** — every Chromium-family app started after login gets it. But it is **Gate 1 only**; without (a) the tree is still shell-only. |
| (c) per-boot script toggling global a11y (chrome://accessibility, CDP, DBus) | runtime, in-process/session | **Does NOT persist and does not reach Gate 2.** chrome://accessibility resets on tab close/restart; CDP is per-DevTools-session and renderer-only; DBus only affects Gate 1 (and only toggles what Heimdall already sees). |

**Recommended for Heimdall (for persistent, per-app coverage):**
- Keep/ensure Gate 1 unconditionally: `ACCESSIBILITY_ENABLED=1` in
  `~/.config/environment.d/heimdall-a11y.conf` (harmless even when the bus is
  already up; makes behavior identical across Hyprland/bare sessions and
  restart-independent).
- Add Gate 2 to each target app's real launch path: edit/override the `.desktop`
  entries for the apps Heimdall tracks (or wrapper binaries) to include
  `--force-renderer-accessibility`, e.g. `Exec=/usr/bin/discord
  --force-renderer-accessibility`. That is the only persistent way to get
  populated trees; it survives reboots, app restarts, and autostart launches.
- Do **not** rely on a per-boot programmatic enable for AT-SPI: both runtime
  channels that can actually flip the mode are in-process and reset on app
  exit, and CDP never touches the AT-SPI bridge anyway.

---

## Sources

Primary:
- `ui/accessibility/platform/atk_util_auralinux.cc` (HEAD) — env-var/DBus/GSettings gate 1
- `ui/accessibility/accessibility_switches.cc` — `kForceRendererAccessibility`
- `content/browser/accessibility/browser_accessibility_state_impl.cc` (and `.h`) — switch parsing, mode bundles, `ScopedAccessibilityMode`, `EnableAXModeFromPlatform`/`FilterModeFlags`
- `ui/accessibility/ax_mode.h` — `kNativeAPIs`/`kWebContents`/bundle definitions
- `ui/accessibility/platform/browser_accessibility_manager_auralinux.cc`, `ax_platform_node_auralinux.cc`, `ax_platform.h`
- `docs/accessibility/overview.md` — command-line options, "Linux: ATK"
- `chrome/browser/ui/webui/accessibility/accessibility_ui.cc` — chrome://accessibility toggles + scoping
- `third_party/blink/renderer/modules/accessibility/inspector_accessibility_agent.cc` — CDP `Accessibility.enable`
- Chrome DevTools Protocol spec, Accessibility domain
- `shell/browser/api/electron_api_app.cc`, `docs/api/command-line-switches.md` (electron/electron)
- Electron issue electron/electron#48268 (maintainer-recommended env-var + flag for Linux AT-SPI)

Historical: Chromium CLs codereview.chromium.org/1990453002 and /1988213002 (2016 `getenv("ACCESSIBILITY_ENABLED")`); commit `24961c1e` (CDP `Accessibility.enable`).

Secondary (labelled, leads only):
- Arch wiki «[Accessibility](https://wiki.archlinux.org/title/Accessibility)» — claims both `ACCESSIBILITY_ENABLED=1` and `--force-renderer-accessibility`; verified above against source.
- orca-list/GNOME Orca Chromium page; microsoft/vscode#84833 (VS Code forwards the flag); xa11y.dev accessibility-quirks page.