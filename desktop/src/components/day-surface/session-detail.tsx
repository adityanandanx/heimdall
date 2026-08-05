import { useEffect, useMemo } from "react";
import { X } from "lucide-react";
import type { Session } from "@/lib/api";
import { formatDateTime, formatTime } from "@/lib/format";
import { sessionWatchedSec, fmtDur, playerColor } from "@/lib/timeline";
import { cn } from "@/lib/utils";

interface SessionDetailProps {
    sessions: Session[];
    onClose: () => void;
    onJump: (ts: number) => void;
}

interface Cue {
    t?: number;
    start_ms?: number;
    end_ms?: number;
    text?: string;
}

export function SessionDetail({ sessions, onClose, onJump }: SessionDetailProps) {
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.key === "Escape") onClose();
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [onClose]);

    const main = sessions[0];
    if (!main) return null;

    const color = playerColor(main.player);

    const watched = useMemo(() => sessions.reduce((a, s) => a + sessionWatchedSec(s), 0), [sessions]);
    const words = useMemo(
        () => sessions.reduce((a, s) => a + (s.transcript?.split(/\s+/).length ?? 0), 0),
        [sessions],
    );
    const cues = useMemo<Cue[]>(() => {
        try {
            return (JSON.parse(main.cues_json ?? "null") as Cue[] | null) ?? [];
        } catch {
            return [];
        }
    }, [main.cues_json]);

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-background/70 p-6 backdrop-blur-sm"
            data-testid="session-detail-overlay"
            onClick={onClose}
        >
            <div
                className="flex max-h-[80vh] w-[440px] max-w-[92vw] flex-col overflow-hidden rounded-lg border border-line bg-surface shadow-[var(--e2)]"
                onClick={(e) => e.stopPropagation()}
                role="dialog"
                aria-modal="true"
                aria-label="watch session details"
            >
                <div className="relative shrink-0 bg-[linear-gradient(135deg,var(--surface-2),var(--surface))] px-5 pt-4 pb-3.5">
                    <button
                        type="button"
                        aria-label="close"
                        onClick={onClose}
                        className="absolute top-3 right-3 flex size-6 items-center justify-center rounded-full text-dim transition-colors hover:bg-surface-2 hover:text-foreground"
                    >
                        <X className="size-3.5" />
                    </button>

                    <div className="mb-2 flex items-center gap-2 pr-6">
                        <span
                            className="flex size-5 items-center justify-center rounded-md text-[10px] font-bold"
                            style={{ background: `color-mix(in srgb, ${color} 25%, transparent)`, color }}
                        >
                            ▶
                        </span>
                        <span
                            className="rounded-full border px-2 py-0.5 text-[10px]"
                            style={{
                                borderColor: `color-mix(in srgb, ${color} 50%, transparent)`,
                                color,
                            }}
                        >
                            {main.player}
                        </span>
                        {main.live === 1 && (
                            <span className="flex shrink-0 items-center gap-1 rounded-full border border-danger/40 px-2 py-0.5 text-[10px] text-danger">
                                <span className="h-1 w-1 rounded-full bg-danger" /> LIVE
                            </span>
                        )}
                    </div>
                    <h3 className="text-[15px] leading-snug font-bold break-words">
                        {main.media_title ?? "Untitled media"}
                    </h3>
                    {main.media_source && (
                        <div className="mt-0.5 truncate text-[11px] text-faint">{main.media_source}</div>
                    )}
                </div>

                <div className="grid grid-cols-2 gap-px border-b border-line bg-line">
                    <Meta k="watched" v={fmtDur(watched)} />
                    <Meta k="time" v={rangeLabel(main)} />
                    <Meta k="words" v={words.toLocaleString()} />
                    <Meta k="source" v={main.transcript_source ?? "—"} />
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
                    {cues.length > 0 && (
                        <section className="mb-4">
                            <h4 className="mb-2 text-[10px] font-semibold tracking-[1.2px] text-faint uppercase">
                                Cues
                            </h4>
                            <div className="flex flex-col gap-1 rounded-md border border-line bg-surface-2 p-3">
                                {cues.map((c, i) => (
                                    <div key={i} className="flex gap-2 text-[11px]">
                                        <span className="shrink-0 font-mono text-faint">
                                            {c.t != null
                                                ? fmtDur(c.t)
                                                : c.start_ms != null
                                                  ? fmtDur(c.start_ms / 1000)
                                                  : "—"}
                                        </span>
                                        <span className="text-dim">{c.text ?? ""}</span>
                                    </div>
                                ))}
                            </div>
                        </section>
                    )}

                    <section className="mb-4">
                        <h4 className="mb-2 text-[10px] font-semibold tracking-[1.2px] text-faint uppercase">
                            Transcript
                        </h4>
                        <p
                            className={cn(
                                "max-h-[150px] overflow-y-auto rounded-md border border-line bg-surface-2 p-3 text-[11px] leading-relaxed text-dim",
                                !main.transcript && "text-faint",
                            )}
                        >
                            {main.transcript ?? "No transcript captured."}
                        </p>
                    </section>
                </div>

                <div className="shrink-0 border-t border-line p-3.5">
                    <button
                        type="button"
                        onClick={() => onJump(new Date(main.ts_start).getTime())}
                        className="w-full rounded-md bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground transition-[filter] hover:brightness-110"
                    >
                        Jump to moment
                    </button>
                </div>
            </div>
        </div>
    );
}

function Meta({ k, v }: { k: string; v: string }) {
    return (
        <div className="flex flex-col gap-0.5 bg-surface px-4 py-2.5">
            <span className="text-[10px] tracking-wide text-faint uppercase">{k}</span>
            <span className="font-mono text-[12px] text-foreground">{v}</span>
        </div>
    );
}

function rangeLabel(s: Session): string {
    const a = formatDateTime(s.ts_start);
    if (!a) return "—";
    const b = s.ts_end ? formatTime(s.ts_end) : "now";
    return `${a} → ${b ?? "—"}`;
}