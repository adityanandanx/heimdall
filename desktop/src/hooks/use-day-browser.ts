import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import {
    fetchDayFrames,
    fetchDaySessions,
    fetchFacets,
    fetchRecentSessions,
    fetchSearchPage,
    runPipe,
    type PipeRunResult,
} from "@/lib/api";

export function useDayFrames(
    baseUrl: string,
    day: string,
    refetchIntervalMs: number | false = false,
) {
    return useQuery({
        queryKey: ["day-frames", baseUrl, day],
        queryFn: () => fetchDayFrames(baseUrl, day),
        enabled: !!baseUrl && !!day,
        refetchOnWindowFocus: false,
        refetchInterval: refetchIntervalMs || false,
    });
}

export function useDaySessions(baseUrl: string, day: string) {
    return useQuery({
        queryKey: ["day-sessions", baseUrl, day],
        queryFn: () => fetchDaySessions(baseUrl, day),
        enabled: !!baseUrl && !!day,
        refetchOnWindowFocus: false,
    });
}

export function useRecentSessions(baseUrl: string, days = 7) {
    return useQuery({
        queryKey: ["recent-sessions", baseUrl, days],
        queryFn: () => fetchRecentSessions(baseUrl, days),
        enabled: !!baseUrl,
        staleTime: 30_000,
        refetchOnWindowFocus: false,
    });
}

export function useDebouncedValue<T>(value: T, delayMs: number): T {
    const [debounced, setDebounced] = useState(value);
    useEffect(() => {
        const t = window.setTimeout(() => setDebounced(value), delayMs);
        return () => window.clearTimeout(t);
    }, [value, delayMs]);
    return debounced;
}

export const SEARCH_PAGE_SIZE = 100;

export function useSearch(baseUrl: string, params: URLSearchParams, active: boolean) {
    // `active` is the same searchActive(f, q) gate the component renders with,
    // debounced; it covers client-side app/player filters that leave no
    // server params behind (#59). Offset pages are disjoint per scope, so
    // appending never duplicates; a scope change resets to page 0 (#61).
    return useInfiniteQuery({
        queryKey: ["search-pages", baseUrl, params.toString()],
        queryFn: ({ pageParam, signal }) =>
            fetchSearchPage(baseUrl, params, pageParam, SEARCH_PAGE_SIZE, signal),
        initialPageParam: 0,
        getNextPageParam: (lastPage, allPages) => {
            const loaded = allPages.reduce((n, p) => n + p.items.length, 0);
            if (lastPage.items.length === 0 || loaded >= lastPage.total) return undefined;
            return loaded;
        },
        enabled: !!baseUrl && active,
        staleTime: 30_000,
        refetchOnWindowFocus: false,
    });
}

export function useFacets(baseUrl: string, params: URLSearchParams) {
    // Counts refresh with the debounced scope; each scope is its own cache
    // key, so late responses for an old scope are never applied (race-safe).
    return useQuery({
        queryKey: ["search-facets", baseUrl, params.toString()],
        queryFn: ({ signal }) => fetchFacets(baseUrl, params, signal),
        enabled: !!baseUrl,
        staleTime: 30_000,
        refetchOnWindowFocus: false,
    });
}

export function useRunPipe(baseUrl: string, day: string) {
    const queryClient = useQueryClient();
    const [results, setResults] = useState<Record<string, PipeRunResult>>({});
    const [error, setError] = useState<string | null>(null);

    const run = useCallback(
        async (name: string) => {
            setError(null);
            try {
                const result = await runPipe(baseUrl, name, day);
                setResults((prev) => ({ ...prev, [name]: result }));
                void queryClient.invalidateQueries({ queryKey: ["status"] });
                return result;
            } catch (err) {
                setError(err instanceof Error ? err.message : String(err));
                throw err;
            }
        },
        [baseUrl, day, queryClient],
    );

    const mutation = useMutation({ mutationFn: run });
    return { run: mutation.mutate, isRunning: mutation.isPending, results, error };
}

// Re-export so App and the day browser share one /health cache entry.
export { useHealth, useStatus } from "./use-heimdall";