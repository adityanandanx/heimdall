import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import App from "./App";
import { base } from "@/test/msw/handlers";
import { renderWithQuery } from "@/test/render";

beforeEach(() => {
    window.localStorage.clear();
});

describe("App", () => {
    it("boots to the Day surface with the default server url", async () => {
        renderWithQuery(<App />);
        expect(await screen.findByText("DAY")).toBeInTheDocument();
        expect(await screen.findAllByText(/watch-lane\.tsx/)).not.toHaveLength(0);
        expect(screen.queryByTestId("offline-banner")).not.toBeInTheDocument();
    });

    it("navigates surfaces through the sidebar", async () => {
        renderWithQuery(<App />);
        await screen.findAllByText(/watch-lane\.tsx/);
        fireEvent.click(screen.getByRole("button", { name: "Status" }));
        expect(await screen.findByText("online")).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "Sessions" }));
        expect(await screen.findByText("Omurice — Uncle Roger")).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "Settings" }));
        expect(screen.getByLabelText("server url")).toHaveValue(base);
    });

    it("jumps from search to the day surface", async () => {
        renderWithQuery(<App />);
        await screen.findAllByText(/watch-lane\.tsx/);
        fireEvent.click(screen.getByRole("button", { name: "Search" }));
        const input = await screen.findByLabelText("search query");
        fireEvent.keyDown(window, { key: "k", metaKey: true });
        await screen.findAllByTestId("offline-banner").catch(() => null);
        fireEvent.change(input, { target: { value: "roger" } });
        const card = await screen.findByText("watch session");
        fireEvent.click(card);
        expect(await screen.findByText("DAY")).toBeInTheDocument();
        expect((await screen.findAllByText(/10:00:00/)).length).toBeGreaterThan(0); // session start
    });

    it("hands the day search query to the search surface on plain Enter", async () => {
        renderWithQuery(<App />);
        const input = await screen.findByPlaceholderText(/Search the day/);
        fireEvent.focus(input);
        fireEvent.change(input, { target: { value: "omurice" } });
        await screen.findByTestId("day-suggest");
        fireEvent.keyDown(input, { key: "Enter" });

        expect(await screen.findByPlaceholderText(/e\.g\./)).toBeInTheDocument(); // search surface
        expect(screen.getByLabelText("search query")).toHaveValue("omurice");
        expect(await screen.findByText(/uncle roger review the most difficult/)).toBeInTheDocument();
    });
});
