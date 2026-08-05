import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test/render";
import { base } from "@/test/msw/handlers";
import { DayBrowser } from "./day-browser";

describe("DayBrowser", () => {
    it("shows frames, sessions, recap and watched summary for the day", async () => {
        renderWithQuery(<DayBrowser baseUrl={base} />);

        expect(await screen.findByText(/10 frames/)).toBeInTheDocument();
        expect(screen.getByText(/2 sessions/)).toBeInTheDocument();
        const lane = within(screen.getByTestId("watch-lane"));
        expect(lane.getByText("Omurice — Uncle Roger")).toBeInTheDocument();
        expect(lane.getByText("Some dev video")).toBeInTheDocument();
        expect(screen.getByText("Recaps")).toBeInTheDocument();
        expect(screen.getByText("Day recap")).toBeInTheDocument();
        expect(screen.getByText("Time breakdown")).toBeInTheDocument();
        expect(
            screen.getByRole("heading", { level: 3, name: /Watched today/i }),
        ).toBeInTheDocument();
        const watched = await screen.findAllByText(/\d+m watched/);
        expect(watched.length).toBeGreaterThan(0);
    });

    it("selects the last frame by default and steps with arrow keys", async () => {
        renderWithQuery(<DayBrowser baseUrl={base} />);

        expect(await screen.findByText(/code\.editor · watch-lane\.tsx/)).toBeInTheDocument();

        await userEvent.keyboard("{ArrowLeft}");

        expect(await screen.findByText(/terminal · ~\/\.local\/bin/)).toBeInTheDocument();
    });

    it("shows an empty state when no frames exist that day", async () => {
        renderWithQuery(<DayBrowser baseUrl={base} />);

        await screen.findByText(/10 frames/);
        await userEvent.click(screen.getByLabelText("previous day"));

        expect(await screen.findByText(/No captures for \d{4}-\d{2}-\d{2}/)).toBeInTheDocument();
    });

    it("runs a recap pipe and renders markdown output", async () => {
        const user = userEvent.setup();
        renderWithQuery(<DayBrowser baseUrl={base} />);

        await screen.findByText(/10 frames/);
        await user.click(screen.getByRole("button", { name: "Day recap" }));

        expect(await screen.findByText("A good day.")).toBeInTheDocument();
        expect(screen.getByText("Recap")).toBeInTheDocument();
        expect(screen.getByText("two")).toBeInTheDocument();
        expect(screen.getByText("code")).toBeInTheDocument();
        expect(screen.getByText(/10 frames · 2\.3s/)).toBeInTheDocument();
    });

    it("searches and highlights matching frames", async () => {
        const user = userEvent.setup();
        renderWithQuery(<DayBrowser baseUrl={base} />);

        await screen.findByText(/10 frames/);
        await user.keyboard("/");

        const input = await screen.findByPlaceholderText(/Search frames/);
        await user.type(input, "documentation");

        await screen.findByRole("dialog", { name: "search" });
        const item = await within(screen.getByRole("dialog", { name: "search" })).findByText(/Heimdall docs/);
        await user.click(item);

        expect(await screen.findByText("search hit")).toBeInTheDocument();
    });

    it("opens a watch session for details", async () => {
        const user = userEvent.setup();
        renderWithQuery(<DayBrowser baseUrl={base} />);

        await screen.findByText(/2 sessions/);
        await user.click(within(screen.getByTestId("watch-lane")).getByText("Omurice — Uncle Roger"));

        expect(await screen.findByText("Moments")).toBeInTheDocument();
        expect(screen.getByText("fuiyoh")).toBeInTheDocument();
        expect(screen.getAllByText(/most difficult omelet/).length).toBeGreaterThan(0);
        expect(screen.getByText(/actually watched/)).toBeInTheDocument();
    });
});

describe("DayBrowser keyboard", () => {
    it("opens and closes search with / and Escape", async () => {
        const user = userEvent.setup();
        renderWithQuery(<DayBrowser baseUrl={base} />);

        await screen.findByText(/10 frames/);
        await user.keyboard("/");
        expect(await screen.findByPlaceholderText(/Search frames/)).toBeInTheDocument();
        await user.keyboard("{Escape}");
        expect(screen.queryByPlaceholderText(/Search frames/)).not.toBeInTheDocument();
    });
});