import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SettingsSurface } from "./settings-surface";
import { base } from "@/test/msw/handlers";
import { renderWithQuery } from "@/test/render";

const props = {
    serverUrl: base,
    onServerUrl: vi.fn(),
    refreshSeconds: 10,
    onRefreshSeconds: vi.fn(),
};

describe("SettingsSurface", () => {
    it("shows the saved server url and connection state", async () => {
        renderWithQuery(<SettingsSurface {...props} />);
        expect(screen.getByLabelText("server url")).toHaveValue(base);
        expect(await screen.findByText("connected")).toBeInTheDocument();
    });

    it("saves a new server url", () => {
        renderWithQuery(<SettingsSurface {...props} />);
        const input = screen.getByLabelText("server url");
        fireEvent.change(input, { target: { value: "http://10.0.0.5:3931/" } });
        fireEvent.keyDown(input, { key: "Enter" });
        expect(props.onServerUrl).toHaveBeenCalledWith("http://10.0.0.5:3931");
    });

    it("reports an unreachable server", async () => {
        renderWithQuery(
            <SettingsSurface
                {...props}
                serverUrl="http://127.0.0.1:1"
            />,
        );
        expect(await screen.findByText("not connected")).toBeInTheDocument();
    });

    it("tests the connection against the draft url", async () => {
        renderWithQuery(<SettingsSurface {...props} />);
        fireEvent.click(await screen.findByText("test connection"));
        expect(await screen.findByText("reachable")).toBeInTheDocument();
    });

    it("switches the auto-refresh interval", () => {
        renderWithQuery(<SettingsSurface {...props} />);
        fireEvent.click(screen.getByRole("button", { name: "15s" }));
        expect(props.onRefreshSeconds).toHaveBeenCalledWith(15);
        expect(screen.getByRole("button", { name: "10s" })).toBeInTheDocument();
    });
});
