// Pure timeline geometry for the day browser — ported from the v3 prototype.
// All functions are side-effect free so the collapsed-axis math is unit-testable.
// The axis compresses stretches with no captures (gap > OFF_MIN_MS, i.e. laptop
// off / idle) into a fixed-width marker, so the timeline only shows real activity.

export const OFF_MIN_MS = 8 * 60 * 1000;
export const GAP_W = 14;

export interface Span {
    a: number; // start epoch ms
    b: number; // end epoch ms
    off: boolean;
    x0: number; // canvas px
    x1: number;
}

export function tsMs(ts: string | number): number {
    return typeof ts === "number" ? ts : new Date(ts).getTime();
}

export function buildAxis(frames: Array<{ ts: string }>, ppm: number): Span[] {
    const spans: Span[] = [];
    let x = 0;
    for (let i = 0; i < frames.length - 1; i++) {
        const a = tsMs(frames[i].ts);
        const b = tsMs(frames[i + 1].ts);
        const off = b - a > OFF_MIN_MS;
        const w = off ? GAP_W : ((b - a) / 60000) * ppm;
        spans.push({ a, b, off, x0: x, x1: x + w });
        x += w;
    }
    return spans;
}

export function axisWidth(axis: Span[]): number {
    return axis.length ? axis[axis.length - 1].x1 : 0;
}

/** Canvas x for a timestamp, through the collapsed axis. */
export function axisOf(axis: Span[], ts: string | number): number {
    const t = tsMs(ts);
    if (!axis.length) return 0;
    let lo = 0;
    let hi = axis.length;
    while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (axis[mid].a <= t) lo = mid + 1;
        else hi = mid;
    }
    const s = axis[Math.max(0, lo - 1)];
    if (t <= s.a) return s.x0;
    if (t >= s.b) return s.x1;
    return s.x0 + ((t - s.a) / (s.b - s.a)) * (s.x1 - s.x0);
}

/** Timestamp (epoch ms) for a canvas x, through the collapsed axis. */
export function tsOf(axis: Span[], x: number): number {
    x = Math.max(0, Math.min(x, axisWidth(axis)));
    if (!axis.length) return 0;
    let lo = 0;
    let hi = axis.length;
    while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (axis[mid].x1 <= x) lo = mid + 1;
        else hi = mid;
    }
    const s = axis[Math.min(Math.max(lo, 0), axis.length - 1)];
    return s.a + ((x - s.x0) / (s.x1 - s.x0)) * (s.b - s.a);
}

export function frameNear<T extends { ts: string }>(frames: T[], t: number): T {
    let best = frames[0];
    let bd = Infinity;
    for (const f of frames) {
        const d = Math.abs(tsMs(f.ts) - t);
        if (d < bd) {
            bd = d;
            best = f;
        }
    }
    return best;
}

export interface Chapter<T> {
    cls: string;
    frames: T[];
}

/** Consecutive runs of one window class, split when a gap exceeds OFF_MIN_MS. */
export function chapters<T extends { ts: string; window_class: string }>(frames: T[]): Chapter<T>[] {
    const out: Chapter<T>[] = [];
    for (const f of frames) {
        const last = out[out.length - 1];
        if (
            last &&
            last.cls === f.window_class &&
            tsMs(f.ts) - tsMs(last.frames[last.frames.length - 1].ts) <= OFF_MIN_MS
        ) {
            last.frames.push(f);
        } else {
            out.push({ cls: f.window_class, frames: [f] });
        }
    }
    return out;
}

const APP_SEMANTIC: Array<{ re: RegExp; color: string }> = [
    // Prototype color-coding: code → accent, browsers → ok, terminals → warn, media → warn.
    { re: /code|editor|ide|obsidian|notion/, color: "#61afef" },
    { re: /browser|chrome|chromium|firefox|brave|vivaldi|edge/, color: "#98c379" },
    { re: /term|bash|zsh|fish|ssh|alacritty|kitty|ghostty/, color: "#e5c07b" },
    { re: /sidra|spotify|music|lofi/, color: "#e5c07b" },
    { re: /vlc|mpv|video|youtube|plex/, color: "#37c2d6" },
    { re: /mail|gmail|thunderbird|telegram|whatsapp|discord|slack/, color: "#c07bff" },
];

const APP_PALETTE = ["#5b8cff", "#3ecf8e", "#f0b456", "#c07bff", "#ff7b9c", "#37c2d6", "#b0c2ff"];

export function clsColor(cls: string | null | undefined): string {
    cls = cls ?? "";
    for (const { re, color } of APP_SEMANTIC) {
        if (re.test(cls)) return color;
    }
    let h = 0;
    for (const ch of cls) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return APP_PALETTE[h % APP_PALETTE.length];
}

const PLAYER_COLORS: Record<string, string> = {
    chromium: "#ff6b6b",
    brave: "#f0a65b",
    sidra: "#3ecf8e",
    vlc: "#37c2d6",
};

export function playerColor(player: string | null | undefined): string {
    return PLAYER_COLORS[(player ?? "").split(".")[0]] ?? "#5b8cff";
}

export interface WatchSessionLike {
    player: string;
    media_title: string | null;
    media_source?: string | null;
    ts_start: string;
    ts_end: string | null;
    ranges: number[][];
    transcript?: string | null;
}

