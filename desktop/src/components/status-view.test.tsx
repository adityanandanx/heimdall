import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { server } from "@/test/msw/server";
import { renderWithQuery } from "@/test/render";
import { base, capturedStatus } from "@/test/msw/handlers";
import { StatusView } from "./status-view";

describe("StatusView", () => {
    it("shows the server online with capture, db, players, llama and last session", async () => {
        renderWithQuery(<StatusView baseUrl={base} />);

        expect(await screen.findByText("online")).toBeInTheDocument();
        expect(screen.getByText("heimdall 0.1.0")).toBeInTheDocument();
        expect(screen.getByText("412")).toBeInTheDocument();
        expect(screen.getByText("10.4 MB")).toBeInTheDocument();
        expect(screen.getByText("running")).toBeInTheDocument();
        expect(screen.getByText("chromium.instance1208")).toBeInTheDocument();
        expect(screen.getByText("playing")).toBeInTheDocument();
        expect(screen.getByText("reachable")).toBeInTheDocument();
        expect(
            screen.getByText("Uncle Roger Review THE MOST DIFFICULT OMELET (Omurice)"),
        ).toBeInTheDocument();
    });

    it("tells you to run `heimdall serve` when the server is offline", async () => {
        server.use(
            http.get(`${base}/health`, () => HttpResponse.error()),
            http.get(`${base}/status`, () => HttpResponse.error()),
        );

        renderWithQuery(<StatusView baseUrl={base} />);

        expect(await screen.findByText("Server offline")).toBeInTheDocument();
        expect(screen.getByText("heimdall serve")).toBeInTheDocument();
        expect(screen.getByText(base)).toBeInTheDocument();
    });

    it("flags a stopped capture daemon", async () => {
        server.use(
            http.get(`${base}/status`, () =>
                HttpResponse.json(capturedStatus({ capture: { alive: false } })),
            ),
        );

        renderWithQuery(<StatusView baseUrl={base} />);

        expect(await screen.findByText("online")).toBeInTheDocument();
        expect(screen.getByText("not running")).toBeInTheDocument();
        expect(screen.getByText(/capture daemon isn't recording/)).toBeInTheDocument();
    });

    it("shows an unreachable llama", async () => {
        server.use(
            http.get(`${base}/status`, () =>
                HttpResponse.json(capturedStatus({ llama: { reachable: false } })),
            ),
        );

        renderWithQuery(<StatusView baseUrl={base} />);

        expect(await screen.findByText("online")).toBeInTheDocument();
        expect(screen.getByText("unreachable")).toBeInTheDocument();
    });

    it("shows the no-sessions state", async () => {
        server.use(
            http.get(`${base}/status`, () =>
                HttpResponse.json(capturedStatus({ media: { last_session: null } })),
            ),
        );

        renderWithQuery(<StatusView baseUrl={base} />);

        expect(await screen.findByText("online")).toBeInTheDocument();
        expect(screen.getByText("no watch sessions yet")).toBeInTheDocument();
    });

    it("shows the players-empty state", async () => {
        server.use(
            http.get(`${base}/status`, () =>
                HttpResponse.json(
                    capturedStatus({ capture: { alive: true, players: [] } }),
                ),
            ),
        );

        renderWithQuery(<StatusView baseUrl={base} />);

        expect(await screen.findByText("online")).toBeInTheDocument();
        expect(screen.getByText("no media players detected")).toBeInTheDocument();
    });
});