/** Per-day selected-frame memory (module-local, like session-search).
 *
 * Survives tab switches and surface remounts within the app session:
 * returning to the DAY tab puts you back on the exact frame you were
 * viewing, per day. Dies with the app.
 */

let byDay = new Map<string, number>();

/** Frame the user last had selected on this day, if any. */
export function savedFrame(day: string): number | null {
    return byDay.get(day) ?? null;
}

/** Remember the user's selection for a day. */
export function rememberFrame(day: string, frameId: number): void {
    byDay.set(day, frameId);
}

/** Test seam: forget everything. */
export function resetDaySelection(): void {
    byDay = new Map();
}