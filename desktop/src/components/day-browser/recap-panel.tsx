import { Fragment } from "react";
import type { PipeRunResult } from "@/lib/api";
import { useRunPipe } from "@/hooks/use-day-browser";
import { cn } from "@/lib/utils";

const PIPES = [
    { name: "day-recap", label: "Day recap", hint: "Summarize your day" },
    { name: "time-breakdown", label: "Time breakdown", hint: "Where the day went" },
] as const;

interface RecapPanelProps {
    baseUrl: string;
    day: string;
}

export function RecapPanel({ baseUrl, day }: RecapPanelProps) {
    const { run, isRunning, results, error } = useRunPipe(baseUrl, day);

    return (
        <section className="flex flex-col gap-2 rounded-xl border border-border bg-card p-4">
            <h2 className="text-sm font-semibold">Recaps</h2>
            <div className="flex flex-wrap gap-2">
                {PIPES.map((p) => {
                    const done = results[p.name];
                    return (
                        <button
                            key={p.name}
                            type="button"
                            disabled={isRunning}
                            className={cn(
                                "rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted/50",
                                done && "border-emerald-500/50",
                                isRunning && "cursor-default opacity-60",
                            )}
                            onClick={() => run(p.name)}
                            title={p.hint}
                        >
                            {p.label}
                        </button>
                    );
                })}
                <span className="ml-auto self-center text-[11px] text-muted-foreground tabular-nums">
                    {isRunning ? "running…" : results && countRuns(results) > 0 ? `${countRuns(results)} run` : ""}
                </span>
            </div>

            {error && (
                <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-2 text-xs text-destructive">
                    {error}
                </p>
            )}

            {PIPES.map((p) => {
                const r = results[p.name];
                if (!r) return null;
                return (
                    <div key={p.name} className="flex flex-col gap-1 rounded-lg border border-border bg-muted/40 p-3">
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                            <span className="font-semibold text-foreground">{p.label}</span>
                            <span className="tabular-nums">
                                {r.frame_count} frames · {fmtMs(r.run_ms)}
                            </span>
                            {r.output_path && <span className="truncate text-[10px]">at {r.output_path}</span>}
                        </div>
                        <Markdown text={r.output_markdown} baseUrl={baseUrl} traceUrl={r.trace_url} />
                    </div>
                );
            })}
        </section>
    );
}

function countRuns(results: Record<string, PipeRunResult>): number {
    return Object.keys(results).length;
}

function fmtMs(ms: number): string {
    if (ms < 1000) return `${Math.round(ms)}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
}

function renderInline(s: string): React.ReactNode[] {
    const parts = s.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
    return parts.map((p, i) => {
        if (p.startsWith("**") && p.endsWith("**")) return <strong key={i}>{p.slice(2, -2)}</strong>;
        if (p.startsWith("`") && p.endsWith("`"))
            return (
                <code key={i} className="rounded bg-muted px-1 py-0.5 font-mono text-[0.9em]">
                    {p.slice(1, -1)}
                </code>
            );
        return <Fragment key={i}>{p}</Fragment>;
    });
}

interface MarkdownProps {
    text: string;
    baseUrl: string;
    traceUrl: string | null;
}

function Markdown({ text, traceUrl }: MarkdownProps) {
    const lines = text.split("\n");
    const blocks: React.ReactNode[] = [];
    const list: string[] = [];
    let inCode = false;
    let code: string[] = [];
    let key = 0;

    function flushList() {
        if (!list.length) return;
        blocks.push(
            <ul key={`ul-${key++}`} className="my-1 list-disc space-y-0.5 pl-5">
                {list.map((li, i) => (
                    <li key={i}>{renderInline(li)}</li>
                ))}
            </ul>,
        );
        list.length = 0;
    }

    for (const line of lines) {
        const t = line.trim();
        if (inCode) {
            if (t === "```") {
                blocks.push(
                    <pre key={`pre-${key++}`} className="my-1 overflow-x-auto rounded-lg border border-border bg-black/40 p-2 font-mono text-[11px] leading-relaxed">
                        {code.join("\n")}
                    </pre>,
                );
                code = [];
                inCode = false;
            } else {
                code.push(line);
            }
            continue;
        }
        if (t === "```") {
            flushList();
            inCode = true;
            code = [];
            continue;
        }
        if (t.startsWith("- ") || t.startsWith("* ")) {
            list.push(t.slice(2));
            continue;
        }
        if (/^#{1,3}\s/.test(t)) {
            flushList();
            const level = /^#{1,3}/.exec(t)![0].length;
            const cls = level === 1 ? "text-sm font-bold" : "text-[13px] font-semibold";
            blocks.push(
                <p key={`h-${key++}`} className={cls}>
                    {renderInline(t.replace(/^#{1,3}\s/, ""))}
                </p>,
            );
            continue;
        }
        flushList();
        if (!t) continue;
        blocks.push(<p key={`p-${key++}`} className="text-[13px] leading-relaxed">{renderInline(t)}</p>);
    }
    flushList();

    return (
        <div className="flex flex-col">
            {blocks}
            {traceUrl && (
                <p className="mt-1 truncate text-[11px] text-muted-foreground">
                    trace: <span className="font-mono">{traceUrl}</span>
                </p>
            )}
        </div>
    );
}