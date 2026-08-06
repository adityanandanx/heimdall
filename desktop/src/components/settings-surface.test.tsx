import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SettingsSurface, RULES_CATEGORIES } from "./settings-surface";
import { base, settingsStore } from "@/test/msw/handlers";
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

describe("SettingsSurface · capture", () => {
    it("renders the engine segmented control with the configured value", async () => {
        renderWithQuery(<SettingsSurface {...props} />);
        expect(await screen.findByText("OCR engine")).toBeInTheDocument();
        const auto = screen.getByRole("button", { name: /Auto.*fastest that works/i });
        expect(auto.className).toContain("border-primary/50");
    });

    it("writes a new engine through POST /settings", async () => {
        renderWithQuery(<SettingsSurface {...props} />);
        const npu = await screen.findByRole("button", { name: /NPU.*lowest power/i });
        fireEvent.click(npu);
        await waitFor(() => expect(settingsStore["capture.ocr_engine"]).toBe("npu"));
        expect(await screen.findByText("saved")).toBeInTheDocument();
    });

    it("shows the amber NPU→CPU fallback hint", async () => {
        settingsStore["capture.ocr_engine"] = "npu";
        renderWithQuery(<SettingsSurface {...props} />);
        expect(
            await screen.findByText(/NPU requested, but it isn't available/i),
        ).toBeInTheDocument();
    });

    it("pauses capture through the toggle", async () => {
        renderWithQuery(<SettingsSurface {...props} />);
        const toggle = await screen.findByRole("switch", { name: "pause capture" });
        fireEvent.click(toggle);
        await waitFor(() => expect(settingsStore["capture.paused"]).toBe(true));
        expect(await screen.findByText("Capture paused")).toBeInTheDocument();
    });
});

describe("SettingsSurface · exclusions", () => {
    it("renders the excluded player chips from config", async () => {
        renderWithQuery(<SettingsSurface {...props} />);
        expect(await screen.findByText("spotify")).toBeInTheDocument();
    });

    it("adds a free-typed player to the exclusion list", async () => {
        renderWithQuery(<SettingsSurface {...props} />);
        const input = await screen.findByLabelText("add player");
        fireEvent.change(input, { target: { value: "vlc" } });
        fireEvent.keyDown(input, { key: "Enter" });
        await waitFor(() =>
            expect(settingsStore["watch.excluded_players"]).toEqual(["spotify", "vlc"]),
        );
    });

    it("removes a chip from the exclusion list", async () => {
        renderWithQuery(<SettingsSurface {...props} />);
        fireEvent.click(await screen.findByLabelText("remove spotify"));
        await waitFor(() =>
            expect(settingsStore["watch.excluded_players"]).toEqual([]),
        );
    });

    it("suggests DB-captured window classes as exclusion chips", async () => {
        renderWithQuery(<SettingsSurface {...props} />);
        // facets apps include browser + terminal from the search fixtures
        const suggestion = await screen.findByRole("button", { name: "+ browser" });
        expect(suggestion).toBeInTheDocument();
    });
});

describe("SettingsSurface · rules", () => {
    it("renders rule rows for captured apps with category selects", async () => {
        renderWithQuery(<SettingsSurface {...props} />);
        expect(await screen.findByLabelText("category for browser")).toBeInTheDocument();
        // default rules from the store: sidra → Music
        expect(screen.getByLabelText("category for sidra")).toHaveValue("Music");
    });

    it("assigns a category by whole-dict write-through", async () => {
        renderWithQuery(<SettingsSurface {...props} />);
        const select = await screen.findByLabelText("category for sidra");
        fireEvent.change(select, { target: { value: "Other" } });
        await waitFor(() =>
            expect(settingsStore["rules.window_class_category"]).toEqual(
                expect.objectContaining({ sidra: "Other" }),
            ),
        );
    });

    it("shows the 8 category options", async () => {
        renderWithQuery(<SettingsSurface {...props} />);
        const select = await screen.findByLabelText("category for sidra");
        const options = Array.from(select.querySelectorAll("option")).map((o) => o.value);
        for (const c of RULES_CATEGORIES) expect(options).toContain(c);
    });

    it("adds a free-typed window class", async () => {
        renderWithQuery(<SettingsSurface {...props} />);
        const input = await screen.findByPlaceholderText("add window class…");
        fireEvent.change(input, { target: { value: "blender" } });
        fireEvent.keyDown(input, { key: "Enter" });
        await waitFor(() =>
            expect(settingsStore["rules.window_class_category"]).toEqual(
                expect.objectContaining({ blender: "Other" }),
            ),
        );
    });
});

describe("SettingsSurface · scheduled pipes", () => {
    it("renders both pipes with their schedules", async () => {
        renderWithQuery(<SettingsSurface {...props} />);
        expect(await screen.findByText("Day recap")).toBeInTheDocument();
        expect(screen.getByText("Time breakdown")).toBeInTheDocument();
        expect(screen.getByText("off")).toBeInTheDocument(); // day_recap: null
        expect(screen.getByLabelText("Time breakdown cron")).toHaveValue("30 23 * * *");
    });

    it("shows the next-run readout from status", async () => {
        renderWithQuery(<SettingsSurface {...props} />);
        expect(await screen.findByText(/next .*2026/)).toBeInTheDocument();
    });

    it("enables a disabled pipe and writes the cron", async () => {
        renderWithQuery(<SettingsSurface {...props} />);
        const switches = await screen.findAllByRole("switch", { checked: false });
        fireEvent.click(switches[0]);
        await waitFor(() =>
            expect(settingsStore["scheduler.day_recap"]).toBe("0 22 * * *"),
        );
    });

    it("disables a pipe by writing null", async () => {
        renderWithQuery(<SettingsSurface {...props} />);
        const switches = await screen.findAllByRole("switch", { checked: true });
        // pause toggle + time-breakdown are checked; disable the pipe's own
        const timeBreakdown = switches.find((el) =>
            el.closest(".rounded-md.border.border-line\\/70")?.textContent?.includes("Time breakdown"),
        ) ?? switches[1];
        fireEvent.click(timeBreakdown);
        await waitFor(() => expect(settingsStore["scheduler.time_breakdown"]).toBeNull());
    });
});

describe("SettingsSurface · passive", () => {
    it("renders the extraction mode segmented control", async () => {
        renderWithQuery(<SettingsSurface {...props} />);
        expect(await screen.findByText("Extraction mode")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /A11y.*accessibility tree/i })).toBeInTheDocument();
    });

    it("flips the telemetry toggle through the store", async () => {
        renderWithQuery(<SettingsSurface {...props} />);
        const telemetry = await screen.findByRole("switch", { name: "telemetry" });
        expect(telemetry).toHaveAttribute("aria-checked", "false");
        fireEvent.click(telemetry);
        await waitFor(() => expect(settingsStore["observability.enabled"]).toBe(true));
    });

    it("renders the media resolver segmented control", async () => {
        renderWithQuery(<SettingsSurface {...props} />);
        expect(await screen.findByText("Media resolver")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /Extension.*reports the URL/i })).toBeInTheDocument();
    });
});

