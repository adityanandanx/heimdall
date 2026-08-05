import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import type { SearchItem } from "@/lib/api";
import { frameImageUrl } from "@/lib/api";
import { relTime } from "@/lib/format";
import { srcOf } from "@/lib/frames";
import { dayStrOf } from "@/lib/timeline";
import { cn } from "@/lib/utils";
import { useDayFrames, useSearch } from "@/hooks/use-day-browser";

interface SearchSurfaceProps {
    baseUrl: string;
    focusNonce: number;
    onPick: (item: SearchItem) => void;
}

type Filter = "all" | "frames" | "sessions" | "today" | "week";

const FILTERS: Array<{ id: Filter; label: string }> = [
    { id: "all", label: "all" },
    { id: "frames", label: "frames" },
    { id: "sessions", label: "sessions" },
    { id: "today", label: "today" },
    { id: "week", label: "this week" },
];

export function SearchSurface({ baseUrl, focusNonce, onPick }: SearchSurfaceProps) {
    const [q, setQ] = useState("");
    const [filter, setFilter] = useState<Filter>("all");
    const inputRef = useRef<HTMLInputElement>(null);

    const { data, isFetching } = useSearch(baseUrl, q);

    // Autofocus when the surface opens (or is summoned with ⌘K).
    useEffect(() => {
        if (focusNonce > 0) window.setTimeout(() => inputRef.current?.focus(), 0);
    }, [focusNonce]);

    const results = useMemo(() => {
        if (!data) return null;
        let items = data;
        if (filter === "frames") items = items.filter((i) => i.kind === "frame");
        if (filter === "sessions") items = items.filter((i) => i.kind === "session");
        if (filter === "today" || filter === "week") {
            const cutoff = new Date();
            if (filter === "today") cutoff.setHours(0, 0, 0, 0);
            else cutoff.setDate(cutoff.getDate() - 6);
            items = items.filter((i) => new Date(i.ts).getTime() >= cutoff.getTime());
        }
        return items;
    }, [data, filter]);

    const query = q.trim();

    return (
        <div className="flex h-full flex-col gap-4 overflow-y-auto p-7">
            <div>
                <div className="mb-0.5 text-[26px] font-extrabold tracking-tight">Search</div>
                <div className="mb-3 text-xs text-faint">
                    Everything on your screen — a11y text, OCR, window titles, watch transcripts.
                </div>
            </div>

            <div className="relative max-w-[640px]">
                <span className="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-[15px] text-faint">
                    ⌕
                </span>
                <input
                    ref={inputRef}
                    value={q}
                    onChange={(e) => setQ(e.currentTarget.value)}
                    placeholder="e.g.  tauri setup  ·  lofi  ·  PR review"
                    aria-label="search query"
                    className="w-full rounded-lg border border-line bg-surface py-3 pr-14 pl-10 text-sm outline-none transition-shadow placeholder:text-faint focus:border-primary focus:shadow-[0_0_0_3px_rgba(97,175,239,0.18)]"
                />
                <span className="absolute top-1/2 right-3 -translate-y-1/2 font-mono text-[10px] text-dim">
                    {isFetching ? "…" : "⌘K"}
                </span>
            </div>

            <div className="flex flex-wrap gap-2">
                {FILTERS.map((f) => (
                    <button
                        key={f.id}
                        type="button"
                        onClick={() => setFilter(f.id)}
                        className={cn(
                            "rounded-full border px-2.5 py-1 text-[11px] transition-colors",
                            filter === f.id
                                ? "border-primary/40 text-primary"
                                : "border-line text-dim hover:text-foreground",
                        )}
                    >
                        {f.label}
                    </button>
                ))}
            </div>

            {query.length >= 2 && (
                <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] items-start gap-3">
                    {(results ?? []).map((item) => (
                        <ResultCard key={`${item.kind}-${item.id}`} item={item} query={query} baseUrl={baseUrl} onPick={onPick} />
                    ))}
                    {results && results.length === 0 && (
                        <p className="col-span-full text-xs text-dim">No matches.</p>
                    )}
                </div>
            )}
        </div>
    );
}

function ResultCard({
    item,
    query,
    baseUrl,
    onPick,
}: {
    item: SearchItem;
    query: string;
    baseUrl: string;
    onPick: (item: SearchItem) => void;
}) {
    // Resolve the a11y/ocr source for frame results via the cached day frames.
    const day = dayStrOf(new Date(item.ts));
    const { data: dayFrames } = useDayFrames(baseUrl, day);
    const source = useMemo(() => {
        if (item.kind !== "frame") return "session" as const;
        const f = dayFrames?.find((x) => x.id === item.id);
        return f ? srcOf(f) : ("none" as const);
    }, [item, dayFrames]);

    return (
        <button
            type="button"
            onClick={() => onPick(item)}
            className="flex flex-col overflow-hidden rounded-md border border-line bg-surface text-left transition-colors hover:border-primary"
        >
            <div className="flex h-14 w-full shrink-0 items-center justify-center border-b border-line bg-[linear-gradient(135deg,var(--surface-2),var(--surface))] text-[10px] text-faint">
                {item.kind === "frame" ? (
                    <img
                        src={frameImageUrl(baseUrl, item.id)}
                        alt=""
                        className="h-full w-full object-cover"
                        loading="lazy"
                    />
                ) : (
                    <span>session</span>
                )}
            </div>
            <div className="flex min-w-0 flex-col gap-1.5 p-3 pt-2">
                <div className="flex h-4 items-center gap-1.5">
                    <span className="shrink-0 font-mono text-[11px] text-faint">{relTime(item.ts)}</span>
                    <span
                        className={cn(
                            "shrink-0 rounded-full border px-1.5 py-px text-[9px] tracking-wide",
                            source === "a11y" && "border-ok/40 text-ok",
                            source === "ocr" && "border-primary/40 text-primary",
                            source === "session" && "border-line text-dim",
                        )}
                    >
                        {source === "a11y" ? "a11y tree" : source === "ocr" ? "ocr" : source === "session" ? "session" : "no text"}
                    </span>
                    <span className="ml-auto shrink-0 font-mono text-[11px] text-dim">{item.window_class}</span>
                </div>
                <p className="min-w-0 text-xs leading-snug break-words text-dim">
                    <Highlighted text={item.snippet} query={query} />
                </p>
                <div className="flex min-w-0 items-center gap-2 text-[10px] text-faint">
                    <b className="min-w-0 truncate font-semibold text-dim">
                        {item.window_title ?? item.window_class}
                    </b>
                    <span className="ml-auto shrink-0">
                        {item.kind === "frame" ? `score ${item.score.toFixed(2)}` : "watch session"}
                    </span>
                </div>
            </div>
        </button>
    );
}

function Highlighted({ text, query }: { text: string; query: string }) {
    const parts = useMemo(() => {
        const clean = text.replace(/\*\*/g, "");
        const q = query.trim();
        if (!q) return [clean];
        const out: React.ReactNode[] = [];
        let i = 0;
        let key = 0;
        while (i < clean.length) {
            const idx = clean.toLowerCase().indexOf(q.toLowerCase(), i);
            if (idx === -1) {
                out.push(<Fragment key={key++}>{clean.slice(i)}</Fragment>);
                break;
            }
            if (idx > i) out.push(<Fragment key={key++}>{clean.slice(i, idx)}</Fragment>);
            out.push(
                <mark key={key++} className="rounded-[3px] bg-primary/30 px-0.5 text-foreground">
                    {clean.slice(idx, idx + q.length)}
                </mark>,
            );
            i = idx + q.length;
        }
        return out;
    }, [text, query]);
    return <>{parts}</>;
}

