import type { SearchFilters } from "@/lib/search-filters";
import { localISO, shiftDay } from "@/lib/timeline";

// Query language inside the search box (#60). Typed operators like
// `app:sidra` / `on:2024-06-05` compile into the same SearchFilters state the
// widgets drive; everything unrecognized passes through as the FTS5 query.
// The parser is pure: it returns token spans (for the syntax-glow overlay) and
// the leftover text, and never touches state.

export type QueryOperator =
    | "app"
    | "player"
    | "kind"
    | "on"
    | "after"
    | "before"
    | "source"
    | "has"
    | "fullscreen"
    | "ws"
    | "monitor";

export interface QueryToken {
    op: QueryOperator;
    value: string;
    negated: boolean;
    /** Exact source slice — includes `-`, quotes, and trailing value. */
    raw: string;
    /** Offsets into the input string, for the glow overlay. */
    start: number;
    end: number;
    /** after:/before: with a bare HH:MM value. */
    isTime?: boolean;
}

export interface ParsedQuery {
    tokens: QueryToken[];
    /** The FTS5 text query — literal words/phrases, tokens stripped. */
    text: string;
}

const OPS: Record<string, QueryOperator> = {
    app: "app",
    player: "player",
    kind: "kind",
    on: "on",
    after: "after",
    before: "before",
    source: "source",
    has: "has",
    fullscreen: "fullscreen",
    ws: "ws",
    monitor: "monitor",
};

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const TIME_RE = /^(\d{2}):(\d{2})$/;

/** Is value a real calendar day, not just a shape match? */
function isDate(v: string): boolean {
    if (!DATE_RE.test(v)) return false;
    const d = new Date(`${v}T00:00:00`);
    return d.getFullYear() === Number(v.slice(0, 4));
}

function isTime(v: string): boolean {
    const m = TIME_RE.exec(v);
    return m !== null && Number(m[1]) < 24 && Number(m[2]) < 60;
}

/** Valid enum values per operator; anything else in a token degrades to text. */
const ENUM_VALUES: Partial<Record<QueryOperator, string[]>> = {
    kind: ["frame", "session"],
    source: ["a11y", "ocr", "transcript"],
    has: ["transcript"],
    fullscreen: ["yes", "no"],
};

/**
 * Split input into quote-aware tokens, then classify each. A token is either
 * an operator (marked by [start, end)) or literal text. Malformed operator
 * tokens (`app:`), unknown ops (`title:foo`) and bad values (`on:banana`)
 * stay literal — never an error.
 */
export function parseQuery(input: string): ParsedQuery {
    const tokens: QueryToken[] = [];
    const textParts: string[] = [];
    let i = 0;
    while (i < input.length) {
        while (i < input.length && /\s/.test(input[i])) i++;
        if (i >= input.length) break;
        const start = i;
        let inQuote = false;
        while (i < input.length) {
            const ch = input[i];
            if (ch === '"') inQuote = !inQuote;
            if (/\s/.test(ch) && !inQuote) break;
            i++;
        }
        const raw = input.slice(start, i);
        const word = classifyWord(raw);
        if (word) {
            tokens.push({ ...word, raw, start, end: i });
        } else {
            textParts.push(raw);
        }
    }
    return { tokens, text: textParts.join(" ") };
}

