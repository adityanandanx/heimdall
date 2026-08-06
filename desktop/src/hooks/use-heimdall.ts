import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
    apiUrl,
    fetchJson,
    type Health,
    type ServerStatus,
    type SettingsSurfaceValues,
} from "@/lib/api";

// Liveness probe: fast poll, drives the online/offline banner.
export function useHealth(baseUrl: string) {
    return useQuery({
        queryKey: ["health", baseUrl],
        queryFn: ({ signal }) => fetchJson<Health>(apiUrl(baseUrl, "/health"), signal),
        refetchInterval: 10_000,
        retry: false,
    });
}

// Rich status payload: everything the "is everything in order" screen shows.
export function useStatus(baseUrl: string) {
    return useQuery({
        queryKey: ["status", baseUrl],
        queryFn: ({ signal }) => fetchJson<ServerStatus>(apiUrl(baseUrl, "/status"), signal),
        refetchInterval: 15_000,
        retry: false,
    });
}

// The writable settings surface (values live in config.yaml, read live so a
// daemon reload or external edit shows up on the next visit).
export function useSettings(baseUrl: string) {
    return useQuery({
        queryKey: ["settings", baseUrl],
        queryFn: ({ signal }) => fetchJson<SettingsSurfaceValues>(apiUrl(baseUrl, "/settings"), signal),
        enabled: !!baseUrl,
        staleTime: 30_000,
        refetchOnWindowFocus: false,
    });
}

export function useInvalidateSettings(baseUrl: string) {
    const queryClient = useQueryClient();
    return () =>
        queryClient.invalidateQueries({ queryKey: ["settings", baseUrl] }) as unknown as Promise<void>;
}