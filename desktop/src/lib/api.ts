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