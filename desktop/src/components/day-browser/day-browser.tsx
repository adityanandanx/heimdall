import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Frame, SearchItem } from "@/lib/api";
import { formatTimeS } from "@/lib/format";
import { dayStrOf, frameNear, fmtDur, aggregateMedia, playerColor } from "@/lib/timeline";
import { useDayFrames, useDaySessions } from "@/hooks/use-day-browser";
import { Scrubber } from "./scrubber";
import { FramePreview } from "./frame-preview";
import { WatchLane } from "./watch-lane";
import { RecapPanel } from "./recap-panel";
import { SearchBox } from "./search-box";
import { Skeleton } from "@/components/ui/skeleton";


interface DayBrowserProps {
    baseUrl: string;
}

export function DayBrowser({ baseUrl }: DayBrowserProps) {
    const [day, setDay] = useState(() => dayStrOf(new Date()));
    const [ppm, setPpm] = useState(10);
    const [selected, setSelected] = useState<Frame | null>(null);
    const [activeSessionId, setActiveSessionId] = useState<number | null>(null);
    const [hits, setHits] = useState<Set<number> | null>(null);
    const [searchOpen, setSearchOpen] = useState(false);
    const [detailOpen, setDetailOpen] = useState(false);

    const userSelectedRef = useRef(false);
    const lastKeyRef = useRef(0);

    const framesQ = useDayFrames(baseUrl, day);
    const sessionsQ = useDaySessions(baseUrl, day);
    const frames = framesQ.data ?? [];
    const sessions = sessionsQ.data ?? [];

    const selectedFrame = useMemo(
        () => selected ?? frames[frames.length - 1] ?? null,
        [selected, frames],
    );
    const activeSession = useMemo(
        () => sessions.find((s) => s.id === activeSessionId) ?? null,
        [sessions, activeSessionId],
    );

    useEffect(() => {
        if (!frames.length || userSelectedRef.current) return;
        setSelected(frames[frames.length - 1]);
    }, [frames]);

    const sessionAt = useCallback(
        (ts: string): number | null => {
            const t = new Date(ts).getTime();
            for (const s of sessions) {
                const st = new Date(s.ts_start).getTime();
                const en = s.ts_end ? new Date(s.ts_end).getTime() : st;
                if (t >= st && t <= en) return s.id;
            }
            return null;
        },
        [sessions],
    );

    const selectFrame = useCallback(
        (f: Frame) => {
            userSelectedRef.current = true;
            setSelected(f);
            const sid = sessionAt(f.ts);
            if (sid !== null) setActiveSessionId(sid);
        },
        [sessionAt],
    );

    const navigateTo = useCallback(
        (epochMs: number) => {
            if (!frames.length) return;
            const target = new Date(Math.max(0, Math.min(epochMs, Date.now()))).toISOString();
            const f = frameNear(frames, new Date(target).getTime());
            selectFrame(f);
        },
        [frames, selectFrame],
    );

    const step = useCallback(
        (delta: number) => {
            if (!frames.length) return;
            const cur = selectedFrame ? frames.findIndex((f) => f.id === selectedFrame.id) : frames.length - 1;
            const next = Math.max(0, Math.min(cur + delta, frames.length - 1));
            selectFrame(frames[next]);
        },
        [frames, selectedFrame, selectFrame],
    );

    const watchedMoment = useCallback(
        (dir: 1 | -1) => {
            if (!activeSession) return;
            const rs = activeSession.ranges || [];
            if (!rs.length) return;
            const t = selectedFrame ? new Date(selectedFrame.ts).getTime() : 0;
            const mids = rs
                .map(([b, e]) => ((b + e) / 2) * 1000)
                .sort((a, b) => a - b);
            const cur = mids.reduce((best, m) => (Math.abs(m - t) < Math.abs(best - t) ? m : best), mids[0]);
            const i = mids.indexOf(cur);
            const next = (i + dir + mids.length) % mids.length;
            navigateTo(mids[next]);
        },
        [activeSession, selectedFrame, navigateTo],
    );

    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.metaKey || e.ctrlKey || e.altKey) return;
            const target = e.target as HTMLElement | null;
            const typing =
                target &&
                (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
            if (typing && e.key !== "Escape") return;
            const now = Date.now();
            if (now - lastKeyRef.current < 100) return;
            lastKeyRef.current = now;
            if (e.key === "ArrowRight" && !e.shiftKey) {
                e.preventDefault();
                step(1);
            } else if (e.key === "ArrowLeft" && !e.shiftKey) {
                e.preventDefault();
                step(-1);
            } else if (e.key === "ArrowRight" && e.shiftKey) {
                e.preventDefault();
                step(3);
            } else if (e.key === "ArrowLeft" && e.shiftKey) {
                e.preventDefault();
                step(-3);
            } else if (e.key.toLowerCase() === "g") {
                e.preventDefault();
                step(frames.length);
            } else if (e.key.toLowerCase() === "h") {
                e.preventDefault();
                step(-frames.length);
            } else if (e.key === "n" || e.key === "N") {
                e.preventDefault();
                watchedMoment(1);
            } else if (e.key === "p" || e.key === "P") {
                e.preventDefault();
                watchedMoment(-1);
            } else if (e.key === "/") {
                e.preventDefault();
                setSearchOpen((o) => !o);
            } else if (e.key === "Escape") {
                setSearchOpen(false);
            }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [step, watchedMoment, frames.length]);

    function changeDay(n: number) {
        setDay((d) => shift(d, n));
        userSelectedRef.current = false;
        setSelected(null);
        setActiveSessionId(null);
        setHits(null);
    }

    function goToday() {
        changeDay(0);
    }

    function pickSearch(item: SearchItem, allResults: SearchItem[]) {
        if (item.kind === "frame") {
            const f = frames.find((x) => x.id === item.id);
            if (f) selectFrame(f);
            setHits(new Set(allResults.filter((r) => r.kind === "frame").map((r) => r.id)));
        } else {
            const s = sessions.find((x) => x.id === item.id);
            if (s) {
                setActiveSessionId(s.id);
                navigateTo(new Date(s.ts_start).getTime());
            }
            setHits(null);
        }
    }

    const summary = useMemo(() => aggregateMedia(sessions), [sessions]);

    return (
        <div className="flex flex-col gap-4">
            <header className="flex items-center gap-3">
                <div className="flex items-center gap-1">
                    <button
                        type="button"
                        className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-muted/60"
                        aria-label="previous day"
                        onClick={() => changeDay(-1)}
                    >
                        ←
                    </button>
                    <button
                        type="button"
                        className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-muted/60"
                        onClick={() => changeDay(1)}
                        aria-label="next day"
                    >
                        →
                    </button>
                    <button
                        type="button"
                        className="ml-1 rounded-lg border border-border px-2 py-1 text-xs font-medium hover:bg-muted/60"
                        onClick={goToday}
                    >
                        Today
                    </button>
                </div>
                <h2 className="text-lg font-semibold tabular-nums">{formatDay(day)}</h2>
                <span className="text-[11px] text-muted-foreground">
                    {framesQ.isLoading ? "loading frames…" : `${frames.length} frames`}
                    {sessionsQ.isLoading ? " · loading sessions…" : ` · ${sessions.length} sessions`}
                </span>
                <button
                    type="button"
                    className="ml-auto rounded-lg border border-border px-2.5 py-1 text-xs font-medium hover:bg-muted/60"
                    onClick={() => setSearchOpen((o) => !o)}
                >
                    ⌕ Search{" "}
                    <kbd className="ml-1 rounded bg-muted px-1 text-[9px] text-muted-foreground">/</kbd>
                </button>
            </header>

            {framesQ.isLoading ? (
                <Skeleton className="h-32 w-full" />
            ) : frames.length === 0 ? (
                <p className="rounded-xl border border-border bg-card p-6 text-sm text-muted-foreground">
                    No captures for {day}. Check that the capture service is running and the day is correct.
                </p>
            ) : (
                <>
                    <Scrubber
                        baseUrl={baseUrl}
                        frames={frames}
                        selected={selectedFrame}
                        onSelect={selectFrame}
                        hits={hits}
                        ppm={ppm}
                        onPpmChange={setPpm}
                    />

                    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(300px,340px)_1fr_minmax(280px,340px)]">
                        <div className="flex flex-col gap-4">
                            <WatchLane sessions={sessions} onNavigate={navigateTo} />
                            <RecapPanel baseUrl={baseUrl} day={day} />
                        </div>

                        <div className="flex min-w-0 flex-col gap-4">
                            <div className="rounded-xl border border-border bg-card p-4">
                                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                                    Keyboard
                                </h3>
                                <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
                                    <span><kbd className="rounded bg-muted px-1 py-px text-[9px] font-mono text-muted-foreground">←</kbd> <kbd className="rounded bg-muted px-1 py-px text-[9px] font-mono text-muted-foreground">→</kbd> step frame</span>
                                    <span><kbd className="rounded bg-muted px-1 py-px text-[9px] font-mono text-muted-foreground">shift</kbd>+<kbd className="rounded bg-muted px-1 py-px text-[9px] font-mono text-muted-foreground">←</kbd> step 3</span>
                                    <span><kbd className="rounded bg-muted px-1 py-px text-[9px] font-mono text-muted-foreground">g</kbd> latest · <kbd className="rounded bg-muted px-1 py-px text-[9px] font-mono text-muted-foreground">h</kbd> first</span>
                                    <span><kbd className="rounded bg-muted px-1 py-px text-[9px] font-mono text-muted-foreground">n</kbd>/<kbd className="rounded bg-muted px-1 py-px text-[9px] font-mono text-muted-foreground">p</kbd> next/prev watched moment</span>
                                    <span><kbd className="rounded bg-muted px-1 py-px text-[9px] font-mono text-muted-foreground">/</kbd> search · <kbd className="rounded bg-muted px-1 py-px text-[9px] font-mono text-muted-foreground">esc</kbd> close</span>
                                </div>
                            </div>
                            <div className="rounded-xl border border-border bg-card p-4">
                                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                                    Watched today
                                </h3>
                                {summary.length === 0 ? (
                                    <p className="text-xs text-muted-foreground">Nothing watched.</p>
                                ) : (
                                    <ul className="flex flex-col gap-1.5" data-testid="watched-summary">
                                        {summary.slice(0, 8).map((m) => (
                                            <li key={`${m.player}|${m.title}`} className="flex items-center gap-2 text-xs">
                                                <span
                                                    className="inline-block size-2 shrink-0 rounded-full"
                                                    style={{ background: playerColor(m.player) }}
                                                />
                                                <span className="truncate">{m.title}</span>
                                                <span className="ml-auto shrink-0 text-[10px] text-muted-foreground tabular-nums">
                                                    {fmtDur(m.watched_sec)}
                                                </span>
                                            </li>
                                        ))}
                                    </ul>
                                )}
                            </div>
                        </div>

                        <div className="lg:sticky lg:top-4 lg:self-start">
                            <FramePreview
                                baseUrl={baseUrl}
                                frame={selectedFrame}
                                hits={hits}
                                className="rounded-xl border border-border bg-card p-4"
                            />
                            <button
                                type="button"
                                className="mt-2 w-full rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium hover:bg-muted/60"
                                onClick={() => setDetailOpen(true)}
                            >
                                Details…
                            </button>
                        </div>
                    </div>
                </>
            )}

            {searchOpen && (
                <SearchBox
                    baseUrl={baseUrl}
                    onPick={pickSearch}
                    onClose={() => setSearchOpen(false)}
                />
            )}

            {detailOpen && selectedFrame && (
                <FrameDetailOverlay
                    frame={selectedFrame}
                    onClose={() => setDetailOpen(false)}
                />
            )}

            <span className="sr-only" data-testid="day-browser" />
        </div>
    );
}

