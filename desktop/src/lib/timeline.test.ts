import { describe, expect, it } from "vitest";
import {
    aggregateMedia,
    assignLanes,
    axisOf,
    axisWidth,
    buildAxis,
    buildRuns,
    chapters,
    clsColor,
    dayBoundsISO,
    dayStrOf,
    fmtDur,
    frameNear,
    GAP_W,
    localISO,
    OFF_MIN_MS,
    playerColor,
    sessionWatchedSec,
    shiftDay,
    tsOf,
    type Run,
    type Span,
} from "@/lib/timeline";

const at = (h: number, m = 0) => new Date(2026, 7, 4, h, m, 30, 0);
const iso = (d: Date) => localISO(d);

// Gaps within a chapter are kept under OFF_MIN_MS so the class runs stay whole.
function mkFrames(): Array<{ id: number; ts: string; window_class: string }> {
    return [
        { id: 1, ts: iso(at(9, 0)), window_class: "code.editor" },
        { id: 2, ts: iso(at(9, 2)), window_class: "code.editor" },
        { id: 3, ts: iso(at(9, 4)), window_class: "code.editor" },
        { id: 4, ts: iso(at(9, 6)), window_class: "browser" },
        { id: 5, ts: iso(at(9, 8)), window_class: "browser" },
        { id: 6, ts: iso(at(9, 10)), window_class: "browser" },
        // off gap (>8 min) splits the class run
        { id: 7, ts: iso(at(11, 0)), window_class: "code.editor" },
        { id: 8, ts: iso(at(11, 2)), window_class: "code.editor" },
        { id: 9, ts: iso(at(11, 4)), window_class: "code.editor" },
        { id: 10, ts: iso(at(11, 6)), window_class: "code.editor" },
    ];
}

describe("buildAxis / axisWidth", () => {
    it("stretches active gaps by ppm and collapses off gaps to a fixed marker", () => {
        const frames = [
            { ts: iso(at(9, 0)) },
            { ts: iso(at(9, 1)) },
            { ts: iso(at(9, 30)) },
        ];
        const ppm = 10;
        const axis = buildAxis(frames, ppm);
        expect(axis[0]).toMatchObject({ off: false, x0: 0 });
        expect(axis[0].x1).toBe(10); // 1 min * 10 px/min
        expect(axis[1].off).toBe(true);
        expect(axis[1].x1 - axis[1].x0).toBe(GAP_W);
        expect(axisWidth(axis)).toBeCloseTo(10 + GAP_W, 5);
    });

    it("produces no spans for 0 or 1 frames", () => {
        expect(buildAxis([], 10)).toHaveLength(0);
        expect(buildAxis([{ ts: iso(at(9, 0)) }], 10)).toHaveLength(0);
    });
});

describe("axisOf / tsOf", () => {
    const axis = buildAxis(mkFrames().map((f) => ({ ts: f.ts })), 10);

    it("maps frame timestamps to increasing x positions", () => {
        const xs = mkFrames().map((f) => axisOf(axis, f.ts));
        for (let i = 1; i < xs.length; i++) expect(xs[i]).toBeGreaterThan(xs[i - 1]);
    });

    it("clamps timestamps before/after the axis", () => {
        expect(axisOf(axis, iso(at(8, 0)))).toBe(0);
        expect(axisOf(axis, iso(at(23, 0)))).toBeCloseTo(axisWidth(axis), 5);
    });

    it("round-trips timestamps through x", () => {
        for (const f of mkFrames()) {
            const x = axisOf(axis, f.ts);
            const t = tsOf(axis, x);
            expect(Math.abs(t - new Date(f.ts).getTime())).toBeLessThan(60_000);
        }
    });

    it("round-trips the span start at span edge", () => {
        const frames = mkFrames();
        const m0 = Math.round(tsOf(axis, 0));
        expect(Math.abs(m0 - new Date(frames[0].ts).getTime())).toBeLessThan(60_000);
    });
});

describe("frameNear", () => {
    const frames = mkFrames();

    it("picks the closest frame by time", () => {
        const target = new Date(at(9, 5)).getTime();
        expect(frameNear(frames, target).id).toBe(3);
        expect(frameNear(frames, new Date(at(8, 0)).getTime()).id).toBe(1);
    });
});

