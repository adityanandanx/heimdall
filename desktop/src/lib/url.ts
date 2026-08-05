export function normalizeUrl(raw: string): string {
    const trimmed = raw.trim().replace(/\/+$/, "");
    if (/^https?:\/\//i.test(trimmed)) return trimmed;
    return `http://${trimmed}`;
}

export function isHttpUrl(url: string): boolean {
    try {
        const u = new URL(url);
        return u.protocol === "http:" || u.protocol === "https:";
    } catch {
        return false;
    }
}