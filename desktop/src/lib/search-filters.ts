import { localISO } from "@/lib/timeline";

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
}

export const DEFAULT_FILTERS: SearchFilters = {
    kind: "all",
    preset: "all",
    start: "",
    end: "",
    source: "any",
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

export function isDefaultFilters(f: SearchFilters): boolean {
    return (
        f.kind === "all" &&
        f.preset === "all" &&
        f.start === "" &&
        f.end === "" &&
        f.source === "any"
    );
}

/** Resolve the custom start/end revealed by the state (dates in, ISOs out). */
export function dateRangeOf(
    f: SearchFilters,
    now: Date = new Date(),
): { start: string; end: string } {
    const midnight = (d: Date) =>
        new Date(d.getFullYear(), d.getMonth(), d.getDate(), 0, 0, 0, 0);
    const iso = (d: Date) => localISO(d);

    if (f.start || f.end) {
        return {
            start: f.start ? iso(new Date(f.start)) : "",
            end: f.end ? iso(new Date(f.end)) : "",
        };
    }
    switch (f.preset) {
        case "today":
            return { start: iso(midnight(now)), end: iso(now) };
        case "yesterday": {
            const start = midnight(now);
            start.setDate(start.getDate() - 1);
            return { start: iso(start), end: iso(midnight(now)) };
        }
        case "last7": {
            const start = midnight(now);
            start.setDate(start.getDate() - 6);
            return { start: iso(start), end: iso(now) };
        }
        case "thisMonth": {
            const start = new Date(now.getFullYear(), now.getMonth(), 1, 0, 0, 0, 0);
            return { start: iso(start), end: iso(now) };
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
    if (f.kind !== "all") params.set("kind", f.kind);
    if (f.source !== "any") params.set("source", f.source);
    const { start, end } = dateRangeOf(f);
    if (start) params.set("start", start);
    if (end) params.set("end", end);
    return params;
}

export type ChipId = "kind" | "source" | "date";

export interface ActiveChip {
    id: ChipId;
    label: string;
}

/** The removable chips shown while a filter is active (slim row, #58). */
export function activeChips(f: SearchFilters): ActiveChip[] {
    const chips: ActiveChip[] = [];
    const kindLabel = KINDS.find((k) => k.id === f.kind)?.label;
    const sourceLabel = SOURCES.find((s) => s.id === f.source)?.label;
    if (f.kind !== "all" && kindLabel) chips.push({ id: "kind", label: kindLabel });
    if (f.source !== "any" && sourceLabel) chips.push({ id: "source", label: sourceLabel });
    if (f.preset !== "all" || f.start || f.end) {
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
    }
}

/** Is this a fetched scope (text ready or any filter set)? Mirrors the hook gate. */
export function wouldFetch(f: SearchFilters, q: string): boolean {
    return q.trim().length >= 2 || !isDefaultFilters(f);
}