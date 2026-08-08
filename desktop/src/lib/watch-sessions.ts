import type { Session } from "@/lib/api";
import { sessionWatchedSec, tsMs } from "@/lib/timeline";

/** Merge overlapping/sorted watched ranges (µs pairs) into disjoint segments. */
export function mergeRangesUs(ranges: number[][]): number[][] {
    const sorted = [...ranges]
        .filter(([a, b]) => b > a)
        .sort((a, b) => a[0] - b[0]);
    const out: number[][] = [];
    for (const [s, e] of sorted) {
        const last = out[out.length - 1];
        if (last && s <= last[1]) last[1] = Math.max(last[1], e);
        else out.push([s, e]);
    }
    return out;
}

const SOURCE_LABELS: Record<string, string> = {
    "youtube.com": "YouTube",
    "m.youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "netflix.com": "Netflix",
    "spotify.com": "Spotify",
    "twitch.tv": "Twitch",
    "vimeo.com": "Vimeo",
    "primevideo.com": "Prime Video",
    "disneyplus.com": "Disney+",
    "soundcloud.com": "SoundCloud",
    "bandcamp.com": "Bandcamp",
};

/** Human label for a media source URL ("https://www.youtube.com/watch?v=…" → "YouTube"). */
export function sourceLabelOf(source: string | null | undefined): string {
    if (!source) return "No source";
    try {
        const host = new URL(source).hostname.replace(/^www\./, "");
        return SOURCE_LABELS[host] ?? host;
    } catch {
        return "No source";
    }
}

/** The openable URL for a session: its media_source href, else a constructed
 * YouTube link from media_id, else none (title-only/local media). */
export function openUrlOf(s: Session): string | null {
    if (s.media_source) return s.media_source;
    if (s.media_id) return `https://www.youtube.com/watch?v=${s.media_id}`;
    return null;
}

export interface VideoGroup {
    key: string;
    source: string | null;
    sourceLabel: string;
    mediaId: string | null;
    title: string;
    players: string[];
    count: number;
    watchedSec: number;
    lengthUs: number;
    /** Merged, disjoint watched segments in µs, normalized against lengthUs. */
    rangesUs: number[][];
    /** Percentage of the video length covered by watched ranges; null when no length. */
    coveragePct: number | null;
    /** Playback position at the end of the most recent session (µs), if known. */
    lastPosUs: number | null;
    lastTs: number;
    isLive: boolean;
    words: number;
    openUrl: string | null;
    sessions: Session[];
}

export interface SourceGroup {
    label: string;
    videos: VideoGroup[];
}

/** Group sessions by video (media_source URL; player|title for title-only
 * sessions), then by source label, newest video first. */
export function groupSessionsBySource(sessions: Session[]): SourceGroup[] {
    const videos = new Map<string, VideoGroup>();
    for (const s of sessions) {
        const key = s.media_source ?? `${s.player}|${s.media_title ?? ""}`;
        let v = videos.get(key);
        if (!v) {
            v = {
                key,
                source: s.media_source ?? null,
                sourceLabel: sourceLabelOf(s.media_source),
                mediaId: s.media_id ?? null,
                title: s.media_title ?? "(untitled)",
                players: [],
                count: 0,
                watchedSec: 0,
                lengthUs: 0,
                rangesUs: [],
                coveragePct: null,
                lastPosUs: null,
                lastTs: 0,
                isLive: false,
                words: 0,
                openUrl: openUrlOf(s),
                sessions: [],
            };
            videos.set(key, v);
        }
        v.sessions.push(s);
        v.count += 1;
        v.watchedSec += sessionWatchedSec(s);
        v.lengthUs = Math.max(v.lengthUs, s.length ?? 0);
        v.rangesUs.push(...(s.ranges ?? []));
        v.words += (s.transcript ?? "").split(/\s+/).filter(Boolean).length;
        v.isLive = v.isLive || s.live === 1;
        if (!v.players.includes(s.player)) v.players.push(s.player);
        const t = tsMs(s.ts_start);
        if (t > v.lastTs) {
            v.lastTs = t;
            v.lastPosUs = s.pos_end ?? s.pos_start ?? null;
        }
    }

    for (const v of videos.values()) {
        v.rangesUs = mergeRangesUs(v.rangesUs);
        if (v.lengthUs > 0) {
            const covered = v.rangesUs.reduce((a, [x, y]) => a + (y - x), 0);
            // #1: backend sanitization clamps ranges to length, but clamp here
            // too so badges can never show >100% even for legacy/corrupt data.
            v.coveragePct = Math.min(100, Math.round((covered / v.lengthUs) * 100));
        }
        v.sessions.sort((a, b) => tsMs(a.ts_start) - tsMs(b.ts_start));
    }

    const byLabel = new Map<string, VideoGroup[]>();
    for (const v of videos.values()) {
        const list = byLabel.get(v.sourceLabel);
        if (list) list.push(v);
        else byLabel.set(v.sourceLabel, [v]);
    }
    return [...byLabel.entries()]
        .map(([label, list]) => ({
            label,
            videos: list.sort((a, b) => b.lastTs - a.lastTs),
        }))
        .sort((a, b) => b.videos[0].lastTs - a.videos[0].lastTs);
}

// ---------------------------------------------------------------------------
// Caption cues (backend shape: video-time ms {start_ms, end_ms, text})
// ---------------------------------------------------------------------------

export interface CueSegment {
    startMs: number;
    endMs: number;
    text: string;
}

export function sessionCues(s: Session): CueSegment[] {
    if (!s.cues_json) return [];
    try {
        const raw = JSON.parse(s.cues_json) as Array<{
            start_ms?: number;
            end_ms?: number;
            text?: string;
        }>;
        if (!Array.isArray(raw)) return [];
        return raw
            .filter((c) => typeof c.text === "string" && Number.isFinite(c.start_ms as number))
            .map((c) => ({
                startMs: c.start_ms as number,
                endMs: Number.isFinite(c.end_ms as number)
                    ? (c.end_ms as number)
                    : (c.start_ms as number),
                text: c.text as string,
            }));
    } catch {
        return [];
    }
}

/** Cues across all of a video's sessions, deduped and sorted by video time. */
export function unifiedCues(sessions: Session[]): CueSegment[] {
    const seen = new Set<string>();
    const out: CueSegment[] = [];
    for (const s of sessions) {
        for (const c of sessionCues(s)) {
            const key = `${c.startMs}|${c.text}`;
            if (seen.has(key)) continue;
            seen.add(key);
            out.push(c);
        }
    }
    out.sort((a, b) => a.startMs - b.startMs);
    return out;
}

/** "2:05"-style video-time label for a cue. */
export function cueTimeFmt(ms: number): string {
    const s = Math.floor(ms / 1000);
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function isYoutubeUrl(url: string | null | undefined): boolean {
    if (!url) return false;
    try {
        const host = new URL(url).hostname.replace(/^www\.|^m\./, "");
        return host === "youtube.com" || host === "youtu.be";
    } catch {
        return false;
    }
}

/** The YT playback link for a cue — the same URL with a `t=<sec>s` param. */
export function youtubeUrlAt(url: string, ms: number): string {
    if (!isYoutubeUrl(url)) return url;
    try {
        const u = new URL(url);
        u.searchParams.set("t", `${Math.floor(ms / 1000)}s`);
        return u.toString();
    } catch {
        return url;
    }
}
