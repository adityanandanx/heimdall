# Heimdall desktop client — Tauri 2 scaffold research (tray, settings store, shadcn/Tailwind, CSP→local API, subdir layout)

Reference for the `desktop/` client tickets. Everything below is cited from primary
sources (official docs at tauri.app / v2.tauri.app / tailwindcss.com / ui.shadcn.com, the
packaged template files in `tauri-apps/create-tauri-app`, and the tauri / plugins-workspace
source). **No installs or builds were run** — this is research only. Where the docs are
ambiguous, it is marked **verify on first build**. All sources fetched 2026-08-05.

## 0. TL;DR

| question | answer |
|---|---|
| stable Tauri major | **v2** (not v1): `tauri` crate 2.11.5, `@tauri-apps/cli` 2.11.4, `@tauri-apps/api` 2.11.1 (2026-07-01 / 2026-06-28 / 2026-06-17) |
| scaffold | `npm create tauri-app@latest my-app -- --template react-ts`; frontend at app root (`src/`, `index.html`, `vite.config.ts`), `src-tauri/` beside it |
| tray | **core, not a plugin** — `tray-icon` Cargo feature + `@tauri-apps/api/tray` `TrayIcon.new({icon, menu})`; needs icon (path or `defaultWindowIcon()`) and a `Menu` |
| settings / server URL | plugin **store**: crate `tauri-plugin-store` + npm `@tauri-apps/plugin-store` (both 2.4.4); `Store.load('settings.json')` / `LazyStore`; capability `store:default` |
| shadcn/ui + Tailwind | current = Tailwind **v4** (`@tailwindcss/vite`, `@import "tailwindcss";`) + `npx shadcn@latest init`; v3 flow is the legacy precedent |
| webview → http://127.0.0.1:3931 | cross-origin in every mode → CORS applies; API's `access-control-allow-origin: *` passes non-credentialed calls; **CSP must allow `connect-src http://127.0.0.1:3931`**; capabilities only gate Tauri IPC, not `fetch` |
| run from `desktop/` subdir | yes. CLI finds `src-tauri` in cwd, `cwd/src-tauri`, or a subtree search (default depth 3, `TAURI_CLI_CONFIG_DEPTH`). Paths in `tauri.conf.json` are relative to the config file; `beforeDevCommand` runs in the frontend dir by default (or an explicit `cwd`) |

## 1. Current stable major and the `react-ts` template

### 1.1 Tauri is on v2

- Tauri 2 is stable (v2.0.0 era, 2024); current patch line **2.11.x**. Release pages:
  `tauri` crate 2.11.5 (2026-07-01), `tauri-cli` 2.11.4 (2026-06-28), `@tauri-apps/api`
  2.11.1 (2026-06-17). Source: https://v2.tauri.app/release/ ,
  https://v2.tauri.app/release/tauri/ , crates.io, npm registry.
