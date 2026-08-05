import { Fragment, type RefObject, useRef } from "react";
import type { QueryToken } from "@/lib/query-language";
import { cn } from "@/lib/utils";

interface GlowInputProps {
    value: string;
    tokens: QueryToken[];
    onChange: (value: string) => void;
    placeholder: string;
    ariaLabel: string;
    inputRef?: RefObject<HTMLInputElement | null>;
    className?: string;
}

/** Search box with a syntax-glow overlay (#60): recognized query tokens are
 * underlined/colored by a transparent mirror layer while the input itself
 * stays a plain, fully editable text field. The mirror scrolls in lockstep
 * with the input. */
export function GlowInput({
    value,
    tokens,
    onChange,
    placeholder,
    ariaLabel,
    inputRef,
    className,
}: GlowInputProps) {
    const mirrorRef = useRef<HTMLDivElement>(null);
    const ownRef = useRef<HTMLInputElement>(null);
    const ref = inputRef ?? ownRef;

    const onScroll = () => {
        if (mirrorRef.current && ref.current) {
            mirrorRef.current.scrollLeft = ref.current.scrollLeft;
        }
    };

    return (
        <div className={cn("relative", className)}>
            <div
                ref={mirrorRef}
                aria-hidden
                className="pointer-events-none absolute inset-0 flex items-center overflow-hidden px-10 pr-14 text-sm whitespace-pre text-foreground"
            >
                {renderTokens(value, tokens)}
            </div>
            <input
                ref={ref}
                value={value}
                onChange={(e) => onChange(e.currentTarget.value)}
                onScroll={onScroll}
                placeholder={placeholder}
                aria-label={ariaLabel}
                className="relative w-full rounded-lg border border-line bg-surface py-3 pr-14 pl-10 text-sm caret-foreground outline-none transition-shadow placeholder:text-faint selection:bg-primary/25 focus:border-primary focus:shadow-[0_0_0_3px_rgba(97,175,239,0.18)]"
            />
        </div>
    );
}

function renderTokens(value: string, tokens: QueryToken[]): React.ReactNode {
    const nodes: React.ReactNode[] = [];
    let cursor = 0;
    for (const t of tokens) {
        if (t.start > cursor) {
            nodes.push(<Fragment key={cursor}>{value.slice(cursor, t.start)}</Fragment>);
        }
        nodes.push(
            <span
                key={t.start}
                className={cn(
                    "rounded-sm text-primary underline decoration-primary/60 decoration-1 underline-offset-2",
                    t.negated && "line-through decoration-warn/70",
                )}
            >
                {t.raw}
            </span>,
        );
        cursor = Math.max(cursor, t.end);
    }
    if (cursor < value.length) nodes.push(<Fragment key={cursor}>{value.slice(cursor)}</Fragment>);
    return nodes;
}
