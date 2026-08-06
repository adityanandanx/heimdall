import { useEffect, useMemo, useState } from "react";
import { Check, Clock, Plus, RotateCcw, ShieldOff, Trash2, X } from "lucide-react";
import { DEFAULT_SERVER_URL, ApiError, forgetData, writeSetting } from "@/lib/api";
import {
    useFacets,
    useHealth,
    useInvalidateSettings,
    useSettings,
    useStatus,
} from "@/hooks/use-day-browser";
import { cn } from "@/lib/utils";

interface SettingsSurfaceProps {
    serverUrl: string;
    onServerUrl: (url: string) => void;
    refreshSeconds: number;
    onRefreshSeconds: (s: number) => void;
}

const REFRESH_OPTIONS = [5, 10, 15, 30, 60];

/** The 8 fixed rules categories (mirrors pipes.prompts.BREAKDOWN_CATEGORIES). */
export const RULES_CATEGORIES = [
    "Building projects",
    "Researching",
    "Job applications",
    "YouTube",
    "Movies",
    "Music",
    "DSA",
    "Other",
];

const ENGINES = [
    { id: "auto", label: "Auto", hint: "fastest that works — NPU when available, CPU fallback" },
    { id: "npu", label: "NPU", hint: "lowest power & heat on this machine" },
    { id: "cpu", label: "CPU", hint: "compatible everywhere, slower" },
] as const;

const EXTRACTION_MODES = [
    { id: "auto", label: "Auto", hint: "a11y text when available, else OCR" },
    { id: "a11y", label: "A11y", hint: "accessibility tree only — zero OCR cost" },
    { id: "ocr", label: "OCR", hint: "pixel OCR only — works in blind apps" },
] as const;

const RESOLVERS = [
    { id: "extension", label: "Extension", hint: "chromium extension reports the URL" },
    { id: "cdp", label: "CDP", hint: "browser remote debugging protocol" },
] as const;

const FORGET_CATEGORIES = [
    { id: "frames", label: "Frames", hint: "screen captures + their OCR/a11y text" },
    { id: "sessions", label: "Watch sessions", hint: "what you watched, when" },
    { id: "transcripts", label: "Transcripts", hint: "caption-cache files of those sessions" },
] as const;

