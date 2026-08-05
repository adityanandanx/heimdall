import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import type { SearchItem } from "@/lib/api";
import { frameImageUrl } from "@/lib/api";
import { relTime } from "@/lib/format";
import { srcOf } from "@/lib/frames";
import { dayStrOf } from "@/lib/timeline";
import {
    activeChips,
    DEFAULT_FILTERS,
    KINDS,
    PRESETS,
    SOURCES,
    withChipRemoved,
    wouldFetch,
    type ChipId,
    type SearchFilters,
} from "@/lib/search-filters";
import { cn } from "@/lib/utils";
import { useDayFrames, useSearch } from "@/hooks/use-day-browser";

interface SearchSurfaceProps {
    baseUrl: string;
    focusNonce: number;
    seed: string;
    onPick: (item: SearchItem) => void;
}

export function SearchSurface({ baseUrl, focusNonce, seed, onPick }: SearchSurfaceProps) {
    const [q, setQ] = useState("");
    const [filters, setFilters] = useState<SearchFilters>(DEFAULT_FILTERS);
    const inputRef = useRef<HTMLInputElement>(null);

    const { data, isFetching } = useSearch(baseUrl, q, filters);

    // Autofocus when the surface opens (or is summoned with ⌘K).
    useEffect(() => {
        if (focusNonce > 0) window.setTimeout(() => inputRef.current?.focus(), 0);
    }, [focusNonce]);

    // Seed the query when the day surface hands off a search.
    useEffect(() => {
        if (seed) setQ(seed);
    }, [seed]);

    const patch = (partial: Partial<SearchFilters>) =>
        setFilters((prev) => ({ ...prev, ...partial }));

    const removeChip = (id: ChipId) =>
        setFilters((prev) => withChipRemoved(prev, id));

    const query = q.trim();
    const chips = useMemo(() => activeChips(filters), [filters]);
    const showResults = wouldFetch(filters, q);

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

            {/* Always-visible filter bar (#58) */}
            <div className="flex flex-wrap items-center gap-2">
                <div
                    role="group"
                    aria-label="kind filter"
                    className="flex overflow-hidden rounded-full border border-line"
                >
                    {KINDS.map((k) => (
                        <button
                            key={k.id}
                            type="button"
                            onClick={() => patch({ kind: k.id })}
                            className={cn(
                                "px-2.5 py-1 text-[11px] transition-colors",
                                filters.kind === k.id
                                    ? "bg-primary/15 text-primary"
                                    : "text-dim hover:text-foreground",
                            )}
                        >
                            {k.label}
                        </button>
                    ))}
                </div>
                <select
                    aria-label="date range preset"
                    value={filters.preset}
                    onChange={(e) => patch({ preset: e.currentTarget.value as SearchFilters["preset"] })}
                    className="rounded-md border border-line bg-surface px-2 py-1 text-[11px] text-dim outline-none focus:border-primary [color-scheme:dark]"
                >
                    {PRESETS.map((p) => (
                        <option key={p.id} value={p.id}>
                            {p.label}
                        </option>
                    ))}
                </select>
                <input
                    type="datetime-local"
                    aria-label="start time"
                    value={filters.start}
                    onChange={(e) => patch({ start: e.currentTarget.value })}
                    className="rounded-md border border-line bg-surface px-2 py-1 text-[11px] text-dim outline-none focus:border-primary [color-scheme:dark]"
                />
                <input
                    type="datetime-local"
                    aria-label="end time"
                    value={filters.end}
                    onChange={(e) => patch({ end: e.currentTarget.value })}
                    className="rounded-md border border-line bg-surface px-2 py-1 text-[11px] text-dim outline-none focus:border-primary [color-scheme:dark]"
                />
                <select
                    aria-label="source type"
                    value={filters.source}
                    onChange={(e) => patch({ source: e.currentTarget.value as SearchFilters["source"] })}
                    className="rounded-md border border-line bg-surface px-2 py-1 text-[11px] text-dim outline-none focus:border-primary [color-scheme:dark]"
                >
                    {SOURCES.map((s) => (
                        <option key={s.id} value={s.id}>
                            {s.label}
                        </option>
                    ))}
                </select>
            </div>

            {chips.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5" aria-label="active filters">
                    {chips.map((chip) => (
                        <button
                            key={chip.id}
                            type="button"
                            onClick={() => removeChip(chip.id)}
                            aria-label={`remove ${chip.label} filter`}
                            className="flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-[10px] text-primary transition-colors hover:bg-primary/20"
                        >
                            {chip.label}
                            <span aria-hidden>×</span>
                        </button>
                    ))}
                </div>
            )}

            {showResults && (
                <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] items-start gap-3">
                    {(data ?? []).map((item) => (
                        <ResultCard key={`${item.kind}-${item.id}`} item={item} query={query} baseUrl={baseUrl} onPick={onPick} />
                    ))}
                    {data && data.length === 0 && (
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

