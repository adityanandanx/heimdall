import { useEffect, useState } from "react";
import { setServerUrl } from "@/lib/settings";
import { isHttpUrl, normalizeUrl } from "@/lib/url";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface ServerSettingsProps {
    value: string | null;
    onSaved: (url: string) => void;
}

export function ServerSettings({ value, onSaved }: ServerSettingsProps) {
    const [draft, setDraft] = useState("");
    const [error, setError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (value) setDraft(value);
    }, [value]);

    async function handleSubmit(e: React.FormEvent) {
        e.preventDefault();
        const url = normalizeUrl(draft);
        if (!isHttpUrl(url)) {
            setError("Enter a URL like http://127.0.0.1:3931");
            return;
        }
        setError(null);
        setSaving(true);
        try {
            await setServerUrl(url);
            onSaved(url);
        } finally {
            setSaving(false);
        }
    }

    return (
        <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
            <div className="min-w-72">
                <Label htmlFor="server-url">Server URL</Label>
                <Input
                    id="server-url"
                    value={draft}
                    onChange={(e) => {
                        setDraft(e.currentTarget.value);
                        if (error) setError(null);
                    }}
                    placeholder="http://127.0.0.1:3931"
                    spellCheck={false}
                    autoComplete="off"
                    className="mt-1.5"
                />
                {error ? (
                    <p className="mt-1.5 text-xs text-destructive">{error}</p>
                ) : (
                    <p className="mt-1.5 text-xs text-muted-foreground">
                        where the heimdall API listens
                    </p>
                )}
            </div>
            <Button type="submit" disabled={saving || draft === (value ?? "")}>
                {saving ? "Saving…" : "Save"}
            </Button>
        </form>
    );
}