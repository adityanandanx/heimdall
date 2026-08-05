import { useEffect, useState } from "react";
import { getServerUrl } from "@/lib/settings";
import { ServerSettings } from "@/components/server-settings";
import { StatusView } from "@/components/status-view";
import { DayBrowser } from "@/components/day-browser/day-browser";
import { cn } from "@/lib/utils";

type Tab = "status" | "day";

const TABS: Array<{ id: Tab; label: string }> = [
    { id: "status", label: "Status" },
    { id: "day", label: "Day browser" },
];

function App() {
    const [serverUrl, setServerUrl] = useState<string | null>(null);
    const [tab, setTab] = useState<Tab>("day");

    useEffect(() => {
        let cancelled = false;
        getServerUrl().then((url) => {
            if (!cancelled) setServerUrl(url);
        });
        return () => {
            cancelled = true;
        };
    }, []);

    return (
        <main className="mx-auto max-w-7xl px-6 py-8">
            <header className="mb-6">
                <div className="flex items-center gap-4">
                    <h1 className="text-2xl font-semibold tracking-tight">Heimdall</h1>
                    <nav className="flex gap-1" aria-label="views">
                        {TABS.map((t) => (
                            <button
                                key={t.id}
                                type="button"
                                onClick={() => setTab(t.id)}
                                className={cn(
                                    "rounded-lg px-3 py-1 text-sm font-medium transition-colors",
                                    tab === t.id
                                        ? "bg-muted text-foreground"
                                        : "text-muted-foreground hover:text-foreground",
                                )}
                            >
                                {t.label}
                            </button>
                        ))}
                    </nav>
                    <span className="ml-auto">
                        <ServerSettings value={serverUrl} onSaved={setServerUrl} />
                    </span>
                </div>
            </header>

            {serverUrl === null ? (
                <p className="text-sm text-muted-foreground">Loading…</p>
            ) : tab === "status" ? (
                <StatusView baseUrl={serverUrl} />
            ) : (
                <DayBrowser baseUrl={serverUrl} />
            )}
        </main>
    );
}

export default App;