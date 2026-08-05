import { useEffect, useState } from "react";
import { Check, X } from "lucide-react";
import { DEFAULT_SERVER_URL } from "@/lib/api";
import { useHealth } from "@/hooks/use-day-browser";
import { cn } from "@/lib/utils";

interface SettingsSurfaceProps {
    serverUrl: string;
    onServerUrl: (url: string) => void;
    refreshSeconds: number;
    onRefreshSeconds: (s: number) => void;
}

const REFRESH_OPTIONS = [5, 10, 15, 30, 60];

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

    return (
        <div className="flex h-full flex-col gap-4 overflow-y-auto p-7">
            <div>
                <div className="mb-0.5 text-[26px] font-extrabold tracking-tight">Settings</div>
                <div className="mb-3 text-xs text-faint">
                    How the desktop client talks to your heimdall server.
                </div>
            </div>

            <div className="flex max-w-[560px] flex-col gap-5">
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
            </div>
        </div>
    );
}
