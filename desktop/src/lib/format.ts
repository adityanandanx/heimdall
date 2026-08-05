export function formatBytes(bytes: number): string {
    if (!Number.isFinite(bytes) || bytes <= 0) {
        return bytes === 0 ? "0 B" : "—";
    }
    const units = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
    if (i === 0) return `${Math.round(bytes)} B`;
    const value = bytes / 1024 ** i;
    return `${value >= 100 ? Math.round(value) : value.toFixed(1)} ${units[i]}`;
}

function parseTs(ts: string | number | null): Date | null {
    if (ts === null || ts === undefined || ts === "") return null;
    const d = typeof ts === "number" ? new Date(ts) : new Date(ts);
    return Number.isNaN(d.getTime()) ? null : d;
}

const dateTime = new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
});

const time = new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
});

const timeS = new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
});

export function formatDateTime(ts: string | number | null): string | null {
    const d = parseTs(ts);
    return d ? dateTime.format(d) : null;
}

export function formatTime(ts: string | number | null): string | null {
    const d = parseTs(ts);
    return d ? time.format(d) : null;
}

export function formatTimeS(ts: string | number | null): string | null {
    const d = parseTs(ts);
    return d ? timeS.format(d) : null;
}

export function formatUptime(seconds: number): string {
    if (!Number.isFinite(seconds) || seconds < 0) return "—";
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h === 0) return `${m}m`;
    return `${h}h ${m}m`;
}