- v1 is the previous major (docs at https://tauri.app, webkit2gtk 4.0). The v2 docs
  explicitly keep an "Upgrade from Tauri 1.0" migration guide — new apps should use v2.
  Source: https://v2.tauri.app/start/migrate/from-tauri-1/ , https://github.com/tauri-apps/tauri
  (platform table: webkit2gtk 4.1 for v2).

### 1.2 `create-tauri-app` React + Vite + TypeScript template

- Command (npm 7+ needs the extra `--`):
  `npm create tauri-app@latest my-app -- --template react-ts`
  (preset list includes `react-ts`; `.` scaffolds into the current dir). Source:
  https://github.com/tauri-apps/create-tauri-app (README) , https://docs.rs/crate/create-tauri-app/4.5.6 .
- Vite frontend + `src-tauri` are **siblings**: the frontend lives at the project root, not
  in a nested folder the way this app's `desktop/` will. Exact tree of
  `template-react-ts` + the shared `_base_/src-tauri` (both from the repo, dev branch,
  fetched 2026-08-05):

  ```
  my-app/
  ├── index.html                    # <div id="root"> + module /src/main.tsx
  ├── package.json                  # type: module
  ├── tsconfig.json / tsconfig.node.json
  ├── vite.config.ts                # port 1420, strictPort, watch.ignored src-tauri
  ├── src/
  │   ├── main.tsx                  # ReactDOM.createRoot(...).render(<App/>)
  │   ├── App.tsx                   # greet() demo via invoke() from "@tauri-apps/api/core"
  │   ├── App.css                   # styles.css shipped by the template
  │   ├── assets/react.svg ...
  │   └── vite-env.d.ts
  ├── public/vite.svg, tauri.svg
  └── src-tauri/
      ├── Cargo.toml
      ├── build.rs                  # fn main() { tauri_build::build() }
      ├── tauri.conf.json           # "$schema": "https://schema.tauri.app/config/2"
      ├── capabilities/default.json # window "main": ["core:default","opener:default"]
      ├── icons/                    # 32x32.png, 128x128.png, icon.icns, icon.ico, ...
      └── src/
          ├── main.rs               # #![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
          └── lib.rs                # pub fn run() -> tauri::Builder::default().plugin(tauri_plugin_opener::init()).invoke_handler(...)
  ```
  Sources: https://github.com/tauri-apps/create-tauri-app/tree/dev/templates/template-react-ts
  and `templates/_base_/src-tauri/**` (same repo), plus the create-project guide
  https://v2.tauri.app/start/create-project/ .
- Template `package.json` (current dev-branch pins — **these drift**: verify at scaffold
  time): `react ^19.1.0`, `react-dom ^19.1.0`, `@tauri-apps/api ^2`,
  `@tauri-apps/plugin-opener ^2`; devDeps `@vitejs/plugin-react ^6.0.2`,
  `typescript ~6.0.3`, `vite ^8.0.16`, `@tauri-apps/cli ^2`. Scripts:
  `"dev": "vite"`, `"build": "tsc && vite build"`, `"preview": "vite preview"`,
  `"tauri": "tauri"`. Source: `templates/template-react-ts/package.json.lte`.
- Template Rust deps (`Cargo.toml`): `tauri = { version = "2", features = [] }`,
  `tauri-plugin-opener = "2"`, `tauri-build = { version = "2", features = [] }`,
  `serde`/`serde_json`; `[lib] crate-type = ["staticlib","cdylib","rlib"]`;
  `[profile.release] codegen-units=1, lto=true, opt-level=3, panic="abort", strip=true`.
  Source: `templates/_base_/src-tauri/Cargo.toml.lte`.
- Template `tauri.conf.json` defaults (from the template `.manifest`): `beforeDevCommand`
  = pkg-manager dev, `beforeBuildCommand` = pkg-manager build, `devUrl =
  http://localhost:1420`, `frontendDist = ../dist`, `app.security.csp = null`. Source:
  `templates/template-react-ts/.manifest` + `templates/_base_/src-tauri/%(v2)%tauri.conf.json.lte`.
- `vite.config.ts` shipped by the template hard-codes Tauri-specific bits: port `1420`,
  `strictPort: true` (many other tools assume 1420), `clearScreen: false`, and
  `server.watch.ignored: ["**/src-tauri/**"]` so Vite doesn't watch the Rust dir.
  Source: `templates/template-react-ts/vite.config.ts.lte`.

## 2. System tray + settings store

### 2.1 Tray — core in v2, no plugin

- In v2 the tray was moved into the **core** crate/API. There is **no
  `@tauri-apps/plugin-tray`** (npm 404, checked 2026-08-05). Two roles:
  - Rust: add the `tray-icon` Cargo feature, plus `image-png` (or `image-ico`) to load
    icon files: `tauri = { version = "2", features = ["tray-icon", "image-png"] }`.
    Source: https://v2.tauri.app/learn/system-tray/ ,
    https://v2.tauri.app/reference/javascript/api/namespacetray/ .
  - JS: `TrayIcon` from `@tauri-apps/api/tray`, `Menu` from `@tauri-apps/api/menu`.
    Source: https://v2.tauri.app/learn/system-tray/ .
- What a tray needs:
  - **icon** — `TrayIconOptions.icon` (path string, bytes, or `Image`), or
    `defaultWindowIcon()` from `@tauri-apps/api/app`; or declare it once in config
    `app.trayIcon.iconPath` (the only **required** key of `TrayIconConfig`; icon is
    embedded as raw pixels, so keep it small). No config-level menu key exists — the menu
    is always attached via JS/Rust. Sources:
    https://v2.tauri.app/reference/config/#trayiconconfig , https://v2.tauri.app/learn/system-tray/ .
  - **menu** — `Menu.new({ items: [{ id: 'quit', text: 'Quit', accelerator: 'CmdOrCtrl+Q' }] })`,
    passed as `menu` in `TrayIcon.new({...})` or set later via `tray.setMenu(menu)`.
    Source: https://v2.tauri.app/learn/system-tray/ .
- JS usage:
  ```ts
  import { TrayIcon } from "@tauri-apps/api/tray";
  import { Menu } from "@tauri-apps/api/menu";
  import { defaultWindowIcon } from "@tauri-apps/api/app";
  const menu = await Menu.new({ items: [{ id: "quit", text: "Quit" }] });
  const tray = await TrayIcon.new({
    icon: await defaultWindowIcon(),
    menu,
    tooltip: "Heimdall",
    showMenuOnLeftClick: true,
    action: (e) => { /* Click / DoubleClick / Enter / Move / Leave */ },
  });
  ```
  Platform notes: on **Linux the icon sometimes won't show unless a menu is set** (an
  empty `Menu` is enough); `menuOnLeftClick` is deprecated → `showMenuOnLeftClick` (since
  2.2.0); Linux uses `libayatana-appindicator` (env `TAURI_LINUX_AYATANA_APPINDICATOR`).
  Sources: https://v2.tauri.app/reference/javascript/api/namespacetray/ ,
  https://v2.tauri.app/reference/environment-variables/ .
