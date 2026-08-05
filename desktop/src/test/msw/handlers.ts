import { http, HttpResponse } from "msw";

export const healthPayload = {
    status: "ok",
    version: "0.1.0",
    db: "ok",
    uptime_s: 7630,
};

export const statusPayload = {
    server: { status: "ok", version: "0.1.0", uptime_s: 7630 },
    db: { frames_today: 412, size_bytes: 10891264 },
    capture: {
        alive: true,
        last_event_ts: "2026-08-05T03:09:49+05:30",
        extraction: "auto",
        ocr_also: [],
        players: [
            { name: "chromium.instance1208", status: "playing" },
            { name: "sidra", status: "stopped" },
        ],
    },
    media: {
        last_session: {
            session_id: 505,
            player: "chromium",
            media_title: "Uncle Roger Review THE MOST DIFFICULT OMELET (Omurice)",
            media_source: null,
            ts_start: 1785879570118,
            ts_end: 1785879590859,
            transcript_source: null,
        },
    },
    asr: { queued: 0, running: 0, failed: 0, items: [] },
    llama: { reachable: true },
    tracing: { enabled: false, reason: "LANGFUSE_* env vars unset" },
    pipes: { last_runs: { "day-recap": null, "time-breakdown": null } },
};

export const capturedStatus = (overrides: Record<string, unknown> = {}) => {
    const base = statusPayload as unknown as Record<string, unknown>;
    const merged: Record<string, unknown> = { ...base };
    for (const key of Object.keys(overrides)) {
        const baseVal = base[key];
        const override = overrides[key];
        merged[key] =
            baseVal !== null &&
            typeof baseVal === "object" &&
            !Array.isArray(baseVal) &&
            override !== null &&
            typeof override === "object"
                ? { ...(baseVal as object), ...(override as object) }
                : override;
    }
    return merged as typeof statusPayload;
};

export const base = "http://127.0.0.1:3931";

export const handlers = [
    http.get(`${base}/health`, () => HttpResponse.json(healthPayload)),
    http.get(`${base}/status`, () => HttpResponse.json(statusPayload)),
];