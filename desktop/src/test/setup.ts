import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";
import { resetSettingsStore } from "./msw/handlers";
import { server } from "./msw/server";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
    cleanup();
    resetSettingsStore();
    server.resetHandlers();
});
afterAll(() => server.close());