- Rust alternative: `tauri::tray::TrayIconBuilder::new().with_id("tray").icon(img).menu(&menu).tooltip("Heimdall").build(app)`;
  menu events via `app.on_menu_event(...)`. Source: https://docs.rs/tauri/latest/tauri/tray/struct.TrayIconBuilder.html .
- Permissions: `core:tray:default` (included in `core:default`) grants `allow-new`,
  `allow-get-by-id`, `allow-remove-by-id`, `allow-set-icon`, `allow-set-menu`,
  `allow-set-tooltip`, `allow-set-title`, `allow-set-visible`, etc.; menus ride on
  `core:menu:default`. So the stock capability already covers a tray. Source:
  https://v2.tauri.app/reference/acl/core-permissions/ .

### 2.2 Settings / server-URL persistence — the store plugin

- Crate `tauri-plugin-store` **2.4.4** (crates.io), npm `@tauri-apps/plugin-store`
  **2.4.4**. Add with the CLI (`npm run tauri add store`) or manually (Cargo dep, JS dep,
  register `.plugin(tauri_plugin_store::Builder::new().build())`). Source:
  https://v2.tauri.app/plugin/store/ , https://crates.io/crates/tauri-plugin-store ,
  https://www.npmjs.com/package/@tauri-apps/plugin-store .
- Capability permission: add `"store:default"` to the app capability —
  `store:default` = `allow-load, allow-get-store, allow-set, allow-get, allow-has,
  allow-delete, allow-clear, allow-reset, allow-keys, allow-values, allow-entries,
  allow-length, allow-reload, allow-save`. Source: https://v2.tauri.app/plugin/store/
  (permissions section) + `plugins-workspace/plugins/store/permissions/default.toml`.
- API shape (v2):
  ```ts
  import { Store, LazyStore, load } from "@tauri-apps/plugin-store";
  const store = await load("settings.json", { autoSave: true }); // load() shares by path
  await store.set("serverUrl", "http://127.0.0.1:3931");
  const url = await store.get<string>("serverUrl");
  await store.save(); // autoSave debounces 100ms / saves on graceful exit
  // or lazy: const s = new LazyStore("settings.json");  // loads on first access
  ```
  Store files live in the app's `app_data_dir`. Save is async; `Store.load(path, opts)`
  on an empty store is fine for this use case (**verify first-run behavior on first build**).
  Sources: https://v2.tauri.app/plugin/store/ ,
  https://v2.tauri.app/reference/javascript/store/ .

