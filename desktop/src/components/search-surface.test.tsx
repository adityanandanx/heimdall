import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SearchSurface } from "./search-surface";
import { base, searchRequestUrls, setSearchResponseDelay } from "@/test/msw/handlers";
import { renderWithQuery } from "@/test/render";
import { dayBoundsISO, localISO } from "@/lib/timeline";
import { resetSessionSearch } from "@/lib/session-search";

function renderSearch() {
    const onPick = vi.fn();
    renderWithQuery(<SearchSurface baseUrl={base} focusNonce={1} seed="" onPick={onPick} />);
    return { onPick };
}

describe("SearchSurface", () => {
    beforeEach(() => {
        resetSessionSearch();
        searchRequestUrls.length = 0;
        setSearchResponseDelay(0);
    });

    afterEach(() => setSearchResponseDelay(0));

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

    it("color-tags results by application", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "roger" } });
        const playerChip = await screen.findByText("sidra");
        expect(playerChip).toHaveStyle({ color: "#3ecf8e" });

        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "heimdall" } });
        const clsChip = await screen.findByText("browser");
        expect(clsChip).toHaveStyle({ color: "#98c379" });
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

    it("keeps browsing when the all-time preset is selected", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("date range preset"), {
            target: { value: "all" },
        });
        expect(await screen.findByText("Heimdall docs")).toBeInTheDocument();
        expect(screen.getByText("Omurice — Uncle Roger")).toBeInTheDocument();
    });

    it("keeps the filter bar always visible, even idle", () => {
        renderSearch();
        expect(screen.getByRole("group", { name: "kind filter" })).toBeInTheDocument();
        expect(screen.getByLabelText("date range preset")).toBeInTheDocument();
        expect(screen.getByLabelText("start time")).toBeInTheDocument();
        expect(screen.getByLabelText("end time")).toBeInTheDocument();
        expect(screen.getByLabelText("source type")).toBeInTheDocument();
    });

    it("browses today's scope by default on a blank surface", async () => {
        renderSearch();
        await waitFor(() => expect(searchRequestUrls).toHaveLength(1));
        const params = new URL(searchRequestUrls[0]).searchParams;
        expect(params.has("q")).toBe(false); // browse, not a text query
        expect(params.get("start")).toBe(dayBoundsISO(localISO(new Date()).slice(0, 10)).start);
        expect(screen.getByText("Heimdall docs")).toBeInTheDocument();
    });

    it("compiles typed tokens into filters and keeps the text as the FTS query", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), {
            target: { value: "roger app:sidra" },
        });
        await waitFor(() =>
            expect(new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams.get("q")).toBe("roger"),
        );
        expect(await screen.findByText("Omurice — Uncle Roger")).toBeInTheDocument();
        const params = new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams;
        expect(params.get("q")).toBe("roger"); // tokens are stripped from the query text
        expect(await screen.findByRole("button", { name: "remove sidra filter" })).toBeInTheDocument();
    });

    it("runs browse mode for tokens alone, with an empty FTS query", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "app:terminal" } });
        expect(await screen.findByRole("button", { name: "remove terminal filter" })).toBeInTheDocument();
        await waitFor(() => expect(screen.queryByText("Heimdall docs")).not.toBeInTheDocument());
        expect(screen.getByText("htop")).toBeInTheDocument();
        const params = new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams;
        expect(params.get("q")).toBeNull();
    });

    it("reflects widget selections back into the box text", async () => {
        renderSearch();
        fireEvent.click(screen.getByRole("button", { name: /^app/ }));
        fireEvent.click(await screen.findByRole("checkbox", { name: "app browser" }));
        expect(screen.getByLabelText("search query")).toHaveValue("app:browser");
        // toggling the same app off removes the token again (dropdown stays open)
        fireEvent.click(await screen.findByRole("checkbox", { name: "app browser" }));
        expect(screen.getByLabelText("search query")).toHaveValue("");
    });

    it("kind and source widgets write their tokens into the box", async () => {
        renderSearch();
        fireEvent.click(screen.getByRole("button", { name: "frames" }));
        expect(screen.getByLabelText("search query")).toHaveValue("kind:frame");
        fireEvent.change(screen.getByLabelText("source type"), { target: { value: "ocr" } });
        expect(screen.getByLabelText("search query")).toHaveValue("kind:frame source:ocr");
    });

    it("removing a chip removes the token from the box text", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "roger app:sidra kind:session" } });
        fireEvent.click(await screen.findByRole("button", { name: "remove sidra filter" }));
        expect(screen.getByLabelText("search query")).toHaveValue("roger kind:session");
        fireEvent.click(await screen.findByRole("button", { name: "remove sessions filter" }));
        expect(screen.getByLabelText("search query")).toHaveValue("roger");
    });

    it("on: sets a custom day range in the widgets", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "on:2026-06-05" } });
        expect(await screen.findByRole("button", { name: /remove .* filter/ })).toBeInTheDocument();
        expect(screen.getByLabelText("start time")).toHaveValue("2026-06-05T00:00");
        expect(screen.getByLabelText("end time")).toHaveValue("2026-06-06T00:00");
    });

    it("binds after:HH:MM to the widget range's start day", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("date range preset"), { target: { value: "today" } });
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "after:09:30" } });
        expect(await screen.findByRole("button", { name: /remove .* filter/ })).toBeInTheDocument();
        const start = (screen.getByLabelText("start time") as HTMLInputElement).value;
        expect(start).toMatch(/T09:30$/);
    });

    it("glows recognized tokens in the overlay mirror", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "roger app:sidra" } });
        const mirror = document.querySelector('[aria-hidden="true"]');
        expect(mirror?.textContent).toContain("app:sidra");
        expect(mirror?.querySelectorAll("span[class*='text-primary']").length).toBe(1);
    });

    it("changing the date widget strips stale date tokens from the box", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "on:2026-06-05 roger" } });
        expect(screen.getByLabelText("start time")).toHaveValue("2026-06-05T00:00");
        fireEvent.change(screen.getByLabelText("date range preset"), { target: { value: "today" } });
        // the on: token is gone so it can't re-apply over the widget's choice
        expect(screen.getByLabelText("search query")).toHaveValue("roger");
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "roger after:09:30 before:18:00" } });
        fireEvent.change(screen.getByLabelText("date range preset"), { target: { value: "all" } });
        expect(screen.getByLabelText("search query")).toHaveValue("roger");
    });

    it("replaces a differently-cased token when toggled via the widget", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "app:BROWSER" } });
        expect(await screen.findByRole("button", { name: "remove BROWSER filter" })).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: /^app/ }));
        fireEvent.click(await screen.findByRole("checkbox", { name: "app browser" }));
        // token was replaced, not doubly-added or inverted
        expect(screen.getByLabelText("search query")).toHaveValue("app:browser");
        expect(screen.queryByRole("button", { name: "remove BROWSER filter" })).not.toBeInTheDocument();
    });

    it("browses newest-first with only a kind filter and no text", async () => {
        renderSearch();
        fireEvent.click(screen.getByRole("button", { name: "frames" }));
        await waitFor(() => expect(searchRequestUrls).toHaveLength(2)); // today's browse + kind-filtered
        expect(screen.queryByText("Heimdall docs")).toBeInTheDocument();
        const params = new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams;
        expect(params.has("q")).toBe(false);
        expect(params.get("kind")).toBe("frame");
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

    it("keeps browsing when the date scope is widened to all time", async () => {
        renderSearch();
        fireEvent.click(screen.getByRole("button", { name: "sessions" }));
        await screen.findByText("Omurice — Uncle Roger");
        const requestsAfterBrowse = searchRequestUrls.length;
        fireEvent.click(screen.getByRole("button", { name: "remove sessions filter" }));
        // the default today scope keeps the surface browsing — results persist
        expect(screen.getByText("Omurice — Uncle Roger")).toBeInTheDocument();
        fireEvent.change(screen.getByLabelText("date range preset"), { target: { value: "all" } });
        // "all time" is an explicit wider scope, not idle — results stay
        expect(await screen.findByText("Omurice — Uncle Roger")).toBeInTheDocument();
        await waitFor(() => expect(searchRequestUrls.length).toBeGreaterThan(requestsAfterBrowse));
    });

    it("debounces text and filter changes into one server query", async () => {
        renderSearch();
        await waitFor(() => expect(searchRequestUrls).toHaveLength(1)); // today's default browse
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "roger" } });
        fireEvent.change(screen.getByLabelText("source type"), { target: { value: "transcript" } });
        expect(await screen.findByText("watch session")).toBeInTheDocument();
        expect(searchRequestUrls).toHaveLength(2);
        const params = new URL(searchRequestUrls[1]).searchParams;
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
        await waitFor(() =>
            expect(new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams.get("start")).toContain("2026-08-01T00:00"),
        );
        const params = new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams;
        expect(params.get("start")).toContain("2026-08-01T00:00");
        expect(params.get("end")).toContain("2026-08-02T00:00");
        expect(screen.getByText(/08-01 00:00 → 08-02 00:00/)).toBeInTheDocument();
    });

    it("lets a preset replace a stale custom range", async () => {
        renderSearch();
        const urls = searchRequestUrls;
        fireEvent.change(screen.getByLabelText("start time"), {
            target: { value: "2026-08-01T00:00" },
        });
        await waitFor(() => expect(urls.length).toBeGreaterThan(1)); // today's browse + the custom range
        expect(new URL(urls[urls.length - 1]).searchParams.get("start")).toContain("2026-08-01T00:00");
        fireEvent.change(screen.getByLabelText("date range preset"), {
            target: { value: "today" },
        });
        // back on the default today scope, which is the cached mount scope: the
        // custom range is cleared and its stale results are replaced — no refetch
        await waitFor(() => expect(screen.getByText("Heimdall docs")).toBeInTheDocument());
        expect(urls).toHaveLength(2);
        expect(screen.getByLabelText("start time")).toHaveValue(""); // custom cleared
        expect(screen.getByRole("button", { name: "remove today filter" })).toBeInTheDocument();
    });

    it("waits out the debounce before issuing a request", async () => {
        renderSearch();
        await waitFor(() => expect(searchRequestUrls).toHaveLength(1)); // today's default browse
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "roger" } });
        await new Promise((resolve) => setTimeout(resolve, 150));
        expect(searchRequestUrls).toHaveLength(1); // 150ms < 250ms
        expect(await screen.findByText("watch session")).toBeInTheDocument();
        expect(searchRequestUrls).toHaveLength(2);
    });

    it("pins the source=a11y|ocr|transcript gates in browse mode", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("source type"), { target: { value: "ocr" } });
        await waitFor(() =>
            expect(new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams.get("source")).toBe("ocr"),
        );
        expect(await screen.findByText("PNG spec")).toBeInTheDocument();
        expect(screen.queryByText("Heimdall docs")).not.toBeInTheDocument();
        fireEvent.change(screen.getByLabelText("source type"), { target: { value: "a11y" } });
        expect(await screen.findByText("Heimdall docs")).toBeInTheDocument();
        expect(screen.queryByText("PNG spec")).not.toBeInTheDocument();
        fireEvent.change(screen.getByLabelText("source type"), { target: { value: "transcript" } });
        expect(await screen.findByText("Omurice — Uncle Roger")).toBeInTheDocument();
        expect(screen.getByText("Rust borrow checker deep dive")).toBeInTheDocument();
        expect(screen.queryByText("Heimdall docs")).not.toBeInTheDocument();
        expect(screen.queryByText("PNG spec")).not.toBeInTheDocument();
    });

    it("shows facet counts and filters results by selected apps", async () => {
        renderSearch();
        fireEvent.click(screen.getByRole("button", { name: /^app/ }));
        expect(await screen.findByRole("checkbox", { name: "app browser" })).toBeInTheDocument();
        expect(screen.getByRole("checkbox", { name: "app terminal" })).toBeInTheDocument();
        expect(screen.getByText("· 2")).toBeInTheDocument(); // browser count
        fireEvent.click(screen.getByRole("checkbox", { name: "app browser" }));
        expect(await screen.findByRole("button", { name: "remove browser filter" })).toBeInTheDocument();
        expect(await screen.findByText("Heimdall docs")).toBeInTheDocument();
        expect(screen.getByText("PNG spec")).toBeInTheDocument();
        expect(screen.queryByText("htop")).not.toBeInTheDocument(); // terminal frame filtered out
        // the app filter only narrows frames — sessions survive it
        expect(screen.getByText("Omurice — Uncle Roger")).toBeInTheDocument();
        expect(screen.getByText("Rust borrow checker deep dive")).toBeInTheDocument();
    });

    it("filters sessions by selected players, leaving frames alone", async () => {
        renderSearch();
        fireEvent.click(screen.getByRole("button", { name: /^player/ }));
        fireEvent.click(await screen.findByRole("checkbox", { name: "player sidra" }));
        expect(await screen.findByRole("button", { name: "remove sidra filter" })).toBeInTheDocument();
        expect(await screen.findByText("Omurice — Uncle Roger")).toBeInTheDocument();
        expect(screen.queryByText("Rust borrow checker deep dive")).not.toBeInTheDocument();
        expect(screen.getByText("Heimdall docs")).toBeInTheDocument(); // frames unaffected
    });

    it("refreshes facet counts as the query scope changes", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "roger" } });
        await screen.findByText("Omurice — Uncle Roger");
        fireEvent.click(screen.getByRole("button", { name: /^app/ }));
        expect(await screen.findByText("No apps.")).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: /^player/ }));
        expect(await screen.findByRole("checkbox", { name: "player sidra" })).toBeInTheDocument();
        expect(screen.queryByRole("checkbox", { name: "player vlc" })).not.toBeInTheDocument();
    });

    it("refreshes facet counts as the date scope changes", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("date range preset"), { target: { value: "yesterday" } });
        fireEvent.click(screen.getByRole("button", { name: /^app/ }));
        expect(await screen.findByText("No apps.")).toBeInTheDocument(); // fixtures are all today
        fireEvent.change(screen.getByLabelText("date range preset"), { target: { value: "today" } });
        expect(await screen.findByRole("checkbox", { name: "app browser" })).toBeInTheDocument();
        expect(screen.getByRole("checkbox", { name: "app terminal" })).toBeInTheDocument();
    });

    it("renders an empty state for empty facet lists", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "zzzznothing" } });
        await waitFor(() =>
            expect(new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams.get("q")).toBe("zzzznothing"),
        );
        expect(await screen.findByText("No matches.")).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: /^app/ }));
        expect(await screen.findByText("No apps.")).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: /^player/ }));
        expect(await screen.findByText("No players.")).toBeInTheDocument();
    });

    it("clear affordance empties the app selection", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("date range preset"), { target: { value: "today" } });
        fireEvent.click(screen.getByRole("button", { name: /^app/ }));
        fireEvent.click(await screen.findByRole("checkbox", { name: "app browser" }));
        await waitFor(() => expect(screen.queryByText("htop")).not.toBeInTheDocument());
        fireEvent.click(await screen.findByRole("checkbox", { name: "app terminal" }));
        fireEvent.click(screen.getByRole("button", { name: "clear" }));
        await waitFor(() =>
            expect(screen.queryByRole("button", { name: "remove browser filter" })).not.toBeInTheDocument(),
        );
        expect(await screen.findByText("htop")).toBeInTheDocument(); // unfiltered again
    });

    it("applies only the latest scope when text changes rapidly", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "roger" } });
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "zzzznothing" } });
        await waitFor(() =>
            expect(new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams.get("q")).toBe("zzzznothing"),
        );
        expect(await screen.findByText("No matches.")).toBeInTheDocument();
        expect(screen.queryByText("Omurice — Uncle Roger")).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: /^app/ }));
        expect(await screen.findByText("No apps.")).toBeInTheDocument();
        expect(screen.queryByRole("checkbox", { name: "app browser" })).not.toBeInTheDocument();
    });

    it("ignores a late response for an outdated scope", async () => {
        setSearchResponseDelay(300); // hold the first response in flight
        renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "roger" } });
        await waitFor(() => expect(searchRequestUrls.length).toBe(1)); // "roger" is in flight
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "zzzznothing" } });
        expect(await screen.findByText("No matches.")).toBeInTheDocument();
        expect(screen.queryByText("Omurice — Uncle Roger")).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: /^app/ }));
        expect(await screen.findByText("No apps.")).toBeInTheDocument();
        await waitFor(() =>
            expect(new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams.get("q"))
                .toBe("zzzznothing"),
        );
    });

    it("browses newest-first with the relevance toggle hidden (#62)", async () => {
        renderSearch();
        await waitFor(() => expect(searchRequestUrls.length).toBe(1));
        const params = new URL(searchRequestUrls[0]).searchParams;
        expect(params.get("sort")).toBe("ts");
        expect(screen.queryByRole("group", { name: "sort order" })).not.toBeInTheDocument();
    });

    it("defaults to relevance sort once text is present (#62)", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "roger" } });
        await waitFor(() =>
            expect(new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams.get("q")).toBe("roger"),
        );
        expect(new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams.get("sort")).toBe("score");
        const toggle = screen.getByRole("group", { name: "sort order" });
        expect(toggle).toHaveTextContent("relevance");
        expect(toggle).toHaveTextContent("newest");
    });

    it("switches the sort with the toggle (#62)", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "roger" } });
        await waitFor(() => expect(searchRequestUrls.length).toBe(2));
        expect(screen.getByRole("button", { name: "relevance" })).toHaveAttribute("aria-pressed", "true");
        fireEvent.click(screen.getByRole("button", { name: "newest" }));
        expect(screen.getByRole("button", { name: "newest" })).toHaveAttribute("aria-pressed", "true");
        await waitFor(() =>
            expect(new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams.get("sort")).toBe("ts"),
        );
        // Back to relevance: the ts→score transition reuses the cached score
        // scope (no new request), so assert the active state instead.
        fireEvent.click(screen.getByRole("button", { name: "relevance" }));
        expect(screen.getByRole("button", { name: "relevance" })).toHaveAttribute("aria-pressed", "true");
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "roger z" } });
        await waitFor(() =>
            expect(new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams.get("q")).toBe("roger z"),
        );
        expect(new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams.get("sort")).toBe("score");
    });

    it("keeps the chosen query and sort across remounts within the session (#62)", async () => {
        const { unmount } = renderWithQuery(
            <SearchSurface baseUrl={base} focusNonce={1} seed="" onPick={vi.fn()} />,
        );
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "roger" } });
        await waitFor(() => expect(searchRequestUrls.length).toBe(2));
        fireEvent.click(screen.getByRole("button", { name: "newest" }));
        await waitFor(() =>
            expect(new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams.get("sort")).toBe("ts"),
        );
        unmount(); // navigating away unmounts the surface…

        searchRequestUrls.length = 0; // fresh mount must fetch, not replay
        renderWithQuery(<SearchSurface baseUrl={base} focusNonce={1} seed="" onPick={vi.fn()} />);
        // Query AND sort both survived the remount within the session.
        expect(screen.getByLabelText("search query")).toHaveValue("roger");
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "roger z" } });
        await waitFor(() =>
            expect(new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams.get("q")).toBe("roger z"),
        );
        expect(new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams.get("sort")).toBe("ts");
    });

    it("writes the fullscreen segmented control into the box and params (#63)", async () => {
        renderSearch();
        fireEvent.click(screen.getByRole("button", { name: "fullscreen" }));
        expect(screen.getByLabelText("search query")).toHaveValue("fullscreen:yes");
        await waitFor(() =>
            expect(new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams.get("fullscreen")).toBe("true"),
        );
        fireEvent.click(screen.getByRole("button", { name: "windowed" }));
        await waitFor(() =>
            expect(new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams.get("fullscreen")).toBe("false"),
        );
        expect(screen.getByLabelText("search query")).toHaveValue("fullscreen:no");
        fireEvent.click(screen.getByRole("button", { name: "any" }));
        expect(screen.getByLabelText("search query")).toHaveValue("");
    });

    it("picks a workspace and monitor from the facet dropdowns into params (#63)", async () => {
        renderSearch();
        await waitFor(() => expect(screen.getByRole("option", { name: "workspace 2" })).toBeInTheDocument());
        fireEvent.change(screen.getByLabelText("workspace filter"), { target: { value: "2" } });
        expect(screen.getByLabelText("search query")).toHaveValue("ws:2");
        await waitFor(() =>
            expect(new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams.get("workspace")).toBe("2"),
        );
        fireEvent.change(screen.getByLabelText("monitor filter"), { target: { value: "1" } });
        expect(screen.getByLabelText("search query")).toHaveValue("ws:2 monitor:1");
        await waitFor(() =>
            expect(new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams.get("monitor")).toBe("1"),
        );
        const params = new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams;
        expect(params.get("workspace")).toBe("2");
        expect(params.get("monitor")).toBe("1");
    });

    it("reflects frame attribute tokens back into the widgets (#63)", async () => {
        renderSearch();
        await waitFor(() => expect(screen.getByRole("option", { name: "workspace 2" })).toBeInTheDocument());
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "ws:2 fullscreen:no" } });
        expect(screen.getByRole("button", { name: "windowed" })).toHaveAttribute("aria-pressed", "true");
        expect(screen.getByLabelText("workspace filter")).toHaveValue("2");
        fireEvent.change(screen.getByLabelText("monitor filter"), { target: { value: "1" } });
        expect(screen.getByLabelText("search query")).toHaveValue("ws:2 fullscreen:no monitor:1");
    });

    it("applies frame attributes to frames only, sessions never match (#63)", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "ws:2 fullscreen:no" } });
        await waitFor(() =>
            expect(new URL(searchRequestUrls[searchRequestUrls.length - 1]).searchParams.get("workspace")).toBe("2"),
        );
        // Frames: #3 is workspace 2 but fullscreen; #2/#4 are windowed but ws 1 —
        // none qualify. Sessions ignore frame attributes entirely.
        expect(await screen.findByText("Omurice — Uncle Roger")).toBeInTheDocument(); // session ignores frame attrs
        expect(screen.getByText("Rust borrow checker deep dive")).toBeInTheDocument();
        expect(screen.queryByText("Heimdall docs")).not.toBeInTheDocument();
        expect(screen.queryByText("PNG spec")).not.toBeInTheDocument();
        expect(screen.queryByText("htop")).not.toBeInTheDocument();
    });

    it("removes frame-attribute chips via the box text (#63)", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "ws:2 monitor:1 fullscreen:yes" } });
        expect(await screen.findByRole("button", { name: "remove ws 2 filter" })).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "remove ws 2 filter" }));
        expect(screen.getByLabelText("search query")).toHaveValue("monitor:1 fullscreen:yes");
        fireEvent.click(screen.getByRole("button", { name: "remove fullscreen yes filter" }));
        expect(screen.getByLabelText("search query")).toHaveValue("monitor:1");
    });
});