import { frameImageUrl, type Frame } from "@/lib/api";
import { formatTimeS } from "@/lib/format";
import { srcOf } from "@/lib/frames";
import { cn } from "@/lib/utils";

interface FramePreviewProps {
    baseUrl: string;
    frame: Frame;
    hits: Set<number> | null;
    className?: string;
}

export function FramePreview({ baseUrl, frame, hits, className }: FramePreviewProps) {
    const src = srcOf(frame);
    const hit = hits?.has(frame.id) ?? false;
    return (
        <div className={cn("flex flex-col gap-3", className)}>
            <div className="relative aspect-video overflow-hidden rounded-xl border border-border bg-black">
                <img
                    src={frameImageUrl(baseUrl, frame.id)}
                    alt={frame.window_class}
                    className="h-full w-full object-contain"
                    loading="lazy"
                />
                <span className="absolute bottom-2 left-2 rounded-full bg-black/70 px-2 py-0.5 text-[11px] font-bold text-white tabular-nums">
                    {formatTimeS(frame.ts)}
                </span>
                {hit && (
                    <span className="absolute top-2 right-2 rounded-full bg-amber-400/90 px-2 py-0.5 text-[10px] font-bold text-black">
                        search hit
                    </span>
                )}
            </div>
            <div className="min-w-0">
                <p className="truncate text-sm font-semibold">{frame.window_class}</p>
                <p className="truncate text-xs text-muted-foreground">
                    {frame.window_title || "no title"}
                </p>
            </div>
            <div className="flex gap-1.5">
                <span
                    className={cn(
                        "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase",
                        src === "a11y" && "bg-emerald-500/15 text-emerald-600",
                        src === "ocr" && "bg-sky-500/15 text-sky-600",
                        src === "none" && "bg-muted text-muted-foreground",
                    )}
                >
                    {src === "a11y" ? "a11y" : src === "ocr" ? "ocr" : "no text"}
                </span>
                <span
                    className={cn(
                        "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase",
                        frame.fullscreen ? "bg-purple-500/15 text-purple-600" : "bg-muted text-muted-foreground",
                    )}
                >
                    {frame.fullscreen ? "fullscreen" : "windowed"}
                </span>
                {frame.workspace != null && (
                    <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold text-muted-foreground">
                        ws {frame.workspace}
                    </span>
                )}
            </div>
            <div className="max-h-24 overflow-y-auto rounded-lg border border-border bg-muted/40 p-2 text-xs text-muted-foreground">
                {frame.a11y_text || frame.ocr_text || "No captured text for this frame."}
            </div>
        </div>
    );
}