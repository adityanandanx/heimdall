import type { ReactNode } from "react";
import { useState } from "react";
import { Activity, Database, MonitorPlay, Pause, Play, Radio, Sparkles, Tv } from "lucide-react";
import type { ServerStatus } from "@/lib/api";
import { formatBytes, formatTime, formatUptime } from "@/lib/format";
import { fmtDur } from "@/lib/timeline";
import { useHealth, useStatus } from "@/hooks/use-day-browser";
import { writeSetting } from "@/lib/api";
import { cn } from "@/lib/utils";

interface StatusSurfaceProps {
    baseUrl: string;
}

const GRID = "grid grid-cols-12 gap-3";
const S6 = "col-span-6 max-xl:col-span-12";
const S3 = "col-span-3 max-lg:col-span-6 max-md:col-span-12";
const S4 = "col-span-4 max-lg:col-span-6 max-md:col-span-12";

export function StatusSurface({ baseUrl }: StatusSurfaceProps) {
    const health = useHealth(baseUrl);
    const status = useStatus(baseUrl);
    const online = !!health.data;

    const st = status.data;
    const captureAlive = !!st?.capture.alive;
    const llmReachable = !!st?.llama.reachable;
    const lastEvent = st?.capture.last_event_ts ?? null;
    const paused = !!st?.capture.paused;

    return (
        <div className="flex h-full flex-col gap-4 overflow-y-auto p-7">
            <div>
                <div className="mb-0.5 text-[26px] font-extrabold tracking-tight">Status</div>
                <div className="mb-3 text-xs text-faint">
                    Is everything in order? A glanceable dashboard of the heimdall server.
                </div>
            </div>

            <div className={GRID}>
                <Bento span={S6} icon={<Activity className="h-4 w-4" />} label="Server">
                    <div className="mb-1.5 flex items-center gap-2">
                        <LiveDot alive={online} />
                        <span className={cn("text-lg font-bold", online ? "text-ok" : "text-danger")}>
                            {online ? "online" : "offline"}
                        </span>
                        <span className="ml-auto font-mono text-[11px] text-dim">
                            {safeHost(baseUrl)}
                        </span>
                    </div>
                    <MetaRows
                        rows={[
                            ["version", health.data?.version ?? "—"],
                            ["uptime", formatUptime(health.data?.uptime_s ?? -1)],
                            ["db", formatBytes(st?.db.size_bytes ?? 0)],
                        ]}
                    />
                </Bento>

                <Bento span={S3} icon={<Tv className="h-4 w-4" />} label="Capture">
                    <div className="mb-1.5 flex items-center gap-2">
                        <LiveDot alive={captureAlive} />
                        <span className={cn("text-lg font-bold", captureAlive ? "text-ok" : "text-danger")}>
                            {paused ? "paused" : captureAlive ? "running" : "not running"}
                        </span>
                        <PauseButton paused={paused} baseUrl={baseUrl} />
                    </div>
                    <MetaRows
                        rows={[
                            ["extraction", st?.capture.extraction ?? "—"],
                            ["last event", lastEvent ? formatTime(lastEvent) ?? "—" : "never"],
                            ["frames today", String(st?.db.frames_today ?? 0)],
                        ]}
                    />
                    {st && st.capture.ocr_engine && (
                        <EngineHint engine={st.capture.ocr_engine} />
                    )}
                </Bento>

                <Bento span={S3} icon={<Sparkles className="h-4 w-4" />} label="LLM">
                    <div className="mb-1.5 flex items-center gap-2">
                        <LiveDot alive={llmReachable} />
                        <span className={cn("text-lg font-bold", llmReachable ? "text-ok" : "text-danger")}>
                            {llmReachable ? "reachable" : "unreachable"}
                        </span>
                    </div>
                    <MetaRows
                        rows={[
                            ["day recap", st ? lastRun(st, "day-recap") : "—"],
                            ["breakdown", st ? lastRun(st, "breakdown") : "—"],
                        ]}
                    />
                </Bento>

                <Bento span={S4} icon={<MonitorPlay className="h-4 w-4" />} label="Players">
                    {st && st.capture.players.length > 0 ? (
                        <div className="flex flex-col gap-1.5">
                            {st.capture.players.map((p) => (
                                <div key={p.name} className="flex items-center gap-2 text-[11px]">
                                    <span className="min-w-0 truncate text-dim">{p.name}</span>
                                    <PlayerStatus status={p.status} />
                                </div>
                            ))}
                        </div>
                    ) : (
                        <p className="text-xs text-faint">none watched yet</p>
                    )}
                </Bento>

                <Bento span={S4} icon={<Radio className="h-4 w-4" />} label="Last session">
                    {st?.media.last_session ? (
                        <div className="flex min-w-0 flex-col gap-1.5">
                            <span className="truncate text-[13px] font-semibold">
                                {st.media.last_session.media_title ?? "untitled"}
                            </span>
                            <span className="text-[11px] text-dim">
                                on {st.media.last_session.player} · ended{" "}
                                {formatTime(st.media.last_session.ts_end) ?? "—"}
                            </span>
                            <span className="text-[10px] text-faint">
                                {fmtDur(
                                    Math.max(
                                        0,
                                        ((st.media.last_session.ts_end ?? st.media.last_session.ts_start) -
                                            st.media.last_session.ts_start) /
                                            1000,
                                    ),
                                )}{" "}
                                watched
                            </span>
                        </div>
                    ) : (
                        <p className="text-xs text-faint">no sessions yet</p>
                    )}
                </Bento>

                <Bento span={S4} icon={<Database className="h-4 w-4" />} label="Data">
                    <div className="mb-1.5 text-lg font-bold tabular-nums">
                        {formatBytes(st?.db.size_bytes ?? 0)}
                    </div>
                    <MetaRows
                        rows={[
                            ["frames today", String(st?.db.frames_today ?? 0)],
                            ["last capture", lastEvent ? formatTime(lastEvent) ?? "—" : "never"],
                            ["asr queued", String(st?.asr.queued ?? 0)],
                        ]}
                    />
                </Bento>
            </div>
        </div>
    );
}

