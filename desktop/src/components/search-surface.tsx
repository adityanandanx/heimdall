import { Fragment, useCallback, useEffect, useMemo, useRef } from "react";
import type { SearchItem } from "@/lib/api";
import { frameImageUrl } from "@/lib/api";
import { relTime } from "@/lib/format";
import { srcOf } from "@/lib/frames";
import { dayStrOf, clsColor, playerColor } from "@/lib/timeline";
import { AppChip } from "@/components/app-chip";
import {
    activeChips,
    compileSearchParams,
    filterItems,
    FULLSCREENS,
    KINDS,
    PRESETS,
    searchActive,
    SOURCES,
    type ChipId,
    type SearchFilters,
} from "@/lib/search-filters";
import {
    applyQueryTokens,
    insertToken,
    parseQuery,
    removeDateTokens,
    removeOpTokens,
    removeSourceTokens,
    removeToken,
    tokenMatch,
} from "@/lib/query-language";
import { cn } from "@/lib/utils";
import { FacetDropdown } from "@/components/ui/facet-dropdown";
import { GlowInput } from "@/components/ui/glow-input";
import { useDayFrames, useDebouncedValue, useFacets, useSearch } from "@/hooks/use-day-browser";
import {
    getSessionSearch,
    setSessionSearch,
    useSessionSearch,
} from "@/lib/session-search";

interface SearchSurfaceProps {
    baseUrl: string;
    focusNonce: number;
    seed: string;
    onPick: (item: SearchItem) => void;
}

const CONTROL_CLASS =
    "rounded-md border border-line bg-surface px-2 py-1 text-[11px] text-dim outline-none focus:border-primary [color-scheme:dark]";

