import { http, HttpResponse } from "msw";
import { localISO } from "@/lib/timeline";

export const healthPayload = {
    status: "ok",
    version: "0.1.0",
    db: "ok",
    uptime_s: 7630,
};

export const statusPayload = {
    server: { status: "ok", version: "0.1.0", uptime_s: 7630 },
    db: { frames_today: 412, size_bytes: 10891264 },
    capture: {
        alive: true,
        last_event_ts: "2026-08-05T03:09:49+05:30",
        extraction: "auto",
        ocr_also: [],
        players: [
            { name: "chromium.instance1208", status: "playing" },
            { name: "sidra", status: "stopped" },
        ],
    },
    media: {
        last_session: {
            session_id: 505,
            player: "chromium",
            media_title: "Uncle Roger Review THE MOST DIFFICULT OMELET (Omurice)",
            media_source: null,
            ts_start: 1785879570118,
            ts_end: 1785879590859,
            transcript_source: null,
        },
    },
    asr: { queued: 0, running: 0, failed: 0, items: [] },
    llama: { reachable: true },
    tracing: { enabled: false, reason: "LANGFUSE_* env vars unset" },
    pipes: { last_runs: { "day-recap": null, "time-breakdown": null } },
};

export const capturedStatus = (overrides: Record<string, unknown> = {}) => {
    const base = statusPayload as unknown as Record<string, unknown>;
    const merged: Record<string, unknown> = { ...base };
    for (const key of Object.keys(overrides)) {
        const baseVal = base[key];
        const override = overrides[key];
        merged[key] =
            baseVal !== null &&
            typeof baseVal === "object" &&
            !Array.isArray(baseVal) &&
            override !== null &&
            typeof override === "object"
                ? { ...(baseVal as object), ...(override as object) }
                : override;
    }
    return merged as typeof statusPayload;
};

export const base = "http://127.0.0.1:3931";

export const today = new Date();
export const fixtureDay = localISO(today).slice(0, 10);

const at = (h: number, m = 0) =>
    new Date(today.getFullYear(), today.getMonth(), today.getDate(), h, m, 0, 0);

export const frameFixtures = [
    { id: 1, ts: at(9, 0), window_class: "code.editor", window_title: "timeline.ts — heimdall", workspace: "3:3", ocr_text: "axis of frames", a11y_text: null },
    { id: 2, ts: at(9, 15), window_class: "browser", window_title: "Heimdall docs", workspace: "3:3", ocr_text: "readme", a11y_text: "Heimdall documentation" },
    { id: 3, ts: at(9, 30), window_class: "terminal", window_title: "~/.local/bin", workspace: "2:1", ocr_text: "pnpm test", a11y_text: null },
    { id: 4, ts: at(9, 45), window_class: "code.editor", window_title: "scrubber.tsx", workspace: "3:3", ocr_text: "pointer events", a11y_text: null },
    { id: 5, ts: at(10, 0), window_class: "browser", window_title: "YouTube — omurice", workspace: "3:3", ocr_text: "video", a11y_text: null },
    { id: 6, ts: at(10, 30), window_class: "browser", window_title: "YouTube — omurice", workspace: "3:3", ocr_text: "video", a11y_text: null },
    { id: 7, ts: at(11, 0), window_class: "browser", window_title: "YouTube — omurice", workspace: "3:3", ocr_text: "video", a11y_text: null },
    { id: 8, ts: at(11, 30), window_class: "code.editor", window_title: "routers.py", workspace: "3:3", ocr_text: "search endpoint", a11y_text: null },
    { id: 9, ts: at(12, 0), window_class: "terminal", window_title: "~/.local/bin", workspace: "2:1", ocr_text: "git push", a11y_text: null },
    { id: 10, ts: at(12, 30), window_class: "code.editor", window_title: "watch-lane.tsx", workspace: "3:3", ocr_text: "watched ranges", a11y_text: null },
].map((f) => ({
    id: f.id,
    ts: localISO(f.ts),
    monitor: 0,
    workspace: f.workspace,
    window_class: f.window_class,
    window_title: f.window_title,
    fullscreen: 0,
    trigger: "interval",
    image_path: `/tmp/heimdall/frames/${f.id}.png`,
    image_bytes: 8642,
    ocr_text: f.ocr_text,
    ocr_sec: 0.8,
    ocr_engine: "easyocr",
    a11y_text: f.a11y_text,
    a11y_json: null,
}));

