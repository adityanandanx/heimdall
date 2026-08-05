# Heimdall desktop client

Tauri 2 + React 19 + Tailwind v4 (shadcn/ui) + TanStack Query client for the
heimdall API. A pure HTTP client — it connects to a configurable server URL
(default `http://127.0.0.1:3931`) and never spawns or manages the server.

## Commands

- `pnpm tauri dev` — run the app against the live heimdall API (start `heimdall serve` first)
- `pnpm dev` — frontend only, in a plain browser (settings fall back to localStorage)
- `pnpm test` — Vitest + React Testing Library, API boundary mocked with MSW
- `pnpm typecheck` / `pnpm lint` — `tsc --noEmit`
- `pnpm build` — frontend production build (`tsc && vite build`)

## Layout

- `src/lib/api.ts` — typed fetch client over the heimdall HTTP API (the single seam)
- `src/lib/settings.ts` — server URL persisted via `tauri-plugin-store` (localStorage fallback outside Tauri)
- `src/hooks/use-heimdall.ts` — TanStack Query polling for `/health` + `/status`
- `src/components/status-view.tsx` — the "is everything in order" screen
- `src/test/msw/` — MSW handlers shaped off `tests/test_api.py` + the live API
- `src-tauri/` — thin Rust: window + tray + settings store plugin only