export function SettingsSurface({
    serverUrl,
    onServerUrl,
    refreshSeconds,
    onRefreshSeconds,
}: SettingsSurfaceProps) {
    const [urlDraft, setUrlDraft] = useState(serverUrl);
    const [justSaved, setJustSaved] = useState(false);
    const [testState, setTestState] = useState<"idle" | "checking" | "ok" | "fail">("idle");

    useEffect(() => setUrlDraft(serverUrl), [serverUrl]);

    // Live connection check against the *draft* URL.
    const { data: draftHealth, refetch: checkDraft, isFetching } = useHealth(urlDraft);

    const save = () => {
        const url = urlDraft.trim().replace(/\/+$/, "") || DEFAULT_SERVER_URL;
        onServerUrl(url);
        setUrlDraft(url);
        setJustSaved(true);
        window.setTimeout(() => setJustSaved(false), 1500);
    };

    const testConnection = async () => {
        setTestState("checking");
        try {
            const res = await checkDraft();
            setTestState(res.data ? "ok" : "fail");
        } catch {
            setTestState("fail");
        }
    };

    const connected = useHealth(serverUrl).data !== undefined;
    const settings = useSettings(serverUrl);
    const status = useStatus(serverUrl);

    return (
        <div className="flex h-full flex-col gap-4 overflow-y-auto p-7">
            <div>
                <div className="mb-0.5 text-[26px] font-extrabold tracking-tight">Settings</div>
                <div className="mb-3 text-xs text-faint">
                    How the desktop client talks to your heimdall server — and what it captures.
                </div>
            </div>

            <div className="flex max-w-[640px] flex-col gap-5">
                {/* ---- client: connection ---- */}
                <section className="flex flex-col gap-2.5">
                    <div className="flex items-center gap-2">
                        <span className="text-xs font-semibold tracking-wide uppercase">
                            Server URL
                        </span>
                        {justSaved && (
                            <span className="flex items-center gap-1 text-[10px] text-ok">
                                <Check className="h-3 w-3" /> saved
                            </span>
                        )}
                    </div>
                    <div className="flex items-center gap-2">
                        <input
                            value={urlDraft}
                            onChange={(e) => setUrlDraft(e.currentTarget.value)}
                            onKeyDown={(e) => {
                                if (e.key === "Enter") save();
                            }}
                            placeholder={DEFAULT_SERVER_URL}
                            aria-label="server url"
                            className="w-full rounded-lg border border-line bg-surface px-3 py-2 font-mono text-[12px] outline-none transition-shadow focus:border-primary focus:shadow-[0_0_0_3px_rgba(97,175,239,0.18)]"
                        />
                        <button
                            type="button"
                            onClick={save}
                            className="shrink-0 rounded-lg border border-primary/50 bg-primary/10 px-3 py-2 text-[12px] font-medium text-primary transition-colors hover:bg-primary/20"
                        >
                            Save
                        </button>
                    </div>
                    <div className="flex items-center gap-2 text-[11px]">
                        <span
                            className={cn(
                                "flex items-center gap-1.5",
                                connected ? "text-ok" : "text-danger",
                            )}
                            data-testid="settings-connection"
                        >
                            {connected ? (
                                <Check className="h-3 w-3" />
                            ) : (
                                <X className="h-3 w-3" />
                            )}
                            {connected ? "connected" : "not connected"}
                        </span>
                        <button
                            type="button"
                            onClick={testConnection}
                            className="rounded-full border border-line px-2 py-0.5 text-[10px] text-dim transition-colors hover:text-foreground"
                        >
                            {testState === "checking" || isFetching ? "checking…" : "test connection"}
                        </button>
                        {testState === "ok" && <span className="text-[10px] text-ok">reachable</span>}
                        {testState === "fail" && (
                            <span className="text-[10px] text-danger">unreachable</span>
                        )}
                        {draftHealth && draftHealth.status && testState === "idle" && (
                            <span className="text-[10px] text-faint">
                                v{draftHealth.version}
                            </span>
                        )}
                    </div>
                </section>

                <section className="flex flex-col gap-2.5">
                    <span className="text-xs font-semibold tracking-wide uppercase">
                        Status auto-refresh
                    </span>
                    <div className="flex gap-1.5">
                        {REFRESH_OPTIONS.map((s) => (
                            <button
                                key={s}
                                type="button"
                                onClick={() => onRefreshSeconds(s)}
                                className={cn(
                                    "rounded-md border px-2.5 py-1 text-[11px] transition-colors",
                                    refreshSeconds === s
                                        ? "border-primary/50 text-primary"
                                        : "border-line text-dim hover:text-foreground",
                                )}
                            >
                                {s}s
                            </button>
                        ))}
                    </div>
                </section>

                {!connected ? (
                    <p className="text-xs text-faint">
                        Server unreachable — capture settings need a live connection to edit.
                    </p>
                ) : (
                    <>
                        <CaptureSection settings={settings.data?.values} status={status.data} baseUrl={serverUrl} />
                        <ExclusionsSection values={settings.data?.values} baseUrl={serverUrl} />
                        <RulesSection values={settings.data?.values} baseUrl={serverUrl} />
                        <SchedulerSection
                            values={settings.data?.values}
                            scheduler={status.data?.scheduler}
                            baseUrl={serverUrl}
                        />
                        <PassiveSection values={settings.data?.values} baseUrl={serverUrl} />
                        <ForgetSection baseUrl={serverUrl} />
                    </>
                )}
            </div>
        </div>
    );
}

/* ------------------------------------------------------------------ */
/* shared bits                                                          */
/* ------------------------------------------------------------------ */

function SectionTitle({ children, hint }: { children: React.ReactNode; hint?: string }) {
    return (
        <div>
            <span className="text-xs font-semibold tracking-wide uppercase">{children}</span>
            {hint && <p className="mt-1 text-[11px] leading-snug text-faint">{hint}</p>}
        </div>
    );
}

