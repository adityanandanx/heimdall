import { openUrl } from "@tauri-apps/plugin-opener";

// openUrl IPC is only available inside the Tauri webview; outside (dev/tests)
// fall back to window.open.
function inTauri(): boolean {
    return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function openExternal(url: string): Promise<void> {
    if (inTauri()) {
        await openUrl(url);
        return;
    }
    window.open(url, "_blank");
}