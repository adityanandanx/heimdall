import { load } from "@tauri-apps/plugin-store";
import { DEFAULT_SERVER_URL } from "@/lib/api";

// The server URL persists through the Tauri settings store inside the app, and
// falls back to localStorage when running in a plain browser (dev / tests),
// where the store plugin's IPC is unavailable.
const STORE_PATH = "settings.json";
const STORE_KEY = "serverUrl";
const LS_KEY = "heimdall.serverUrl";

function inTauri(): boolean {
    return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

let storePromise: ReturnType<typeof load> | null = null;
function store(): ReturnType<typeof load> {
    if (!storePromise) storePromise = load(STORE_PATH, { autoSave: false });
    return storePromise;
}

export async function getServerUrl(): Promise<string> {
    if (inTauri()) {
        const s = await store();
        return (await s.get<string>(STORE_KEY)) ?? DEFAULT_SERVER_URL;
    }
    return window.localStorage.getItem(LS_KEY) ?? DEFAULT_SERVER_URL;
}

export async function setServerUrl(url: string): Promise<void> {
    if (inTauri()) {
        const s = await store();
        await s.set(STORE_KEY, url);
        await s.save();
        return;
    }
    window.localStorage.setItem(LS_KEY, url);
}