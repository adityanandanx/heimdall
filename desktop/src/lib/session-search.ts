import { useSyncExternalStore } from "react";
import { DEFAULT_FILTERS, type SearchFilters } from "@/lib/search-filters";

export type SearchSort = "score" | "ts";

/** Search-tab state that must survive surface switches within the session
 * (query, filters and sort, #55/#62). Lives in module memory on purpose:
 * alive for the app's lifetime, gone on restart. */
export interface SessionSearchState {
    q: string;
    filters: SearchFilters;
    sort: SearchSort;
}

let state: SessionSearchState = { q: "", filters: DEFAULT_FILTERS, sort: "score" };
const listeners = new Set<() => void>();

function emit(): void {
    for (const l of [...listeners]) l();
}

export function getSessionSearch(): SessionSearchState {
    return state;
}

export function setSessionSearch(patch: Partial<SessionSearchState>): void {
    state = { ...state, ...patch };
    emit();
}

/** Test seam: back to a pristine, untouched store. */
export function resetSessionSearch(): void {
    state = { q: "", filters: DEFAULT_FILTERS, sort: "score" };
    emit();
}

/** Subscribe the component tree to the in-session search state. */
export function useSessionSearch(): SessionSearchState {
    return useSyncExternalStore(
        (l) => {
            listeners.add(l);
            return () => listeners.delete(l);
        },
        getSessionSearch,
        getSessionSearch,
    );
}
