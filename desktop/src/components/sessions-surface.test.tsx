import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SessionsSurface } from "./sessions-surface";
import { base, resetFixtures } from "@/test/msw/handlers";
import { renderWithQuery } from "@/test/render";

const details = () => screen.getByRole("region", { name: "video details" });

describe("SessionsSurface", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        resetFixtures();
    });
    it("shows details of the most recent video in the right pane by default", async () => {
        renderWithQuery(<SessionsSurface baseUrl={base} />);

        await screen.findByRole("button", { name: "local film.mkv — view details" });
        const pane = details();
        expect(within(pane).getByText("local film.mkv")).toBeInTheDocument();
        expect(within(pane).getByText("No source")).toBeInTheDocument();
        expect(
            within(pane).queryByRole("button", { name: "Open video" }),
        ).not.toBeInTheDocument();
    });

    it("merges same-video sessions and shows stats on the card", async () => {
        renderWithQuery(<SessionsSurface baseUrl={base} />);

        await screen.findByText("YouTube");
        expect(screen.getByText("2 videos")).toBeInTheDocument();

        const card = screen.getByRole("button", { name: "Omurice — Uncle Roger — view details" });
        expect(within(card).getByText(/2 sessions/)).toBeInTheDocument();
        expect(within(card).getByText(/watched 1m/)).toBeInTheDocument();
        expect(within(card).getByText(/2% watched/)).toBeInTheDocument();
        expect(within(card).getByText(/13 words/)).toBeInTheDocument();
        expect(card).toHaveAttribute("aria-pressed", "false");
        expect(within(card).getByText("sidra")).toHaveStyle({ color: "#3ecf8e" });
    });

    it("selects a video on click and shows its details in the right pane", async () => {
        renderWithQuery(<SessionsSurface baseUrl={base} />);

        const card = await screen.findByRole("button", {
            name: "Omurice — Uncle Roger — view details",
        });
        fireEvent.click(card);
        expect(card).toHaveAttribute("aria-pressed", "true");

        const pane = details();
        expect(
            within(pane).getByRole("button", { name: "Open video" }),
        ).toBeInTheDocument();
        expect(within(pane).getByText("2")).toBeInTheDocument();
        const sessionsList = within(pane).getAllByRole("list")[0];
        expect(within(sessionsList).getAllByRole("listitem")).toHaveLength(2);
    });

    it("opens the video from the card button without changing selection", async () => {
        const open = vi.spyOn(window, "open").mockImplementation(() => null);
        renderWithQuery(<SessionsSurface baseUrl={base} />);

        await screen.findByRole("button", { name: "local film.mkv — view details" });
        const openBtn = screen.getByRole("button", {
            name: "open video Omurice — Uncle Roger",
        });
        fireEvent.click(openBtn);

        expect(open).toHaveBeenCalledWith(
            "https://www.youtube.com/watch?v=omurice123",
            "_blank",
        );
        expect(within(details()).getByText("local film.mkv")).toBeInTheDocument();
        open.mockRestore();
    });

    it("opens the video from the details pane", async () => {
        const open = vi.spyOn(window, "open").mockImplementation(() => null);
        renderWithQuery(<SessionsSurface baseUrl={base} />);

        const card = await screen.findByRole("button", {
            name: "Omurice — Uncle Roger — view details",
        });
        fireEvent.click(card);
        fireEvent.click(within(details()).getByRole("button", { name: "Open video" }));

        expect(open).toHaveBeenCalledWith(
            "https://www.youtube.com/watch?v=omurice123",
            "_blank",
        );
        open.mockRestore();
    });

    it("disables open for title-only videos and marks live sessions", async () => {
        renderWithQuery(<SessionsSurface baseUrl={base} />);

        await screen.findByText("LIVE");
        const localCard = screen.getByRole("button", { name: "local film.mkv — view details" });
        expect(within(localCard).getByRole("button", { name: "open video local film.mkv" })).toBeDisabled();

        const devCard = screen.getByRole("button", { name: "Some dev video — view details" });
        expect(within(devCard).getByText("LIVE")).toBeInTheDocument();
        expect(within(devCard).getByRole("button", { name: "open video Some dev video" })).toBeEnabled();
    });

    it("shows a unified transcript and opens YouTube at a clicked cue", async () => {
        const open = vi.spyOn(window, "open").mockImplementation(() => null);
        renderWithQuery(<SessionsSurface baseUrl={base} />);

        const card = await screen.findByRole("button", {
            name: "Omurice — Uncle Roger — view details",
        });
        fireEvent.click(card);
        const pane = details();

        expect(within(pane).getByText("the most difficult omelet")).toBeInTheDocument();
        expect(within(pane).getByText("fuiyoh")).toBeInTheDocument();
        expect(within(pane).getByText("fuiyoh so good")).toBeInTheDocument();
        expect(within(pane).getByText("2:00")).toBeInTheDocument();
        expect(within(pane).getByText("15:00")).toBeInTheDocument();

        fireEvent.click(within(pane).getByRole("button", { name: /open the most difficult omelet/ }));
        expect(open).toHaveBeenCalledWith(
            "https://www.youtube.com/watch?v=omurice123&t=120s",
            "_blank",
        );
        open.mockRestore();
    });

    it("falls back to plain transcript text for videos without cues", async () => {
        renderWithQuery(<SessionsSurface baseUrl={base} />);

        const card = await screen.findByRole("button", {
            name: "local film.mkv — view details",
        });
        fireEvent.click(card);
        expect(within(details()).getByText("No transcript captured.")).toBeInTheDocument();
    });

    it("fetches a missing transcript for a stream-backed session (#1)", async () => {
        renderWithQuery(<SessionsSurface baseUrl={base} />);

        const card = await screen.findByRole("button", {
            name: "Some dev video — view details",
        });
        fireEvent.click(card);
        const fetchBtn = within(details()).getByRole("button", {
            name: "⟳ fetch transcript",
        });
        fireEvent.click(fetchBtn);
        expect(await screen.findByText(/transcript · fetch · 5 words/)).toBeInTheDocument();
        expect(
            within(details()).queryByRole("button", { name: "⟳ fetch transcript" }),
        ).not.toBeInTheDocument();
    });

    it("deletes a session after confirm and refreshes the list (#1)", async () => {
        vi.spyOn(window, "confirm").mockReturnValue(true);
        renderWithQuery(<SessionsSurface baseUrl={base} />);

        const card = await screen.findByRole("button", {
            name: "Some dev video — view details",
        });
        fireEvent.click(card);
        fireEvent.click(
            within(details()).getByRole("button", { name: "delete session 22" }),
        );
        await waitFor(() =>
            expect(
                screen.queryByRole("button", { name: "Some dev video — view details" }),
            ).not.toBeInTheDocument(),
        );
    });

    it("keeps the session when delete is cancelled (#1)", async () => {
        vi.spyOn(window, "confirm").mockReturnValue(false);
        renderWithQuery(<SessionsSurface baseUrl={base} />);

        const card = await screen.findByRole("button", {
            name: "Some dev video — view details",
        });
        fireEvent.click(card);
        fireEvent.click(
            within(details()).getByRole("button", { name: "delete session 22" }),
        );
        expect(
            screen.getByRole("button", { name: "Some dev video — view details" }),
        ).toBeInTheDocument();
    });
});