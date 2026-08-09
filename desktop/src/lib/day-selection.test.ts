import { beforeEach, describe, expect, it } from "vitest";
import { rememberFrame, resetDaySelection, savedFrame } from "./day-selection";

beforeEach(() => resetDaySelection());

describe("day-selection", () => {
    it("remembers the last frame per day, keyed by day", () => {
        expect(savedFrame("2026-08-05")).toBeNull();
        rememberFrame("2026-08-05", 7);
        rememberFrame("2026-08-06", 3);
        expect(savedFrame("2026-08-05")).toBe(7);
        expect(savedFrame("2026-08-06")).toBe(3);
        rememberFrame("2026-08-05", 9);
        expect(savedFrame("2026-08-05")).toBe(9);
    });

    it("resets to no memory (test seam)", () => {
        rememberFrame("2026-08-05", 7);
        resetDaySelection();
        expect(savedFrame("2026-08-05")).toBeNull();
    });
});