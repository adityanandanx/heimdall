import type { SearchItem } from "@/lib/api";
import { dayBoundsISO, localISO, shiftDay } from "@/lib/timeline";

export type KindFilter = "all" | "frame" | "session";
export type SourceFilter = "any" | "a11y" | "ocr" | "transcript";
export type DatePreset = "all" | "today" | "yesterday" | "last7" | "thisMonth";

/** All search filters in one state shape; compiled into /search params (#58). */
export interface SearchFilters {
    kind: KindFilter;
    preset: DatePreset;
    /** Custom bounds as datetime-local values ("" = unset); win over the preset. */
    start: string;
    end: string;
    source: SourceFilter;
    /** Multi-select app/player values (facet dropdowns, #59); /search's
     * window_class/player params are single-valued, so these filter
     * client-side while the facets endpoint counts the full scope. */
    apps: string[];
    players: string[];
}

export const DEFAULT_FILTERS: SearchFilters = {
    kind: "all",
    preset: "all",
    start: "",
    end: "",
    source: "any",
    apps: [],
    players: [],
};

export const KINDS: Array<{ id: KindFilter; label: string }> = [
    { id: "all", label: "all" },
    { id: "frame", label: "frames" },
    { id: "session", label: "sessions" },
];

export const PRESETS: Array<{ id: DatePreset; label: string }> = [
    { id: "all", label: "all time" },
    { id: "today", label: "today" },
    { id: "yesterday", label: "yesterday" },
    { id: "last7", label: "last 7 days" },
    { id: "thisMonth", label: "this month" },
];

export const SOURCES: Array<{ id: SourceFilter; label: string }> = [
    { id: "any", label: "any source" },
    { id: "a11y", label: "a11y" },
    { id: "ocr", label: "ocr" },
    { id: "transcript", label: "transcript" },
];

export function hasKind(f: SearchFilters): boolean {
    return f.kind !== "all";
}

export function hasSource(f: SearchFilters): boolean {
    return f.source !== "any";
}

export function hasApps(f: SearchFilters): boolean {
    return f.apps.length > 0;
}

export function hasPlayers(f: SearchFilters): boolean {
    return f.players.length > 0;
}

export function hasDate(f: SearchFilters): boolean {
    return f.preset !== "all" || f.start !== "" || f.end !== "";
}

export function isDefaultFilters(f: SearchFilters): boolean {
    return !hasKind(f) && !hasSource(f) && !hasApps(f) && !hasPlayers(f) && !hasDate(f);
}

/** Is a search scope active (text ready, or any filter set)? The single gate
 * both the fetch hook and the results grid consume (#58/#59). */
export function searchActive(f: SearchFilters, q: string): boolean {
    return q.trim().length >= 2 || !isDefaultFilters(f);
}

/** Resolve the custom start/end revealed by the state (dates in, ISOs out). */
export function dateRangeOf(
    f: SearchFilters,
    now: Date = new Date(),
): { start: string; end: string } {
    if (f.start || f.end) {
        return {
            start: f.start ? localISO(new Date(f.start)) : "",
            end: f.end ? localISO(new Date(f.end)) : "",
        };
    }
    const today = localISO(now).slice(0, 10);
    switch (f.preset) {
        case "today":
            return { start: dayBoundsISO(today).start, end: localISO(now) };
        case "yesterday": {
            const y = shiftDay(today, -1);
            return { start: dayBoundsISO(y).start, end: dayBoundsISO(y).end };
        }
        case "last7": {
            const s = dayBoundsISO(shiftDay(today, -6));
            return { start: s.start, end: localISO(now) };
        }
        case "thisMonth": {
            const start = new Date(now.getFullYear(), now.getMonth(), 1, 0, 0, 0, 0);
            return { start: localISO(start), end: localISO(now) };
        }
        default:
            return { start: "", end: "" };
    }
}

/** The /search query params for the current query + filters. */
export function compileSearchParams(f: SearchFilters, q: string): URLSearchParams {
    const params = new URLSearchParams();
    const trimmed = q.trim();
    if (trimmed) params.set("q", trimmed);
    if (hasKind(f)) params.set("kind", f.kind);
    if (hasSource(f)) params.set("source", f.source);
    const { start, end } = dateRangeOf(f);
    if (start) params.set("start", start);
    if (end) params.set("end", end);
    // The search timeline is always newest-first (#37/#58); the API's default.
    params.set("sort", "ts");
    return params;
}

export type ChipId = "kind" | "source" | "date" | `app:${string}` | `player:${string}`;

export interface ActiveChip {
    id: ChipId;
    label: string;
}

/** The removable chips shown while a filter is active (slim row, #58/#59). */
export function activeChips(f: SearchFilters): ActiveChip[] {
    const chips: ActiveChip[] = [];
    const kindLabel = KINDS.find((k) => k.id === f.kind)?.label;
    const sourceLabel = SOURCES.find((s) => s.id === f.source)?.label;
    if (hasKind(f) && kindLabel) chips.push({ id: "kind", label: kindLabel });
    if (hasSource(f) && sourceLabel) chips.push({ id: "source", label: sourceLabel });
    for (const app of f.apps) chips.push({ id: `app:${app}`, label: app });
    for (const player of f.players) chips.push({ id: `player:${player}`, label: player });
    if (hasDate(f)) {
        let label: string;
        if (f.start || f.end) {
            const fmt = (v: string) => (v ? v.slice(5).replace("T", " ") : "");
            label = [fmt(f.start), fmt(f.end)].filter(Boolean).join(" → ");
        } else {
            label = PRESETS.find((p) => p.id === f.preset)?.label ?? f.preset;
        }
        chips.push({ id: "date", label });
    }
    return chips;
}

/** Reset one filter dimension to its default (chip removal). */
export function withChipRemoved(f: SearchFilters, id: ChipId): SearchFilters {
    switch (id) {
        case "kind":
            return { ...f, kind: "all" };
        case "source":
            return { ...f, source: "any" };
        case "date":
            return { ...f, preset: "all", start: "", end: "" };
        default: {
            if (id.startsWith("app:")) {
                const app = id.slice(4);
                return { ...f, apps: f.apps.filter((a) => a !== app) };
            }
            if (id.startsWith("player:")) {
                const player = id.slice(7);
                return { ...f, players: f.players.filter((p) => p !== player) };
            }
            return f;
        }
    }
}

/** Toggle one value in a multi-select list (facet dropdowns). */
export function toggleValue(list: string[], value: string): string[] {
    return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

/** Apply the client-side app/player membership filters to a result page.
 *
 * Frames match apps on window_class; sessions match players on player —
 * /search's window_class/player params are single-valued, so the facets
 * endpoint counts the full scope while these narrow the results (#59).
 */
export function filterItems(f: SearchFilters, items: SearchItem[]): SearchItem[] {
    let result = items;
    if (hasApps(f)) {
        // only frames carry a window_class — sessions pass through
        result = result.filter((i) => i.kind === "session" || f.apps.includes(i.window_class));
    }
    if (hasPlayers(f)) {
        // only sessions carry a player — frames pass through
        result = result.filter((i) => i.kind === "frame" || f.players.includes(i.player ?? ""));
    }
    return result;
}