function classifyWord(raw: string): Omit<QueryToken, "raw" | "start" | "end"> | null {
    let body = raw;
    let negated = false;
    if (body.startsWith("-")) {
        if (body.length === 1) return null; // bare "-" is a literal hyphen
        negated = true;
        body = body.slice(1);
    }
    const colon = body.indexOf(":");
    if (colon <= 0) return null;
    const op = OPS[body.slice(0, colon).toLowerCase()];
    if (!op) return null;
    let value = body.slice(colon + 1);
    if (value.startsWith('"')) {
        // Quoted value must be exactly `"…"` — anything after the closing
        // quote (or an unclosed quote) makes the whole token literal.
        const last = value.lastIndexOf('"');
        if (last > 0 && last === value.length - 1) {
            value = value.slice(1, last);
        } else {
            return null;
        }
    }
    if (value === "") return null; // `app:` with no value → literal

    if (op === "on" || op === "after" || op === "before") {
        if (isDate(value)) {
            return { op, value, negated, isTime: false };
        }
        if ((op === "after" || op === "before") && isTime(value)) {
            return { op, value, negated, isTime: true };
        }
        return null; // bad date/time → literal text
    }
    if (op === "ws" || op === "monitor") {
        if (!/^\d+$/.test(value)) return null; // workspace ids are ints
        return { op, value, negated, isTime: false };
    }
    const allowed = ENUM_VALUES[op];
    if (allowed && !allowed.includes(value.toLowerCase())) {
        return null; // unknown enum value → literal text
    }
    // Normalize enum values (KIND:FRAME → kind:frame); app/player/ws values
    // keep their case — they match window_class strings verbatim.
    return {
        op,
        value: allowed ? value.toLowerCase() : value,
        negated,
        isTime: false,
    };
}

/** Day context a bare after:/before: time binds to: the `on:` token's day,
 * else the widget date range's start day, else nothing. */
export function timeContextDay(
    parsed: ParsedQuery,
    filters: Pick<SearchFilters, "preset" | "start" | "end">,
    now: Date,
): string | null {
    const on = parsed.tokens.find((t) => t.op === "on" && !t.negated);
    if (on) return on.value;
    const { start } = dayBoundsOfSpan(filters, now);
    return start ? localISO(start).slice(0, 10) : null;
}

function dayBoundsOfSpan(
    f: Pick<SearchFilters, "preset" | "start" | "end">,
    now: Date,
): { start: Date | null; end: Date | null } {
    const startRaw = f.start;
    const endRaw = f.end;
    const presetStart = f.preset !== "all" ? rangeStart(f.preset, now) : null;
    return {
        start: startRaw ? new Date(startRaw) : presetStart,
        end: endRaw ? new Date(endRaw) : null,
    };
}

function rangeStart(preset: SearchFilters["preset"], now: Date): Date | null {
    switch (preset) {
        case "today":
            return new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0, 0);
        case "yesterday": {
            const y = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1, 0, 0, 0, 0);
            return y;
        }
        case "last7": {
            const s = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 6, 0, 0, 0, 0);
            return s;
        }
        case "thisMonth":
            return new Date(now.getFullYear(), now.getMonth(), 1, 0, 0, 0, 0);
        default:
            return null;
    }
}

/**
 * Fold parsed tokens into the filter state and compute the FTS text query.
 *
 * Text-authoritative dimensions (app/player/kind/source/ws/monitor/fullscreen)
 * are ALWAYS overwritten from the tokens — the box is their single source of
 * truth, and widget changes write tokens back into it. Date dimensions are
 * only touched when a date token is present. Returns the unresolved leftover
 * as `text`: literal words plus any recognized token that state can't hold
 * (a bare after:/before: time with no day context).
 */
