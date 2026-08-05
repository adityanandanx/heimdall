import { useLayoutEffect, useMemo, useRef, useState } from "react";
import type { Frame, Session } from "@/lib/api";
import { frameImageUrl } from "@/lib/api";
import { formatTime, formatTimeS } from "@/lib/format";
import { srcOf } from "@/lib/frames";
import { SourceBadge } from "./frame-meta";
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
    type Run,
    type Span,
} from "@/lib/timeline";
import { cn } from "@/lib/utils";

const MIN_PPM = 2;
const MAX_PPM = 120;

const DOTS_ROW_H = 32;
const LANE_H = 22;
const BLOCK_H = 14;

const POPUP_W = 176;

interface FilmstripProps {
    baseUrl: string;
    frames: Frame[];
    sessions: Session[];
    selected: Frame | null;
    onSelect: (f: Frame) => void;
    onMediaOpen: (sessions: Session[]) => void;
    hits: Set<number> | null;
    filterCls: string | null;
    ppm: number;
    onPpmChange: (ppm: number) => void;
}

interface HoverState {
    f: Frame;
    x: number;
    y: number;
}

export function Filmstrip({ baseUrl, frames, sessions, selected, onSelect, onMediaOpen, hits, filterCls, ppm, onPpmChange }: FilmstripProps) {
    const axis = useMemo<Span[]>(() => (frames.length > 1 ? buildAxis(frames, ppm) : []), [frames, ppm]);
    const axisW = axisWidth(axis);

    const scrollRef = useRef<HTMLDivElement>(null);
    const timelineRef = useRef<HTMLDivElement>(null);
    const draggingRef = useRef(false);
    const anchorIdxRef = useRef(0);
    const anchorFracRef = useRef(0);
    const anchorKeepRef = useRef(-1);
    const hoverIdRef = useRef<number | null>(null);
    const [hov, setHov] = useState<HoverState | null>(null);
    const [followLive, setFollowLive] = useState(false);
    const [viewW, setViewW] = useState(0);

    // Track the scroll viewport width so the trailing pad lets the last
    // capture scroll all the way to the middle of the timeline.
    useLayoutEffect(() => {
        const el = scrollRef.current;
        if (!el) return;
        const update = () => setViewW(el.clientWidth);
        update();
        if (typeof ResizeObserver === "undefined") return;
        const ro = new ResizeObserver(update);
        ro.observe(el);
        return () => ro.disconnect();
    }, []);

    // When following live, ride the newest capture by snapping to the end
    // of the timeline whenever new frames come in.
    useLayoutEffect(() => {
        if (!followLive) return;
        const el = scrollRef.current;
        if (el) el.scrollLeft = scrollLimit();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [frames, followLive]);

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
    const sessionsByRun = useMemo(() => {
        const map = new Map<Run, Session[]>();
        for (const lr of laneRuns) {
            map.set(
                lr.run,
                sessions.filter(
                    (s) => s.player === lr.run.player && (s.media_title ?? "(untitled)") === lr.run.title,
                ),
            );
        }
        return map;
    }, [laneRuns, sessions]);

    const timelineH = DOTS_ROW_H + lanes * LANE_H + 6;

    const contentW = axis.length ? axisW : 100;
    const padEnd = axis.length ? Math.ceil(viewW / 2) : 0;
    const scrollLimit = () => {
        const el = scrollRef.current;
        return el ? Math.max(0, contentW + padEnd - el.clientWidth) : 0;
    };

    // Zoom-anchor: keep the span under the cursor stable across ppm changes.
    useLayoutEffect(() => {
        const el = scrollRef.current;
        if (!el || !axis.length || anchorKeepRef.current < 0) return;
        const idx = anchorIdxRef.current;
        const s = axis[Math.min(idx, axis.length - 1)];
        const target = s.x0 + anchorFracRef.current * (s.x1 - s.x0);
        el.scrollLeft = clamp(target - anchorKeepRef.current, 0, scrollLimit());
        anchorKeepRef.current = -1;
    }, [axis, axisW, contentW, padEnd]);

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

    function frameAt(clientX: number, clientY: number) {
        const timeline = timelineRef.current;
        if (!timeline || !axis.length) return null;
        const rect = timeline.getBoundingClientRect();
        const x = clamp(clientX - rect.left, 0, axisW);
        return { f: frameNear(frames, tsOf(axis, x)), clientX, clientY };
    }

    function hover(clientX: number, clientY: number) {
        const hit = frameAt(clientX, clientY);
        if (!hit) return;
        if (hit.f.id !== hoverIdRef.current) {
            hoverIdRef.current = hit.f.id;
        }
        setHov({ f: hit.f, x: hit.clientX, y: hit.clientY });
    }

    function seek(clientX: number) {
        const hit = frameAt(clientX, 0);
        if (!hit) return;
        hoverIdRef.current = hit.f.id;
        onSelect(hit.f);
    }

    const dayStart = frames[0]?.ts ?? null;
    const dayEnd = frames[frames.length - 1]?.ts ?? null;

    return (
        <div className="shrink-0 border-t border-line bg-surface px-5 pt-3.5 pb-4 select-none">
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
                <button
                    type="button"
                    onClick={() => setFollowLive((v) => !v)}
                    aria-pressed={followLive}
                    data-testid="follow-live"
                    className={cn(
                        "flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10px] transition-colors",
                        followLive
                            ? "border-primary/60 text-primary"
                            : "border-line text-dim hover:border-primary/60 hover:text-foreground",
                    )}
                >
                    <span
                        className={cn(
                            "size-1.5 rounded-full",
                            followLive ? "bg-primary shadow-[0_0_6px_var(--primary)]" : "bg-dim",
                        )}
                    />
                    follow
                </button>
            </div>

            <div
                ref={scrollRef}
                className="overflow-x-auto overflow-y-hidden pb-1.5 [scrollbar-width:thin]"
            >
                <div className="relative" style={{ width: contentW + padEnd }}>
                    <div
                        ref={timelineRef}
                        className="relative cursor-pointer touch-none overflow-hidden rounded-md bg-[color-mix(in_srgb,var(--background)_85%,var(--surface-2))] select-none"
                        style={{ width: contentW, height: timelineH }}
                        data-testid="filmstrip-timeline"
                        onPointerDown={(e) => {
                            if (e.button !== 0) return;
                            e.preventDefault();
                            draggingRef.current = true;
                            setHov(null);
                            timelineRef.current?.setPointerCapture(e.pointerId);
                            seek(e.clientX);
                        }}
                        onPointerMove={(e) => {
                            if (draggingRef.current) seek(e.clientX);
                            else hover(e.clientX, e.clientY);
                        }}
                        onPointerUp={() => {
                            draggingRef.current = false;
                        }}
                        onPointerLeave={() => {
                            if (!draggingRef.current) {
                                hoverIdRef.current = null;
                                setHov(null);
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
                                el.scrollLeft = clamp(el.scrollLeft + dx, 0, scrollLimit());
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
                                    role="button"
                                    aria-label={`session ${r.title}`}
                                    className="absolute flex cursor-pointer items-center overflow-hidden rounded-[4px] border transition-[filter] hover:brightness-125"
                                    style={{
                                        left: a,
                                        width: Math.max(b - a, 8),
                                        top: DOTS_ROW_H + lane * LANE_H + 4,
                                        height: BLOCK_H,
                                        background: `color-mix(in srgb, ${color} 30%, transparent)`,
                                        borderColor: `color-mix(in srgb, ${color} 55%, transparent)`,
                                    }}
                                    title={`${r.player} — ${r.title} (click for details)`}
                                    onPointerDown={(e) => e.stopPropagation()}
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        const hit = sessionsByRun.get(r);
                                        if (hit && hit.length) onMediaOpen(hit);
                                    }}
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

            {hov && <HoverPopup hov={hov} baseUrl={baseUrl} />}
        </div>
    );
}

function HoverPopup({ hov, baseUrl }: { hov: HoverState; baseUrl: string }) {
    const left = clamp(hov.x + 16, 8, window.innerWidth - POPUP_W - 8);
    const top = clamp(hov.y - 108, 8, Math.max(8, window.innerHeight - 128));
    return (
        <div
            className="pointer-events-none fixed z-50 overflow-hidden rounded-md border border-line bg-surface shadow-[var(--e1)]"
            style={{ left, top, width: POPUP_W }}
            data-testid="hover-popup"
        >
            <div className="h-20 w-full overflow-hidden bg-[linear-gradient(135deg,var(--surface-2),var(--surface))]">
                <img
                    src={frameImageUrl(baseUrl, hov.f.id)}
                    alt=""
                    className="h-full w-full object-cover"
                    loading="lazy"
                />
            </div>
            <div className="flex flex-col gap-1 p-2">
                <div className="flex items-center gap-2">
                    <b className="font-mono text-[11px]">{formatTimeS(hov.f.ts)}</b>
                    <span className="ml-auto">
                        <SourceBadge src={srcOf(hov.f)} />
                    </span>
                </div>
                <span className="truncate text-[10px] text-dim">{hov.f.window_class}</span>
                {hov.f.window_title && (
                    <span className="truncate text-[10px] text-faint">{hov.f.window_title}</span>
                )}
            </div>
        </div>
    );
}

function clamp(v: number, lo: number, hi: number) {
    return Math.max(lo, Math.min(v, hi));
}
