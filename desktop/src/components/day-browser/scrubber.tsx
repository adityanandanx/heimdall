import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { frameImageUrl, type Frame } from "@/lib/api";
import { formatTime, formatTimeS } from "@/lib/format";
import { srcOf } from "@/lib/frames";
import {
    axisOf,
    axisWidth,
    buildAxis,
    chapters,
    clsColor,
    frameNear,
    tsOf,
    type Span,
} from "@/lib/timeline";
import { cn } from "@/lib/utils";

const MIN_PPM = 2;
const MAX_PPM = 120;
const PEEK_W = 300;
const OFF_GAP = 8 * 60 * 1000;

interface ScrubberProps {
    baseUrl: string;
    frames: Frame[];
    selected: Frame;
    onSelect: (frame: Frame) => void;
    hits: Set<number> | null;
    ppm: number;
    onPpmChange: (ppm: number) => void;
}

function clamp(v: number, lo: number, hi: number) {
    return Math.max(lo, Math.min(v, hi));
}

function chapterEnd<T extends { ts: string }>(
    ch: { cls: string; frames: T[] },
    all: Array<{ cls: string; frames: T[] }>,
): string {
    const i = all.indexOf(ch);
    const next = all[i + 1];
    if (!next) return ch.frames[ch.frames.length - 1].ts;
    const gap =
        new Date(next.frames[0].ts).getTime() -
        new Date(ch.frames[ch.frames.length - 1].ts).getTime();
    return gap > OFF_GAP ? ch.frames[ch.frames.length - 1].ts : next.frames[0].ts;
}

