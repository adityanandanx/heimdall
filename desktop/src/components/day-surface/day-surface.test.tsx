import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DaySurface } from "./day-surface";
import { base, fixtureDay } from "@/test/msw/handlers";
import { shiftDay } from "@/lib/timeline";
import { renderWithQuery } from "@/test/render";

function renderDay(overrides: { day?: string } = {}) {
    const onDayChange = vi.fn();
    const onSeekDone = vi.fn();
    renderWithQuery(
        <DaySurface
            baseUrl={base}
            day={overrides.day ?? fixtureDay}
            onDayChange={onDayChange}
            seek={null}
            onSeekDone={onSeekDone}
        />,
    );
    return { onDayChange, onSeekDone };
}

describe("DaySurface", () => {
    it("renders the day's frames with a default selection and caption", async () => {
        renderDay();
        await screen.findAllByText(/watch-lane\.tsx/); // caption + meta title
        expect(screen.getByText("DAY")).toBeInTheDocument();
        expect(screen.getByText("capturing")).toBeInTheDocument();
    });

    it("steps selection with arrow keys", async () => {
        renderDay();
        await screen.findAllByText(/watch-lane\.tsx/);
        fireEvent.keyDown(window, { key: "ArrowLeft" });
        await screen.findAllByText(/git push/); // 12:00 terminal frame
        fireEvent.keyDown(window, { key: "ArrowRight" });
        await screen.findAllByText(/watch-lane\.tsx/);
    });

    it("jumps to the last frame with g", async () => {
        renderDay();
        await screen.findAllByText(/watch-lane\.tsx/);
        fireEvent.keyDown(window, { key: "ArrowLeft" });
        await screen.findAllByText(/git push/);
        fireEvent.keyDown(window, { key: "g" });
        await screen.findAllByText(/watch-lane\.tsx/);
    });

    it("focuses the day search with /", async () => {
        renderDay();
        await screen.findAllByText(/watch-lane\.tsx/);
        fireEvent.keyDown(window, { key: "/" });
        await waitFor(() =>
            expect(document.activeElement).toHaveAttribute("placeholder", expect.stringContaining("Search the day")),
        );
    });

    it("shows hit count when searching the day", async () => {
        renderDay();
        const input = await screen.findByPlaceholderText(/Search the day/);
        fireEvent.change(input, { target: { value: "omurice" } });
        expect(await screen.findByText("3")).toBeInTheDocument(); // frames 5,6,7
    });

    it("navigates days via the topbar", async () => {
        const { onDayChange } = renderDay();
        await screen.findAllByText(/watch-lane\.tsx/);
        fireEvent.click(screen.getByLabelText("previous day"));
        expect(onDayChange).toHaveBeenCalledWith(expect.not.stringMatching(fixtureDay));
        fireEvent.click(screen.getByLabelText("next day"));
        expect(onDayChange).toHaveBeenLastCalledWith(shiftDay(fixtureDay, 1));
    });

    it("shows a hover popup over the timeline without changing the main preview", async () => {
        renderDay();
        await screen.findAllByText(/watch-lane\.tsx/); // last frame selected in the main preview
        const timeline = screen.getByTestId("filmstrip-timeline");
        fireEvent.pointerMove(timeline, { clientX: 10, clientY: 10 });
        const popup = await screen.findByTestId("hover-popup");
        expect(popup).toHaveTextContent(/\d{2}:\d{2}:\d{2}/); // shows a frame's time
        expect(popup).not.toHaveTextContent("watch-lane.tsx"); // never the main preview
        expect(screen.getAllByText(/watch-lane\.tsx/).length).toBeGreaterThan(0); // main unchanged
    });

    it("dismisses the hover popup when the pointer leaves", async () => {
        renderDay();
        await screen.findAllByText(/watch-lane\.tsx/);
        const timeline = screen.getByTestId("filmstrip-timeline");
        fireEvent.pointerMove(timeline, { clientX: 10, clientY: 10 });
        await screen.findByTestId("hover-popup");
        fireEvent.pointerLeave(timeline);
        expect(screen.queryByTestId("hover-popup")).not.toBeInTheDocument();
    });

    it("runs the day recap and renders its markdown", async () => {
        renderDay();
        await screen.findByText("⟳ synthesize");
        fireEvent.click(screen.getByText("⟳ synthesize"));
        expect(await screen.findByText("A good day.")).toBeInTheDocument();
        expect(screen.getByText(/10 frames · 2\.3s/)).toBeInTheDocument();
    });

    it("lists apps with percentages and filters by class", async () => {
        renderDay();
        await screen.findByText("⟳ synthesize");
        expect(screen.getByTestId("app-filter-code.editor")).toBeInTheDocument();
        expect(screen.getByTestId("app-filter-browser")).toBeInTheDocument();
        fireEvent.click(screen.getByTestId("app-filter-browser"));
        fireEvent.click(screen.getByTestId("apps-filter-clear"));
        expect(screen.getByTestId("app-filter-browser")).toBeInTheDocument();
    });

    it("shows an empty state for days without captures", async () => {
        renderDay({ day: "2020-01-01" });
        expect(await screen.findByText("No captures for 2020-01-01.")).toBeInTheDocument();
    });
});