export const sessionFixtures = [
    {
        id: 21,
        player: "sidra",
        media_title: "Omurice — Uncle Roger",
        media_source: "https://www.youtube.com/watch?v=omurice123",
        media_id: "omurice123",
        ts_start: localISO(at(10, 0)),
        ts_end: localISO(at(13, 50)),
        pos_start: 100000000,
        pos_end: 1050000000,
        length: 2150000000,
        ranges: [[5000000, 8000000], [45000000, 70000000]],
        live: 0,
        cues_json: JSON.stringify([
            { start_ms: 120000, end_ms: 125000, text: "the most difficult omelet" },
            { start_ms: 900000, end_ms: 900800, text: "fuiyoh" },
        ]),
        transcript: "Fuiyoh! He say uncle roger review the most difficult omelet...",
        transcript_source: "whisper",
    },
    {
        id: 22,
        player: "chromium",
        media_title: "Some dev video",
        media_source: "https://www.youtube.com/watch?v=devlive456",
        media_id: "devlive456",
        ts_start: localISO(at(12, 0)),
        ts_end: null,
        pos_start: 0,
        pos_end: null,
        length: null,
        ranges: [[1000000, 3000000]],
        live: 1,
        cues_json: null,
        transcript: null,
        transcript_source: null,
    },
    {
        id: 24,
        player: "sidra",
        media_title: "Omurice — Uncle Roger",
        media_source: "https://www.youtube.com/watch?v=omurice123",
        media_id: "omurice123",
        ts_start: localISO(at(13, 20)),
        ts_end: localISO(at(13, 40)),
        pos_start: 55000000,
        pos_end: 80000000,
        length: 2150000000,
        ranges: [[60000000, 85000000]],
        live: 0,
        cues_json: JSON.stringify([
            { start_ms: 600000, end_ms: 600800, text: "fuiyoh so good" },
        ]),
        transcript: "fuiyoh so good",
        transcript_source: "whisper",
    },
    {
        id: 25,
        player: "vlc",
        media_title: "local film.mkv",
        media_source: null,
        media_id: null,
        ts_start: localISO(at(14, 0)),
        ts_end: localISO(at(15, 30)),
        pos_start: 1000000,
        pos_end: 30000000,
        length: 1800000000,
        ranges: [[1000000, 30000000]],
        live: 0,
        cues_json: null,
        transcript: null,
        transcript_source: null,
    },
];

export const searchFixtures = [
    {
        id: 2,
        ts: localISO(at(9, 15)),
        window_class: "browser",
        window_title: "Heimdall docs",
        workspace: 1,
        monitor: 0,
        fullscreen: 0,
        image_path: "/tmp/heimdall/frames/2.png",
        snippet: "Heimdall **documentation** in browser",
        score: 1.9,
        kind: "frame",
    },
    {
        id: 3,
        ts: localISO(at(11, 0)),
        window_class: "browser",
        window_title: "PNG spec",
        workspace: 2,
        monitor: 1,
        fullscreen: 1,
        image_path: "/tmp/heimdall/frames/3.png",
        snippet: "portable network graphics — **images**",
        score: 0.7,
        kind: "frame",
    },
    {
        id: 4,
        ts: localISO(at(14, 0)),
        window_class: "terminal",
        window_title: "htop",
        workspace: 1,
        monitor: 0,
        fullscreen: 0,
        image_path: "/tmp/heimdall/frames/4.png",
        snippet: "process **monitor** — pid column",
        score: 0.5,
        kind: "frame",
    },
    {
        id: 21,
        ts: localISO(at(10, 0)),
        window_class: null,
        window_title: "Omurice — Uncle Roger",
        workspace: 1,
        image_path: "",
        snippet: "uncle roger review the most difficult **omelet**",
        score: 1.4,
        kind: "session",
        player: "sidra",
    },
    {
        id: 23,
        ts: localISO(at(13, 0)),
        window_class: null,
        window_title: "Rust borrow checker deep dive",
        workspace: 1,
        image_path: "",
        snippet: "**borrow** checker explained with lifetimes",
        score: 0.9,
        kind: "session",
        player: "vlc",
    },
];