## 3. shadcn/ui on Tailwind v4 (current) vs v3

### 3.1 Tailwind v4 (current; docs at tailwindcss.com/docs now default to v4)

- install: `pnpm add tailwindcss @tailwindcss/vite` (a real Vite plugin, no PostCSS config).
- `vite.config.ts`: `plugins: [react(), tailwindcss()]`.
- CSS: replace `src/index.css` with `@import "tailwindcss";`.
  Configuration is **CSS-first** (no `tailwind.config.js`; use `@theme`,
  `@theme inline`, `@custom-variant`, `@utility` in CSS). Current docs page is v4.3.
  Source: https://tailwindcss.com/docs/installation/using-vite .

### 3.2 shadcn/ui (current CLI is `shadcn@latest`, v4.16.1)

- Existing Vite + Tailwind v4 project: set up the `@/*` alias (`baseUrl/paths` in
  `tsconfig.json` + `tsconfig.app.json`, `resolve.alias` + `@types/node` in
  `vite.config.ts`), then:
  - `npx shadcn@latest init` — installs deps, `cn` util, CSS-variable theming
    (`@import "shadcn/tailwind.css"`, `tw-animate-css`), writes `components.json`.
  - `npx shadcn@latest add button` (any component name).
- Fresh Vite scaffold directly from the CLI: `npx shadcn@latest init -t vite`
  (templates: next, vite, start, react-router, laravel, astro); `--monorepo` flag;
  monorepo/workspace case → `npx shadcn@latest add button -c apps/web`.
  Source: https://ui.shadcn.com/docs/installation/vite , https://ui.shadcn.com/docs/cli .

### 3.3 Tailwind v3 (legacy precedent — only if the team explicitly wants v3)

- `pnpm add -D tailwindcss@3 postcss autoprefixer`, then `npx tailwindcss init -p`
  (generates `tailwind.config.js` + `postcss.config.js`); `content` array pointing at
  `./index.html` + `./src/**/*.{js,ts,jsx,tsx}`; CSS becomes `@tailwind base; @tailwind
  components; @tailwind utilities;`. Source: https://v3.tailwindcss.com/docs/guides/vite .
- shadcn on v3 used the same init/add flow but the artifacts differ (a
  `tailwind.config.ts` preset and CSS vars). The current `shadcn@latest` CLI auto-detects
  v3 vs v4 projects, **but the current docs only show the v4 path** — the exact v3
  `init` artifacts are **verify on first build**. The v1-era CLI name was
  `npx shadcn-ui@latest init`. Source: https://ui.shadcn.com/docs/legacy , current CLI
  docs https://ui.shadcn.com/docs/cli .

Recommendation spelled out: use **Tailwind v4 + `shadcn@latest`** — it is the combination
the template ecosystem and current shadcn docs assume.

## 4. Webview → http://127.0.0.1:3931 (origin, CORS, CSP, capabilities)

### 4.1 Where the app runs from (the origin)

- **dev**: `build.devUrl` — the Vite dev server, `http://localhost:1420` by template
  default. Plain `http`.
