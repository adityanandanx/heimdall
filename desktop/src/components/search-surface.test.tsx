import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SearchSurface } from "./search-surface";
import { base, searchRequestUrls } from "@/test/msw/handlers";
import { renderWithQuery } from "@/test/render";

function renderSearch() {
    const onPick = vi.fn();
    renderWithQuery(<SearchSurface baseUrl={base} focusNonce={1} seed="" onPick={onPick} />);
    return { onPick };
}

describe("SearchSurface", () => {
    beforeEach(() => {
        searchRequestUrls.length = 0;
    });

    it("autofocuses the query input when opened", async () => {
        renderSearch();
        await waitFor(() =>
            expect(document.activeElement).toHaveAttribute("placeholder", expect.stringContaining("e.g.")),
        );
    });

    it("returns frame results with a source badge and score", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "heimdall" } });
        expect(await screen.findByText("Heimdall docs")).toBeInTheDocument();
        expect(await screen.findByText("a11y tree")).toBeInTheDocument();
        expect(screen.getByText(/score 1\.90/)).toBeInTheDocument();
    });

    it("returns session results and highlights the match", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "roger" } });
        expect(await screen.findByText("watch session")).toBeInTheDocument();
        expect(screen.getByText("Omurice — Uncle Roger")).toBeInTheDocument();
        const mark = document.querySelector("mark");
        expect(mark).not.toBeNull();
        expect(mark?.textContent).toBe("roger");
    });

    it("picks an item on click", async () => {
        const { onPick } = renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "roger" } });
        const card = await screen.findByText("watch session");
        fireEvent.click(card);
        expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ id: 21, kind: "session" }));
    });

    it("shows an empty state for no matches", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "zzzznothing" } });
        expect(await screen.findByText("No matches.")).toBeInTheDocument();
    });

    it("keeps the filter bar always visible, even idle", () => {
        renderSearch();
        expect(screen.getByRole("group", { name: "kind filter" })).toBeInTheDocument();
        expect(screen.getByLabelText("date range preset")).toBeInTheDocument();
        expect(screen.getByLabelText("start time")).toBeInTheDocument();
        expect(screen.getByLabelText("end time")).toBeInTheDocument();
        expect(screen.getByLabelText("source type")).toBeInTheDocument();
    });

    it("does not fetch on an idle, unfiltered surface", async () => {
        renderSearch();
        await new Promise((resolve) => setTimeout(resolve, 350));
        expect(searchRequestUrls).toHaveLength(0);
    });

    it("browses newest-first with only a kind filter and no text", async () => {
        renderSearch();
        const urls = searchRequestUrls;
        fireEvent.click(screen.getByRole("button", { name: "frames" }));
        expect(await screen.findByText("Heimdall docs")).toBeInTheDocument();
        expect(urls).toHaveLength(1);
        expect(new URL(urls[0]).searchParams.has("q")).toBe(false);
        expect(new URL(urls[0]).searchParams.get("kind")).toBe("frame");
    });

    it("applies the kind filter server-side", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "omurice" } });
        await screen.findByText("watch session");
        fireEvent.click(screen.getByRole("button", { name: "frames" }));
        expect(await screen.findByText("No matches.")).toBeInTheDocument();
        expect(screen.queryByText("watch session")).not.toBeInTheDocument();
    });

    it("show active filters as removable chips and resets on removal", async () => {
        renderSearch();
        fireEvent.click(screen.getByRole("button", { name: "frames" }));
        fireEvent.change(screen.getByLabelText("source type"), { target: { value: "a11y" } });
        fireEvent.change(screen.getByLabelText("date range preset"), { target: { value: "today" } });
        expect(await screen.findByRole("button", { name: "remove frames filter" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "remove a11y filter" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "remove today filter" })).toBeInTheDocument();

        fireEvent.click(screen.getByRole("button", { name: "remove frames filter" }));
        await waitFor(() =>
            expect(screen.queryByRole("button", { name: "remove frames filter" })).not.toBeInTheDocument(),
        );
        expect(screen.getByRole("button", { name: "remove a11y filter" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "remove today filter" })).toBeInTheDocument();
        // kind is back to the default while the other chips keep browse alive
        expect(screen.getByRole("group", { name: "kind filter" }).textContent).toContain("all");
    });

    it("returns to idle when the last chip is removed with no text", async () => {
        renderSearch();
        fireEvent.click(screen.getByRole("button", { name: "sessions" }));
        await screen.findByText("watch session");
        const requestsAfterBrowse = searchRequestUrls.length;
        fireEvent.click(screen.getByRole("button", { name: "remove sessions filter" }));
        await waitFor(() => expect(screen.queryByText("watch session")).not.toBeInTheDocument());
        expect(searchRequestUrls).toHaveLength(requestsAfterBrowse); // no extra fetch
    });

    it("debounces text and filter changes into one server query", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "roger" } });
        fireEvent.change(screen.getByLabelText("source type"), { target: { value: "transcript" } });
        expect(await screen.findByText("watch session")).toBeInTheDocument();
        expect(searchRequestUrls).toHaveLength(1);
        const params = new URL(searchRequestUrls[0]).searchParams;
        expect(params.get("q")).toBe("roger");
        expect(params.get("source")).toBe("transcript");
    });

    it("compiles a custom date range into start/end params", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("start time"), {
            target: { value: "2026-08-01T00:00" },
        });
        fireEvent.change(screen.getByLabelText("end time"), {
            target: { value: "2026-08-02T00:00" },
        });
        await waitFor(() => expect(searchRequestUrls.length).toBeGreaterThan(0));
        const params = new URL(searchRequestUrls[0]).searchParams;
        expect(params.get("start")).toContain("2026-08-01T00:00");
        expect(params.get("end")).toContain("2026-08-02T00:00");
        expect(screen.getByText(/08-01 00:00 → 08-02 00:00/)).toBeInTheDocument();
    });

    it("pins the source=a11y|ocr|transcript gates", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "heimdall" } });
        expect(await screen.findByText("Heimdall docs")).toBeInTheDocument();
        fireEvent.change(screen.getByLabelText("source type"), { target: { value: "ocr" } });
        expect(await screen.findByText("No matches.")).toBeInTheDocument();
        fireEvent.change(screen.getByLabelText("source type"), { target: { value: "a11y" } });
        expect(await screen.findByText("Heimdall docs")).toBeInTheDocument();
    });
});