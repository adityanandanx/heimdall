import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Frame } from "@/lib/api";
import { frameImageUrl } from "@/lib/api";
import { formatTimeS } from "@/lib/format";
import { srcOf } from "@/lib/frames";
import { dayStrOf, frameNear, shiftDay } from "@/lib/timeline";
import { cn } from "@/lib/utils";
import { useDayFrames, useDaySessions, useRunPipe, useStatus } from "@/hooks/use-day-browser";
import { Filmstrip } from "./filmstrip";
import { FrameMeta, SourceBadge } from "./frame-meta";

interface DaySurfaceProps {
    baseUrl: string;
    day: string;
    onDayChange: (day: string) => void;
    seek: { ts: number; nonce: number } | null;
    onSeekDone: () => void;
}

export function DaySurface({ baseUrl, day, onDayChange, seek, onSeekDone }: DaySurfaceProps) {
    const [ppm, setPpm] = useState(14);
    const [selected, setSelected] = useState<Frame | null>(null);
    const [filterCls, setFilterCls] = useState<string | null>(null);
    const [dayQuery, setDayQuery] = useState("");
    const searchRef = useRef<HTMLInputElement>(null);
    const userSelectedRef = useRef(false);

    const framesQ = useDayFrames(baseUrl, day);
    const sessionsQ = useDaySessions(baseUrl, day);
    const statusQ = useStatus(baseUrl);
    const recap = useRunPipe(baseUrl, day);

    const frames = framesQ.data ?? [];
    const sessions = sessionsQ.data ?? [];
    const selectedFrame = selected ?? frames[frames.length - 1] ?? null;

    // Default selection + reply to cross-surface "jump" requests.
    useEffect(() => {
        if (!frames.length) return;
        if (seek) {
            const f = frameNear(frames, seek.ts);
            userSelectedRef.current = true;
            setSelected(f);
            onSeekDone();
            return;
        }
        if (!userSelectedRef.current) setSelected(frames[frames.length - 1]);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [frames, seek?.nonce]);

    const hits = useMemo(() => {
        const q = dayQuery.trim().toLowerCase();
        if (q.length < 2) return null;
        const ids = new Set<number>();
        for (const f of frames) {
            const text = `${f.window_class} ${f.window_title ?? ""} ${f.a11y_text ?? ""} ${f.ocr_text ?? ""}`.toLowerCase();
            if (text.includes(q)) ids.add(f.id);
        }
        return ids;
    }, [dayQuery, frames]);

    const step = useCallback(
        (delta: number) => {
            if (!frames.length) return;
            const cur = selectedFrame ? frames.findIndex((f) => f.id === selectedFrame.id) : frames.length - 1;
            setSelected(frames[Math.max(0, Math.min(cur + delta, frames.length - 1))]);
        },
        [frames, selectedFrame],
    );

    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.metaKey || e.ctrlKey || e.altKey) return;
            const target = e.target as HTMLElement | null;
            const typing =
                target &&
                (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
            if (typing) return;
            if (e.key === "ArrowRight") step(e.shiftKey ? 3 : 1);
            else if (e.key === "ArrowLeft") step(e.shiftKey ? -3 : -1);
            else if (e.key.toLowerCase() === "g") step(frames.length);
            else if (e.key.toLowerCase() === "h") step(-frames.length);
            else if (e.key === "/") {
                e.preventDefault();
                searchRef.current?.focus();
            }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [step, frames.length]);

    const apps = useMemo(() => {
        const map = new Map<string, number>();
        for (const f of frames) map.set(f.window_class, (map.get(f.window_class) ?? 0) + 1);
        const total = frames.length || 1;
        return [...map.entries()]
            .map(([cls, count]) => ({ cls, count, pct: (count / total) * 100 }))
            .sort((a, b) => b.count - a.count);
    }, [frames]);

    const caption = selectedFrame;

    const recapResult = recap.results["day-recap"] ?? recap.results["time-breakdown"];

    return (
        <div className="flex h-full min-h-0 flex-col">
            <div className="flex shrink-0 items-center gap-4 border-b border-line bg-surface px-5 py-3">
                <div className="flex items-center gap-2.5 font-extrabold text-[15px] tracking-wide">
                    <span
                        className={cn(
                            "size-2.5 rounded-full",
                            statusQ.data?.capture.alive ? "bg-ok shadow-[0_0_10px_var(--ok)]" : "bg-faint",
                        )}
                    />
                    DAY
                </div>
                <div className="flex items-center gap-1">
                    <button
                        type="button"
                        className="flex size-7 items-center justify-center rounded-full text-base text-dim transition-colors hover:text-foreground"
                        aria-label="previous day"
                        onClick={() => onDayChange(shiftDay(day, -1))}
                    >
                        ‹
                    </button>
                    <span className="min-w-[170px] text-center font-mono text-sm font-semibold">
                        {formatDay(day)}
                        {day === dayStrOf(new Date()) ? " · Today" : ""}
                    </span>
                    <button
                        type="button"
                        className="flex size-7 items-center justify-center rounded-full text-base text-dim transition-colors hover:text-foreground"
                        aria-label="next day"
                        onClick={() => onDayChange(shiftDay(day, 1))}
                    >
                        ›
                    </button>
                    <button
                        type="button"
                        className="ml-1 rounded-sm px-2.5 py-1 text-xs text-dim transition-colors hover:text-foreground"
                        onClick={() => onDayChange(dayStrOf(new Date()))}
                    >
                        Today
                    </button>
                </div>
                <div className="relative ml-auto w-full max-w-[420px]">
                    <span className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-sm text-faint">
                        ⌕
                    </span>
                    <input
                        ref={searchRef}
                        value={dayQuery}
                        onChange={(e) => setDayQuery(e.currentTarget.value)}
                        placeholder="Search the day…  (⌘K for global)"
                        className="w-full rounded-md border border-line bg-surface-2 py-2 pl-9 pr-3 text-sm outline-none transition-shadow placeholder:text-faint focus:border-primary focus:shadow-[0_0_0_3px_rgba(97,175,239,0.18)]"
                    />
                    {hits && (
                        <span className="absolute top-1/2 right-3 -translate-y-1/2 rounded-full border border-ok/40 px-1.5 py-px text-[10px] text-ok">
                            {hits.size}
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-2">
                    <span
                        className={cn(
                            "rounded-full border px-2.5 py-1 text-[11px]",
                            statusQ.data?.capture.alive
                                ? "border-ok/40 text-ok"
                                : "border-line text-faint",
                        )}
                    >
                        {statusQ.data?.capture.alive ? "capturing" : "idle"}
                    </span>
                    <button
                        type="button"
                        onClick={() => recap.run("day-recap")}
                        disabled={recap.isRunning}
                        className="rounded-md border border-line px-3 py-1.5 text-xs whitespace-nowrap transition-colors hover:border-primary hover:text-foreground disabled:opacity-40"
                    >
                        ⟳ recap
                    </button>
                    <button
                        type="button"
                        onClick={() => recap.run("time-breakdown")}
                        disabled={recap.isRunning}
                        className="rounded-md border border-primary bg-primary px-3 py-1.5 text-xs font-semibold whitespace-nowrap text-primary-foreground transition-[filter] hover:brightness-110 disabled:opacity-40"
                    >
                        + breakdown
                    </button>
                </div>
            </div>

            <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_340px]">
                <div className="flex min-h-0 min-w-0 flex-col">
                    <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-background">
                        <div className="relative h-full w-full overflow-hidden rounded-md shadow-[var(--e1)]">
                            {caption ? (
                                <img
                                    src={frameImageUrl(baseUrl, caption.id)}
                                    alt={caption.window_class}
                                    className="h-full w-full object-contain"
                                />
                            ) : (
                                <div className="flex h-full w-full items-center justify-center bg-[linear-gradient(135deg,var(--surface-2)_0%,var(--surface)_45%,var(--background)_100%)] text-xs text-faint">
                                    {framesQ.isLoading ? "loading…" : "no frames"}
                                </div>
                            )}
                        </div>
                    {caption && (
                            <div className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-3 rounded-full border border-line bg-background/85 px-3.5 py-1.5 text-xs whitespace-nowrap backdrop-blur">
                                <b className="font-mono">{formatTimeS(caption.ts)}</b>
                                <span className="text-dim">
                                    {caption.window_class}
                                    {caption.window_title ? ` · ${caption.window_title}` : ""}
                                </span>
                                <SourceBadge src={srcOf(caption)} />
                            </div>
                        )}
                    </div>
                    <Filmstrip
                        baseUrl={baseUrl}
                        frames={frames}
                        sessions={sessions}
                        selected={selectedFrame}
                        onSelect={(f) => {
                            userSelectedRef.current = true;
                            setSelected(f);
                        }}
                        hits={hits}
                        filterCls={filterCls}
                        ppm={ppm}
                        onPpmChange={setPpm}
                    />
                </div>

                <div className="min-w-0 overflow-y-auto border-l border-line bg-surface p-5">
                    {framesQ.isLoading ? (
                        <p className="text-xs text-dim">loading day…</p>
                    ) : !frames.length ? (
                        <p className="text-xs text-dim">No captures for {day}.</p>
                    ) : (
                        <FrameMeta
                            baseUrl={baseUrl}
                            frame={selectedFrame}
                            recapResult={recapResult}
                            onRunRecap={() => recap.run("day-recap")}
                            recapRunning={recap.isRunning}
                            apps={apps}
                            filterCls={filterCls}
                            onFilter={setFilterCls}
                        />
                    )}
                </div>
            </div>
        </div>
    );
}

function formatDay(day: string): string {
    const [y, m, d] = day.split("-").map(Number);
    return new Date(y, m - 1, d, 12, 0, 0).toLocaleDateString(undefined, {
        weekday: "short",
        month: "short",
        day: "numeric",
    });
}