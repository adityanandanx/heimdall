import { useCallback, useEffect, useMemo, useState } from "react";
import { getServerUrl, setServerUrl as persistServerUrl } from "@/lib/settings";
import type { SurfaceId } from "@/lib/surfaces";
import { Shell } from "@/components/shell";
import { DaySurface } from "@/components/day-surface/day-surface";
import { SearchSurface } from "@/components/search-surface";
import { SessionsSurface } from "@/components/sessions-surface";
import { StatusSurface } from "@/components/status-surface";
import { SettingsSurface } from "@/components/settings-surface";
import { dayStrOf } from "@/lib/timeline";
import { useHealth } from "@/hooks/use-day-browser";
import type { SearchItem, Session } from "@/lib/api";

const LS_REFRESH = "heimdall.refreshSeconds";

function App() {
    const [serverUrl, setServerUrlState] = useState<string | null>(null);
    const [surface, setSurface] = useState<SurfaceId>("day");
    const [day, setDay] = useState<string | null>(null);
    const [seek, setSeek] = useState<{ ts: number; nonce: number } | null>(null);
    const [focusNonce, setFocusNonce] = useState(0);
    const [searchSeed, setSearchSeed] = useState("");
    const [refreshSeconds, setRefreshSeconds] = useState(() => {
        const v = Number(window.localStorage.getItem(LS_REFRESH));
        return Number.isFinite(v) && v > 0 ? v : 10;
    });

    useEffect(() => {
        let cancelled = false;
        getServerUrl().then((url) => {
            if (!cancelled) setServerUrlState(url);
        });
        return () => {
            cancelled = true;
        };
    }, []);

    const setServerUrl = useCallback((url: string) => {
        setServerUrlState(url);
        void persistServerUrl(url);
    }, []);

    const setRefresh = useCallback((s: number) => {
        setRefreshSeconds(s);
        window.localStorage.setItem(LS_REFRESH, String(s));
    }, []);

    const navigate = useCallback((id: SurfaceId) => {
        setSurface(id);
        if (id === "search") {
            setSearchSeed("");
            setFocusNonce((n) => n + 1);
        }
    }, []);

    const openGlobalSearch = useCallback((q: string) => {
        setSearchSeed(q);
        setFocusNonce((n) => n + 1);
        setSurface("search");
    }, []);

    const jumpTo = useCallback((ts: number) => {
        setDay(dayStrOf(new Date(ts)));
        setSeek({ ts, nonce: Date.now() });
        setSurface("day");
    }, []);

    const online = useHealth(serverUrl ?? "").data !== undefined;

    const content = useMemo(() => {
        if (serverUrl === null) return null;
        switch (surface) {
            case "day":
                return (
                    <DaySurface
                        baseUrl={serverUrl}
                        day={day ?? dayStrOf(new Date())}
                        onDayChange={setDay}
                        onOpenSearch={openGlobalSearch}
                        seek={seek}
                        onSeekDone={() => setSeek(null)}
                    />
                );
            case "search":
                return (
                    <SearchSurface
                        baseUrl={serverUrl}
                        focusNonce={focusNonce}
                        seed={searchSeed}
                        onPick={(item: SearchItem) => jumpTo(new Date(item.ts).getTime())}
                    />
                );
            case "sessions":
                return (
                    <SessionsSurface
                        baseUrl={serverUrl}
                        onJump={(s: Session) => jumpTo(new Date(s.ts_start).getTime())}
                    />
                );
            case "status":
                return <StatusSurface baseUrl={serverUrl} />;
            case "settings":
                return (
                    <SettingsSurface
                        serverUrl={serverUrl}
                        onServerUrl={setServerUrl}
                        refreshSeconds={refreshSeconds}
                        onRefreshSeconds={setRefresh}
                    />
                );
        }
    }, [serverUrl, surface, day, seek, focusNonce, searchSeed, refreshSeconds, setServerUrl, setRefresh, jumpTo, openGlobalSearch]);

    return (
        <Shell surface={surface} onSurface={navigate} onGlobalSearch={() => navigate("search")} online={online}>
            {serverUrl === null ? (
                <p className="p-7 text-xs text-dim">loading…</p>
            ) : (
                content
            )}
        </Shell>
    );
}

export default App;
