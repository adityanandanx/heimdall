import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SessionsSurface } from "./sessions-surface";
import { base } from "@/test/msw/handlers";
import { renderWithQuery } from "@/test/render";

describe("SessionsSurface", () => {
    it("lists recent watch sessions grouped by day", async () => {
        const onJump = vi.fn();
        renderWithQuery(<SessionsSurface baseUrl={base} onJump={onJump} />);
        expect(await screen.findByText("Omurice — Uncle Roger")).toBeInTheDocument();
        expect(screen.getByText("Some dev video")).toBeInTheDocument();
        expect(screen.getByText("sidra")).toBeInTheDocument();
        expect(screen.getByText(/watched 1h 30m/)).toBeInTheDocument();
        expect(screen.getByText(/10 words/)).toBeInTheDocument();
    });

    it("marks live sessions", async () => {
        const onJump = vi.fn();
        renderWithQuery(<SessionsSurface baseUrl={base} onJump={onJump} />);
        expect(await screen.findByText("LIVE")).toBeInTheDocument();
    });

    it("jumps to a session on click", async () => {
        const onJump = vi.fn();
        renderWithQuery(<SessionsSurface baseUrl={base} onJump={onJump} />);
        const row = await screen.findByText("Omurice — Uncle Roger");
        fireEvent.click(row);
        expect(onJump).toHaveBeenCalledWith(
            expect.objectContaining({ id: 21, media_title: "Omurice — Uncle Roger" }),
        );
    });
});