/** One segmented control; optimistic write + "saved ✓" + offline note. */
function Segmented<T extends string>({
    label,
    options,
    value,
    onSelect,
    extra,
}: {
    label: string;
    options: ReadonlyArray<{ id: T; label: string; hint: string }>;
    value: T | undefined;
    onSelect: (id: T) => Promise<void>;
    extra?: React.ReactNode;
}) {
    const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
    const [err, setErr] = useState<string | null>(null);

    const pick = async (id: T) => {
        if (id === value || state === "saving") return;
        setState("saving");
        setErr(null);
        try {
            await onSelect(id);
            setState("saved");
            window.setTimeout(() => setState("idle"), 1500);
        } catch (e) {
            setState("error");
            setErr(e instanceof ApiError ? e.message : "write failed");
        }
    };

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-dim">{label}</span>
                {state === "saved" && (
                    <span className="flex items-center gap-1 text-[10px] text-ok">
                        <Check className="h-3 w-3" /> saved
                    </span>
                )}
                {state === "error" && <span className="text-[10px] text-danger">{err}</span>}
                {extra}
            </div>
            <div className="flex gap-1.5">
                {options.map((o) => (
                    <button
                        key={o.id}
                        type="button"
                        onClick={() => pick(o.id)}
                        title={o.hint}
                        className={cn(
                            "rounded-md border px-3 py-1.5 text-left text-[11px] transition-colors",
                            value === o.id
                                ? "border-primary/50 bg-primary/10 text-primary"
                                : "border-line text-dim hover:border-primary/30 hover:text-foreground",
                        )}
                    >
                        <div className="font-semibold">{o.label}</div>
                        <div className="mt-0.5 max-w-[180px] leading-snug text-[9px] opacity-70">
                            {o.hint}
                        </div>
                    </button>
                ))}
            </div>
        </div>
    );
}

function useSettingWriter(baseUrl: string) {
    const invalidate = useInvalidateSettings(baseUrl);
    return async (key: string, value: unknown) => {
        await writeSetting(baseUrl, key, value);
        await invalidate();
    };
}

/* ------------------------------------------------------------------ */
/* capture: engine toggle + pause + fallback hint                       */
/* ------------------------------------------------------------------ */

function CaptureSection({
    settings,
    status,
    baseUrl,
}: {
    settings: Record<string, unknown> | undefined;
    status: ReturnType<typeof useStatus>["data"];
    baseUrl: string;
}) {
    const write = useSettingWriter(baseUrl);
    const configured = settings?.["capture.ocr_engine"] as "auto" | "npu" | "cpu" | undefined;
    const active = status?.capture.ocr_engine?.active;

    // The daemon publishes what it actually resolved; when the user asked for
    // npu but the machine fell back to cpu, surface it in amber (#71).
    const fellBack = configured === "npu" && active === "cpu";

    return (
        <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
            <SectionTitle
                hint="The OCR engine powering capture. The daemon picks the best available; a failed NPU install falls back to CPU."
            >
                Capture
            </SectionTitle>

            <Segmented
                label="OCR engine"
                options={ENGINES}
                value={configured}
                onSelect={(id) => write("capture.ocr_engine", id)}
                extra={
                    configured === "auto" && active ? (
                        <span className="text-[10px] text-dim">
                            currently on <b className="text-foreground">{active}</b>
                        </span>
                    ) : undefined
                }
            />

            {fellBack && (
                <div className="flex items-start gap-2 rounded-md border border-warn/40 bg-warn/10 px-2.5 py-2 text-[11px] text-warn">
                    <ShieldOff className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span>
                        NPU requested, but it isn&apos;t available on this machine — running{" "}
                        <b>CPU</b> instead. Frames are still captured.
                    </span>
                </div>
            )}

            <PauseToggle paused={!!settings?.["capture.paused"]} baseUrl={baseUrl} />
        </section>
    );
}

function PauseToggle({ paused, baseUrl }: { paused: boolean; baseUrl: string }) {
    const write = useSettingWriter(baseUrl);
    const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");

    const flip = async () => {
        setState("saving");
        try {
            await write("capture.paused", !paused);
            setState("saved");
            window.setTimeout(() => setState("idle"), 1500);
        } catch {
            setState("error");
        }
    };

    return (
        <div className="flex items-center gap-3">
            <button
                type="button"
                role="switch"
                aria-checked={!paused}
                aria-label="pause capture"
                onClick={flip}
                className={cn(
                    "relative h-5 w-9 shrink-0 rounded-full transition-colors",
                    paused ? "bg-line" : "bg-ok",
                )}
            >
                <span
                    className={cn(
                        "absolute top-0.5 h-4 w-4 rounded-full bg-surface shadow transition-all",
                        paused ? "left-0.5" : "left-[18px]",
                    )}
                />
            </button>
            <div className="min-w-0">
                <div className="flex items-center gap-2 text-[12px]">
                    <span className={paused ? "font-semibold text-warn" : "text-dim"}>
                        {paused ? "Capture paused" : "Capture active"}
                    </span>
                    {state === "saved" && <Check className="h-3 w-3 text-ok" />}
                    {state === "error" && <X className="h-3 w-3 text-danger" />}
                </div>
                <p className="text-[10px] text-faint">
                    {paused
                        ? "Nothing is stored until resumed. Manual captures still work."
                        : "New frames are stored as you work. Pausing leaves existing data intact."}
                </p>
            </div>
        </div>
    );
}

