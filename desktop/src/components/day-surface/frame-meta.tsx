import { useState } from "react";
import type { Frame, PipeRunResult } from "@/lib/api";
import { formatTimeS } from "@/lib/format";
import { srcOf } from "@/lib/frames";
import { clsColor } from "@/lib/timeline";
import { cn } from "@/lib/utils";
import { Markdown } from "@/lib/markdown";

interface FrameMetaProps {
    baseUrl: string;
    frame: Frame;
    recapResult: PipeRunResult | null;
    onRunRecap: () => void;
    recapRunning: boolean;
    apps: Array<{ cls: string; count: number; pct: number }>;
    selectedApps: string[];
    onToggleApp: (cls: string) => void;
    onClearApps: () => void;
    onDeleteFrame: () => void;
    deleteBusy: boolean;
}

export function FrameMeta({ frame, recapResult, onRunRecap, recapRunning, apps, selectedApps, onToggleApp, onClearApps, onDeleteFrame, deleteBusy }: FrameMetaProps) {
    const src = srcOf(frame);
    const text = frame.a11y_text || frame.ocr_text || "";
    return (
        <>
            <div className="mt-6 mb-2.5 flex items-center justify-between first:mt-0">
                <h2 className="text-[11px] tracking-[1.2px] text-faint uppercase">Frame</h2>
                <button
                    type="button"
                    onClick={onDeleteFrame}
                    disabled={deleteBusy}
                    data-testid="delete-frame"
                    className="rounded-sm border border-danger/40 bg-danger/10 px-2 py-0.5 font-mono text-[10px] text-danger transition-colors hover:bg-danger/25 disabled:opacity-40"
                >
                    {deleteBusy ? "deleting…" : "delete frame"}
                </button>
            </div>
            <div className="flex flex-col gap-2 rounded-md border border-line bg-surface-2 p-3 text-xs">
                <Row k="time" v={formatTimeS(frame.ts) ?? "—"} mono />
                <div className="flex items-center justify-between gap-2">
                    <span className="shrink-0 text-faint">source</span>
                    <SourceBadge src={src} />
                </div>
                {frame.source_url ? (
                    <div className="flex justify-between gap-2.5">
                        <span className="shrink-0 text-faint">url</span>
                        <a
                            href={frame.source_url}
                            target="_blank"
                            rel="noreferrer"
                            title={frame.source_url}
                            className="min-w-0 truncate font-mono text-[11px] text-primary hover:underline"
                            data-testid="frame-source-url"
                        >
                            {frame.source_url}
                        </a>
                    </div>
                ) : (
                    <div className="flex justify-between gap-2.5" data-testid="frame-source-url-empty">
                        <span className="shrink-0 text-faint">url</span>
                        <span className="font-mono text-[11px] text-faint">—</span>
                    </div>
                )}
                <Row k="window" v={frame.window_class} mono />
                <p className="text-xs break-words text-dim">{frame.window_title || "(untitled)"}</p>
                <Row k="monitor" v={frame.monitor != null ? String(frame.monitor) : "—"} mono />
                <Row k="workspace" v={frame.workspace ?? "—"} mono />
                <Row
                    k="capture"
                    v={[frame.trigger, frame.fullscreen ? "fullscreen" : null].filter(Boolean).join(" · ")}
                    mono
                />
                <Row
                    k="status"
                    v={frame.text_pending ? "extracting…" : "done"}
                    mono
                />
                <Row
                    k="ocr_sec"
                    v={
                        frame.ocr_sec != null
                            ? `${frame.ocr_sec.toFixed(1)}s${frame.ocr_engine ? ` · ${frame.ocr_engine}` : ""}`
                            : "—"
                    }
                    mono
                />
            </div>

            <h2 className="mb-2.5 mt-6 text-[11px] tracking-[1.2px] text-faint uppercase">OCR text</h2>
            <OcrBox frame={frame} text={text} />

            <h2 className="mb-2.5 mt-6 text-[11px] tracking-[1.2px] text-faint uppercase">Recap</h2>
            <div className="rounded-md border border-primary/25 bg-primary/7 p-3">
                {recapResult ? (
                    <>
                        <div className="mb-1.5 text-[13px] font-semibold">{recapResult.pipe}</div>
                        <Markdown text={recapResult.output_markdown} />
                        <div className="mt-2 text-[10px] text-faint">
                            {recapResult.frame_count} frames · {(recapResult.run_ms / 1000).toFixed(1)}s
                        </div>
                    </>
                ) : (
                    <>
                        <div className="mb-1.5 text-[13px] font-semibold">Day recap</div>
                        <p className="text-xs text-dim">
                            What you watched and worked on today, synthesized from frames and transcripts.
                        </p>
                        <div className="mt-2">
                            <button
                                type="button"
                                onClick={onRunRecap}
                                disabled={recapRunning}
                                className="rounded-sm border border-line bg-surface px-2.5 py-1 text-[10px] text-[var(--text-dim)] transition-colors hover:border-primary hover:text-foreground disabled:opacity-40"
                            >
                                {recapRunning ? "running…" : "⟳ synthesize"}
                            </button>
                        </div>
                    </>
                )}
            </div>

            <h2 className="mb-2.5 mt-6 text-[11px] tracking-[1.2px] text-faint uppercase">Apps</h2>
            <div className="flex flex-col">
                {apps.length === 0 && <p className="text-xs text-dim">No apps today.</p>}
                <button
                    type="button"
                    className="flex items-center gap-2.5 rounded-sm px-2 py-1.5 text-left transition-colors hover:bg-surface-2"
                    onClick={onClearApps}
                    data-testid="apps-filter-clear"
                >
                    <span className="w-2 shrink-0 rounded-[3px] bg-border" />
                    <div className="min-w-0 flex-1">
                        <span className="text-xs text-dim">all apps</span>
                    </div>
                </button>
                {apps.map((a) => {
                    const active = selectedApps.includes(a.cls);
                    return (
                        <button
                            key={a.cls}
                            type="button"
                            className={cn(
                                "flex items-center gap-2.5 rounded-sm px-2 py-1.5 text-left transition-colors hover:bg-surface-2",
                                active && "bg-surface-2",
                            )}
                            onClick={() => onToggleApp(a.cls)}
                            data-testid={`app-filter-${a.cls}`}
                        >
                            <span className="w-2 shrink-0 rounded-[3px]" style={{ background: clsColor(a.cls) }} />
                            <div className="min-w-0 flex-1">
                                <div className="flex items-baseline gap-2">
                                    <span className="min-w-0 flex-1 truncate text-xs">{a.cls}</span>
                                    <span className="shrink-0 font-mono text-[11px] text-faint">
                                        {Math.round(a.pct)}% · {a.count}
                                    </span>
                                </div>
                                <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-surface-2">
                                    <span
                                        className="block h-full rounded-full"
                                        style={{ width: `${a.pct}%`, background: clsColor(a.cls) }}
                                    />
                                </div>
                            </div>
                        </button>
                    );
                })}
            </div>
        </>
    );
}