function shift(day: string, n: number): string {
    const [y, m, d] = day.split("-").map(Number);
    return dayStrOf(new Date(y, m - 1, d + n, 12, 0, 0));
}

function formatDay(day: string): string {
    const [y, m, d] = day.split("-").map(Number);
    return new Date(y, m - 1, d, 12, 0, 0).toLocaleDateString(undefined, {
        weekday: "short",
        month: "short",
        day: "numeric",
    });
}

function FrameDetailOverlay({ frame, onClose }: { frame: Frame; onClose: () => void }) {
    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6" onClick={onClose}>
            <div
                className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-border bg-popover p-5 shadow-2xl"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="mb-3 flex items-center justify-between gap-3">
                    <h3 className="text-base font-semibold">{frame.window_class}</h3>
                    <span className="text-xs text-muted-foreground tabular-nums">{formatTimeS(frame.ts)}</span>
                </div>
                <pre className="mb-4 max-h-72 overflow-y-auto whitespace-pre-wrap rounded-lg border border-border bg-muted/40 p-3 text-xs leading-relaxed">
                    {JSON.stringify(
                        {
                            id: frame.id,
                            monitor: frame.monitor,
                            workspace: frame.workspace,
                            window_class: frame.window_class,
                            window_title: frame.window_title,
                            fullscreen: Boolean(frame.fullscreen),
                            trigger: frame.trigger,
                            ocr_engine: frame.ocr_engine,
                        },
                        null,
                        2,
                    )}
                </pre>
                <div className="flex flex-col gap-2 text-xs">
                    <h4 className="font-semibold text-muted-foreground">A11y text</h4>
                    <p className="whitespace-pre-wrap leading-relaxed">{frame.a11y_text || "(none)"}</p>
                    <h4 className="mt-2 font-semibold text-muted-foreground">OCR text</h4>
                    <p className="whitespace-pre-wrap leading-relaxed">{frame.ocr_text || "(none)"}</p>
                </div>
            </div>
        </div>
    );
}