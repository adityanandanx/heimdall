import { useLayoutEffect, useMemo, useRef } from "react";
import type { Frame, Session } from "@/lib/api";
import { formatTime } from "@/lib/format";
import {
    assignLanes,
    axisOf,
    axisWidth,
    buildAxis,
    buildRuns,
    clsColor,
    frameNear,
    playerColor,
    tsOf,
    tsMs,
    type Span,
} from "@/lib/timeline";
import { cn } from "@/lib/utils";

const MIN_PPM = 2;
const MAX_PPM = 120;
const DENSITY_BUCKETS = 48;

const DOTS_ROW_H = 32;
const LANE_H = 22;
const BLOCK_H = 14;

interface FilmstripProps {
    frames: Frame[];
    sessions: Session[];
    selected: Frame | null;
    onSelect: (f: Frame) => void;
    hits: Set<number> | null;
    filterCls: string | null;
    ppm: number;
    onPpmChange: (ppm: number) => void;
    onHover: (f: Frame | null) => void;
}

export function Filmstrip({ frames, sessions, selected, onSelect, hits, filterCls, ppm, onPpmChange, onHover }: FilmstripProps) {
    const axis = useMemo<Span[]>(() => (frames.length > 1 ? buildAxis(frames, ppm) : []), [frames, ppm]);
    const axisW = axisWidth(axis);

    const scrollRef = useRef<HTMLDivElement>(null);
    const timelineRef = useRef<HTMLDivElement>(null);
    const draggingRef = useRef(false);
    const anchorIdxRef = useRef(0);
    const anchorFracRef = useRef(0);
    const anchorKeepRef = useRef(-1);
    const hoverIdRef = useRef<number | null>(null);

    const density = useMemo(() => {
        if (!frames.length) return [] as number[];
        const start = tsMs(frames[0].ts);
        const end = tsMs(frames[frames.length - 1].ts);
        const span = Math.max(end - start, 1);
        const buckets = new Array<number>(DENSITY_BUCKETS).fill(0);
        for (const f of frames) {
            const i = Math.min(DENSITY_BUCKETS - 1, Math.floor(((tsMs(f.ts) - start) / span) * DENSITY_BUCKETS));
            buckets[i]++;
        }
        return buckets;
    }, [frames]);

    const maxDensity = Math.max(1, ...density);

    const runs = useMemo(() => buildRuns(sessions), [sessions]);
    const laneRuns = useMemo(() => assignLanes(runs), [runs]);
    const lanes = useMemo(
        () => laneRuns.reduce((m, l) => Math.max(m, l.lane + 1), 0),
        [laneRuns],
    );
    const players = useMemo(
        () => new Set(sessions.map((s) => s.player)).size,
        [sessions],
    );

    const timelineH = DOTS_ROW_H + lanes * LANE_H + 6;

    // Zoom-anchor: keep the span under the cursor stable across ppm changes.
    useLayoutEffect(() => {
        const el = scrollRef.current;
        if (!el || !axis.length || anchorKeepRef.current < 0) return;
        const idx = anchorIdxRef.current;
        const s = axis[Math.min(idx, axis.length - 1)];
        const target = s.x0 + anchorFracRef.current * (s.x1 - s.x0);
        el.scrollLeft = clamp(target - anchorKeepRef.current, 0, Math.max(0, axisW - el.clientWidth));
        anchorKeepRef.current = -1;
    }, [axis, axisW]);

    function zoomBy(factor: number, anchorClientX?: number) {
        const el = scrollRef.current;
        const timeline = timelineRef.current;
        if (!el || !timeline || !axis.length) return;
        const rect = timeline.getBoundingClientRect();
        const keep = anchorClientX != null ? anchorClientX - rect.left : el.clientWidth / 2;
        const oldX = keep + el.scrollLeft;
        let lo = 0;
        let hi = axis.length;
        while (lo < hi) {
            const mid = (lo + hi) >> 1;
            if (axis[mid].x1 <= oldX) lo = mid + 1;
            else hi = mid;
        }
        const idx = Math.min(lo, axis.length - 1);
        const s = axis[idx];
        const frac = s.x1 - s.x0 ? (oldX - s.x0) / (s.x1 - s.x0) : 0;
        anchorIdxRef.current = idx;
        anchorFracRef.current = frac;
        anchorKeepRef.current = keep;
        onPpmChange(clamp(Math.round(ppm * factor), MIN_PPM, MAX_PPM));
    }

    function frameAt(clientX: number) {
        const timeline = timelineRef.current;
        if (!timeline || !axis.length) return null;
        const rect = timeline.getBoundingClientRect();
        const x = clamp(clientX - rect.left, 0, axisW);
        return { f: frameNear(frames, tsOf(axis, x)), x };
    }

    function hover(clientX: number) {
        const hit = frameAt(clientX);
        if (!hit) return;
        if (hit.f.id !== hoverIdRef.current) {
            hoverIdRef.current = hit.f.id;
            onHover(hit.f);
        }
    }

    function seek(clientX: number) {
        const hit = frameAt(clientX);
        if (!hit) return;
        hoverIdRef.current = hit.f.id;
        onHover(hit.f);
        onSelect(hit.f);
    }

    const dayStart = frames[0]?.ts ?? null;
    const dayEnd = frames[frames.length - 1]?.ts ?? null;

    return (
        <div className="shrink-0 border-t border-line bg-surface px-5 pt-3.5 pb-4">
            <div className="mb-2.5 flex flex-wrap items-center gap-2.5">
                <span className="font-mono text-xs text-dim">
                    {dayStart ? formatTime(dayStart) : "—"}
                    <span className="text-faint"> — </span>
                    {dayEnd ? formatTime(dayEnd) : "—"}
                </span>
                <span className="ml-auto rounded-full border border-line px-2.5 py-0.5 text-[10px] text-faint">
                    ~{frames.length} frames
                </span>
                {players > 0 && (
                    <span className="rounded-full border border-ok/40 px-2 py-0.5 text-[10px] text-ok">
                        ▮▮ {players} player{players > 1 ? "s" : ""}
                    </span>
                )}
            </div>

            <div
                ref={scrollRef}
                className="overflow-x-auto overflow-y-hidden pb-1.5 [scrollbar-width:thin]"
            >
                <div className="relative" style={{ width: Math.max(axisW, 100) }}>
                    <div className="mb-2 flex h-6 items-end gap-0.5">
                        {density.map((n, i) => (
                            <div
                                key={i}
                                className={cn(
                                    "min-w-0.5 flex-1 rounded-t-[2px] bg-primary/28",
                                    n >= maxDensity * 0.6 && n > 0 && "bg-primary/75",
                                )}
                                style={{ height: n ? Math.max(3, Math.min(24, n * 2.2)) : 3 }}
                            />
                        ))}
                    </div>

                    <div
                        ref={timelineRef}
                        className="relative cursor-pointer touch-none overflow-hidden rounded-md border border-line bg-surface-2 select-none"
                        style={{ height: timelineH }}
                        data-testid="filmstrip-timeline"
                        onPointerDown={(e) => {
                            if (e.button !== 0) return;
                            draggingRef.current = true;
                            timelineRef.current?.setPointerCapture(e.pointerId);
                            seek(e.clientX);
                        }}
                        onPointerMove={(e) => {
                            if (draggingRef.current) seek(e.clientX);
                            else hover(e.clientX);
                        }}
                        onPointerUp={() => {
                            draggingRef.current = false;
                        }}
                        onPointerLeave={() => {
                            if (!draggingRef.current) {
                                hoverIdRef.current = null;
                                onHover(null);
                            }
                        }}
                        onPointerCancel={() => {
                            draggingRef.current = false;
                        }}
                        onWheel={(e) => {
                            let dx = e.deltaX;
                            let dy = e.deltaY;
                            if (e.deltaMode === 1) {
                                dx *= 16;
                                dy *= 16;
                            }
                            if (e.shiftKey && dy && !dx) {
                                dx = dy;
                                dy = 0;
                            }
                            const el = scrollRef.current;
                            if (el && Math.abs(dx) > 0) {
                                el.scrollLeft = clamp(el.scrollLeft + dx, 0, Math.max(0, axisW - el.clientWidth));
                            }
                            if (Math.abs(dy) > 0) {
                                zoomBy(dy < 0 ? 1.25 : 0.8, e.clientX);
                            }
                        }}
                    >
                        {/* No-activity (laptop off / idle) spans — dimmed striped blocks. */}
                        {axis.filter((s) => s.off).map((s) => (
                            <div
                                key={s.a}
                                className="pointer-events-none absolute top-0 bottom-0 rounded-[3px] bg-[repeating-linear-gradient(45deg,rgba(224,108,117,0.09)_0_6px,transparent_6px_12px)]"
                                style={{ left: s.x0, width: Math.max(s.x1 - s.x0, 1) }}
                            />
                        ))}

                        <div className="absolute inset-x-0 top-0 flex h-8 items-center">
                            {frames.map((f) => {
                                const sel = f.id === selected?.id;
                                const hit = hits?.has(f.id);
                                const muted = filterCls !== null && f.window_class !== filterCls;
                                return (
                                    <div
                                        key={f.id}
                                        className={cn(
                                            "absolute size-1.75 -translate-x-1/2 rounded-full ring-2 transition-[background,transform]",
                                            sel && "scale-[1.7]",
                                            hit && "ring-ok",
                                            sel && !hit && "ring-background/90",
                                            muted && "opacity-25",
                                        )}
                                        style={{
                                            left: axisOf(axis, f.ts),
                                            top: "50%",
                                            background: clsColor(f.window_class),
                                        }}
                                    />
                                );
                            })}
                        </div>

                        {laneRuns.map(({ run: r, lane }) => {
                            const a = axisOf(axis, r.start);
                            const b = Math.max(axisOf(axis, r.end), a + 8);
                            const music = r.player.split(".")[0] === "sidra";
                            const color = playerColor(r.player);
                            return (
                                <div
                                    key={`${r.player}|${r.title}|${r.start}`}
                                    className="absolute flex items-center overflow-hidden rounded-[4px] border"
                                    style={{
                                        left: a,
                                        width: Math.max(b - a, 8),
                                        top: DOTS_ROW_H + lane * LANE_H + 4,
                                        height: BLOCK_H,
                                        background: `color-mix(in srgb, ${color} 30%, transparent)`,
                                        borderColor: `color-mix(in srgb, ${color} 55%, transparent)`,
                                    }}
                                    title={`${r.player} — ${r.title}`}
                                >
                                    <span
                                        className="truncate px-1.5 text-[9px] whitespace-nowrap"
                                        style={{ color }}
                                    >
                                        {music ? "♫ " : "▶ "}
                                        {r.title}
                                    </span>
                                </div>
                            );
                        })}

                        {selected && axis.length > 0 && (
                            <div
                                className="pointer-events-none absolute top-[-4px] bottom-[-4px] z-10 w-0.5 bg-primary"
                                style={{ left: axisOf(axis, selected.ts) }}
                            >
                                <div className="absolute top-[-3px] left-1/2 h-0 w-0 -translate-x-1/2 border-x-[5px] border-t-[6px] border-x-transparent border-t-primary" />
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}

function clamp(v: number, lo: number, hi: number) {
    return Math.max(lo, Math.min(v, hi));
}
