import { useQuery } from "@tanstack/react-query";
import { apiUrl, fetchJson, type Health, type ServerStatus } from "@/lib/api";

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