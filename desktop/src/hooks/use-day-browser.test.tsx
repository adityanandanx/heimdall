import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it } from "vitest";
import { useDayFrames } from "./use-day-browser";
import { base, fixtureDay, frameRequestUrls } from "@/test/msw/handlers";

const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
);

describe("useDayFrames", () => {
    beforeEach(() => {
        frameRequestUrls.length = 0;
    });

    it("does not poll when refetchIntervalMs is off", async () => {
        const { result } = renderHook(() => useDayFrames(base, fixtureDay), { wrapper });
        await waitFor(() => expect(result.current.isSuccess).toBe(true));
        const count = frameRequestUrls.length;
        await new Promise((r) => setTimeout(r, 150));
        expect(frameRequestUrls.length).toBe(count);
    });

    it("refetches on an interval when refetchIntervalMs is set", async () => {
        const { result } = renderHook(() => useDayFrames(base, fixtureDay, 20), { wrapper });
        await waitFor(() => expect(result.current.isSuccess).toBe(true));
        const count = frameRequestUrls.length;
        await waitFor(() => expect(frameRequestUrls.length).toBeGreaterThan(count), {
            timeout: 3000,
            interval: 40,
        });
    });
});