type SearchFixture = (typeof searchFixtures)[number];

/** Extra search fixtures tests can push for pagination coverage (#61); the
 * /search handler pages over both fixture arrays. Reset in afterEach. */
export const searchFixtureExtras: SearchFixture[] = [];

// Which text source each search fixture won by, for the source= filter.
const searchSources: Record<number, "a11y" | "ocr" | "session"> = {
    2: "a11y",
    3: "ocr",
    4: "ocr",
    21: "session",
    23: "session",
};

/** Every /search request the UI made this session (URL strings), for tests. */
export const searchRequestUrls: string[] = [];

/** Every /search/facets request the UI made this session, for tests. */
export const searchFacetsRequestUrls: string[] = [];

/** Delay applied to /search responses, so tests can exercise in-flight races. */
let searchResponseDelayMs = 0;

export function setSearchResponseDelay(ms: number) {
    searchResponseDelayMs = ms;
}

/** Every /frames request the UI made this session, for tests. */
export const frameRequestUrls: string[] = [];

export const pipesPayload = {
    "day-recap": {
        pipe: "day-recap",
        ts: localISO(at(13, 0)),
        run_ms: 2311,
        output_markdown: "# Recap\n\nA good day.\n\n- **two** hours of focus\n- one video\n\n```\ncode\n```\n",
        output_path: `/tmp/heimdall/recaps/day-recap-${fixtureDay}.md`,
        trace_url: "https://cloud.langfuse.com/project/xyz/trace/abc",
        frame_count: 10,
    },
    "time-breakdown": {
        pipe: "time-breakdown",
        ts: localISO(at(13, 5)),
        run_ms: 940,
        output_markdown: "| app | minutes |\n|---|---|\n| code.editor | 90 |\n",
        output_path: `/tmp/heimdall/recaps/time-breakdown-${fixtureDay}.md`,
        trace_url: "",
        frame_count: 10,
    },
};

const PNG_1PX = new Uint8Array([
    0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52,
    0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x06, 0x00, 0x00, 0x00, 0x1f, 0x15, 0xc4,
    0x89, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9c, 0x62, 0x00, 0x01, 0x00, 0x00,
    0x05, 0x00, 0x01, 0x0d, 0x0a, 0x2d, 0xb4, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4e, 0x44, 0xae,
    0x42, 0x60, 0x82,
]);

