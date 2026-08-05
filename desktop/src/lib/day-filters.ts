import type { Frame, Session } from "@/lib/api";
import type { ParsedQuery } from "@/lib/query-language";

/** Day-scoped filter state (#64): the day is fixed, so the date range
 * collapses to time-of-day after:/before: HH:MM values. All other
 * dimensions mirror the Search surface's text-authoritative state. */
export interface DayFilterState {
    kind: "all" | "frame" | "session";
    source: "any" | "a11y" | "ocr" | "transcript";
    apps: string[];
    players: string[];
    /** HH:MM within the day ("" = unset). */
    after: string;
    before: string;
}

/** Fold the day box's parsed tokens into state; `on:`/`ws:`/`monitor:`/
 * `fullscreen:` tokens have no meaning for a fixed day and are dropped
 * from the FTS text (they don't compile to day state). */
export function dayStateFrom(parsed: ParsedQuery): DayFilterState {
    const { tokens } = parsed;
    const vals = (op: "app" | "player") =>
        tokens.filter((t) => t.op === op && !t.negated).map((t) => t.value);
    const kindToken = tokens.find((t) => t.op === "kind");
    const sourceToken = tokens.find((t) => t.op === "source" && !t.negated);
    const hasToken = tokens.find((t) => t.op === "has" && !t.negated);
    const after = tokens.find((t) => t.op === "after" && t.isTime && !t.negated);
    const before = tokens.find((t) => t.op === "before" && t.isTime && !t.negated);
    return {
        kind: kindToken
            ? ((kindToken.negated
                ? (kindToken.value === "frame" ? "session" : "frame")
                : kindToken.value) as DayFilterState["kind"])
            : "all",
        source: sourceToken
            ? (sourceToken.value as DayFilterState["source"])
            : hasToken
              ? "transcript"
              : "any",
        apps: vals("app"),
        players: vals("player"),
        after: after?.value ?? "",
        before: before?.value ?? "",
    };
}

/** Does this frame pass the day filters? Used for timeline dimming and for
 * pruning the suggestion list (a dimmed frame is not suggested). */
export function matchesDayFrame(f: DayFilterState, frame: Frame): boolean {
    if (f.kind === "session") return false;
    if (f.apps.length > 0 && !f.apps.some((a) => a.toLowerCase() === frame.window_class.toLowerCase())) {
        return false;
    }
    if (f.source === "a11y") return !!frame.a11y_text;
    if (f.source === "ocr") return !!frame.ocr_text;
    if (f.source === "transcript") return false;
    return inDayWindow(f, frame.ts);
}

/** Same for sessions; transcript frames have no a11y/ocr, a11y/ocr applies
 * to frames only. */
export function matchesDaySession(f: DayFilterState, session: Session): boolean {
    if (f.kind === "frame") return false;
    if (f.players.length > 0 && !f.players.some((p) => p.toLowerCase() === session.player.toLowerCase())) {
        return false;
    }
    if (f.source === "transcript") return !!session.transcript;
    if (f.source === "a11y" || f.source === "ocr") return false;
    return inDayWindow(f, session.ts_start);
}

function inDayWindow(f: DayFilterState, tsIso: string): boolean {
    const hm = tsIso.slice(11, 16);
    if (f.after && hm < f.after) return false;
    if (f.before && hm > f.before) return false;
    return true;
}

/** Is any day filter active (vs. the pristine box)? */
export function dayFiltersActive(f: DayFilterState): boolean {
    return (
        f.kind !== "all" ||
        f.source !== "any" ||
        f.apps.length > 0 ||
        f.players.length > 0 ||
        f.after !== "" ||
        f.before !== ""
    );
}

/** Compile the handoff query for the Search tab: leftover text + tokens,
 * with time-of-day folded into an absolute `on:` day range so the Search
 * surface resolves after:/before: against this day (#64). */
export function dayHandoffQuery(f: DayFilterState, text: string, day: string): string {
    const parts = text.trim() ? [text.trim()] : [];
    for (const app of f.apps) parts.push(`app:${app}`);
    for (const player of f.players) parts.push(`player:${player}`);
    if (f.kind !== "all") parts.push(`kind:${f.kind}`);
    if (f.source !== "any") parts.push(`source:${f.source}`);
    if (f.after || f.before) {
        parts.push(`on:${day}`);
        if (f.after) parts.push(`after:${f.after}`);
        if (f.before) parts.push(`before:${f.before}`);
    }
    return parts.join(" ");
}