function Row({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
    return (
        <div className="flex justify-between gap-2.5">
            <span className="shrink-0 text-faint">{k}</span>
            <span className={cn("min-w-0 text-right break-words", mono && "font-mono")}>{v}</span>
        </div>
    );
}

export function SourceBadge({ src }: { src: "a11y" | "ocr" | "none" }) {
    return (
        <span
            className={cn(
                "rounded-full border px-2 py-0.5 text-[10px]",
                src === "a11y" && "border-ok/40 text-ok",
                src === "ocr" && "border-primary/40 text-primary",
                src === "none" && "border-line text-[var(--text-faint)]",
            )}
        >
            {src === "a11y" ? "a11y tree" : src === "ocr" ? "ocr" : "no text"}
        </span>
    );
}

function OcrBox({ frame, text }: { frame: Frame; text: string }) {
    const [copied, setCopied] = useState(false);
    const pending = frame.text_pending;
    const status = pending
        ? "extraction queued — text will appear when OCR / a11y finishes"
        : !text
          ? frame.ocr_sec != null
              ? `OCR ran ${frame.ocr_sec.toFixed(1)}s (${frame.ocr_engine ?? "engine"}) — read nothing`
              : "a11y tree was empty · OCR not invoked"
          : null;
    return (
        <div className="relative rounded-md border border-line bg-surface-2 p-3 text-xs text-dim">
            {text || (pending ? "Extracting text…" : "No text captured for this frame.")}
            {status && (
                <div className="mt-1.5 border-t border-line pt-1.5 text-[10px] text-faint">
                    {status}
                </div>
            )}
            <button
                type="button"
                onClick={() => {
                    try {
                        void navigator.clipboard.writeText(text);
                        setCopied(true);
                        window.setTimeout(() => setCopied(false), 1200);
                    } catch {
                        /* clipboard unavailable */
                    }
                }}
                disabled={!text}
                className="absolute top-1.5 right-1.5 rounded-sm border border-line bg-surface px-2 py-0.5 font-mono text-[10px] text-dim transition-colors hover:border-primary hover:text-foreground disabled:opacity-40"
            >
                {copied ? "copied" : "copy"}
            </button>
        </div>
    );
}