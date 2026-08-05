import { describe, expect, it } from "vitest";
import {
    applyQueryTokens,
    insertToken,
    parseQuery,
    removeOpTokens,
    removeToken,
} from "@/lib/query-language";
import { DEFAULT_FILTERS, type SearchFilters } from "@/lib/search-filters";

const NOW = new Date(2026, 5, 5, 12, 0, 0); // 2026-06-05 12:00 local

const F = (partial: Partial<SearchFilters> = {}): SearchFilters => ({
    ...DEFAULT_FILTERS,
    ...partial,
});

describe("parseQuery", () => {
    it("recognizes every operator", () => {
        const input =
            "app:sidra player:vlc kind:frame on:2026-06-05 after:09:30 before:18:00 source:ocr has:transcript fullscreen:yes ws:3 monitor:1";
        const { tokens } = parseQuery(input);
        expect(tokens.map((t) => `${t.op}:${t.value}`)).toEqual([
            "app:sidra",
            "player:vlc",
            "kind:frame",
            "on:2026-06-05",
            "after:09:30",
            "before:18:00",
            "source:ocr",
            "has:transcript",
            "fullscreen:yes",
            "ws:3",
            "monitor:1",
        ]);
        expect(tokens.every((t) => !t.negated)).toBe(true);
    });

it("is case-insensitive for operators and enum values", () => {
        const { tokens } = parseQuery("APP:Sidra KIND:FRAME SOURCE:A11y Fullscreen:Yes HAS:TranscriPT");
        expect(tokens.map((t) => `${t.op}:${t.value}`)).toEqual([
            "app:Sidra", // non-enum values keep their case (window_class match)
            "kind:frame",
            "source:a11y",
            "fullscreen:yes",
            "has:transcript",
        ]);
    });

    it("handles double-quoted values with spaces", () => {
        const { tokens, text } = parseQuery('app:"google chrome" roger');
        expect(tokens).toHaveLength(1);
        expect(tokens[0]).toMatchObject({ op: "app", value: "google chrome" });
        expect(tokens[0].raw).toBe('app:"google chrome"');
        expect(text).toBe("roger");
    });

    it("marks negation with the - prefix", () => {
        const { tokens } = parseQuery("-kind:frame -fullscreen:yes");
        expect(tokens[0]).toMatchObject({ op: "kind", value: "frame", negated: true });
        expect(tokens[1]).toMatchObject({ op: "fullscreen", value: "yes", negated: true });
    });

    it("treats malformed and unknown tokens as literal text", () => {
        const { tokens, text } = parseQuery(
            "app: source:on:banana after:25:99 title:foo app:\"unclosed has:anything ws:x on: 2026-06-05",
        );
        expect(tokens).toEqual([]);
        expect(text).toBe(
            'app: source:on:banana after:25:99 title:foo app:"unclosed has:anything ws:x on: 2026-06-05',
        );
    });

    it("treats empty and quoted-empty values as literal text", () => {
        expect(parseQuery("app:").tokens).toEqual([]);
        expect(parseQuery('app:""').tokens).toEqual([]);
    });

    it("keeps bare quoted phrases as FTS text", () => {
        const { tokens, text } = parseQuery('"borrow checker" app:sidra');
        expect(tokens).toHaveLength(1);
        expect(text).toBe('"borrow checker"');
    });

    it("reports exact token spans for the glow overlay", () => {
        const input = "  roger app:sidra player:vlc  ";
        const { tokens } = parseQuery(input);
        expect(tokens.map((t) => input.slice(t.start, t.end))).toEqual(["app:sidra", "player:vlc"]);
        expect(tokens[0].start).toBe(8);
        expect(tokens[0].end).toBe(17);
        expect(tokens[1].start).toBe(18);
        expect(tokens[1].end).toBe(28);
    });

    it("leaves empty input empty", () => {
        expect(parseQuery("  ")).toEqual({ tokens: [], text: "" });
    });
});

