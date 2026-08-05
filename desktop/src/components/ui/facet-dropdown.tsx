import { useEffect, useRef, useState } from "react";
import type { FacetValue } from "@/lib/api";
import { cn } from "@/lib/utils";

interface FacetDropdownProps {
    label: string;
    options: FacetValue[];
    pending?: boolean;
    selected: string[];
    onToggle: (value: string) => void;
    onClear: () => void;
    className?: string;
}

/** Multi-select dropdown of faceted values with counts (#59). Closes on
 * outside click; results are served by the parent's query cache (scoped),
 * so opening never waits for a fetch. While the current scope's counts are
 * still loading we hold the empty state, so "No {label}s." only appears for
 * a genuinely empty response (never for an in-flight request). */
export function FacetDropdown({
    label,
    options,
    pending = false,
    selected,
    onToggle,
    onClear,
    className,
}: FacetDropdownProps) {
    const [open, setOpen] = useState(false);
    const ref = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!open) return;
        const onDown = (e: MouseEvent) => {
            if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
        };
        document.addEventListener("mousedown", onDown);
        return () => document.removeEventListener("mousedown", onDown);
    }, [open]);

    return (
        <div ref={ref} className="relative">
            <button
                type="button"
                aria-label={label}
                aria-expanded={open}
                onClick={() => setOpen((v) => !v)}
                className={cn(
                    "rounded-md border border-line bg-surface px-2 py-1 text-[11px] text-dim outline-none focus:border-primary",
                    selected.length > 0 && "border-primary/40 text-primary",
                    open && "border-primary",
                    className,
                )}
            >
                {label}
                {selected.length > 0 && <span aria-hidden className="ml-1">· {selected.length}</span>}
                <span aria-hidden className="ml-1 opacity-60">▾</span>
            </button>

            {open && (
                <div className="absolute top-full left-0 z-20 mt-1 max-h-64 w-60 overflow-y-auto rounded-md border border-line bg-surface shadow-xl">
                    {pending && options.length === 0 ? (
                        <p className="px-2 py-1.5 text-[11px] text-faint">loading…</p>
                    ) : options.length === 0 ? (
                        <p className="px-2 py-1.5 text-[11px] text-faint">No {label}s.</p>
                    ) : null}
                    {options.map((option) => {
                        const checked = selected.includes(option.value);
                        return (
                            <label
                                key={option.value}
                                className="flex cursor-pointer items-center gap-2 px-2 py-1 text-[11px] hover:bg-primary/5"
                            >
                                <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={() => onToggle(option.value)}
                                    aria-label={`${label} ${option.value}`}
                                />
                                <span className="min-w-0 truncate">{option.value}</span>
                                <span className="ml-auto shrink-0 font-mono text-[10px] text-faint">
                                    · {option.count}
                                </span>
                            </label>
                        );
                    })}
                    {selected.length > 0 && (
                        <button
                            type="button"
                            onClick={onClear}
                            className="w-full border-t border-line px-2 py-1.5 text-[10px] text-primary hover:bg-primary/5"
                        >
                            clear
                        </button>
                    )}
                </div>
            )}
        </div>
    );
}