function safeHost(baseUrl: string): string {
    try {
        return new URL(baseUrl).host;
    } catch {
        return baseUrl;
    }
}

function lastRun(st: ServerStatus, name: string): string {
    const ts = st.pipes.last_runs?.[name] ?? null;
    return ts ? `ran ${formatTime(ts) ?? "—"}` : "ready";
}

function LiveDot({ alive }: { alive: boolean }) {
    return (
        <span
            className={cn(
                "h-2 w-2 rounded-full",
                alive ? "bg-ok shadow-[0_0_6px_rgba(152,195,121,0.8)]" : "bg-danger",
            )}
        />
    );
}

function MetaRows({ rows }: { rows: Array<[string, string]> }) {
    return (
        <div className="flex flex-col gap-1">
            {rows.map(([k, v]) => (
                <div key={k} className="flex items-baseline gap-2 text-[11px]">
                    <span className="shrink-0 text-faint">{k}</span>
                    <span className="ml-auto truncate font-mono text-dim">{v}</span>
                </div>
            ))}
        </div>
    );
}

/** One-tap pause/resume for capture (writes capture.paused live, #76). */
function PauseButton({ paused, baseUrl }: { paused: boolean; baseUrl: string }) {
    const [state, setState] = useState<"idle" | "saving" | "error">("idle");

    const flip = async () => {
        setState("saving");
        try {
            await writeSetting(baseUrl, "capture.paused", !paused);
            setState("idle");
        } catch {
            setState("error");
        }
    };

    return (
        <button
            type="button"
            onClick={flip}
            disabled={state === "saving"}
            title={paused ? "Resume capture" : "Pause capture (stops storing new frames)"}
            aria-label={paused ? "resume capture" : "pause capture"}
            className={cn(
                "ml-auto flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] transition-colors",
                paused
                    ? "border-ok/50 bg-ok/10 text-ok hover:bg-ok/20"
                    : "border-line text-dim hover:border-warn/50 hover:text-warn",
            )}
        >
            {state === "error" ? (
                <span className="text-danger">write failed</span>
            ) : paused ? (
                <>
                    <Play className="h-2.5 w-2.5" /> resume
                </>
            ) : (
                <>
                    <Pause className="h-2.5 w-2.5" /> pause
                </>
            )}
        </button>
    );
}

/** Amber hint when the daemon fell back to a different engine than asked. */
function EngineHint({ engine }: { engine: { configured: string; active: string } }) {
    if (engine.active === engine.configured) return null;
    return (
        <p className="mt-2 flex items-start gap-1.5 rounded-md border border-warn/40 bg-warn/10 px-2 py-1.5 text-[10px] leading-snug text-warn">
            <Sparkles className="mt-px h-3 w-3 shrink-0" />
            <span>
                {engine.configured} requested, running <b>{engine.active}</b> (fallback)
            </span>
        </p>
    );
}

function PlayerStatus({ status }: { status: string }) {    const color =
        status === "playing"
            ? "bg-ok"
            : status === "paused"
              ? "bg-warn"
              : "bg-faint";
    return (
        <span className="ml-auto flex shrink-0 items-center gap-1 rounded-full border border-line px-1.5 py-px text-[9px] text-dim">
            <span className={cn("h-1 w-1 rounded-full", color)} />
            {status}
        </span>
    );
}

function Bento({
    span,
    icon,
    label,
    children,
}: {
    span: string;
    icon: ReactNode;
    label: string;
    children: ReactNode;
}) {
    return (
        <div className={cn("rounded-lg border border-line bg-surface p-4", span)}>
            <div className="mb-2.5 flex items-center gap-2 text-[11px] font-semibold tracking-wide text-dim uppercase">
                {icon}
                {label}
            </div>
            {children}
        </div>
    );
}