export function Scrubber({ baseUrl, frames, selected, onSelect, hits, ppm, onPpmChange }: ScrubberProps) {
    const axis = useMemo<Span[]>(() => (frames.length > 1 ? buildAxis(frames, ppm) : []), [frames, ppm]);
    const axisW = axisWidth(axis);

    const tapeRef = useRef<HTMLDivElement>(null);
    const contentRef = useRef<HTMLDivElement>(null);
    const trackRef = useRef<HTMLDivElement>(null);
    const caretRef = useRef<HTMLDivElement>(null);
    const pillRef = useRef<HTMLSpanElement>(null);
    const peekRef = useRef<HTMLDivElement>(null);
    const peekCaretRef = useRef<HTMLDivElement>(null);

    const lastScrolledRef = useRef<string>("");
    const draggingRef = useRef(false);
    const panningRef = useRef(false);
    const panXRef = useRef(0);
    const panScrollRef = useRef(0);
    const anchorIdxRef = useRef(0);
    const anchorFracRef = useRef(0);
    const anchorKeepRef = useRef(-1);

    const [tip, setTip] = useState<Frame | null>(null);
    const [peekShown, setPeekShown] = useState(false);

    const lastTipIdRef = useRef<number | null>(null);

    // Keep the page from scrolling when the wheel is used over the tape.
    useEffect(() => {
        const tape = tapeRef.current;
        if (!tape) return;
        const block = (e: WheelEvent) => e.preventDefault();
        tape.addEventListener("wheel", block, { passive: false });
        return () => tape.removeEventListener("wheel", block);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Zoom-anchor: keep the span under the cursor stable across ppm changes.
    useLayoutEffect(() => {
        const tape = tapeRef.current;
        if (!tape || !axis.length || anchorKeepRef.current < 0) return;
        const idx = anchorIdxRef.current;
        const s = axis[Math.min(idx, axis.length - 1)];
        const target = s.x0 + anchorFracRef.current * (s.x1 - s.x0);
        tape.scrollLeft = clamp(target - anchorKeepRef.current, 0, Math.max(0, axisW - tape.clientWidth));
        anchorKeepRef.current = -1;
    }, [axis, axisW]);

    // Scroll so the playhead is visible, but only when the selection actually moved.
    useLayoutEffect(() => {
        const tape = tapeRef.current;
        if (!tape || !frames.length || draggingRef.current || panningRef.current) return;
        if (selected.ts === lastScrolledRef.current && lastScrolledRef.current !== "") return;
        lastScrolledRef.current = selected.ts;
        const x = axisOf(axis, selected.ts);
        if (x < tape.scrollLeft || x > tape.scrollLeft + tape.clientWidth) {
            tape.scrollLeft = clamp(x - tape.clientWidth / 3, 0, Math.max(0, axisW - tape.clientWidth));
        }
    }, [axis, axisW, selected, frames.length]);

    function zoomBy(factor: number, anchorClientX?: number) {
        const tape = tapeRef.current;
        const track = trackRef.current;
        if (!tape || !track || !axis.length) return;
        const rect = track.getBoundingClientRect();
        const keep = anchorClientX != null ? anchorClientX - rect.left : tape.clientWidth / 2;
        const oldX = keep + tape.scrollLeft;
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
        const track = trackRef.current;
        if (!track) return null;
        const rect = track.getBoundingClientRect();
        const x = clamp(clientX - rect.left, 0, axisW);
        const ts = tsOf(axis, x);
        return { f: frameNear(frames, ts), x, ts };
    }

    function positionOverlay(clientX: number) {
        const caret = caretRef.current;
        const pill = pillRef.current;
        const peek = peekRef.current;
        const peekCaret = peekCaretRef.current;
        const hit = frameAt(clientX);
        if (!caret || !pill || !hit) return;
        caret.style.left = `${hit.x.toFixed(1)}px`;
        caret.style.opacity = "1";
        pill.textContent = formatTimeS(hit.ts) ?? "";
        if (peek && peekCaret) {
            const left = clamp(clientX - PEEK_W / 2, 8, window.innerWidth - PEEK_W - 8);
            peek.style.left = `${left}px`;
            peek.style.top = `${(caret.getBoundingClientRect().top - 12 - peek.offsetHeight).toFixed(0)}px`;
            peekCaret.style.left = `${(clientX - left - 7).toFixed(1)}px`;
        }
        if (hit.f.id !== lastTipIdRef.current) {
            lastTipIdRef.current = hit.f.id;
            setTip(hit.f);
        }
    }

    function hidePeek() {
        const caret = caretRef.current;
        if (caret) caret.style.opacity = "0";
        setPeekShown(false);
    }

    function seek(clientX: number) {
        const hit = frameAt(clientX);
        if (!hit) return;
        lastTipIdRef.current = hit.f.id;
        setTip(hit.f);
        onSelect(hit.f);
    }

    function handlePointerDown(e: React.PointerEvent) {
        const tape = tapeRef.current;
        const track = trackRef.current;
        if (!tape || !track) return;
        if (e.button === 1) {
            e.preventDefault();
            panningRef.current = true;
            panXRef.current = e.clientX;
            panScrollRef.current = tape.scrollLeft;
            hidePeek();
            track.setPointerCapture(e.pointerId);
            return;
        }
        draggingRef.current = true;
        track.setPointerCapture(e.pointerId);
        seek(e.clientX);
    }

    function handlePointerMove(e: React.PointerEvent) {
        const tape = tapeRef.current;
        if (!tape) return;
        if (panningRef.current) {
            tape.scrollLeft = clamp(
                panScrollRef.current - (e.clientX - panXRef.current),
                0,
                Math.max(0, axisW - tape.clientWidth),
            );
            return;
        }
        positionOverlay(e.clientX);
        setPeekShown(true);
        if (draggingRef.current) seek(e.clientX);
    }

    function handlePointerUp(e: React.PointerEvent) {
        if (panningRef.current) {
            panningRef.current = false;
            return;
        }
        if (!draggingRef.current) return;
        draggingRef.current = false;
        const track = trackRef.current;
        if (track) {
            const r = track.getBoundingClientRect();
            if (e.clientX < r.left || e.clientX > r.right) hidePeek();
        }
    }

    const chapterList = useMemo(() => chapters(frames), [frames]);

    const hourMarks = useMemo(() => {
        const marks: Date[] = [];
        const seen = new Set<number>();
        for (const f of frames) {
            const d = new Date(f.ts);
            const h = d.getHours();
            if (seen.has(h)) continue;
            seen.add(h);
            const m = new Date(d);
            m.setMinutes(0, 0, 0);
            marks.push(m);
        }
        return marks.sort((a, b) => a.getTime() - b.getTime());
    }, [frames]);

    return (
        <div className="rounded-xl border border-border bg-card">
            <div
                ref={tapeRef}
                className="overflow-x-auto overflow-y-hidden p-4 [scrollbar-width:thin]"
            >
                <div ref={contentRef} className="relative" style={{ width: axisW }}>
                    <div className="relative text-[10px] leading-relaxed text-muted-foreground">
                        {hourMarks.map((m) => (
                            <span
                                key={m.getTime()}
                                className="absolute -translate-x-1/2 tabular-nums"
                                style={{ left: axisOf(axis, m.toISOString()) }}
                            >
                                {formatTime(m.toISOString())}
                            </span>
                        ))}
                    </div>
                    <div
                        ref={trackRef}
                        className="relative h-14 cursor-pointer touch-none overflow-hidden rounded-lg border border-border bg-secondary select-none"
                        data-testid="scrubber-track"
                        onPointerDown={handlePointerDown}
                        onPointerMove={handlePointerMove}
                        onPointerUp={handlePointerUp}
                        onPointerLeave={() => {
                            if (!draggingRef.current && !panningRef.current) hidePeek();
                        }}
                        onPointerCancel={() => {
                            draggingRef.current = false;
                            panningRef.current = false;
                            hidePeek();
                        }}
                    >
                        <div className="pointer-events-none absolute inset-0">
                            {hourMarks.map((m) => (
                                <div
                                    key={m.getTime()}
                                    className="absolute top-0 bottom-0 w-px bg-border opacity-70"
                                    style={{ left: axisOf(axis, m.toISOString()) }}
                                />
                            ))}
                            <div className="absolute inset-0">
                                {axis.filter((s) => s.off).map((s) => (
                                    <div
                                        key={s.a}
                                        className="absolute top-0 bottom-0 bg-black/30"
                                        style={{ left: s.x0, width: Math.max(s.x1 - s.x0, 1) }}
                                    />
                                ))}
                            </div>
                        </div>
                        <div className="absolute inset-0">
                            {chapterList.map((ch) => {
                                const a = axisOf(axis, ch.frames[0].ts);
                                const b = axisOf(axis, chapterEnd(ch, chapterList));
                                return (
                                    <div
                                        key={ch.cls + ch.frames[0].ts}
                                        className="absolute top-0 bottom-0 border-r border-black/30 opacity-60"
                                        style={{
                                            left: a,
                                            width: Math.max(b - a, 1),
                                            background: clsColor(ch.cls),
                                        }}
                                        title={ch.cls}
                                    />
                                );
                            })}
                        </div>
                        <div className="pointer-events-none absolute inset-0">
                            {frames.map((f) => {
                                const src = srcOf(f);
                                const hit = hits?.has(f.id);
                                return (
                                    <div
                                        key={f.id}
                                        className={cn(
                                            "absolute top-1/2 size-1 -translate-x-1/2 -translate-y-1/2 rounded-full",
                                            hit && "size-1.5 bg-amber-400",
                                            !hit && src === "a11y" && "size-1.5 bg-emerald-500",
                                            !hit && src === "ocr" && "bg-sky-500",
                                            !hit && src === "none" && "bg-border opacity-45",
                                        )}
                                        style={{ left: axisOf(axis, f.ts) }}
                                    />
                                );
                            })}
                        </div>
                        <div
                            className="pointer-events-none absolute top-0 bottom-0 w-[3px] bg-accent shadow-[0_0_10px_var(--accent)]"
                            style={{ left: axisOf(axis, selected.ts) }}
                        />
                        <div ref={caretRef} className="pointer-events-none absolute top-0 bottom-0 w-0.5 bg-foreground opacity-0">
                            <span
                                ref={pillRef}
                                className="absolute top-1 left-1/2 -translate-x-1/2 rounded-full border border-border bg-background px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap tabular-nums shadow-sm"
                            />
                        </div>
                    </div>
                </div>
            </div>

            <div className="flex items-center gap-4 px-4 pb-4 pr-4 pt-2">
                <span className="min-w-24 text-[13px] font-semibold tabular-nums">
                    {formatTimeS(selected.ts)}
                </span>
                <span className="truncate text-xs text-muted-foreground">
                    {selected.window_class}
                    {selected.window_title ? ` · ${selected.window_title}` : ""}
                </span>
                <div className="ml-auto flex items-center gap-2">
                    <button
                        type="button"
                        className="inline-flex size-5 items-center justify-center rounded-md border border-border text-sm text-muted-foreground hover:text-foreground"
                        aria-label="zoom out"
                        onClick={() => {
                            lastScrolledRef.current = "";
                            zoomBy(1 / 1.5);
                        }}
                    >
                        −
                    </button>
                    <input
                        type="range"
                        min={MIN_PPM}
                        max={MAX_PPM}
                        step={1}
                        value={ppm}
                        aria-label="zoom"
                        className="w-28"
                        onChange={(e) => onPpmChange(Number(e.currentTarget.value))}
                    />
                    <button
                        type="button"
                        className="inline-flex size-5 items-center justify-center rounded-md border border-border text-sm text-muted-foreground hover:text-foreground"
                        aria-label="zoom in"
                        onClick={() => {
                            lastScrolledRef.current = "";
                            zoomBy(1.5);
                        }}
                    >
                        +
                    </button>
                    <span className="min-w-11 text-right text-[10px] text-muted-foreground tabular-nums">
                        {ppm}px/min
                    </span>
                </div>
            </div>

            <div
                ref={peekRef}
                className={cn(
                    "pointer-events-none fixed z-50 w-[300px] transition-[opacity,transform] duration-150 ease-out",
                    peekShown ? "translate-y-0 opacity-100" : "-translate-y-[10px] opacity-0",
                )}
            >
                <div className="relative aspect-video overflow-hidden rounded-lg border border-border bg-black shadow-2xl">
                    {tip && (
                        <img
                            src={frameImageUrl(baseUrl, tip.id)}
                            alt="frame preview"
                            className="h-full w-full object-cover"
                        />
                    )}
                    <span className="absolute bottom-2 left-2 rounded-full bg-black/70 px-2 py-0.5 text-[11px] font-bold text-white tabular-nums">
                        {tip ? formatTimeS(tip.ts) : ""}
                    </span>
                </div>
                <p className="mt-1 truncate text-[11px] text-muted-foreground">
                    {tip ? `${tip.window_class}${tip.window_title ? ` · ${tip.window_title}` : ""}` : ""}
                </p>
                <div
                    ref={peekCaretRef}
                    className="absolute top-full h-0 w-0 border-[7px] border-t-accent border-x-transparent border-b-transparent"
                />
            </div>
        </div>
    );
}