describe("chapters", () => {
    it("groups consecutive frames by window class", () => {
        const ch = chapters(mkFrames());
        expect(ch.map((c) => c.cls)).toEqual(["code.editor", "browser", "code.editor"]);
        expect(ch.map((c) => c.frames.length)).toEqual([3, 3, 4]);
    });

    it("splits a run when the gap exceeds OFF_MIN_MS even for the same class", () => {
        const frames = [
            { ts: iso(at(9, 0)), window_class: "code.editor" },
            { ts: iso(at(10, 30)), window_class: "code.editor" },
        ];
        const ch = chapters(frames);
        expect(ch).toHaveLength(2);
    });
});

describe("session helpers", () => {
    it("sessionWatchedSec sums the ranges", () => {
        expect(
            sessionWatchedSec({ ranges: [[1_000_000, 4_000_000], [10_000_000, 12_000_000]] } as never),
        ).toBe(5);
    });

    it("buildRuns merges adjacent sessions of the same title", () => {
        const runs = buildRuns([
            {
                player: "sidra",
                media_title: "A",
                ts_start: iso(at(9, 0)),
                ts_end: iso(at(9, 20)),
                ranges: [[1_000_000, 1_100_000]],
            },
            {
                player: "sidra",
                media_title: "A",
                ts_start: iso(at(9, 23)),
                ts_end: iso(at(9, 40)),
                ranges: [[1_000_000, 2_000_000]],
            },
            {
                player: "chromium",
                media_title: "B",
                ts_start: iso(at(10, 0)),
                ts_end: iso(at(10, 30)),
                ranges: [[1_000_000, 3_000_000]],
            },
        ]);
        expect(runs).toHaveLength(2);
        expect(runs[0]).toMatchObject({ player: "sidra", watched_sec: 1.1 });
        expect(runs[1]).toMatchObject({ player: "chromium", watched_sec: 2 });
    });

    it("buildRuns splits on an off gap regardless of title", () => {
        const runs = buildRuns([
            {
                player: "sidra",
                media_title: "A",
                ts_start: iso(at(9, 0)),
                ts_end: iso(at(9, 20)),
                ranges: [],
            },
            {
                player: "sidra",
                media_title: "A",
                ts_start: iso(at(11, 0)),
                ts_end: iso(at(11, 20)),
                ranges: [],
            },
        ]);
        expect(runs).toHaveLength(2);
    });

    it("aggregateMedia groups by player|title and sorts by watched time", () => {
        const media = aggregateMedia([
            {
                player: "sidra",
                media_title: "B",
                ts_start: iso(at(10, 0)),
                ts_end: iso(at(10, 30)),
                ranges: [[1_000_000, 3_000_000]],
            },
            {
                player: "chromium",
                media_title: "A",
                ts_start: iso(at(9, 0)),
                ts_end: iso(at(9, 40)),
                ranges: [[1_000_000, 5_000_000]],
            },
        ]);
        expect(media.map((m) => m.title)).toEqual(["A", "B"]);
        expect(media[0]).toMatchObject({ player: "chromium", watched_sec: 4 });
    });
});

describe("day helpers", () => {
    it("dayStrOf pads to YYYY-MM-DD", () => {
        expect(dayStrOf(new Date(2026, 7, 4))).toBe("2026-08-04");
    });

    it("shiftDay crosses month boundaries", () => {
        expect(shiftDay("2026-08-01", -1)).toBe("2026-07-31");
        expect(shiftDay("2026-08-31", 1)).toBe("2026-09-01");
        expect(shiftDay("2026-12-31", 1)).toBe("2027-01-01");
    });

    it("dayBoundsISO returns offset timestamps exactly a day apart", () => {
        const { start, end } = dayBoundsISO("2026-08-04");
        const ms = (s: string) => new Date(s).getTime();
        expect(ms(end) - ms(start)).toBe(24 * 60 * 60 * 1000);
        expect(Number.isNaN(ms(start))).toBe(false);
        expect(/\d{2}:\d{2}:\d{2}/.test(start.slice(11))).toBe(true);
    });

    it("localISO round-trips through Date", () => {
        const d = new Date(2026, 7, 4, 9, 30, 5, 0);
        expect(new Date(localISO(d)).getTime()).toBe(d.getTime());
    });
});

