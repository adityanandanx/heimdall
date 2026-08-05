import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
    fetchDayFrames,
    fetchDaySessions,
    fetchRecentSessions,
    fetchSearch,
    runPipe,
    type PipeRunResult,
} from "@/lib/api";
import {
    compileSearchParams,
    type SearchFilters,
} from "@/lib/search-filters";

export function useDayFrames(baseUrl: string, day: string) {
    return useQuery({
        queryKey: ["day-frames", baseUrl, day],
        queryFn: () => fetchDayFrames(baseUrl, day),
        enabled: !!baseUrl && !!day,
        refetchOnWindowFocus: false,
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

export function useSearch(baseUrl: string, query: string, filters: SearchFilters) {
    const params = useMemo(() => compileSearchParams(filters, query), [filters, query]);
    const debounced = useDebouncedValue(params, 250);
    const enabled = useMemo(() => {
        if (!baseUrl) return false;
        const q = debounced.get("q") ?? "";
        const filterActive =
            debounced.has("kind") ||
            debounced.has("source") ||
            debounced.has("start") ||
            debounced.has("end");
        // Browse mode: text or any filter fetches; bare idle state does not.
        return q.length >= 2 || filterActive;
    }, [baseUrl, debounced]);
    return useQuery({
        queryKey: ["search", baseUrl, debounced.toString()],
        queryFn: ({ signal }) => fetchSearch(baseUrl, debounced, signal),
        enabled,
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