describe("applyQueryTokens", () => {
    it("projects app/player tokens and clears them when absent", () => {
        const out = applyQueryTokens(F({ apps: ["stale"] }), parseQuery("roger app:sidra"), NOW);
        expect(out.filters.apps).toEqual(["sidra"]);
        expect(out.text).toBe("roger");
        const cleared = applyQueryTokens(out.filters, parseQuery("roger"), NOW);
        expect(cleared.filters.apps).toEqual([]);
    });

    it("compiles kind with negation as the complement", () => {
        expect(applyQueryTokens(F(), parseQuery("kind:session"), NOW).filters.kind).toBe("session");
        expect(applyQueryTokens(F(), parseQuery("-kind:frame"), NOW).filters.kind).toBe("session");
        expect(applyQueryTokens(F(), parseQuery("-kind:session"), NOW).filters.kind).toBe("frame");
    });

    it("compiles source and has:transcript", () => {
        expect(applyQueryTokens(F(), parseQuery("source:ocr"), NOW).filters.source).toBe("ocr");
        expect(applyQueryTokens(F(), parseQuery("has:transcript"), NOW).filters.source).toBe("transcript");
        expect(applyQueryTokens(F(), parseQuery("roger"), NOW).filters.source).toBe("any");
    });

    it("compiles workspace/monitor/fullscreen and resets without tokens", () => {
        const out = applyQueryTokens(F(), parseQuery("ws:3 monitor:1 fullscreen:yes"), NOW);
        expect(out.filters).toMatchObject({ workspace: "3", monitor: "1", fullscreen: "yes" });
        expect(applyQueryTokens(F(), parseQuery("-fullscreen:yes"), NOW).filters.fullscreen).toBe("no");
        expect(applyQueryTokens(F(), parseQuery("roger"), NOW).filters.fullscreen).toBe("any");
    });

    it("on: sets a full-day custom range", () => {
        const out = applyQueryTokens(F(), parseQuery("on:2026-06-05"), NOW);
        expect(out.filters).toMatchObject({
            preset: "all",
            start: "2026-06-05T00:00",
            end: "2026-06-06T00:00",
        });
    });

    it("after:/before: dates set the range edges", () => {
        const out = applyQueryTokens(F(), parseQuery("after:2026-06-05 before:2026-06-07"), NOW);
        expect(out.filters).toMatchObject({ start: "2026-06-05T00:00", end: "2026-06-08T00:00" });
    });

    it("binds bare times to the on: token day", () => {
        const out = applyQueryTokens(F(), parseQuery("on:2026-06-05 after:09:30 before:18:00"), NOW);
        expect(out.filters).toMatchObject({ start: "2026-06-05T09:30", end: "2026-06-05T18:00" });
    });

    it("binds bare times to the widget range's start day", () => {
        const range = F({ start: "2026-06-03T10:00", end: "2026-06-04T10:00" });
        const out = applyQueryTokens(range, parseQuery("after:09:30"), NOW);
        expect(out.filters.start).toBe("2026-06-03T09:30");
    });

    it("leaves a bare time without day context in the text query", () => {
        const out = applyQueryTokens(F(), parseQuery("after:09:30 roger"), NOW);
        expect(out.filters.start).toBe("");
        expect(out.text).toBe("roger after:09:30");
    });

    it("drops recognized but inexpressible negations from the text", () => {
        const out = applyQueryTokens(F(), parseQuery("-app:sidra roger"), NOW);
        expect(out.filters.apps).toEqual([]);
        expect(out.text).toBe("roger");
    });
});

describe("token text edits", () => {
    it("insertToken appends unless the token already exists", () => {
        expect(insertToken("roger", "app", "sidra")).toBe("roger app:sidra");
        expect(insertToken("app:sidra", "app", "sidra")).toBe("app:sidra");
        expect(insertToken("APP:sidra", "app", "SIDRA")).toBe("APP:sidra");
    });

    it("removeToken strips one specific token", () => {
        expect(removeToken("app:sidra roger app:vlc", "app", "sidra")).toBe("roger app:vlc");
        expect(removeToken("roger", "app", "sidra")).toBe("roger");
    });

    it("removeOpTokens strips every token of an operator", () => {
        expect(removeOpTokens("kind:frame app:sidra kind:session", "kind")).toBe("app:sidra");
        expect(removeOpTokens("roger", "kind")).toBe("roger");
    });
});
