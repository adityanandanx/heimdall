import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test/render";
import { ServerSettings } from "./server-settings";

describe("ServerSettings", () => {
    it("prefills the input with the current URL", () => {
        renderWithQuery(<ServerSettings value="http://127.0.0.1:3931" onSaved={() => {}} />);

        expect(screen.getByLabelText("Server URL")).toHaveValue("http://127.0.0.1:3931");
    });

    it("saves a new URL and notifies the parent", async () => {
        const user = userEvent.setup();
        const onSaved = vi.fn();
        renderWithQuery(<ServerSettings value="http://127.0.0.1:3931" onSaved={onSaved} />);

        const input = screen.getByLabelText("Server URL");
        await user.clear(input);
        await user.type(input, "http://192.168.1.10:3931/");
        await user.click(screen.getByRole("button", { name: "Save" }));

        expect(onSaved).toHaveBeenCalledWith("http://192.168.1.10:3931");
    });

    it("rejects a non-URL value", async () => {
        const user = userEvent.setup();
        const onSaved = vi.fn();
        renderWithQuery(<ServerSettings value="http://127.0.0.1:3931" onSaved={onSaved} />);

        const input = screen.getByLabelText("Server URL");
        await user.clear(input);
        await user.type(input, "not a url");
        await user.click(screen.getByRole("button", { name: "Save" }));

        expect(onSaved).not.toHaveBeenCalled();
        expect(screen.getByText(/Enter a URL like/)).toBeInTheDocument();
    });
});