/* ------------------------------------------------------------------ */
/* exclusions: players + windows, DB-sourced + free-type                */
/* ------------------------------------------------------------------ */

function ExclusionsSection({
    values,
    baseUrl,
}: {
    values: Record<string, unknown> | undefined;
    baseUrl: string;
}) {
    const write = useSettingWriter(baseUrl);
    const players = (values?.["watch.excluded_players"] as string[] | undefined) ?? [];
    const windows = (values?.["watch.excluded_windows"] as string[] | undefined) ?? [];

    // DB-sourced suggestions: classes we've actually captured (frame-count desc).
    const { data: facets } = useFacets(baseUrl, new URLSearchParams());
    const capturedApps = facets?.apps.map((a) => a.value) ?? [];

    return (
        <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
            <SectionTitle
                hint="Never capture these players or windows. Excluded windows are dropped before any frame is stored — manual captures always work."
            >
                Exclusions
            </SectionTitle>

            <ChipList
                label="Excluded players"
                addLabel="add player"
                items={players}
                suggestions={[]}
                placeholder="e.g. spotify, vlc"
                onCommit={(next) => write("watch.excluded_players", next)}
            />
            <ChipList
                label="Excluded windows"
                addLabel="add window class"
                items={windows}
                suggestions={capturedApps}
                placeholder="e.g. steam, settings"
                onCommit={(next) => write("watch.excluded_windows", next)}
            />
        </section>
    );
}