export function sessionWatchedSec(s: WatchSessionLike): number {
    return (s.ranges || []).reduce((a, [b, e]) => a + Math.max(0, e - b), 0) / 1e6;
}

export interface Run {
    player: string;
    title: string;
    start: number;
    end: number;
    watched_sec: number;
}

export interface LaneRun {
    run: Run;
    lane: number;
}

/**
 * Assign non-overlapping lanes (parallel rows) to media runs, first-fit by
 * end time — overlapping sessions (e.g. sidra music while YouTube is up)
 * stack into separate lanes so they render side by side, time-aligned.
 */
export function assignLanes(runs: Run[]): LaneRun[] {
    const sorted = [...runs].sort((a, b) => a.start - b.start);
    const ends: number[] = [];
    const out: LaneRun[] = [];
    for (const r of sorted) {
        let lane = ends.findIndex((end) => r.start >= end);
        if (lane === -1) {
            lane = ends.length;
            ends.push(0);
        }
        ends[lane] = r.end;
        out.push({ run: r, lane });
    }
    return out;
}

/** Contiguous media runs — a gap longer than OFF_MIN_MS splits a run. */
export function buildRuns(sessions: WatchSessionLike[]): Run[] {
    const runs: Run[] = [];
    const sorted = [...sessions].sort((a, b) => tsMs(a.ts_start) - tsMs(b.ts_start));
    for (const s of sorted) {
        const st = tsMs(s.ts_start);
        const en = s.ts_end ? tsMs(s.ts_end) : st;
        if (en < st) continue;
        let hit: Run | null = null;
        for (let j = runs.length - 1; j >= 0; j--) {
            const r = runs[j];
            if (r.player === s.player && r.title === (s.media_title ?? "(untitled)") && st - r.end <= OFF_MIN_MS) {
                hit = r;
                break;
            }
        }
        if (hit) {
            hit.end = Math.max(hit.end, en);
            hit.watched_sec += sessionWatchedSec(s);
        } else {
            runs.push({
                player: s.player,
                title: s.media_title ?? "(untitled)",
                start: st,
                end: en,
                watched_sec: sessionWatchedSec(s),
            });
        }
    }
    return runs;
}

export function fmtDur(sec: number): string {
    sec = Math.round(sec || 0);
    if (sec >= 3600) return `${Math.floor(sec / 3600)}h ${Math.round((sec % 3600) / 60)}m`;
    return `${Math.max(1, Math.round(sec / 60))}m`;
}

const p2 = (n: number) => String(n).padStart(2, "0");

export function dayStrOf(d: Date): string {
    return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`;
}

/** Shift a YYYY-MM-DD string by n days (safe across month/year boundaries). */
export function shiftDay(day: string, n: number): string {
    const d = new Date(`${day}T12:00:00`);
    d.setDate(d.getDate() + n);
    return dayStrOf(d);
}

/** ISO-8601 with the local timezone offset (the API rejects naive timestamps). */
export function localISO(d: Date): string {
    const off = -d.getTimezoneOffset();
    const sign = off >= 0 ? "+" : "-";
    const abs = Math.abs(off);
    return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}T${p2(d.getHours())}:${p2(
        d.getMinutes(),
    )}:${p2(d.getSeconds())}${sign}${p2(Math.floor(abs / 60))}:${p2(abs % 60)}`;
}

/**
 * Scroll position that brings the playhead into view: centers it when it
 * leaves the viewport (with a small edge margin), otherwise keeps the
 * current position. Clamped to the timeline's scroll limits.
 */
export function scrollToPlayhead(
    playheadX: number,
    viewW: number,
    limit: number,
    scrollLeft: number,
    margin = 8,
): number {
    if (playheadX < scrollLeft + margin || playheadX > scrollLeft + viewW - margin) {
        return Math.max(0, Math.min(playheadX - viewW / 2, limit));
    }
    return scrollLeft;
}

/** Day start/end for a YYYY-MM-DD string as local-midnight ISO strings. */
export function dayBoundsISO(day: string): { start: string; end: string } {
    const [y, m, d] = day.split("-").map(Number);
    const start = new Date(y, m - 1, d, 0, 0, 0, 0);
    const end = new Date(y, m - 1, d + 1, 0, 0, 0, 0);
    return { start: localISO(start), end: localISO(end) };
}

/** Aggregate sessions by player|title into the media summary (watched_s etc). */
export interface MediaSummary {
    player: string;
    title: string;
    src: string | null;
    watched_sec: number;
    tx: string;
}

export function aggregateMedia(sessions: WatchSessionLike[]): MediaSummary[] {
    const map = new Map<string, MediaSummary>();
    for (const s of sessions) {
        const k = `${s.player}|${s.media_title}`;
        let m = map.get(k);
        if (!m) {
            m = {
                player: s.player,
                title: s.media_title ?? "(untitled)",
                src: s.media_source ?? null,
                watched_sec: 0,
                tx: "",
            };
            map.set(k, m);
        }
        m.watched_sec += sessionWatchedSec(s);
        m.tx += s.transcript?.slice(0, 20000) ?? "";
    }
    return [...map.values()].sort((a, b) => b.watched_sec - a.watched_sec).slice(0, 30);
}