describe("SettingsSurface · forget", () => {
    it("requires the typed gate before arming", async () => {
        renderWithQuery(<SettingsSurface {...props} />);
        fireEvent.click(await screen.findByRole("button", { name: /forget data…/i }));
        const button = screen.getByRole("button", { name: "Forget" });
        expect(button).toBeDisabled();
        const input = screen.getByLabelText("type forget to confirm");
        fireEvent.change(input, { target: { value: "forge" } });
        expect(button).toBeDisabled();
        fireEvent.change(input, { target: { value: "forget" } });
        expect(button).toBeEnabled();
    });

    it("posts the categories + window to /forget", async () => {
        renderWithQuery(<SettingsSurface {...props} />);
        fireEvent.click(await screen.findByRole("button", { name: /forget data…/i }));
        const input = screen.getByLabelText("type forget to confirm");
        fireEvent.change(input, { target: { value: "forget" } });
        fireEvent.click(screen.getByRole("button", { name: "Forget" }));
        await waitFor(() =>
            expect(screen.findByText(/done — deleted rows and files/i)).toBeTruthy(),
        );
    });

    it("never fires without at least one category", async () => {
        renderWithQuery(<SettingsSurface {...props} />);
        fireEvent.click(await screen.findByRole("button", { name: /forget data…/i }));
        // frames + sessions are pre-checked; uncheck both
        fireEvent.click(screen.getAllByRole("checkbox")[0]);
        fireEvent.click(screen.getAllByRole("checkbox")[1]);
        const input = screen.getByLabelText("type forget to confirm");
        fireEvent.change(input, { target: { value: "forget" } });
        expect(screen.getByRole("button", { name: "Forget" })).toBeDisabled();
    });
});