function ChipList({
    label,
    addLabel,
    items,
    suggestions,
    placeholder,
    onCommit,
}: {
    label: string;
    addLabel: string;
    items: string[];
    suggestions: string[];
    placeholder: string;
    onCommit: (next: string[]) => Promise<void>;
}) {
    const [draft, setDraft] = useState("");
    const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
    const [err, setErr] = useState<string | null>(null);

    const save = async (next: string[]) => {
        setState("saving");
        setErr(null);
        try {
            await onCommit(next);
            setState("saved");
            window.setTimeout(() => setState("idle"), 1500);
        } catch (e) {
            setState("error");
            setErr(e instanceof ApiError ? e.message : "write failed");
        }
    };

    const add = () => {
        const v = draft.trim();
        if (!v || items.includes(v)) return;
        setDraft("");
        void save([...items, v]);
    };

    const suggestionsToShow = suggestions
        .filter((s) => !items.includes(s))
        .slice(0, 6);

    return (
        <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2">
                <span className="text-[11px] font-medium text-dim">{label}</span>
                {state === "saved" && (
                    <span className="flex items-center gap-1 text-[10px] text-ok">
                        <Check className="h-3 w-3" /> saved
                    </span>
                )}
                {state === "error" && <span className="text-[10px] text-danger">{err}</span>}
            </div>

            {items.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                    {items.map((item) => (
                        <span
                            key={item}
                            className="flex items-center gap-1.5 rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[11px] text-dim"
                        >
                            {item}
                            <button
                                type="button"
                                aria-label={`remove ${item}`}
                                onClick={() => void save(items.filter((i) => i !== item))}
                                className="text-faint transition-colors hover:text-danger"
                            >
                                <X className="h-3 w-3" />
                            </button>
                        </span>
                    ))}
                </div>
            )}

            <div className="flex items-center gap-1.5">
                <input
                    value={draft}
                    onChange={(e) => setDraft(e.currentTarget.value)}
                    onKeyDown={(e) => {
                        if (e.key === "Enter") add();
                    }}
                    placeholder={placeholder}
                    aria-label={addLabel}
                    list={undefined}
                    className="w-full rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-[11px] outline-none focus:border-primary"
                />
                <button
                    type="button"
                    onClick={add}
                    className="shrink-0 rounded-md border border-primary/50 bg-primary/10 px-2.5 py-1.5 text-[11px] text-primary transition-colors hover:bg-primary/20"
                >
                    <Plus className="h-3 w-3" />
                </button>
            </div>

            {suggestionsToShow.length > 0 && (
                <div className="flex flex-wrap gap-1">
                    <span className="text-[9px] text-faint">captured:</span>
                    {suggestionsToShow.map((s) => (
                        <button
                            key={s}
                            type="button"
                            onClick={() => void save([...items, s])}
                            className="rounded-full border border-line px-1.5 py-px text-[9px] text-faint transition-colors hover:border-primary/40 hover:text-dim"
                        >
                            + {s}
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}

/* ------------------------------------------------------------------ */
/* rules: window class → category, whole-dict write-through             */
/* ------------------------------------------------------------------ */

function RulesSection({
    values,
    baseUrl,
}: {
    values: Record<string, unknown> | undefined;
    baseUrl: string;
}) {
    const write = useSettingWriter(baseUrl);
    const rules = (values?.["rules.window_class_category"] as Record<string, string> | undefined) ?? {};

    // Captured apps, frame-count desc — unassigned classes are offered first.
    const { data: facets } = useFacets(baseUrl, new URLSearchParams());
    const apps = facets?.apps ?? [];

    const rows = useMemo(() => {
        const entries: Array<{ cls: string; category: string; frames: number }> = [];
        for (const app of apps) {
            entries.push({
                cls: app.value,
                category: rules[app.value] ?? "unassigned",
                frames: app.count,
            });
        }
        for (const [cls, category] of Object.entries(rules)) {
            if (!entries.some((e) => e.cls === cls)) {
                entries.push({ cls, category, frames: 0 });
            }
        }
        return entries.sort((a, b) => b.frames - a.frames);
    }, [apps, rules]);

    const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
    const [err, setErr] = useState<string | null>(null);
    const [draftClass, setDraftClass] = useState("");

    const commit = async (next: Record<string, string>) => {
        setState("saving");
        setErr(null);
        try {
            await write("rules.window_class_category", next);
            setState("saved");
            window.setTimeout(() => setState("idle"), 1500);
        } catch (e) {
            setState("error");
            setErr(e instanceof ApiError ? e.message : "write failed");
        }
    };

    const setCategory = (cls: string, category: string) => {
        const next = { ...rules };
        if (category === "unassigned") delete next[cls];
        else next[cls] = category;
        void commit(next);
    };

    const addClass = () => {
        const cls = draftClass.trim();
        if (!cls || cls in rules) return;
        setDraftClass("");
        void commit({ ...rules, [cls]: "Other" });
    };

    return (
        <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
            <SectionTitle
                hint="Which category a window counts toward in the time breakdown. Saved as a whole when any row changes."
            >
                Rules
            </SectionTitle>

            <div className="flex items-center gap-2">
                <span className="text-[11px] font-medium text-dim">Window → category</span>
                {state === "saved" && (
                    <span className="flex items-center gap-1 text-[10px] text-ok">
                        <Check className="h-3 w-3" /> saved
                    </span>
                )}
                {state === "error" && <span className="text-[10px] text-danger">{err}</span>}
            </div>

            <div className="flex max-h-52 flex-col gap-1 overflow-y-auto pr-1">
                {rows.length === 0 && (
                    <p className="text-[11px] text-faint">
                        No captured windows yet — they&apos;ll appear here as frames are stored.
                    </p>
                )}
                {rows.map((row) => (
                    <div key={row.cls} className="flex items-center gap-2 text-[11px]">
                        <span className="min-w-0 flex-1 truncate font-mono text-dim">{row.cls}</span>
                        <span className="shrink-0 text-[9px] text-faint">
                            {row.frames > 0 ? `${row.frames} frames` : "configured"}
                        </span>
                        <select
                            aria-label={`category for ${row.cls}`}
                            value={row.category}
                            onChange={(e) => setCategory(row.cls, e.currentTarget.value)}
                            className="w-36 shrink-0 rounded-md border border-line bg-surface-2 px-1.5 py-1 text-[11px] text-dim outline-none focus:border-primary [color-scheme:dark]"
                        >
                            <option value="unassigned">unassigned</option>
                            {RULES_CATEGORIES.map((c) => (
                                <option key={c} value={c}>
                                    {c}
                                </option>
                            ))}
                        </select>
                    </div>
                ))}
            </div>

            <div className="flex items-center gap-1.5">
                <input
                    value={draftClass}
                    onChange={(e) => setDraftClass(e.currentTarget.value)}
                    onKeyDown={(e) => {
                        if (e.key === "Enter") addClass();
                    }}
                    placeholder="add window class…"
                    aria-label="add window class"
                    className="w-full rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-[11px] outline-none focus:border-primary"
                />
                <button
                    type="button"
                    onClick={addClass}
                    className="shrink-0 rounded-md border border-primary/50 bg-primary/10 px-2.5 py-1.5 text-[11px] text-primary transition-colors hover:bg-primary/20"
                >
                    <Plus className="h-3 w-3" />
                </button>
            </div>
        </section>
    );
}

/* ------------------------------------------------------------------ */
/* scheduler: day recap + time breakdown, null = off                    */
/* ------------------------------------------------------------------ */

const PIPES = [
    { key: "day_recap", job: "day-recap", label: "Day recap", hint: "your evening summary" },
    { key: "time_breakdown", job: "time-breakdown", label: "Time breakdown", hint: "how your day split by category" },
] as const;

function SchedulerSection({
    values,
    scheduler,
    baseUrl,
}: {
    values: Record<string, unknown> | undefined;
    scheduler: Record<string, string | null> | undefined;
    baseUrl: string;
}) {
    const write = useSettingWriter(baseUrl);

    return (
        <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
            <SectionTitle hint="Scheduled pipes run on the server (while `heimdall serve` is up). A blank schedule means off.">
                Scheduled pipes
            </SectionTitle>

            {PIPES.map((pipe) => (
                <PipeRow
                    key={pipe.key}
                    label={pipe.label}
                    hint={pipe.hint}
                    expr={values?.[`scheduler.${pipe.key}`] as string | null | undefined}
                    nextRun={scheduler?.[pipe.job] ?? null}
                    onCommit={(expr) => write(`scheduler.${pipe.key}`, expr)}
                />
            ))}
        </section>
    );
}

function PipeRow({
    label,
    hint,
    expr,
    nextRun,
    onCommit,
}: {
    label: string;
    hint: string;
    expr: string | null | undefined;
    nextRun: string | null;
    onCommit: (expr: string | null) => Promise<void>;
}) {
    const [draft, setDraft] = useState(expr ?? "");
    const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
    const [err, setErr] = useState<string | null>(null);

    useEffect(() => setDraft(expr ?? ""), [expr]);

    const save = async (next: string | null) => {
        setState("saving");
        setErr(null);
        try {
            await onCommit(next);
            setState("saved");
            window.setTimeout(() => setState("idle"), 1500);
        } catch (e) {
            setState("error");
            setErr(e instanceof ApiError ? e.message : "write failed");
        }
    };

    const disabled = expr === null;

    return (
        <div className="flex flex-col gap-1.5 rounded-md border border-line/70 bg-surface-2 p-2.5">
            <div className="flex items-center gap-2">
                <span className="text-[12px] font-semibold text-dim">{label}</span>
                <span className="text-[10px] text-faint">{hint}</span>
                {state === "saved" && (
                    <span className="ml-auto flex items-center gap-1 text-[10px] text-ok">
                        <Check className="h-3 w-3" /> saved
                    </span>
                )}
                {state === "error" && (
                    <span className="ml-auto text-[10px] text-danger">{err}</span>
                )}
            </div>

            <div className="flex items-center gap-1.5">
                <button
                    type="button"
                    role="switch"
                    aria-checked={!disabled}
                    onClick={() => void save(disabled ? "0 22 * * *" : null)}
                    className={cn(
                        "relative h-5 w-9 shrink-0 rounded-full transition-colors",
                        disabled ? "bg-line" : "bg-ok",
                    )}
                >
                    <span
                        className={cn(
                            "absolute top-0.5 h-4 w-4 rounded-full bg-surface shadow transition-all",
                            disabled ? "left-0.5" : "left-[18px]",
                        )}
                    />
                </button>
                {!disabled ? (
                    <>
                        <input
                            value={draft}
                            onChange={(e) => setDraft(e.currentTarget.value)}
                            onKeyDown={(e) => {
                                if (e.key === "Enter") void save(draft.trim() || null);
                            }}
                            aria-label={`${label} cron`}
                            placeholder="minute hour day month dow"
                            className="w-40 rounded-md border border-line bg-surface-2 px-2 py-1 font-mono text-[11px] outline-none focus:border-primary"
                        />
                        <button
                            type="button"
                            onClick={() => void save(draft.trim() || null)}
                            className="rounded-md border border-primary/50 bg-primary/10 px-2 py-1 text-[10px] text-primary transition-colors hover:bg-primary/20"
                        >
                            Set
                        </button>
                    </>
                ) : (
                    <span className="text-[10px] text-faint">off</span>
                )}
                <span className="ml-auto flex items-center gap-1 text-[10px] text-faint">
                    <Clock className="h-3 w-3" />
                    {nextRun ? `next ${new Date(nextRun).toLocaleString()}` : "no run scheduled"}
                </span>
            </div>
        </div>
    );
}

/* ------------------------------------------------------------------ */
/* passive: screen reading + telemetry + advanced                       */
/* ------------------------------------------------------------------ */

function PassiveSection({
    values,
    baseUrl,
}: {
    values: Record<string, unknown> | undefined;
    baseUrl: string;
}) {
    const write = useSettingWriter(baseUrl);

    return (
        <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
            <SectionTitle>Screen reading, telemetry &amp; advanced</SectionTitle>

            <div className="grid gap-3">
                <Segmented
                    label="Extraction mode"
                    options={EXTRACTION_MODES}
                    value={values?.["capture.extraction"] as "auto" | "a11y" | "ocr" | undefined}
                    onSelect={(id) => write("capture.extraction", id)}
                />

                <div className="flex items-center justify-between gap-3 rounded-md border border-line/70 bg-surface-2 p-2.5">
                    <div>
                        <div className="text-[12px] font-semibold text-dim">Telemetry</div>
                        <p className="text-[10px] text-faint">
                            Send pipe traces to Langfuse (LANGFUSE_* env vars). Flipping this
                            applies immediately, no restart needed.
                        </p>
                    </div>
                    <Toggle
                        checked={!!values?.["observability.enabled"]}
                        onChange={(v) => write("observability.enabled", v)}
                        label="telemetry"
                    />
                </div>

                <Segmented
                    label="Media resolver"
                    options={RESOLVERS}
                    value={values?.["watch.media_resolver"] as "extension" | "cdp" | undefined}
                    onSelect={(id) => write("watch.media_resolver", id)}
                />
            </div>
        </section>
    );
}

function Toggle({
    checked,
    onChange,
    label,
}: {
    checked: boolean;
    onChange: (v: boolean) => Promise<void>;
    label: string;
}) {
    const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");

    const flip = async () => {
        setState("saving");
        try {
            await onChange(!checked);
            setState("saved");
            window.setTimeout(() => setState("idle"), 1500);
        } catch {
            setState("error");
        }
    };

    return (
        <div className="flex items-center gap-2">
            <button
                type="button"
                role="switch"
                aria-checked={checked}
                aria-label={label}
                onClick={flip}
                className={cn(
                    "relative h-5 w-9 shrink-0 rounded-full transition-colors",
                    checked ? "bg-ok" : "bg-line",
                )}
            >
                <span
                    className={cn(
                        "absolute top-0.5 h-4 w-4 rounded-full bg-surface shadow transition-all",
                        checked ? "left-[18px]" : "left-0.5",
                    )}
                />
            </button>
            {state === "saved" && <Check className="h-3 w-3 text-ok" />}
            {state === "error" && <X className="h-3 w-3 text-danger" />}
        </div>
    );
}

/* ------------------------------------------------------------------ */
/* forget: typed-gate hard delete                                      */
/* ------------------------------------------------------------------ */

function ForgetSection({ baseUrl }: { baseUrl: string }) {
    const [open, setOpen] = useState(false);
    const [categories, setCategories] = useState<string[]>(["frames", "sessions"]);
    const [window, setWindow] = useState<"1d" | "7d" | "30d" | "all">("7d");
    const [typed, setTyped] = useState("");
    const [state, setState] = useState<"idle" | "running" | "done" | "error">("idle");
    const [err, setErr] = useState<string | null>(null);

    const armed = typed.trim() === "forget" && categories.length > 0;

    const doForget = async () => {
        if (!armed) return;
        setState("running");
        setErr(null);
        try {
            const now = Date.now();
            const start = new Date(
                window === "all" ? 0 : window === "1d" ? now - 86_400_000 : window === "7d" ? now - 7 * 86_400_000 : now - 30 * 86_400_000,
            ).toISOString();
            const end = new Date(now).toISOString();
            await forgetData(baseUrl, categories, start, end);
            setState("done");
        } catch (e) {
            setState("error");
            setErr(e instanceof ApiError ? e.message : "forget failed");
        }
    };

    if (!open) {
        return (
            <section className="flex flex-col gap-2 rounded-lg border border-danger/30 bg-surface p-4">
                <SectionTitle hint="Permanently delete captured data. There is no undo — this is the only way data ever leaves your disk.">
                    Forget
                </SectionTitle>
                <button
                    type="button"
                    onClick={() => setOpen(true)}
                    className="self-start rounded-md border border-danger/50 bg-danger/10 px-3 py-1.5 text-[11px] text-danger transition-colors hover:bg-danger/20"
                >
                    <Trash2 className="mr-1 inline h-3 w-3" />
                    forget data…
                </button>
            </section>
        );
    }

    return (
        <section className="flex flex-col gap-3 rounded-lg border border-danger/40 bg-surface p-4">
            <div className="flex items-center gap-2">
                <SectionTitle>Forget data</SectionTitle>
                <button
                    type="button"
                    onClick={() => setOpen(false)}
                    className="ml-auto text-faint transition-colors hover:text-foreground"
                    aria-label="close forget"
                >
                    <X className="h-4 w-4" />
                </button>
            </div>

            <div className="flex flex-col gap-2">
                {FORGET_CATEGORIES.map((c) => (
                    <label key={c.id} className="flex cursor-pointer items-start gap-2 text-[12px]">
                        <input
                            type="checkbox"
                            checked={categories.includes(c.id)}
                            onChange={(e) => {
                                const checked = (e.target as HTMLInputElement).checked;
                                setCategories((prev) =>
                                    checked
                                        ? [...prev, c.id]
                                        : prev.filter((x) => x !== c.id),
                                );
                            }}
                            className="mt-0.5 accent-[var(--danger)]"
                        />
                        <span>
                            <span className="font-semibold text-dim">{c.label}</span>
                            <span className="ml-1.5 text-[10px] text-faint">{c.hint}</span>
                        </span>
                    </label>
                ))}
            </div>

            <div className="flex items-center gap-2">
                <span className="text-[11px] font-medium text-dim">Window</span>
                <div className="flex gap-1">
                    {(
                        [
                            ["1d", "last day"],
                            ["7d", "last week"],
                            ["30d", "last month"],
                            ["all", "everything"],
                        ] as const
                    ).map(([id, label]) => (
                        <button
                            key={id}
                            type="button"
                            onClick={() => setWindow(id)}
                            className={cn(
                                "rounded-md border px-2 py-1 text-[10px] transition-colors",
                                window === id
                                    ? "border-danger/50 bg-danger/10 text-danger"
                                    : "border-line text-dim hover:text-foreground",
                            )}
                        >
                            {label}
                        </button>
                    ))}
                </div>
            </div>

            <div className="flex items-center gap-2">
                <input
                    value={typed}
                    onChange={(e) => setTyped(e.currentTarget.value)}
                    placeholder="type forget to confirm"
                    aria-label="type forget to confirm"
                    className="w-full rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-[11px] outline-none focus:border-danger"
                />
                <button
                    type="button"
                    onClick={doForget}
                    disabled={!armed || state === "running"}
                    className={cn(
                        "shrink-0 rounded-md border px-3 py-1.5 text-[11px] font-semibold transition-colors",
                        armed
                            ? "border-danger bg-danger/15 text-danger hover:bg-danger/25"
                            : "cursor-not-allowed border-line text-faint",
                    )}
                >
                    {state === "running" ? "deleting…" : "Forget"}
                </button>
            </div>

            {state === "done" && (
                <p className="flex items-center gap-1.5 text-[11px] text-ok">
                    <RotateCcw className="h-3 w-3" /> done — deleted rows and files.
                </p>
            )}
            {state === "error" && <p className="text-[11px] text-danger">{err}</p>}
            {state === "idle" && categories.length === 0 && (
                <p className="text-[10px] text-faint">pick at least one category</p>
            )}
        </section>
    );
}