export function applyQueryTokens(
    filters: SearchFilters,
    parsed: ParsedQuery,
    now: Date,
): { filters: SearchFilters; text: string } {
    let next = filters;
    const unresolved: string[] = [];
    const { tokens } = parsed;

    // Text-authoritative dimensions: ALWAYS overwritten from the tokens, so
    // removing a token (or widget edit) resets the state rather than
    // leaving a stale value.
    const vals = (op: QueryOperator) =>
        tokens.filter((t) => t.op === op && !t.negated).map((t) => t.value);
    next = { ...next, apps: vals("app"), players: vals("player") };

    const kindToken = tokens.find((t) => t.op === "kind");
    next = {
        ...next,
        kind: kindToken
            ? ((kindToken.negated
                ? (kindToken.value === "frame" ? "session" : "frame")
                : kindToken.value) as SearchFilters["kind"])
            : "all",
    };
    const sourceToken = tokens.find((t) => t.op === "source" && !t.negated);
    const hasToken = tokens.find((t) => t.op === "has" && !t.negated);
    next = {
        ...next,
        source: sourceToken
            ? (sourceToken.value as SearchFilters["source"])
            : hasToken
              ? "transcript"
              : "any",
    };

    const wsToken = tokens.find((t) => t.op === "ws");
    next = { ...next, workspace: wsToken && !wsToken.negated ? wsToken.value : "" };
    const monitorToken = tokens.find((t) => t.op === "monitor");
    next = { ...next, monitor: monitorToken && !monitorToken.negated ? monitorToken.value : "" };
    const fullToken = tokens.find((t) => t.op === "fullscreen");
    next = {
        ...next,
        fullscreen: fullToken
            ? ((fullToken.negated
                ? (fullToken.value === "yes" ? "no" : "yes")
                : fullToken.value) as SearchFilters["fullscreen"])
            : "any",
    };

    const day = timeContextDay(parsed, next, now);
    const onToken = tokens.find((t) => t.op === "on");
    if (onToken && !onToken.negated) {
        // datetime-local bounds (what the start/end widgets bind to)
        next = {
            ...next,
            preset: "all",
            start: `${onToken.value}T00:00`,
            end: `${shiftDay(onToken.value, 1)}T00:00`,
        };
    }
    const afterToken = tokens.find((t) => t.op === "after");
    if (afterToken && !afterToken.negated) {
        if (afterToken.isTime && day) {
            next = { ...next, start: `${day}T${afterToken.value}` };
        } else if (!afterToken.isTime) {
            next = { ...next, start: `${afterToken.value}T00:00` };
        } else {
            unresolved.push(afterToken.raw);
        }
    }
    const beforeToken = tokens.find((t) => t.op === "before");
    if (beforeToken && !beforeToken.negated) {
        if (beforeToken.isTime && day) {
            next = { ...next, end: `${day}T${beforeToken.value}` };
        } else if (!beforeToken.isTime) {
            next = { ...next, end: `${shiftDay(beforeToken.value, 1)}T00:00` };
        } else {
            unresolved.push(beforeToken.raw);
        }
    }

    // FTS text: literal words + tokens the state can't hold. Recognized but
    // inexpressible negations are dropped silently rather than risk a 422.
    return { filters: next, text: [...parsed.text.split(/\s+/).filter(Boolean), ...unresolved].join(" ") };
}

/** Append `op:value` to the box text unless an identical token already exists. */
export function insertToken(text: string, op: QueryOperator, value: string): string {
    const parsed = parseQuery(text);
    if (parsed.tokens.some((t) => t.op === op && t.value.toUpperCase() === value.toUpperCase() && !t.negated)) {
        return text;
    }
    const trimmed = text.trimEnd();
    return trimmed ? `${trimmed} ${op}:${value}` : `${op}:${value}`;
}

/** Remove one specific token (op + value) from the box text. */
export function removeToken(text: string, op: QueryOperator, value: string): string {
    const parsed = parseQuery(text);
    const out: string[] = [];
    let prev = 0;
    let changed = false;
    for (const t of parsed.tokens) {
        if (t.op === op && t.value.toUpperCase() === value.toUpperCase()) {
            out.push(text.slice(prev, t.start).trim());
            prev = t.end;
            changed = true;
        } else {
            out.push("");
        }
    }
    if (!changed) return text;
    out.push(text.slice(prev).trim());
    return out.filter(Boolean).join(" ");
}

/** Remove every token of one operator from the box text. */
export function removeOpTokens(text: string, op: QueryOperator): string {
    const parsed = parseQuery(text);
    const spans: Array<[number, number]> = [];
    for (const t of parsed.tokens) {
        if (t.op === op) spans.push([t.start, t.end]);
    }
    let out = text;
    for (const [s, e] of spans.reverse()) {
        out = `${out.slice(0, s)}${out.slice(e)}`;
    }
    return out.split(/\s+/).filter(Boolean).join(" ");
}