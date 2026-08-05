import { useState } from "react";
import type { Session } from "@/lib/api";
import { formatTimeS } from "@/lib/format";
import { fmtDur, playerColor, sessionWatchedSec } from "@/lib/timeline";
import { cn } from "@/lib/utils";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";

interface WatchLaneProps {
    sessions: Session[];
    onNavigate: (epochMs: number) => void;
}

function rangeOf(s: Session): { start: number; end: number } {
    const start = new Date(s.ts_start).getTime();
    const end = s.ts_end ? new Date(s.ts_end).getTime() : start;
    return { start, end };
}

function fmtRange(s: Session): string {
    const { start, end } = rangeOf(s);
    const st = formatTimeS(start);
    const en = formatTimeS(end);
    return `${st} – ${en}`;
}

function snap(t: number, session: Session): number {
    const rs = session.ranges || [];
    if (!rs.length) return t;
    let best = rs[0][0] * 1000;
    let bd = Infinity;
    for (const [b, e] of rs) {
        const mid = ((b + e) / 2) * 1000;
        const d = Math.abs(mid - t);
        if (d < bd) {
            bd = d;
            best = mid;
        }
    }
    return best;
}

export function WatchLane({ sessions, onNavigate }: WatchLaneProps) {
    const [openId, setOpenId] = useState<number | null>(null);
    const open = sessions.find((s) => s.id === openId) ?? null;

    const sorted = [...sessions].sort(
        (a, b) => new Date(a.ts_start).getTime() - new Date(b.ts_start).getTime(),
    );

    return (
        <div className="flex flex-col gap-2" data-testid="watch-lane">
            {sorted.length === 0 && (
                <p className="text-xs text-muted-foreground">No watch sessions this day.</p>
            )}
            {sorted.map((s) => {
                const color = playerColor(s.player);
                const watched = sessionWatchedSec(s);
                const live = Boolean(s.live);
                const { start } = rangeOf(s);
                return (
                    <button
                        key={s.id}
                        type="button"
                        className="group flex flex-col gap-1 rounded-lg border border-border bg-card px-3 py-2 text-left transition-colors hover:border-foreground/30 hover:bg-muted/50"
                        onClick={() => {
                            onNavigate(start);
                            setOpenId(s.id);
                        }}
                    >
                        <span className="flex items-center gap-2 text-sm">
                            <span
                                className="inline-block size-2.5 shrink-0 rounded-full"
                                style={{ background: color }}
                            />
                            <span className="truncate font-semibold">{s.media_title || "(untitled)"}</span>
                            {live && (
                                <span className="rounded-full bg-red-500/15 px-2 py-0.5 text-[10px] font-bold uppercase text-red-500">
                                    live
                                </span>
                            )}
                            <span className="ml-auto shrink-0 text-[11px] text-muted-foreground tabular-nums">
                                {fmtDur(watched)} watched
                            </span>
                        </span>
                        <span className="flex items-center gap-2 text-[11px] text-muted-foreground">
                            <span className="capitalize">{s.player}</span>
                            <span className="text-border">·</span>
                            <span className="tabular-nums">{fmtRange(s)}</span>
                            <span className="text-border">·</span>
                            <span className="truncate">
                                {fmtDur(s.length ?? 0)} {s.live ? "elapsed" : "playback"}
                            </span>
                        </span>
                    </button>
                );
            })}
            {open && (
                <SessionDialog
                    session={open}
                    onOpenChange={(o) => {
                        if (!o) setOpenId(null);
                    }}
                    onSeek={(ms) => onNavigate(snap(ms, open))}
                />
            )}
        </div>
    );
}

interface SessionDialogProps {
    session: Session;
    onOpenChange: (open: boolean) => void;
    onSeek: (epochMs: number) => void;
}

