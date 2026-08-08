import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DaySurface } from "./day-surface";
import { base, fixtureDay, resetFixtures } from "@/test/msw/handlers";
import { shiftDay } from "@/lib/timeline";
import { renderWithQuery } from "@/test/render";

function renderDay(overrides: { day?: string } = {}) {
    const onDayChange = vi.fn();
    const onOpenSearch = vi.fn();
    const onSeekDone = vi.fn();
    renderWithQuery(
        <DaySurface
            baseUrl={base}
            day={overrides.day ?? fixtureDay}
            onDayChange={onDayChange}
            onOpenSearch={onOpenSearch}
            seek={null}
            onSeekDone={onSeekDone}
        />,
    );
    return { onDayChange, onOpenSearch, onSeekDone };
}

describe("DaySurface #1 request", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        resetFixtures();
    });

    it("marks a frame as extracting… until its text extraction completes (#1)", async () => {
        renderDay();
        await screen.findByText("⟳ synthesize");
        // Walk from the default (frame 10) back two frames to frame 8, the
        // fixture frame that is still queued for text extraction.
        fireEvent.keyDown(window, { key: "ArrowLeft" });
        fireEvent.keyDown(window, { key: "ArrowLeft" });
        expect(await screen.findByText("extracting…")).toBeInTheDocument();
        expect(
            screen.getByText(/extraction queued — text will appear/),
        ).toBeInTheDocument();
        // Pending is a live per-frame state: no OCR text to copy yet.
        expect(screen.getByText("Extracting text…")).toBeInTheDocument();
    });

    it("shows the selected frame's exact time above the playhead and follows selection", async () => {
        renderDay();
        await screen.findByText("⟳ synthesize");
        // Default selection: last frame (12:30:00).
        expect(screen.getByTestId("playhead-time")).toHaveTextContent("12:30:00");
        fireEvent.keyDown(window, { key: "ArrowLeft" });
        await waitFor(() =>
            expect(screen.getByTestId("playhead-time")).toHaveTextContent("12:00:00"),
        );
    });

    it("shows the frame's tab source URL in the sidebar and caption overlay (#1)", async () => {
        renderDay();
        await screen.findByText("⟳ synthesize");
        fireEvent.keyDown(window, { key: "ArrowLeft" });
        fireEvent.keyDown(window, { key: "ArrowLeft" });
        fireEvent.keyDown(window, { key: "ArrowLeft" });
        fireEvent.keyDown(window, { key: "ArrowLeft" });
        fireEvent.keyDown(window, { key: "ArrowLeft" }); // frame 5, YouTube tab
        const url = "https://www.youtube.com/watch?v=omurice-630";
        const link = await screen.findByTestId("frame-source-url");
        expect(link).toHaveTextContent(url);
        expect(link).toHaveAttribute("href", url);
        // same URL on the bottom caption overlay
        expect(screen.getAllByText(url).length).toBe(2);
    });

    it("deletes the selected frame after confirm and reselects the newest remaining (#1)", async () => {
        renderDay();
        await screen.findAllByText(/watch-lane\.tsx/); // frame 10 selected by default
        const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
        fireEvent.click(screen.getByTestId("delete-frame"));
        await waitFor(() =>
            expect(screen.queryByText(/watch-lane\.tsx/)).not.toBeInTheDocument(),
        );
        expect(confirm).toHaveBeenCalledTimes(1);
        // Selection fell back to the new last frame (12:00 git push terminal).
        await screen.findAllByText(/git push/);
    });

    it("keeps the frame when delete is cancelled (#1)", async () => {
        renderDay();
        await screen.findAllByText(/watch-lane\.tsx/);
        vi.spyOn(window, "confirm").mockReturnValue(false);
        fireEvent.click(screen.getByTestId("delete-frame"));
        await screen.findAllByText(/watch-lane\.tsx/);
        expect(screen.queryByTestId("frame-source-url")).not.toBeInTheDocument();
    });

    it("deletes a session from its detail popup (#1)", async () => {
        renderDay();
        await screen.findAllByText(/watch-lane\.tsx/);
        fireEvent.click(screen.getByRole("button", { name: /Some dev video/ }));
        await screen.findByRole("dialog", { name: /session details/i });
        vi.spyOn(window, "confirm").mockReturnValue(true);
        fireEvent.click(screen.getByTestId("delete-session"));
        await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
        // Refetched list no longer has the deleted session's lane.
        await waitFor(() =>
            expect(screen.queryByRole("button", { name: /Some dev video/ })).not.toBeInTheDocument(),
        );
    });

    it("manually fetches a missing transcript from the detail dialog (#1)", async () => {
        renderDay();
        await screen.findAllByText(/watch-lane\.tsx/);
        fireEvent.click(screen.getByRole("button", { name: /Some dev video/ }));
        const dialog = await screen.findByRole("dialog", { name: /session details/i });
        expect(dialog).toHaveTextContent("No transcript captured.");
        fireEvent.click(screen.getByTestId("fetch-transcript"));
        expect(await screen.findByText("Freshly fetched captions for testing.")).toBeInTheDocument();
        expect(screen.queryByTestId("fetch-transcript")).not.toBeInTheDocument();
    });
});

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

    it("shows a suggestion dropdown of matching frames and sessions while typing", async () => {
        renderDay();
        const input = await screen.findByPlaceholderText(/Search the day/);
        fireEvent.focus(input);
        fireEvent.change(input, { target: { value: "omurice" } });
        const listbox = await screen.findByTestId("day-suggest");
        expect(listbox).toHaveTextContent("Omurice — Uncle Roger");
        expect(listbox).toHaveTextContent("sidra");
        fireEvent.change(input, { target: { value: "watch" } });
        expect(await screen.findByTestId("day-suggest")).toHaveTextContent(/watch-lane\.tsx/); // frames
    });

    it("clicking a suggestion jumps the timeline and clears the query", async () => {
        const { onOpenSearch } = renderDay();
        const input = await screen.findByPlaceholderText(/Search the day/);
        fireEvent.focus(input);
        fireEvent.change(input, { target: { value: "omurice" } });
        fireEvent.click(await screen.findByRole("option", { name: /Omurice — Uncle Roger/ }));
        expect(screen.queryByTestId("day-suggest")).not.toBeInTheDocument();
        expect(input).toHaveValue("");
        expect(onOpenSearch).not.toHaveBeenCalled();
    });

    it("Enter with an arrow/tab-selected suggestion jumps the timeline, not the search tab", async () => {
        const { onOpenSearch } = renderDay();
        const input = await screen.findByPlaceholderText(/Search the day/);
        fireEvent.focus(input);
        fireEvent.change(input, { target: { value: "omurice" } });
        await screen.findByTestId("day-suggest");
        fireEvent.keyDown(input, { key: "ArrowDown" });
        fireEvent.keyDown(input, { key: "Enter" });
        expect(onOpenSearch).not.toHaveBeenCalled();
        expect(screen.queryByTestId("day-suggest")).not.toBeInTheDocument();
        expect(input).toHaveValue("");
    });

    it("plain Enter hands the query to the global search tab", async () => {
        const { onOpenSearch } = renderDay();
        const input = await screen.findByPlaceholderText(/Search the day/);
        fireEvent.focus(input);
        fireEvent.change(input, { target: { value: "omurice" } });
        await screen.findByTestId("day-suggest");
        fireEvent.keyDown(input, { key: "Enter" });
        expect(onOpenSearch).toHaveBeenCalledWith("omurice");
        expect(screen.queryByTestId("day-suggest")).not.toBeInTheDocument();
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

    it("opens a media popup with session details when clicking a block", async () => {
        renderDay();
        await screen.findAllByText(/watch-lane\.tsx/);
        fireEvent.click(screen.getByRole("button", { name: /Omurice/ }));
        const dialog = await screen.findByRole("dialog", { name: /session details/i });
        expect(dialog).toHaveTextContent("Omurice — Uncle Roger");
        expect(dialog).toHaveTextContent("sidra");
        expect(dialog).toHaveTextContent("whisper");
        expect(dialog).toHaveTextContent("the most difficult omelet"); // cue
        expect(dialog).toHaveTextContent("Fuiyoh"); // transcript
        expect(dialog).toHaveTextContent("Jump to moment");
    });

    it("jumps to the media's moment and closes the popup", async () => {
        renderDay();
        await screen.findAllByText(/watch-lane\.tsx/);
        fireEvent.click(screen.getByRole("button", { name: /Some dev video/ }));
        await screen.findByRole("dialog", { name: /session details/i });
        fireEvent.click(screen.getByText("Jump to moment"));
        await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    });

    it("toggles the follow-live button", async () => {
        renderDay();
        await screen.findAllByText(/watch-lane\.tsx/);
        const btn = screen.getByTestId("follow-live");
        expect(btn).toHaveAttribute("aria-pressed", "false");
        fireEvent.click(btn);
        expect(btn).toHaveAttribute("aria-pressed", "true");
        fireEvent.click(btn);
        expect(btn).toHaveAttribute("aria-pressed", "false");
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

    it("opens the three-zone filter dropdown on focus and closes on blur (#64)", async () => {
        renderDay();
        const input = await screen.findByPlaceholderText(/Search the day/);
        fireEvent.focus(input);
        // widget zone + chips zone + suggestions zone all present
        const dd = await screen.findByTestId("day-suggest");
        expect(dd).toHaveTextContent("type to search the day"); // suggestions zone hint
        expect(screen.getByRole("group", { name: "day kind filter" })).toBeInTheDocument();
        expect(screen.getByLabelText("day source filter")).toBeInTheDocument();
        expect(screen.getByLabelText("after time")).toBeInTheDocument();
        expect(screen.getByLabelText("before time")).toBeInTheDocument();
        fireEvent.blur(input);
        expect(screen.queryByTestId("day-suggest")).not.toBeInTheDocument();
    });

    it("day-scoped widgets write tokens and give time-of-day, not a date range (#64)", async () => {
        renderDay();
        const input = await screen.findByPlaceholderText(/Search the day/);
        fireEvent.focus(input);
        fireEvent.click(screen.getByRole("button", { name: "sessions" }));
        expect(input).toHaveValue("kind:session");
        fireEvent.change(screen.getByLabelText("after time"), { target: { value: "09:30" } });
        expect(input).toHaveValue("kind:session after:09:30");
        fireEvent.change(screen.getByLabelText("day source filter"), { target: { value: "transcript" } });
        expect(input).toHaveValue("kind:session after:09:30 source:transcript");
        expect(screen.getByRole("button", { name: "remove sessions filter" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "remove after 09:30 filter" })).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "remove after 09:30 filter" }));
        expect(input).toHaveValue("kind:session source:transcript");
    });

    it("sidebar app chips and dropdown widget share one state (#64)", async () => {
        renderDay();
        await screen.findByText("⟳ synthesize");
        const input = await screen.findByPlaceholderText(/Search the day/);
        fireEvent.focus(input);
        // entrance 1: sidebar chip
        fireEvent.click(screen.getByTestId("app-filter-browser"));
        expect(screen.getByRole("button", { name: "remove browser filter" })).toBeInTheDocument();
        // entrance 2: dropdown pill reflects the same selection
        const pill = screen.getByRole("button", { name: /^browser/, pressed: true });
        expect(pill).toBeInTheDocument();
        // and toggling the dropdown pill clears the sidebar selection again
        fireEvent.click(pill);
        expect(screen.queryByRole("button", { name: "remove browser filter" })).not.toBeInTheDocument();
    });

    it("app/time filters dim non-matching frames on the timeline (#64)", async () => {
        renderDay();
        const input = await screen.findByPlaceholderText(/Search the day/);
        fireEvent.focus(input);
        fireEvent.change(input, { target: { value: "after:11:00" } });
        // After 11:00: frames 8,9,10 remain lit; earlier frames dim (opacity-25).
        const timeline = screen.getByTestId("filmstrip-timeline");
        await waitFor(() => expect(timeline.querySelectorAll(".opacity-25").length).toBeGreaterThan(0));
        fireEvent.change(input, { target: { value: "" } });
        await waitFor(() => expect(timeline.querySelectorAll(".opacity-25").length).toBe(0));
    });

    it("compiles the query language in the day box and hands off with an absolute range (#64)", async () => {
        const { onOpenSearch } = renderDay();
        const input = await screen.findByPlaceholderText(/Search the day/);
        fireEvent.focus(input);
        fireEvent.change(input, { target: { value: "omurice app:browser after:09:00" } });
        fireEvent.keyDown(input, { key: "Enter" });
        expect(onOpenSearch).toHaveBeenCalledWith(`omurice app:browser on:${fixtureDay} after:09:00`);
        expect(screen.queryByTestId("day-suggest")).not.toBeInTheDocument();
    });

    it("day-scoped kinds prune suggestions (sessions only shows sessions) (#64)", async () => {
        renderDay();
        const input = await screen.findByPlaceholderText(/Search the day/);
        fireEvent.focus(input);
        fireEvent.change(input, { target: { value: "kind:session omurice" } });
        const listbox = await screen.findByRole("listbox", { name: "day search suggestions" });
        expect(listbox).toHaveTextContent("Omurice — Uncle Roger");
        expect(listbox).not.toHaveTextContent("watch-lane");
    });
});
