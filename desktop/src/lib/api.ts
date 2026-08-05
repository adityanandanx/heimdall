import { dayBoundsISO, dayStrOf } from "@/lib/timeline";

export const DEFAULT_SERVER_URL = "http://127.0.0.1:3931";

export interface Health {
    status: string;
    version: string;
    db: string;
    uptime_s: number;
}

export interface MediaPlayer {
    name: string;
    status: string;
}

export interface WatchSession {
    session_id: number;
    player: string;
    media_title: string | null;
    media_source: string | null;
    ts_start: number;
    ts_end: number | null;
    transcript_source: string | null;
}

export interface ServerStatus {
    server: { status: string; version: string; uptime_s: number };
    db: { frames_today: number; size_bytes: number };
    capture: {
        alive: boolean;
        last_event_ts: string | null;
        extraction: string;
        ocr_also: string[];
        players: MediaPlayer[];
    };
    media: { last_session: WatchSession | null };
    asr: { queued: number; running: number; failed: number; items: unknown[] };
    llama: { reachable: boolean };
    tracing: { enabled: boolean; reason: string };
    pipes: { last_runs: Record<string, string | null> };
}

export interface Frame {
    id: number;
    ts: string;
    monitor: number | null;
    workspace: string | null;
    window_class: string;
    window_title: string | null;
    fullscreen: number;
    trigger: string;
    image_path: string;
    image_bytes: number | null;
    ocr_text: string | null;
    ocr_sec: number | null;
    ocr_engine: string | null;
    a11y_text: string | null;
    a11y_json: string | null;
}

export interface Session {
    id: number;
    player: string;
    media_title: string | null;
    media_source: string | null;
    media_id: string | null;
    ts_start: string;
    ts_end: string | null;
    pos_start: number | null;
    pos_end: number | null;
    length: number | null;
    ranges: number[][];
    live: number;
    cues_json: string | null;
    transcript: string | null;
    transcript_source: string | null;
    kind?: "frame" | "session";
}

export interface SearchItem {
    id: number;
    ts: string;
    window_class: string;
    window_title: string | null;
    workspace: number | null;
    image_path: string;
    snippet: string;
    score: number;
    kind: "frame" | "session";
}

export interface PipeRunResult {
    pipe: string;
    ts: string;
    run_ms: number;
    output_markdown: string;
    output_path: string;
    trace_url: string | null;
    frame_count: number;
}

export class ApiError extends Error {}

export function apiUrl(base: string, path: string): string {
    return `${base.replace(/\/+$/, "")}${path}`;
}

export async function fetchJson<T>(url: string, signal?: AbortSignal): Promise<T> {
    const res = await fetch(url, { signal });
    if (!res.ok) {
        throw new ApiError(`${res.status} ${res.statusText}`);
    }
    return (await res.json()) as T;
}

export function frameImageUrl(base: string, frameId: number): string {
    return apiUrl(base, `/frames/${frameId}/image`);
}

async function fetchAll<T>(base: string, path: string, params: URLSearchParams): Promise<T[]> {
    const out: T[] = [];
    let offset = 0;
    let total = Infinity;
    while (offset < total) {
        const q = new URLSearchParams(params);
        q.set("offset", String(offset));
        q.set("limit", "100");
        const body = await fetchJson<{ total: number; items: T[] }>(apiUrl(base, path) + `?${q}`);
        const items = body.items || [];
        out.push(...items);
        total = body.total ?? out.length;
        if (!items.length) break;
        offset += items.length;
    }
    return out;
}

export function fetchDayFrames(base: string, day: string): Promise<Frame[]> {
    const { start, end } = dayBoundsISO(day);
    const params = new URLSearchParams({ start, end, order: "asc" });
    return fetchAll<Frame>(base, "/frames", params);
}

export function fetchDaySessions(base: string, day: string): Promise<Session[]> {
    const { start, end } = dayBoundsISO(day);
    const params = new URLSearchParams({ start, end });
    return fetchAll<Session>(base, "/sessions", params);
}

export async function fetchRecentSessions(base: string, days = 7): Promise<Session[]> {
    const out = new Map<number, Session>();
    for (let i = 0; i < days; i++) {
        const d = new Date();
        d.setDate(d.getDate() - i);
        const items = await fetchDaySessions(base, dayStrOf(d));
        for (const s of items) out.set(s.id, s);
    }
    return [...out.values()].sort(
        (a, b) => new Date(b.ts_start).getTime() - new Date(a.ts_start).getTime(),
    );
}

export function fetchSearch(
    base: string,
    params: URLSearchParams,
    signal?: AbortSignal,
): Promise<SearchItem[]> {
    const full = new URLSearchParams(params);
    if (!full.has("limit")) full.set("limit", "100");
    return fetchJson<{ total: number; items: SearchItem[] }>(
        apiUrl(base, "/search") + `?${full}`,
        signal,
    ).then((body) => body.items);
}

export async function runPipe(base: string, name: string, day: string): Promise<PipeRunResult> {
    const res = await fetch(
        apiUrl(base, `/pipes/run/${name}`) + `?day=${encodeURIComponent(day)}`,
        { method: "POST" },
    );
    if (!res.ok) {
        let detail = `${res.status} ${res.statusText}`;
        try {
            const body = (await res.json()) as { detail?: unknown };
            if (body?.detail) detail = String(body.detail);
        } catch {
            /* keep status text */
        }
        throw new ApiError(detail);
    }
    return (await res.json()) as PipeRunResult;
}