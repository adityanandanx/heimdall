import { describe, expect, it } from "vitest";
import {
    cueTimeFmt,
    groupSessionsBySource,
    isYoutubeUrl,
    mergeRangesUs,
    openUrlOf,
    sessionCues,
    sourceLabelOf,
    unifiedCues,
    youtubeUrlAt,
} from "./watch-sessions";
import { localISO } from "./timeline";

const session = (over: Record<string, unknown>) =>
    ({
        id: 1,
        player: "sidra",
        media_title: "T",
        media_source: null,
        media_id: null,
        ts_start: localISO(new Date()),
        ts_end: null,
        pos_start: 0,
        pos_end: null,
        length: 0,
        ranges: [],
        live: 0,
        cues_json: null,
        transcript: null,
        transcript_source: null,
        ...over,
    }) as never;

describe("mergeRangesUs", () => {
    it("sorts, merges overlaps and drops empties", () => {
        expect(mergeRangesUs([[10, 20], [15, 30], [0, 5], [5, 5]])).toEqual([
            [0, 5],
            [10, 30],
        ]);
    });
});

describe("sourceLabelOf", () => {
    it("maps known hosts and falls back to the hostname", () => {
        expect(sourceLabelOf("https://www.youtube.com/watch?v=x")).toBe("YouTube");
        expect(sourceLabelOf("https://youtu.be/x")).toBe("YouTube");
        expect(sourceLabelOf("https://netflix.com/watch/1")).toBe("Netflix");
        expect(sourceLabelOf("https://example.com/v")).toBe("example.com");
        expect(sourceLabelOf(null)).toBe("No source");
        expect(sourceLabelOf("not a url")).toBe("No source");
    });
});

describe("openUrlOf", () => {
    it("prefers media_source, falls back to a YouTube link from media_id", () => {
        expect(openUrlOf(session({ media_source: "https://netflix.com/w" }))).toBe(
            "https://netflix.com/w",
        );
        expect(openUrlOf(session({ media_source: null, media_id: "abc" }))).toBe(
            "https://www.youtube.com/watch?v=abc",
        );
        expect(openUrlOf(session({ media_source: null, media_id: null }))).toBeNull();
    });
});

describe("groupSessionsBySource", () => {
    it("merges same-URL sessions and orders groups newest-first", () => {
        const old = session({
            id: 1,
            media_title: "V",
            media_source: "https://www.youtube.com/watch?v=v",
            media_id: "v",
            ts_start: localISO(new Date(2026, 0, 1)),
            ranges: [[0, 10_000_000]],
            length: 1_000_000_000,
        });
        const fresh = session({
            id: 2,
            media_title: "V",
            media_source: "https://www.youtube.com/watch?v=v",
            media_id: "v",
            ts_start: localISO(new Date(2026, 0, 2)),
            ranges: [[5_000_000, 15_000_000]],
            length: 1_000_000_000,
            transcript: "a b c",
        });
        const local = session({
            id: 3,
            player: "vlc",
            media_title: "local",
            media_source: null,
            ts_start: localISO(new Date(2026, 0, 3)),
            ranges: [[0, 5_000_000]],
            length: 100_000_000,
        });

        const groups = groupSessionsBySource([local, old, fresh]);

        expect(groups.map((g) => g.label)).toEqual(["No source", "YouTube"]);

        const video = groups[1].videos[0];
        expect(video.count).toBe(2);
        expect(video.sessions.map((s) => s.id)).toEqual([1, 2]);
        expect(video.rangesUs).toEqual([[0, 15_000_000]]);
        expect(video.coveragePct).toBe(2);
        expect(video.watchedSec).toBe(20);
        expect(video.words).toBe(3);
        expect(video.openUrl).toBe("https://www.youtube.com/watch?v=v");
        expect(video.isLive).toBe(false);

        expect(groups[0].videos[0].title).toBe("local");
        expect(groups[0].videos[0].openUrl).toBeNull();
        expect(groups[0].videos[0].coveragePct).toBe(5);
    });

    it("never reports coverage above 100% even for legacy corrupt ranges (#1)", () => {
        const groups = groupSessionsBySource([
            session({
                media_id: "v",
                length: 100_000_000,
                ranges: [[200_000_000, 400_000_000], [0, 50_000_000]],
            }),
        ]);
        // 250M watched of a 100M video — clamped display, not 250%.
        expect(groups[0].videos[0].coveragePct).toBe(100);
    });
});

describe("cues", () => {
    const withCues = (cues: unknown[]) => session({ cues_json: JSON.stringify(cues) });

    it("parses the backend cue shape", () => {
        expect(
            sessionCues(withCues([
                { start_ms: 120000, end_ms: 125000, text: "hello" },
                { start_ms: 600000, text: "no end" },
                { start_ms: "x", text: "bad" },
                { text: "no start" },
            ])),
        ).toEqual([
            { startMs: 120000, endMs: 125000, text: "hello" },
            { startMs: 600000, endMs: 600000, text: "no end" },
        ]);
        expect(sessionCues(session({ cues_json: "{not json" }))).toEqual([]);
        expect(sessionCues(session({ cues_json: null }))).toEqual([]);
    });

    it("merges and sorts cues across sessions, deduping repeats", () => {
        const a = withCues([{ start_ms: 900000, end_ms: 901000, text: "later" }]);
        const b = withCues([
            { start_ms: 100000, end_ms: 101000, text: "earlier" },
            { start_ms: 900000, end_ms: 901000, text: "later" },
        ]);
        expect(unifiedCues([a, b])).toEqual([
            { startMs: 100000, endMs: 101000, text: "earlier" },
            { startMs: 900000, endMs: 901000, text: "later" },
        ]);
    });

    it("formats cue times and builds YouTube seek URLs", () => {
        expect(cueTimeFmt(125_000)).toBe("2:05");
        expect(cueTimeFmt(0)).toBe("0:00");
        expect(isYoutubeUrl("https://www.youtube.com/watch?v=x")).toBe(true);
        expect(isYoutubeUrl("https://youtu.be/x")).toBe(true);
        expect(isYoutubeUrl("https://netflix.com/w")).toBe(false);
        expect(isYoutubeUrl(null)).toBe(false);
        expect(youtubeUrlAt("https://www.youtube.com/watch?v=abc&x=1", 125_000)).toBe(
            "https://www.youtube.com/watch?v=abc&x=1&t=125s",
        );
        expect(youtubeUrlAt("https://youtu.be/abc", 90_000)).toBe("https://youtu.be/abc?t=90s");
        expect(youtubeUrlAt("https://netflix.com/w", 90_000)).toBe("https://netflix.com/w");
    });
});
