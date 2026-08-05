import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusSurface } from "./status-surface";
import { base } from "@/test/msw/handlers";
import { renderWithQuery } from "@/test/render";

describe("StatusSurface", () => {
    it("reports the server as online with version and uptime", async () => {
        renderWithQuery(<StatusSurface baseUrl={base} />);
        expect(await screen.findByText("online")).toBeInTheDocument();
        expect(screen.getByText("0.1.0")).toBeInTheDocument();
        expect(screen.getByText("2h 7m")).toBeInTheDocument();
    });

    it("reports capture and llm health", async () => {
        renderWithQuery(<StatusSurface baseUrl={base} />);
        expect(await screen.findByText("running")).toBeInTheDocument();
        expect(screen.getByText("reachable")).toBeInTheDocument();
    });

    it("lists watched players with status chips", async () => {
        renderWithQuery(<StatusSurface baseUrl={base} />);
        expect(await screen.findByText("chromium.instance1208")).toBeInTheDocument();
        expect(screen.getByText("playing")).toBeInTheDocument();
        expect(screen.getByText("stopped")).toBeInTheDocument();
    });

    it("shows the last session", async () => {
        renderWithQuery(<StatusSurface baseUrl={base} />);
        expect(
            await screen.findByText("Uncle Roger Review THE MOST DIFFICULT OMELET (Omurice)"),
        ).toBeInTheDocument();
        expect(screen.getByText(/watched/)).toBeInTheDocument();
    });

    it("shows data size", async () => {
        renderWithQuery(<StatusSurface baseUrl={base} />);
        expect((await screen.findAllByText("10.4 MB")).length).toBeGreaterThan(0);
    });
});