export function SearchSurface({ baseUrl, focusNonce, seed, onPick }: SearchSurfaceProps) {
    const inputRef = useRef<HTMLInputElement>(null);
    const nowRef = useRef<Date>(new Date());
    // In-session store: query, filters and sort survive surface switches
    // (#55/#62) — the component remounts per tab, the store does not.
    const { q, filters, sort } = useSessionSearch();

    // The box text is the single source of truth for the text-authoritative
    // dimensions (app/player/kind/source/ws/monitor/fullscreen); the parse
    // projects them into filter state. Date dimensions live in the widgets.
    const parsed = useMemo(() => parseQuery(q), [q]);
    const setText = useCallback((text: string) => {
        const prev = getSessionSearch();
        const { filters: next } = applyQueryTokens(prev.filters, parseQuery(text), nowRef.current);
        setSessionSearch({ q: text, filters: next });
    }, []);

    // Widget ↓ text sync: absolute-select dims (kind/source/ws/monitor/
    // fullscreen) replace the token; multi-select dims (app/player) toggle
    // one value in/out.
    const setTextDim = (op: "kind" | "source" | "ws" | "monitor" | "fullscreen", value: string) => {
        const base = op === "source" ? removeSourceTokens(q) : removeOpTokens(q, op);
        setText(value === "all" || value === "any" || value === "" ? base : insertToken(base, op, value));
    };
    const toggleTextValue = (op: "app" | "player", value: string) => {
        const match = parsed.tokens.find((t) => tokenMatch(t, op, value) && !t.negated);
        if (!match) {
            setText(insertToken(q, op, value));
        } else if (match.value === value) {
            setText(removeToken(q, op, value));
        } else {
            // Token typed with different casing — replace, don't invert.
            setText(insertToken(removeToken(q, op, match.value), op, value));
        }
    };
    // Date widgets own the date dimension entirely — clear any date tokens.
    const setDateDim = (partial: Partial<SearchFilters>) => {
        const prev = getSessionSearch();
        setSessionSearch({ q: removeDateTokens(prev.q), filters: { ...prev.filters, ...partial } });
    };

    const params = useMemo(() => {
        const apiQ = parsed.text;
        return compileSearchParams(filters, apiQ, sort);
    }, [parsed.text, filters, sort]);
    const active = useMemo(() => searchActive(filters, parsed.text), [filters, parsed.text]);
    // Debounce params and the gate as ONE object so they can never land in
    // an inconsistent intermediate state (spurious browse fetches).
    const scope = useMemo(() => ({ params, active }), [params, active]);
    const debounced = useDebouncedValue(scope, 250);
    const {
        data: searchPages,
        isFetching,
        isFetchingNextPage,
        hasNextPage,
        fetchNextPage,
        isError,
    } = useSearch(baseUrl, debounced.params, debounced.active);
    const { data: facets, isPending: facetsPending } = useFacets(baseUrl, debounced.params);
    const sentinelRef = useRef<HTMLDivElement>(null);

    const items = useMemo(() => (searchPages?.pages ?? []).flatMap((p) => p.items), [searchPages]);
    const total = searchPages?.pages[0]?.total ?? 0;
    const loadingMore = isFetchingNextPage || isFetching;
    const loadMore = () => {
        if (!loadingMore && hasNextPage) void fetchNextPage();
    };

    // Bottom sentinel: load the next page as the user scrolls near it; the
    // load-more button stays as the deterministic fallback (#61).
    useEffect(() => {
        const el = sentinelRef.current;
        if (!el || !hasNextPage || !("IntersectionObserver" in window)) return;
        const observer = new IntersectionObserver(
            (entries) => {
                if (entries[0]?.isIntersecting && !loadingMore && !isError) loadMore();
            },
            { rootMargin: "600px" },
        );
        observer.observe(el);
        return () => observer.disconnect();
    }, [hasNextPage, loadingMore, isError]);

    // Autofocus when the surface opens (or is summoned with ⌘K).
    useEffect(() => {
        if (focusNonce > 0) window.setTimeout(() => inputRef.current?.focus(), 0);
    }, [focusNonce]);

    // Seed the query when the day surface hands off a search.
    useEffect(() => {
        if (seed) setText(seed);
    }, [seed, setText]);

    const removeChip = (id: ChipId) => {
        // Chips for text-authoritative dimensions edit the box text (which
        // then resets the state); the date chip clears the widgets too.
        switch (id) {
            case "kind":
                setText(removeOpTokens(q, "kind"));
                return;
            case "source":
                setText(removeSourceTokens(q));
                return;
            case "workspace":
                setText(removeOpTokens(q, "ws"));
                return;
            case "monitor":
                setText(removeOpTokens(q, "monitor"));
                return;
            case "fullscreen":
                setText(removeOpTokens(q, "fullscreen"));
                return;
            case "date":
                setDateDim({ preset: "all", start: "", end: "" });
                return;
            default:
                if (id.startsWith("app:")) {
                    setText(removeToken(q, "app", id.slice(4)));
                    return;
                }
                if (id.startsWith("player:")) {
                    setText(removeToken(q, "player", id.slice(7)));
                    return;
                }
        }
    };

    const query = parsed.text;
    const chips = useMemo(() => activeChips(filters), [filters]);
    // Same gate the fetch hook uses (on raw state, so clearing filters hides
    // stale results instantly rather than after the debounce).
    const showResults = active;
    // Client-side app/player membership (the API params are single-valued).
    const filtered = useMemo(
        () => (items ? filterItems(filters, items) : items),
        [items, filters],
    );

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
                <GlowInput
                    value={q}
                    tokens={parsed.tokens}
                    onChange={setText}
                    placeholder="e.g.  tauri setup  ·  lofi  ·  PR review"
                    ariaLabel="search query"
                    inputRef={inputRef}
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
                            onClick={() => setTextDim("kind", k.id)}
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
                    onChange={(e) => {
                        const preset = e.currentTarget.value as SearchFilters["preset"];
                        setDateDim({ preset, start: "", end: "" });
                    }}
                    className={CONTROL_CLASS}
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
                    onChange={(e) => setDateDim({ start: e.currentTarget.value, preset: "all" })}
                    className={CONTROL_CLASS}
                />
                <input
                    type="datetime-local"
                    aria-label="end time"
                    value={filters.end}
                    onChange={(e) => setDateDim({ end: e.currentTarget.value, preset: "all" })}
                    className={CONTROL_CLASS}
                />
                <select
                    aria-label="source type"
                    value={filters.source}
                    onChange={(e) => setTextDim("source", e.currentTarget.value as SearchFilters["source"])}
                    className={CONTROL_CLASS}
                >
                    {SOURCES.map((s) => (
                        <option key={s.id} value={s.id}>
                            {s.label}
                        </option>
                    ))}
                </select>
                <div
                    role="group"
                    aria-label="fullscreen filter"
                    className="flex overflow-hidden rounded-full border border-line"
                >
                    {FULLSCREENS.map((fs) => (
                        <button
                            key={fs.id}
                            type="button"
                            aria-pressed={filters.fullscreen === fs.id}
                            onClick={() => setTextDim("fullscreen", fs.id)}
                            className={cn(
                                "px-2.5 py-1 text-[11px] transition-colors",
                                filters.fullscreen === fs.id
                                    ? "bg-primary/15 text-primary"
                                    : "text-dim hover:text-foreground",
                            )}
                        >
                            {fs.label}
                        </button>
                    ))}
                </div>
                <select
                    aria-label="workspace filter"
                    value={filters.workspace}
                    onChange={(e) => setTextDim("ws", e.currentTarget.value)}
                    className={CONTROL_CLASS}
                >
                    <option value="">any workspace</option>
                    {(facets?.workspaces ?? []).map((ws) => (
                        <option key={ws.value} value={ws.value}>
                            workspace {ws.value}
                        </option>
                    ))}
                </select>
                <select
                    aria-label="monitor filter"
                    value={filters.monitor}
                    onChange={(e) => setTextDim("monitor", e.currentTarget.value)}
                    className={CONTROL_CLASS}
                >
                    <option value="">any monitor</option>
                    {(facets?.monitors ?? []).map((m) => (
                        <option key={m.value} value={m.value}>
                            monitor {m.value}
                        </option>
                    ))}
                </select>
                <FacetDropdown
                    label="app"
                    options={facets?.apps ?? []}
                    pending={facetsPending}
                    selected={filters.apps}
                    onToggle={(value) => toggleTextValue("app", value)}
                    onClear={() => setText(removeOpTokens(q, "app"))}
                    className={CONTROL_CLASS}
                />
                <FacetDropdown
                    label="player"
                    options={facets?.players ?? []}
                    pending={facetsPending}
                    selected={filters.players}
                    onToggle={(value) => toggleTextValue("player", value)}
                    onClear={() => setText(removeOpTokens(q, "player"))}
                    className={CONTROL_CLASS}
                />
                {parsed.text.trim().length > 0 && (
                    <div
                        role="group"
                        aria-label="sort order"
                        className="ml-auto flex overflow-hidden rounded-full border border-line"
                    >
                        <SortOption active={sort === "score"} label="relevance" onClick={() => setSessionSearch({ sort: "score" })} />
                        <SortOption active={sort === "ts"} label="newest" onClick={() => setSessionSearch({ sort: "ts" })} />
                    </div>
                )}
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
                <div className="flex flex-col gap-3">
                    <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] items-start gap-3">
                        {(filtered ?? []).map((item) => (
                            <ResultCard key={`${item.kind}-${item.id}`} item={item} query={query} baseUrl={baseUrl} onPick={onPick} />
                        ))}
                        {filtered && filtered.length === 0 && (
                            <p className="col-span-full text-xs text-dim">No matches.</p>
                        )}
                    </div>
                    {total > 0 && (filtered?.length ?? 0) > 0 && (
                        <div
                            className="flex items-center gap-2 text-[11px] text-dim"
                            aria-label="pagination"
                        >
                            <span>
                                showing {filtered!.length.toLocaleString()} of {total.toLocaleString()}
                            </span>
                            {hasNextPage && (
                                <button
                                    type="button"
                                    onClick={loadMore}
                                    disabled={loadingMore}
                                    aria-label="load more"
                                    className="rounded-full border border-line px-2.5 py-0.5 text-[10px] text-primary transition-colors hover:border-primary disabled:opacity-50"
                                >
                                    {isFetchingNextPage ? "…" : isError ? "load more · retry" : "load more"}
                                </button>
                            )}
                        </div>
                    )}
                    <div ref={sentinelRef} aria-hidden className="h-px" />
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
            <div className="flex aspect-video w-full shrink-0 items-center justify-center overflow-hidden border-b border-line bg-[linear-gradient(135deg,var(--surface-2),var(--surface))] text-[10px] text-faint">
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
            <div className="flex min-w-0 flex-col gap-2 p-4 pt-2.5">
                <div className="flex h-5 items-center gap-1.5">
                    <span className="shrink-0 font-mono text-xs text-faint">{relTime(item.ts)}</span>
                    <span
                        className={cn(
                            "shrink-0 rounded-full border px-1.5 py-px text-[10px] tracking-wide",
                            source === "a11y" && "border-ok/40 text-ok",
                            source === "ocr" && "border-primary/40 text-primary",
                            source === "session" && "border-line text-dim",
                        )}
                    >
                        {source === "a11y" ? "a11y tree" : source === "ocr" ? "ocr" : source === "session" ? "session" : "no text"}
                    </span>
                    <span className="ml-auto flex shrink-0 items-center gap-1">
                        {item.player && (
                            <AppChip label={item.player} color={playerColor(item.player)} />
                        )}
                        {item.window_class && (
                            <AppChip label={item.window_class} color={clsColor(item.window_class)} />
                        )}
                    </span>
                </div>
                <p className="line-clamp-2 min-w-0 text-[13px] leading-snug break-words text-dim">
                    <Highlighted text={item.snippet} query={query} />
                </p>
                <div className="flex min-w-0 items-center gap-2 text-[11px] text-faint">
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

function SortOption({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
    return (
        <button
            type="button"
            onClick={onClick}
            aria-pressed={active}
            className={
                active
                    ? "bg-primary/15 px-2.5 py-1 text-[11px] text-primary"
                    : "px-2.5 py-1 text-[11px] text-dim transition-colors hover:text-foreground"
            }
        >
            {label}
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