function SessionDialog({ session, onOpenChange, onSeek }: SessionDialogProps) {
    const [speed, setSpeed] = useState(1);
    const [dir, setDir] = useState<1 | -1>(1);
    const [seekMs, setSeekMs] = useState(5000);

    const cues = parseCues(session.cues_json);
    const start = new Date(session.ts_start).getTime();
    const end = session.ts_end ? new Date(session.ts_end).getTime() : start;

    function apply(step: number, direction: 1 | -1) {
        const target = direction === 1 ? start + step : end - step;
        onSeek(Math.max(start, Math.min(target, end)));
    }

    return (
        <Dialog open onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-lg">
                <DialogHeader className="pr-8">
                    <DialogTitle className="flex items-center gap-2">
                        <span
                            className="inline-block size-2.5 rounded-full"
                            style={{ background: playerColor(session.player) }}
                        />
                        <span className="truncate">{session.media_title || "(untitled)"}</span>
                    </DialogTitle>
                </DialogHeader>
                <DialogDescription>
                    {fmtRange(session)} · {fmtDur(session.length ?? 0)} on {session.player} ·{" "}
                    {fmtDur(sessionWatchedSec(session))} actually watched
                </DialogDescription>

                <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-medium text-muted-foreground">Jump:</span>
                    <span className="text-[11px] text-muted-foreground tabular-nums">−{fmtDur(seekMs / 1000)}</span>
                    <input
                        type="range"
                        min={1000}
                        max={120000}
                        step={1000}
                        value={seekMs}
                        aria-label="jump size"
                        className="w-24"
                        onChange={(e) => setSeekMs(Number(e.currentTarget.value))}
                    />
                    <span className="text-[11px] text-muted-foreground tabular-nums">+{fmtDur(seekMs / 1000)}</span>
                    <span className="ml-2 text-xs font-medium text-muted-foreground">Speed:</span>
                    <input
                        type="range"
                        min={0.5}
                        max={3}
                        step={0.5}
                        value={speed}
                        aria-label="playback speed"
                        className="w-24"
                        onChange={(e) => setSpeed(Number(e.currentTarget.value))}
                    />
                    <span className="text-[11px] text-muted-foreground tabular-nums">{speed}×</span>
                    <div className="ml-auto flex gap-1">
                        <button
                            type="button"
                            aria-label="seek to previous watched moment"
                            className={cn(
                                "inline-flex size-7 items-center justify-center rounded-md border border-border text-xs",
                                dir === -1 && "border-foreground/40 bg-accent",
                            )}
                            onClick={() => setDir(-1)}
                        >
                            ◂
                        </button>
                        <button
                            type="button"
                            aria-label="seek to next watched moment"
                            className={cn(
                                "inline-flex size-7 items-center justify-center rounded-md border border-border text-xs",
                                dir === 1 && "border-foreground/40 bg-accent",
                            )}
                            onClick={() => setDir(1)}
                        >
                            ▸
                        </button>
                    </div>
                </div>
                <div className="flex gap-2">
                    <button
                        type="button"
                        className="rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium hover:bg-muted/50"
                        onClick={() => apply(seekMs, -1)}
                    >
                        Jump −{fmtDur(seekMs / 1000)}
                    </button>
                    <button
                        type="button"
                        className="rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium hover:bg-muted/50"
                        onClick={() => apply(seekMs, 1)}
                    >
                        Jump +{fmtDur(seekMs / 1000)}
                    </button>
                </div>

                <div className="flex flex-col gap-1.5">
                    <span className="text-xs font-medium text-muted-foreground">Watched ranges</span>
                    {session.ranges && session.ranges.length > 0 ? (
                        session.ranges.map(([b, e], i) => (
                            <span key={i} className="text-xs tabular-nums">
                                {formatTimeS(b * 1000)} – {formatTimeS(e * 1000)}{" "}
                                <span className="text-muted-foreground">({fmtDur((e - b) / 1e6)})</span>
                            </span>
                        ))
                    ) : (
                        <span className="text-xs text-muted-foreground">No ranges recorded.</span>
                    )}
                </div>

                {session.transcript && (
                    <div className="flex flex-col gap-1.5">
                        <span className="text-xs font-medium text-muted-foreground">Transcript</span>
                        <div className="max-h-36 overflow-y-auto whitespace-pre-wrap rounded-lg border border-border bg-muted/40 p-3 text-xs leading-relaxed">
                            {session.transcript}
                        </div>
                    </div>
                )}

                {cues.length > 0 && (
                    <div className="flex flex-col gap-1.5">
                        <span className="text-xs font-medium text-muted-foreground">Moments</span>
                        <div className="max-h-36 overflow-y-auto rounded-lg border border-border bg-muted/40 p-3 text-xs leading-relaxed">
                            {cues.map((c, i) => (
                                <p key={i}>
                                    <span className="tabular-nums text-muted-foreground">{formatTimeS(c.t * 1000)}</span>{" "}
                                    {c.text}
                                </p>
                            ))}
                        </div>
                    </div>
                )}
            </DialogContent>
        </Dialog>
    );
}

function parseCues(raw: string | null): Array<{ t: number; text: string }> {
    if (!raw) return [];
    try {
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) return [];
        return parsed
            .map((c) => {
                if (typeof c !== "object" || c === null) return null;
                const t = Number(c.t ?? c.timestamp ?? c.start);
                const text = String(c.text ?? c.content ?? "");
                if (!Number.isFinite(t) || !text) return null;
                return { t, text };
            })
            .filter((c): c is { t: number; text: string } => c !== null);
    } catch {
        return [];
    }
}