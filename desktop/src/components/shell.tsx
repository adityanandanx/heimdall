import { useEffect, useRef } from "react";
import { surfaces, type SurfaceId } from "@/lib/surfaces";
import { cn } from "@/lib/utils";

interface ShellProps {
    surface: SurfaceId;
    onSurface: (s: SurfaceId) => void;
    onGlobalSearch: () => void;
    online: boolean;
    children: React.ReactNode;
}

export function Shell({ surface, onSurface, onGlobalSearch, online, children }: ShellProps) {
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
                e.preventDefault();
                onGlobalSearch();
            }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [onGlobalSearch]);

    return (
        <div className="flex h-screen">
            <aside className="flex w-[210px] shrink-0 flex-col overflow-hidden border-r border-line bg-surface">
                <div className="flex items-center gap-2.5 border-b border-line px-3.5 pt-3.5 pb-3">
                    <div className="flex size-6.5 shrink-0 items-center justify-center rounded-lg bg-primary text-[13px] font-extrabold text-primary-foreground">
                        H
                    </div>
                    <div className="text-sm font-extrabold tracking-wide whitespace-nowrap">
                        HEIMDALL
                        <span
                            className={cn(
                                "ml-1.5 inline-block size-2 rounded-full",
                                online ? "bg-ok shadow-[0_0_8px_var(--ok)]" : "bg-faint",
                            )}
                        />
                    </div>
                </div>

                <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto p-2" aria-label="views">
                    {(["browse", "system"] as const).map((section) => (
                        <div key={section}>
                            <div className="px-2.5 pt-3.5 pb-1.5 text-[10px] tracking-[1.2px] uppercase text-faint">
                                {section === "browse" ? "Browse" : "System"}
                            </div>
                            {surfaces
                                .filter((s) => s.section === section)
                                .map((s) => {
                                    const Icon = s.icon;
                                    const active = surface === s.id;
                                    return (
                                        <button
                                            key={s.id}
                                            type="button"
                                            onClick={() => onSurface(s.id)}
                                            className={cn(
                                                "flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left whitespace-nowrap transition-colors",
                                                active
                                                    ? "bg-accent/12 text-foreground"
                                                    : "text-dim hover:bg-surface-2 hover:text-foreground",
                                            )}
                                            aria-current={active ? "page" : undefined}
                                        >
                                            <Icon
                                                className={cn(
                                                    "size-4 shrink-0",
                                                    active && "text-primary",
                                                )}
                                            />
                                            <span>{s.label}</span>
                                        </button>
                                    );
                                })}
                        </div>
                    ))}
                </nav>

                <div className="flex flex-col gap-0.5 border-t border-line p-2">
                    <div className="flex items-center gap-2 px-2.5 py-1.5 text-[11px] text-faint whitespace-nowrap">
                        <kbd>⌘K</kbd> search anywhere
                    </div>
                </div>
            </aside>

            <div className="flex min-w-0 flex-1 flex-col">
                {!online && (
                    <div
                        className="flex items-center gap-3 border-b border-danger/35 bg-danger/10 px-5 py-2.5 text-xs text-danger"
                        data-testid="offline-banner"
                    >
                        <b>Server unreachable.</b>
                        <span>
                            Start it with <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono">heimdall serve</code> —
                            reconnects automatically.
                        </span>
                    </div>
                )}
                <div className="min-h-0 flex-1">{children}</div>
            </div>
        </div>
    );
}

export function useFocusOnMount<T extends HTMLElement>(active: boolean) {
    const ref = useRef<T>(null);
    useEffect(() => {
        if (active) ref.current?.focus();
    }, [active]);
    return ref;
}
