import { useEffect, useMemo, useState } from "react";
import { Trash2, X } from "lucide-react";
import type { Session } from "@/lib/api";
import { deleteSession, fetchSessionTranscript } from "@/lib/api";
import { formatDateTime, formatTime } from "@/lib/format";
import { sessionWatchedSec, fmtDur, playerColor } from "@/lib/timeline";
import { unifiedCues } from "@/lib/watch-sessions";
import { cn } from "@/lib/utils";

interface SessionDetailProps {
    sessions: Session[];
    baseUrl: string;
    onClose: () => void;
    onJump: (ts: number) => void;
    onMutated: () => void;
}

export function SessionDetail({ sessions, baseUrl, onClose, onJump, onMutated }: SessionDetailProps) {
    const [deleteBusy, setDeleteBusy] = useState(false);
    const [fetchBusy, setFetchBusy] = useState(false);
    const [fetchError, setFetchError] = useState<string | null>(null);
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
    const cues = useMemo(() => unifiedCues(sessions), [sessions]);
    const transcriptText = useMemo(
        () => sessions.map((s) => s.transcript ?? "").filter(Boolean).join(" "),
        [sessions],
    );

    const deleteSessionRow = async () => {
        if (deleteBusy) return;
        if (!window.confirm(`Delete this "${main.media_title ?? "untitled"}" session?`)) return;
        setDeleteBusy(true);
        try {
            await deleteSession(baseUrl, main.id);
            onMutated();
            onClose();
        } catch (e) {
            console.error(e);
        } finally {
            setDeleteBusy(false);
        }
    };

    const fetchTranscript = async () => {
        if (fetchBusy) return;
        setFetchBusy(true);
        setFetchError(null);
        try {
            await fetchSessionTranscript(baseUrl, main.id);
            onMutated();
        } catch (e) {
            setFetchError(e instanceof Error ? e.message : String(e));
        } finally {
            setFetchBusy(false);
        }
    };

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-background/70 p-6 backdrop-blur-sm"
            data-testid="session-detail-overlay"
            onClick={onClose}
        >
            <div
                className="flex max-h-[92vh] w-[1200px] max-w-[98vw] flex-col overflow-hidden rounded-lg border border-line bg-surface shadow-[var(--e2)]"
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

                <div className="grid min-h-0 flex-1 grid-cols-2 gap-0">
                    <div className="min-h-0 overflow-y-auto border-r border-line px-5 py-4">
                        <h4 className="mb-2 text-[10px] font-semibold tracking-[1.2px] text-faint uppercase">
                            Cues
                        </h4>
                        {cues.length > 0 ? (
                            <div className="flex flex-col gap-1">
                                {cues.map((c, i) => (
                                    <div key={i} className="flex gap-2 rounded-sm border-b border-line pb-1 text-[11px] last:border-b-0">
                                        <span className="shrink-0 font-mono text-faint">
                                            {fmtDur(c.startMs / 1000)}
                                        </span>
                                        <span className="text-dim">{c.text}</span>
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <p className="text-[11px] text-faint">No cues captured.</p>
                        )}
                    </div>

                    <div className="min-h-0 overflow-y-auto px-5 py-4">
                        <div className="mb-2 flex items-center gap-2">
                            <h4 className="text-[10px] font-semibold tracking-[1.2px] text-faint uppercase">
                                Transcript
                            </h4>
                            {!transcriptText && main.media_id && (
                                <button
                                    type="button"
                                    onClick={fetchTranscript}
                                    disabled={fetchBusy}
                                    data-testid="fetch-transcript"
                                    className="ml-auto rounded-sm border border-line bg-surface px-2 py-0.5 font-mono text-[10px] text-dim transition-colors hover:border-primary hover:text-foreground disabled:opacity-40"
                                >
                                    {fetchBusy ? "fetching…" : "⟳ fetch now"}
                                </button>
                            )}
                        </div>
                        {fetchError && (
                            <p className="mb-1.5 text-[10px] text-danger" data-testid="fetch-transcript-error">
                                {fetchError}
                            </p>
                        )}
                        <p
                            className={cn(
                                "rounded-md border border-line bg-surface-2 p-3 text-[11px] leading-relaxed text-dim",
                                !transcriptText && "text-faint",
                            )}
                        >
                            {transcriptText || "No transcript captured."}
                        </p>
                    </div>
                </div>

                <div className="flex gap-2 border-t border-line p-3.5">
                    <button
                        type="button"
                        onClick={() => onJump(new Date(main.ts_start).getTime())}
                        className="flex-1 rounded-md bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground transition-[filter] hover:brightness-110"
                    >
                        Jump to moment
                    </button>
                    <button
                        type="button"
                        onClick={deleteSessionRow}
                        disabled={deleteBusy}
                        data-testid="delete-session"
                        aria-label="delete session"
                        className="flex items-center gap-1.5 rounded-md border border-line px-3 py-2 text-xs text-dim transition-colors hover:border-danger/50 hover:text-danger disabled:opacity-40"
                    >
                        <Trash2 className="size-3.5" />
                        {deleteBusy ? "deleting…" : "delete"}
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