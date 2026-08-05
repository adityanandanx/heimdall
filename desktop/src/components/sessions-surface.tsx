import { useMemo } from "react";
import { ChevronRight } from "lucide-react";
import type { Session } from "@/lib/api";
import { relTime } from "@/lib/format";
import { fmtDur } from "@/lib/timeline";
import { useRecentSessions } from "@/hooks/use-day-browser";
import { cn } from "@/lib/utils";

interface SessionsSurfaceProps {
    baseUrl: string;
    onJump: (s: Session) => void;
}

export function SessionsSurface({ baseUrl, onJump }: SessionsSurfaceProps) {
    const { data, isLoading } = useRecentSessions(baseUrl, 7);

    const groups = useMemo(() => {
        if (!data) return [];
        const out: Array<{ day: string; items: Session[] }> = [];
        for (const s of data) {
            const day = s.ts_start.slice(0, 10);
            const last = out[out.length - 1];
            if (last?.day === day) last.items.push(s);
            else out.push({ day, items: [s] });
        }
        return out;
    }, [data]);

    return (
        <div className="flex h-full flex-col gap-4 overflow-y-auto p-7">
            <div>
                <div className="mb-0.5 text-[26px] font-extrabold tracking-tight">Sessions</div>
                <div className="mb-3 text-xs text-faint">
                    Watch sessions from the last 7 days — click to jump straight to that moment.
                </div>
            </div>

            {isLoading && <p className="text-xs text-dim">loading…</p>}

            <div className="flex max-w-[680px] flex-col gap-5">
                {groups.map((g) => (
                    <div key={g.day} className="flex flex-col gap-2">
                        <div className="text-[10px] font-semibold tracking-[0.12em] text-faint uppercase">
                            {g.day}
                        </div>
                        {g.items.map((s) => (
                            <SessionRow key={s.id} session={s} onJump={onJump} />
                        ))}
                    </div>
                ))}
                {!isLoading && groups.length === 0 && (
                    <p className="text-xs text-dim">No watch sessions recorded yet.</p>
                )}
            </div>
        </div>
    );
}

function SessionRow({ session: s, onJump }: { session: Session; onJump: (s: Session) => void }) {
    const duration = useMemo(() => {
        const start = new Date(s.ts_start).getTime();
        const end = s.ts_end ? new Date(s.ts_end).getTime() : Date.now();
        return fmtDur(Math.max(0, end - start) / 1000);
    }, [s.ts_start, s.ts_end]);

    const words = useMemo(() => s.transcript?.split(/\s+/).length ?? 0, [s.transcript]);

    return (
        <button
            type="button"
            onClick={() => onJump(s)}
            className="group flex items-center gap-3 rounded-md border border-line bg-surface px-3.5 py-2.5 text-left transition-colors hover:border-primary"
        >
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface-2 text-[11px] text-dim">
                ▷
            </div>
            <div className="flex min-w-0 flex-col">
                <div className="flex min-w-0 items-center gap-2">
                    <span className="truncate text-xs font-medium">
                        {s.media_title ?? s.media_source ?? "untitled"}
                    </span>
                    <span className="shrink-0 rounded-full border border-line px-1.5 py-px text-[9px] text-dim">
                        {s.player}
                    </span>
                    {s.live === 1 && (
                        <span className="flex shrink-0 items-center gap-1 rounded-full border border-danger/40 px-1.5 py-px text-[9px] text-danger">
                            <span className="h-1 w-1 rounded-full bg-danger" /> LIVE
                        </span>
                    )}
                </div>
                <div className="mt-0.5 text-[10px] text-faint">
                    {relTime(s.ts_start)} · watched {duration}
                    {words > 0 && <span className="text-faint"> · {words.toLocaleString()} words</span>}
                </div>
            </div>
            <ChevronRight
                className={cn(
                    "ml-auto h-4 w-4 shrink-0 text-faint transition-colors group-hover:text-primary",
                )}
            />
        </button>
    );
}
