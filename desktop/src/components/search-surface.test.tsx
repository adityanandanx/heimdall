import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SearchSurface } from "./search-surface";
import { base } from "@/test/msw/handlers";
import { renderWithQuery } from "@/test/render";

function renderSearch() {
    const onPick = vi.fn();
    renderWithQuery(<SearchSurface baseUrl={base} focusNonce={1} onPick={onPick} />);
    return { onPick };
}

describe("SearchSurface", () => {
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

    it("filters results by kind", async () => {
        renderSearch();
        fireEvent.change(screen.getByLabelText("search query"), { target: { value: "omurice" } });
        await screen.findByText("watch session");
        fireEvent.click(screen.getByRole("button", { name: "frames" }));
        expect(screen.queryByText("watch session")).not.toBeInTheDocument();
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
});