- **production**: bundled assets are served from the built-in custom protocol:
  - **macOS / Linux / iOS: `tauri://localhost`**
  - **Windows / Android: `http://tauri.localhost`** — v2 switched the custom protocol to
    the `http` scheme on Windows (previously `https://`); `useHttpsScheme: true` exists to
    flip back, changing your localstorage/IndexedDB locations.
  Sources: `packages/api/src/webview.ts`
  (https://github.com/tauri-apps/tauri/blob/dev/packages/api/src/webview.ts — documents
  "the devServer URL on development, or `tauri://localhost/` and `https://tauri.localhost/`
  on production" and the `useHttpsScheme` note), Tauri discussion #11091
  https://github.com/tauri-apps/tauri/discussions/11091 ("On windows and android it's
  `http://tauri.localhost/` and on linux/macos/ios it's `tauri://localhost/`"), core PR
  #7779 ("custom protocol on Windows now uses the http scheme").

### 4.2 CORS — yes, it applies; `access-control-allow-origin: *` covers it

- In **every** mode the webview origin (`tauri://localhost`, `http://tauri.localhost`, or
  `http://localhost:1420` in dev) differs from `http://127.0.0.1:3931`, so the engine
  (WKWebView / WebKitGTK / WebView2) enforces CORS on `fetch` to the API.
- The API already returns `access-control-allow-origin: *`. For **non-credentialed**
  requests that is enough for a `fetch(..., { method: "GET" })` / `POST` to succeed.
- Caveats (`verify on first build`): `*` is invalid with `credentials` (cookies /
  `Authorization` with `credentials: "include"`) — the MDN CORS model requires the actual
  origin then; and HTTP-to-HTTP is fine on all three platforms, but if anyone flips
  `useHttpsScheme: true`, fetching a plain-`http://` endpoint becomes **mixed content**
  and is blocked — the webview.ts source note explicitly contrasts this with the
  `://localhost` schemes used on macOS/Linux, **which allow http fetches**. Source:
  https://github.com/tauri-apps/tauri/blob/dev/packages/api/src/webview.ts ,
  MDN CORS https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS .
- If CORS ever becomes a blocker, the escape hatch is `tauri-plugin-http`
  (https://v2.tauri.app/plugin/http-client/) which does the request in Rust — no webview
  CORS at all. Not needed given the `*` header.

### 4.3 CSP (tauri.conf.json)

- CSP lives under `app.security.csp` in `tauri.conf.json` (a string or a directive object).
  The stock template sets `"csp": null` — i.e. **disabled** (then there is no CSP
  blocking, but also no XSS protection). Source: https://v2.tauri.app/reference/config/
  (AppConfig → SecurityConfig; `csp` + `devCsp`), template `tauri.conf.json.lte`.
- To allow the webview's `fetch` to the API while keeping CSP on, add the host to
  `connect-src`, e.g.:
  ```jsonc
  "security": {
    "csp": {
      "default-src": "'self' customprotocol: asset:",
      "connect-src": "ipc: http://ipc.localhost http://127.0.0.1:3931",
      "font-src": [...], "img-src": ["'self' asset: http://asset.localhost blob: data:"],
      "style-src": ["'unsafe-inline' 'self'"]
    }
  }
  ```
  Tauri appends its own hashes/nonces for bundled code at compile time — you only add what
  is unique to the app. The `connect-src` example above mirrors the official `api` example
  (`"connect-src": "ipc: http://ipc.localhost"`). There is also `app.security.devCsp` for
  development; which one actually governs the Vite-served dev URL is **verify on first
  build**. Sources: https://v2.tauri.app/security/csp/ , https://v2.tauri.app/reference/config/ .

### 4.4 Capabilities / permissions — gate IPC only, not `fetch`

- Capabilities control **Tauri IPC** (`invoke`, plugin JS APIs) — a plain `fetch` to an
  http URL is not touched by them. If the client talks to the API purely over `fetch`, no
  capability is needed for that call.
- Plugins DO need capability entries. The template ships
  `src-tauri/capabilities/default.json`:
  `{ "identifier": "default", "windows": ["main"], "permissions": ["core:default", "opener:default"] }`.
  A window/webview that matches no capability has **no IPC access at all**. For tray add
  nothing (it's inside `core:default`); for the store add `"store:default"`.
  Sources: https://v2.tauri.app/security/capabilities/ ,
  https://v2.tauri.app/reference/config/ (Capability), template `capabilities/default.json.lte`.
- Remote-origin capability (`remote.urls`) and `dangerousRemoteDomainIpcAccess` are for
  webviews loaded from external URLs — not applicable to a bundled app.

## 5. Running the whole app from a `desktop/` subdirectory

There is **no required Vite plugin**: the orchestration is CLI-driven
(`beforeDevCommand` starts Vite, `devUrl` points at it, `frontendDist` feeds the build)
plus template `vite.config.ts` settings. Sources: https://v2.tauri.app/start/frontend/vite/ ,
https://v2.tauri.app/start/create-project/ (server.watch.ignored advice).

### 5.1 Which config keys adjust (tauri.conf.json, under `build`)

- `frontendDist` — **paths are relative to the config file** (i.e. `src-tauri/`). Quote
  from the config reference: "When a path relative to the configuration file is
  provided, it is read recursively and all files are embedded". `tauri init -D` help says
  the same: "Web assets location, relative to `<project-dir>/src-tauri`". So a
  `desktop/src-tauri/tauri.conf.json` with `"frontendDist": "../dist"` points at
  `desktop/dist` (and works for *any* depth, e.g. `"frontendDist": "../frontend/dist"`).
- `devUrl` — a URL, typically `http://localhost:1420` (the template's Vite port). No path
  resolution involved.
- `beforeDevCommand` / `beforeBuildCommand` — plain string or the object form
  `{ "script": "...", "cwd": "...", "wait": false }`. The default cwd for the hook is the
  **resolved frontend dir** (the directory containing `package.json`); set an explicit
  `cwd` when the frontend lives somewhere non-obvious. Sources:
  https://v2.tauri.app/reference/config/ (BuildConfig / BeforeDevCommand),
  tauri-cli `crates/tauri-cli/src/dev.rs` (hook spawns `sh -c`, `current_dir(script_cwd.unwrap_or(dir(s.frontend)))`).

### 5.2 How the CLI finds the project

`tauri-cli`'s `resolve_tauri_dir()` checks, in order: cwd, `cwd/src-tauri` (for
`tauri.conf.json` / `tauri.conf.json5` / `Tauri.toml`), then a **subtree walk from cwd**
bounded by `TAURI_CLI_CONFIG_DEPTH` (default `3`) levels, accepting a config file or a
folder containing one. So from the **repo root** it finds `desktop/src-tauri/tauri.conf.json`
if it sits within the depth, and from **inside `desktop/`** it finds `desktop/src-tauri`
directly. The frontend dir is resolved the same way (`package.json` search). The `dev`
command then `chdir`s to the tauri dir internally, and hooks run in the frontend dir.
Sources: `crates/tauri-cli/src/helpers/app_paths.rs` ,
https://v2.tauri.app/reference/environment-variables/ (`TAURI_CLI_CONFIG_DEPTH` — "Number
of levels to traverse and find tauri configuration file"). **Verify against the installed
CLI before relying on running from the repo root** — the depth-walk behaviour above is
from the dev branch of tauri-cli; the safe, documented-in-practice invocation is to run
`tauri dev` from within `desktop/`.

### 5.3 Recommended heimdall layout

- `desktop/` = the create-tauri-app scaffold root (`package.json`, `src/`, `index.html`,
  `vite.config.ts`, `src-tauri/`). Commands are `desktop: npm run tauri dev` /
  `npm run tauri build`. Everything in §5.1 keeps template defaults.
- Config merging for CI/flavours: `tauri dev/build -c <file-or-json>` merges JSON config(s)
  over the default (e.g. override `devUrl`); `TAURI_CONFIG` env var does the same and was
  set by the CLI itself for the merge. Sources: https://v2.tauri.app/reference/cli/ (dev/
  build `-c, --config`), https://v2.tauri.app/reference/environment-variables/ .
- Watch out: Vite `strictPort` + port `1420` — a second dev instance (or another tool on
  1420) will fail `tauri dev`, which is intended (fail-fast), not a config bug.

## Verify on first build checklist

- Template pins drift (`vite ^8`, `react ^19.1`, `typescript ~6.0.3`, plugin versions) —
  read the generated `package.json`/`Cargo.toml` rather than trusting this doc's pins.
- Tailwind v3 + shadcn artifact specifics (only the v4 path is documented now).
- Which CSP (`csp` vs `devCsp`) actually governs the Vite-served dev URL; confirm
  `connect-src http://127.0.0.1:3931` is honoured on every platform's engine.
- CORS with `access-control-allow-origin: *`: fine for anonymous calls; re-check if the
  API ever needs cookies/`Authorization`.
- `TAURI_CLI_CONFIG_DEPTH` / running `tauri dev` from the repo root vs from `desktop/` on
  the installed CLI version.
- Store plugin first-run (`Store.load` on a not-yet-existing file, `autoSave` debounce),
  Linux appindicator tray, and the empty-menu-on-Linux caveat.