export const handlers = [
    http.get(`${base}/health`, () => HttpResponse.json(healthPayload)),
    http.get(`${base}/status`, () => HttpResponse.json(statusPayload)),
    http.get(`${base}/frames`, ({ request }) => {
        frameRequestUrls.push(request.url);
        const url = new URL(request.url);
        const start = url.searchParams.get("start");
        const end = url.searchParams.get("end");
        let items = frameFixtures;
        if (start) items = items.filter((f) => f.ts >= start);
        if (end) items = items.filter((f) => f.ts < end);
        const order = url.searchParams.get("order") ?? "asc";
        if (order === "desc") items = [...items].reverse();
        const offset = Number(url.searchParams.get("offset") ?? 0);
        const limit = Number(url.searchParams.get("limit") ?? 100);
        return HttpResponse.json({
            total: items.length,
            items: items.slice(offset, offset + limit),
        });
    }),
    http.get(`${base}/sessions`, ({ request }) => {
        const url = new URL(request.url);
        const start = url.searchParams.get("start");
        const end = url.searchParams.get("end");
        let items = sessionFixtures;
        if (start) items = items.filter((s) => s.ts_end === null || s.ts_end > start);
        if (end) items = items.filter((s) => s.ts_start < end);
        return HttpResponse.json({ total: items.length, items });
    }),
    http.get(`${base}/search`, async ({ request }) => {
        if (searchResponseDelayMs > 0) {
            await new Promise((resolve) => setTimeout(resolve, searchResponseDelayMs));
        }
        const url = new URL(request.url);
        searchRequestUrls.push(request.url);
        const q = url.searchParams.get("q")?.toLowerCase() ?? "";
        const kind = url.searchParams.get("kind");
        const source = url.searchParams.get("source");
        const start = url.searchParams.get("start");
        const end = url.searchParams.get("end");
        const workspace = url.searchParams.get("workspace");
        const monitor = url.searchParams.get("monitor");
        const fullscreen = url.searchParams.get("fullscreen");
        const offset = Number(url.searchParams.get("offset") ?? 0);
        const limit = Number(url.searchParams.get("limit") ?? 100);
        let items = [...searchFixtures, ...searchFixtureExtras].filter((s) =>
            (s.snippet + s.window_class + (s.window_title ?? "")).toLowerCase().includes(q),
        );
        if (kind === "frame") items = items.filter((s) => s.kind === "frame");
        if (kind === "session") items = items.filter((s) => s.kind === "session");
        if (source === "a11y") items = items.filter((s) => searchSources[s.id] === "a11y");
        if (source === "ocr") items = items.filter((s) => searchSources[s.id] === "ocr");
        if (source === "transcript") items = items.filter((s) => searchSources[s.id] === "session");
        // Frame attributes apply to frames only; sessions never match (#63).
        if (workspace) items = items.filter((s) => s.kind === "session" || s.workspace === Number(workspace));
        if (monitor) items = items.filter((s) => s.kind === "session" || s.monitor === Number(monitor));
        if (fullscreen) items = items.filter((s) => s.kind === "session" || s.fullscreen === (fullscreen === "true" ? 1 : 0));
        if (start) items = items.filter((s) => s.ts >= start);
        if (end) items = items.filter((s) => s.ts <= end);
        items = [...items].sort((a, b) => (a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0));
        const page = items.slice(offset, offset + limit);
        return HttpResponse.json({ total: items.length, items: page });
    }),
    http.get(`${base}/search/facets`, ({ request }) => {
        const url = new URL(request.url);
        searchFacetsRequestUrls.push(request.url);
        const q = url.searchParams.get("q")?.toLowerCase() ?? "";
        const kind = url.searchParams.get("kind");
        const start = url.searchParams.get("start");
        const end = url.searchParams.get("end");
        const workspace = url.searchParams.get("workspace");
        const monitor = url.searchParams.get("monitor");
        const inScope = (s: SearchFixture) =>
            (kind ? s.kind === kind : true) &&
            (s.snippet + s.window_class + (s.window_title ?? "")).toLowerCase().includes(q) &&
            (!start || s.ts >= start) &&
            (!end || s.ts <= end);
        const topFacets = (rows: SearchFixture[], key: (s: SearchFixture) => string) => {
            const counts = new Map<string, number>();
            for (const row of rows) {
                const value = key(row);
                counts.set(value, (counts.get(value) ?? 0) + 1);
            }
            return [...counts.entries()]
                .map(([value, count]) => ({ value, count }))
                .sort((a, b) => b.count - a.count || (a.value < b.value ? -1 : 1))
                .slice(0, 25);
        };
        const scoped = searchFixtures.filter(inScope);
        // Classic faceting: workspace narrows the *other* frame dimensions
        // (apps, monitors) but never its own facet, and vice versa (#63).
        const frames = scoped.filter((s) => s.kind === "frame");
        const inWorkspace = (s: SearchFixture) => !workspace || s.workspace === Number(workspace);
        const inMonitor = (s: SearchFixture) => !monitor || s.monitor === Number(monitor);
        return HttpResponse.json({
            apps: topFacets(frames.filter(inWorkspace).filter(inMonitor), (s) => s.window_class ?? ""),
            players: topFacets(scoped.filter((s) => s.kind === "session"), (s) => s.player ?? s.window_class ?? ""),
            workspaces: topFacets(frames.filter(inMonitor), (s) => String(s.workspace)),
            monitors: topFacets(frames.filter(inWorkspace), (s) => String(s.monitor)),
        });
    }),
    http.post(`${base}/pipes/run/:name`, ({ params }) => {
        const name = params.name as keyof typeof pipesPayload;
        return HttpResponse.json(pipesPayload[name] ?? { detail: "unknown pipe" }, {
            status: name ? 200 : 404,
        });
    }),
    http.get(`${base}/frames/:id/image`, () =>
        HttpResponse.arrayBuffer(PNG_1PX.buffer as ArrayBuffer, {
            headers: { "Content-Type": "image/png" },
        }),
    ),
];