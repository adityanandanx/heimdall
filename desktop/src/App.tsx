import { useEffect, useState } from "react";
import { getServerUrl } from "@/lib/settings";
import { ServerSettings } from "@/components/server-settings";
import { StatusView } from "@/components/status-view";
import { Separator } from "@/components/ui/separator";

function App() {
    const [serverUrl, setServerUrl] = useState<string | null>(null);

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
        <main className="mx-auto max-w-3xl px-6 py-8">
            <header className="mb-6">
                <h1 className="text-2xl font-semibold tracking-tight">Heimdall</h1>
                <p className="text-sm text-muted-foreground">
                    desktop client — status of your capture server
                </p>
            </header>

            <ServerSettings value={serverUrl} onSaved={setServerUrl} />

            <Separator className="my-6" />

            {serverUrl === null ? (
                <p className="text-sm text-muted-foreground">Loading…</p>
            ) : (
                <StatusView baseUrl={serverUrl} />
            )}
        </main>
    );
}

export default App;