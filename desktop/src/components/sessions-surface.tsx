import { useMemo, useState } from "react";
import { ExternalLink } from "lucide-react";
import { formatTime, relTime } from "@/lib/format";
import { fmtDur, playerColor, sessionWatchedSec } from "@/lib/timeline";
import {
    cueTimeFmt,
    groupSessionsBySource,
    isYoutubeUrl,
    unifiedCues,
    youtubeUrlAt,
    type CueSegment,
    type VideoGroup,
} from "@/lib/watch-sessions";
import { useRecentSessions } from "@/hooks/use-day-browser";
import { openExternal } from "@/lib/open";
import { AppChip } from "@/components/app-chip";
import { cn } from "@/lib/utils";

interface SessionsSurfaceProps {
    baseUrl: string;
}

export function SessionsSurface({ baseUrl }: SessionsSurfaceProps) {
    const { data, isLoading } = useRecentSessions(baseUrl, 7);

    const groups = useMemo(() => groupSessionsBySource(data ?? []), [data]);
    const [selectedKey, setSelectedKey] = useState<string | null>(null);

    const selected =
        groups.flatMap((g) => g.videos).find((v) => v.key === selectedKey) ??
        groups[0]?.videos[0] ??
        null;

    const openVideo = (v: VideoGroup) => {
        if (v.openUrl) void openExternal(v.openUrl);
    };

    return (
        <div className="flex h-full flex-col gap-4 p-7">
            <div>
                <div className="mb-0.5 text-[26px] font-extrabold tracking-tight">Sessions</div>
                <div className="mb-3 text-xs text-faint">
                    Watch sessions from the last 7 days — select a video to see its details.
                </div>
            </div>

            {isLoading ? (
                <p className="text-xs text-dim">loading…</p>
            ) : (
                <div className="flex min-h-0 flex-1 gap-4">
                    <div className="flex min-w-0 flex-1 flex-col gap-5 overflow-y-auto pr-1">
                        {groups.map((g) => (
                            <section key={g.label} className="flex flex-col gap-2" aria-label={g.label}>
                                <div className="flex items-center gap-2 text-[10px] font-semibold tracking-[0.12em] text-faint uppercase">
                                    {g.label}
                                    <span className="rounded-full border border-line px-1.5 py-px text-[9px] font-normal tracking-normal text-dim">
                                        {g.videos.length} {g.videos.length === 1 ? "video" : "videos"}
                                    </span>
                                </div>
                                {g.videos.map((v) => (
                                    <VideoCard
                                        key={v.key}
                                        video={v}
                                        selected={selected?.key === v.key}
                                        onSelect={() => setSelectedKey(v.key)}
                                        onOpen={() => openVideo(v)}
                                    />
                                ))}
                            </section>
                        ))}
                        {groups.length === 0 && (
                            <p className="text-xs text-dim">No watch sessions recorded yet.</p>
                        )}
                    </div>

                    <div className="flex w-[340px] shrink-0 flex-col overflow-y-auto rounded-lg border border-line bg-surface">
                        {selected && (
                            <VideoDetails video={selected} onOpen={() => openVideo(selected)} />
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}

function VideoCard({
    video: v,
    selected,
    onSelect,
    onOpen,
}: {
    video: VideoGroup;
    selected: boolean;
    onSelect: () => void;
    onOpen: () => void;
}) {
    const onKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onSelect();
        }
    };

    return (
        <div
            role="button"
            tabIndex={0}
            aria-label={`${v.title} — view details`}
            aria-pressed={selected}
            onClick={onSelect}
            onKeyDown={onKeyDown}
            className={cn(
                "rounded-md border bg-surface px-3.5 py-2.5",
                selected ? "border-primary" : "border-line hover:border-primary",
            )}
        >
            <div className="flex min-w-0 items-center gap-2">
                <span className="truncate text-xs font-medium">{v.title}</span>
                {v.isLive && (
                    <span className="flex shrink-0 items-center gap-1 rounded-full border border-danger/40 px-1.5 py-px text-[9px] text-danger">
                        <span className="h-1 w-1 rounded-full bg-danger" /> LIVE
                    </span>
                )}
                <span className="ml-auto flex shrink-0 items-center gap-1">
                    {v.players.map((p) => (
                        <AppChip key={p} label={p} color={playerColor(p)} />
                    ))}
                    <button
                        type="button"
                        aria-label={`open video ${v.title}`}
                        disabled={!v.openUrl}
                        onClick={(e) => {
                            e.stopPropagation();
                            onOpen();
                        }}
                        className="flex items-center gap-0.5 rounded-full border border-line px-1.5 py-px text-[9px] text-dim transition-colors enabled:hover:border-primary enabled:hover:text-primary disabled:opacity-40"
                    >
                        <ExternalLink className="h-2.5 w-2.5" />
                        open
                    </button>
                </span>
            </div>

            <div className="mt-1.5 text-[10px] text-faint">
                {v.count} {v.count === 1 ? "session" : "sessions"} · watched {fmtDur(v.watchedSec)}
                {v.coveragePct !== null && <span> · {v.coveragePct}% watched</span>}
                {" · "}last {relTime(v.lastTs)}
                {v.words > 0 && <span> · {v.words.toLocaleString()} words</span>}
            </div>

            {v.lengthUs > 0 ? (
                <div
                    className="relative mt-2 h-1.5 w-full rounded-full bg-surface-2"
                    aria-label={`watch timeline for ${v.title}`}
                >
                    {v.rangesUs.map(([s, e], i) => (
                        <div
                            key={i}
                            className="absolute top-0 h-full rounded-full bg-primary/60"
                            style={{
                                left: `${(s / v.lengthUs) * 100}%`,
                                width: `${((e - s) / v.lengthUs) * 100}%`,
                            }}
                        />
                    ))}
                    {v.lastPosUs !== null &&
                        v.lastPosUs > 0 &&
                        v.lastPosUs <= v.lengthUs && (
                            <div
                                className="absolute top-[-2px] h-[10px] w-[2px] bg-foreground"
                                style={{ left: `${(v.lastPosUs / v.lengthUs) * 100}%` }}
                            />
                        )}
                </div>
            ) : (
                v.isLive && <div className="mt-2 text-[10px] text-faint">live — no timeline</div>
            )}
        </div>
    );
}

function VideoDetails({ video: v, onOpen }: { video: VideoGroup; onOpen: () => void }) {
    return (
        <div role="region" aria-label="video details" className="flex flex-col gap-3 p-4">
            <div className="flex min-w-0 items-start gap-2">
                <span className="min-w-0 text-sm font-semibold break-words">{v.title}</span>
                {v.isLive && (
                    <span className="flex shrink-0 items-center gap-1 rounded-full border border-danger/40 px-1.5 py-px text-[9px] text-danger">
                        <span className="h-1 w-1 rounded-full bg-danger" /> LIVE
                    </span>
                )}
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
                <span className="rounded-full border border-line px-1.5 py-px text-[9px] text-dim">
                    {v.sourceLabel}
                </span>
                {v.players.map((p) => (
                    <AppChip key={p} label={p} color={playerColor(p)} />
                ))}
            </div>

            {v.openUrl && (
                <button
                    type="button"
                    onClick={onOpen}
                    className="flex w-fit items-center gap-1.5 rounded-md border border-primary px-2.5 py-1.5 text-[11px] font-medium text-primary transition-colors hover:bg-primary hover:text-white"
                >
                    <ExternalLink className="h-3 w-3" />
                    Open video
                </button>
            )}

            <dl className="grid grid-cols-2 gap-2 text-[10px]">
                <div className="rounded-md border border-line px-2 py-1.5">
                    <dt className="text-faint">Sessions</dt>
                    <dd className="mt-0.5 font-medium">{v.count}</dd>
                </div>
                <div className="rounded-md border border-line px-2 py-1.5">
                    <dt className="text-faint">Watched</dt>
                    <dd className="mt-0.5 font-medium">{fmtDur(v.watchedSec)}</dd>
                </div>
                <div className="rounded-md border border-line px-2 py-1.5">
                    <dt className="text-faint">Coverage</dt>
                    <dd className="mt-0.5 font-medium">{v.coveragePct !== null ? `${v.coveragePct}%` : "—"}</dd>
                </div>
                <div className="rounded-md border border-line px-2 py-1.5">
                    <dt className="text-faint">Transcript</dt>
                    <dd className="mt-0.5 font-medium">{v.words > 0 ? `${v.words.toLocaleString()} words` : "—"}</dd>
                </div>
            </dl>

            <div className="text-[10px] text-faint">last {relTime(v.lastTs)}</div>

            {v.lengthUs > 0 && (
                <div
                    className="relative h-2 w-full rounded-full bg-surface-2"
                    aria-label={`watch timeline for ${v.title}`}
                >
                    {v.rangesUs.map(([s, e], i) => (
                        <div
                            key={i}
                            className="absolute top-0 h-full rounded-full bg-primary/60"
                            style={{
                                left: `${(s / v.lengthUs) * 100}%`,
                                width: `${((e - s) / v.lengthUs) * 100}%`,
                            }}
                        />
                    ))}
                    {v.lastPosUs !== null &&
                        v.lastPosUs > 0 &&
                        v.lastPosUs <= v.lengthUs && (
                            <div
                                className="absolute top-[-2px] h-[12px] w-[2px] bg-foreground"
                                style={{ left: `${(v.lastPosUs / v.lengthUs) * 100}%` }}
                            />
                        )}
                </div>
            )}

            <div className="mt-1 text-[10px] font-semibold tracking-[0.12em] text-faint uppercase">
                Sessions
            </div>
            <ul className="flex flex-col gap-2">
                {v.sessions.map((s) => (
                    <li key={s.id} className="rounded-md border border-line px-2.5 py-2">
                        <div className="flex items-center justify-between gap-2">
                            <span className="text-[10px] text-dim">{formatTime(s.ts_start)}</span>
                            {s.live === 1 && (
                                <span className="flex items-center gap-1 text-[9px] text-danger">
                                    <span className="h-1 w-1 rounded-full bg-danger" /> LIVE
                                </span>
                            )}
                            <span className="text-[10px] text-dim">
                                watched {fmtDur(sessionWatchedSec(s))}
                            </span>
                        </div>
                    </li>
                ))}
            </ul>

            <div className="mt-1 text-[10px] font-semibold tracking-[0.12em] text-faint uppercase">
                Transcript
            </div>
            <Transcript cues={unifiedCues(v.sessions)} text={v.sessions.map((s) => s.transcript ?? "").filter(Boolean).join(" ")} seekUrl={isYoutubeUrl(v.openUrl) ? v.openUrl : null} />
        </div>
    );
}

function Transcript({
    cues,
    text,
    seekUrl,
}: {
    cues: CueSegment[];
    text: string;
    seekUrl: string | null;
}) {
    if (cues.length > 0) {
        return (
            <ol className="flex flex-col rounded-md border border-line">
                {cues.map((c, i) =>
                    seekUrl ? (
                        <li key={i} className="border-b border-line last:border-b-0">
                            <button
                                type="button"
                                aria-label={`open ${c.text} at ${cueTimeFmt(c.startMs)}`}
                                onClick={() => void openExternal(youtubeUrlAt(seekUrl, c.startMs))}
                                className="flex w-full items-start gap-2 px-2.5 py-1.5 text-left text-[10px] text-dim transition-colors hover:bg-surface-2 hover:text-foreground"
                            >
                                <span className="shrink-0 font-mono text-faint">
                                    {cueTimeFmt(c.startMs)}
                                </span>
                                <span className="min-w-0 break-words">{c.text}</span>
                            </button>
                        </li>
                    ) : (
                        <li
                            key={i}
                            className="flex items-start gap-2 border-b border-line px-2.5 py-1.5 text-[10px] text-dim last:border-b-0"
                        >
                            <span className="shrink-0 font-mono text-faint">
                                {cueTimeFmt(c.startMs)}
                            </span>
                            <span className="min-w-0 break-words">{c.text}</span>
                        </li>
                    ),
                )}
            </ol>
        );
    }
    if (text) {
        return (
            <p className="rounded-md border border-line px-2.5 py-2 text-[10px] leading-relaxed text-faint">
                {text}
            </p>
        );
    }
    return <p className="text-[10px] text-faint">No transcript captured.</p>;
}
