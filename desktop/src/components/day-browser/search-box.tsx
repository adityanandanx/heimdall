import { useRef, useState } from "react";
import { SearchItem } from "@/lib/api";
import { formatTimeS } from "@/lib/format";
import { useSearch } from "@/hooks/use-day-browser";
import { cn } from "@/lib/utils";

interface SearchBoxProps {
    baseUrl: string;
    onPick: (item: SearchItem, allResults: SearchItem[]) => void;
    onClose: () => void;
}

function snippet(stripped: string): string {
    return stripped.length > 220 ? stripped.slice(0, 220) + "…" : stripped;
}

export function SearchBox({ baseUrl, onPick, onClose }: SearchBoxProps) {
    const [q, setQ] = useState("");
    const inputRef = useRef<HTMLInputElement>(null);
    const { data, isFetching } = useSearch(baseUrl, q);
    const open = q.trim().length >= 2;

    return (
        <div
            className="fixed top-4 left-1/2 z-50 w-[min(640px,92vw)] -translate-x-1/2"
            role="dialog"
            aria-label="search"
        >
            <div className="flex items-center gap-2 rounded-xl border border-border bg-card px-3 py-2 shadow-2xl">
                <span className="text-sm text-muted-foreground">⌕</span>
                <input
                    ref={inputRef}
                    autoFocus
                    value={q}
                    placeholder="Search frames & sessions…  (Esc to close)"
                    className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                    onChange={(e) => setQ(e.currentTarget.value)}
                    onKeyDown={(e) => {
                        if (e.key === "Escape") onClose();
                    }}
                />
                {isFetching && <span className="text-[10px] text-muted-foreground">searching…</span>}
            </div>
            {open && (
                <ul className="mt-2 max-h-[60vh] overflow-y-auto rounded-xl border border-border bg-card shadow-2xl">
                    {data && data.length === 0 && (
                        <li className="px-3 py-2 text-xs text-muted-foreground">No matches.</li>
                    )}
                    {data?.map((item) => (
                        <li key={`${item.kind}-${item.id}`}>
                            <button
                                type="button"
                                className="flex w-full flex-col gap-0.5 px-3 py-2 text-left hover:bg-muted/60"
                                onClick={() => {
                                    onPick(item, data ?? []);
                                    onClose();
                                }}
                            >
                                <span className="flex items-center gap-2 text-xs">
                                    <span
                                        className={cn(
                                            "shrink-0 rounded-full px-1.5 py-px text-[9px] font-bold uppercase",
                                            item.kind === "frame"
                                                ? "bg-sky-500/15 text-sky-600"
                                                : "bg-emerald-500/15 text-emerald-600",
                                        )}
                                    >
                                        {item.kind}
                                    </span>
                                    <span className="truncate font-medium">{item.window_class}</span>
                                    {item.window_title && (
                                        <span className="truncate text-muted-foreground">
                                            {item.window_title}
                                        </span>
                                    )}
                                    <span className="ml-auto shrink-0 text-[10px] text-muted-foreground tabular-nums">
                                        {formatTimeS(item.ts)}
                                    </span>
                                </span>
                                <span className="line-clamp-2 text-[11px] leading-relaxed text-muted-foreground">
                                    {snippet(item.snippet.replace(/\*\*/g, ""))}
                                </span>
                            </button>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}