describe("colors & durations", () => {
    it("clsColor is deterministic and in bounds", () => {
        expect(clsColor("code.editor")).toBe(clsColor("code.editor"));
        expect(clsColor("anything")).toMatch(/^#[0-9a-f]{6}$/);
        expect(clsColor("a")).not.toBe(clsColor("b"));
    });

    it("clsColor maps common classes to the prototype palette", () => {
        expect(clsColor("code.editor")).toBe("#61afef"); // accent
        expect(clsColor("browser")).toBe("#98c379"); // ok
        expect(clsColor("terminal")).toBe("#e5c07b"); // warn
        expect(clsColor("google-chrome")).toBe("#98c379");
        expect(clsColor("sidra")).toBe("#e5c07b");
        expect(clsColor("vlc")).toBe("#37c2d6");
    });

    it("playerColor falls back for unknown players", () => {
        expect(playerColor("chromium")).toBe("#ff6b6b");
        expect(playerColor("unknown")).toMatch(/^#[0-9a-f]{6}$/);
    });

    it("fmtDur formats hours, minutes and seconds", () => {
        expect(fmtDur(0)).toBe("1m");
        expect(fmtDur(45)).toBe("1m");
        expect(fmtDur(3600)).toBe("1h 0m");
        expect(fmtDur(7260)).toBe("2h 1m");
    });
});

describe("assignLanes", () => {
    const run = (start: number, end: number): Run => ({
        player: "sidra",
        title: "x",
        start,
        end,
        watched_sec: 0,
    });
    const MIN = 60_000;

    it("keeps sequential runs on one lane", () => {
        const lanes = assignLanes([run(0, MIN), run(MIN, 2 * MIN), run(2 * MIN, 3 * MIN)]);
        expect(lanes.map((l) => l.lane)).toEqual([0, 0, 0]);
    });

    it("stacks overlapping runs onto parallel lanes", () => {
        const lanes = assignLanes([
            run(0, 5 * MIN), //  A ──────────
            run(2 * MIN, 4 * MIN), //   B ──── (overlaps A)
            run(4 * MIN, 6 * MIN), //     C ────── (overlaps B? starts when A still active)
        ]);
        expect(lanes.map((l) => l.lane)).toEqual([0, 1, 1]);
    });

    it("reuses a lane once the previous run ended", () => {
        const lanes = assignLanes([run(0, 3 * MIN), run(1 * MIN, 2 * MIN), run(3 * MIN, 4 * MIN)]);
        expect(lanes.map((l) => l.lane)).toEqual([0, 1, 0]);
    });

    it("never assigns overlapping runs the same lane", () => {
        const lanes = assignLanes([
            run(0, 10 * MIN),
            run(1 * MIN, 9 * MIN),
            run(2 * MIN, 8 * MIN),
            run(11 * MIN, 12 * MIN),
        ]);
        for (let i = 0; i < lanes.length; i++) {
            for (let j = i + 1; j < lanes.length; j++) {
                const a = lanes[i];
                const b = lanes[j];
                const overlap = a.run.start < b.run.end && b.run.start < a.run.end;
                if (overlap) expect(a.lane).not.toBe(b.lane);
            }
        }
        expect(new Set(lanes.map((l) => l.lane)).size).toBe(3);
    });
});

describe("geometry invariants", () => {
    it("spans are contiguous", () => {
        const axis = buildAxis(mkFrames().map((f) => ({ ts: f.ts })), 10);
        expect(axis[0].x0).toBe(0);
        for (let i = 1; i < axis.length; i++) {
            expect(axis[i].x0).toBeCloseTo(axis[i - 1].x1, 5);
        }
        expect(OFF_MIN_MS).toBe(8 * 60 * 1000);
        expect(axis.every((s: Span) => s.x1 >= s.x0)).toBe(true);
    });
});