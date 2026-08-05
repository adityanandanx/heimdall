import { Fragment } from "react";

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

/** Minimal markdown for pipe output: headings, lists, code fences, bold/inline code. */
export function Markdown({ text, className }: { text: string; className?: string }) {
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
                    <pre
                        key={`pre-${key++}`}
                        className="my-1 overflow-x-auto rounded-lg border border-line bg-black/40 p-2 font-mono text-[11px] leading-relaxed"
                    >
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

    return <div className={className}>{blocks}</div>;
}
