import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Shell } from "./shell";
import { renderWithQuery } from "@/test/render";

describe("Shell", () => {
    it("renders all five surfaces in two groups", () => {
        renderWithQuery(
            <Shell surface="day" onSurface={vi.fn()} onGlobalSearch={vi.fn()} online>
                content
            </Shell>,
        );
        expect(screen.getByText("Browse")).toBeInTheDocument();
        expect(screen.getByText("System")).toBeInTheDocument();
        for (const label of ["Day", "Search", "Sessions", "Status", "Settings"]) {
            expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
        }
    });

    it("marks the active surface", () => {
        renderWithQuery(
            <Shell surface="settings" onSurface={vi.fn()} onGlobalSearch={vi.fn()} online>
                content
            </Shell>,
        );
        expect(screen.getByRole("button", { name: "Settings" })).toHaveAttribute("aria-current", "page");
        expect(screen.getByRole("button", { name: "Day" })).not.toHaveAttribute("aria-current");
    });

    it("navigates on sidebar click", () => {
        const onSurface = vi.fn();
        renderWithQuery(
            <Shell surface="day" onSurface={onSurface} onGlobalSearch={vi.fn()} online>
                content
            </Shell>,
        );
        fireEvent.click(screen.getByRole("button", { name: "Status" }));
        expect(onSurface).toHaveBeenCalledWith("status");
    });

    it("summons global search with ⌘K", () => {
        const onGlobalSearch = vi.fn();
        renderWithQuery(
            <Shell surface="day" onSurface={vi.fn()} onGlobalSearch={onGlobalSearch} online>
                content
            </Shell>,
        );
        fireEvent.keyDown(window, { key: "k", metaKey: true });
        expect(onGlobalSearch).toHaveBeenCalled();
    });

    it("shows the offline banner when disconnected", () => {
        renderWithQuery(
            <Shell surface="day" onSurface={vi.fn()} onGlobalSearch={vi.fn()} online={false}>
                content
            </Shell>,
        );
        expect(screen.getByTestId("offline-banner")).toBeInTheDocument();
        expect(screen.getByText(/Start it with/)).toBeInTheDocument();
    });

    it("hides the offline banner when connected", () => {
        renderWithQuery(
            <Shell surface="day" onSurface={vi.fn()} onGlobalSearch={vi.fn()} online>
                content
            </Shell>,
        );
        expect(screen.queryByText(/Start it with/)).not.toBeInTheDocument();
    });
});
