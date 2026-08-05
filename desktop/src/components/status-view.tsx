import type { ServerStatus, MediaPlayer } from "@/lib/api";
import { formatBytes, formatDateTime, formatTime, formatUptime } from "@/lib/format";
import { useHealth, useStatus } from "@/hooks/use-heimdall";
import {
    Badge,
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
    Skeleton,
} from "@/components/ui";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
    return (
        <div className="flex items-center justify-between gap-4">
            <span className="text-sm text-muted-foreground">{label}</span>
            {children}
        </div>
    );
}

export function OfflineCard({ baseUrl }: { baseUrl: string }) {
    return (
        <Card className="border-destructive/40 bg-destructive/5">
            <CardHeader>
                <CardTitle className="flex items-center gap-2">
                    <span className="size-2 rounded-full bg-destructive" />
                    Server offline
                </CardTitle>
                <CardDescription>
                    Couldn&apos;t reach the heimdall server at{" "}
                    <code className="rounded bg-muted px-1">{baseUrl}</code>. Start it with{" "}
                    <code className="rounded bg-muted px-1">heimdall serve</code> and this view
                    updates by itself.
                </CardDescription>
            </CardHeader>
        </Card>
    );
}

function StatusSkeleton() {
    return (
        <div className="grid gap-4 sm:grid-cols-2">
            <Card>
                <CardHeader>
                    <Skeleton className="h-5 w-40" />
                </CardHeader>
                <CardContent className="space-y-3">
                    <Skeleton className="h-4 w-full" />
                    <Skeleton className="h-4 w-2/3" />
                </CardContent>
            </Card>
            <Card>
                <CardHeader>
                    <Skeleton className="h-5 w-40" />
                </CardHeader>
                <CardContent className="space-y-3">
                    <Skeleton className="h-4 w-full" />
                    <Skeleton className="h-4 w-3/4" />
                </CardContent>
            </Card>
        </div>
    );
}

function ServerCard({ status }: { status: ServerStatus }) {
    const { server, db } = status;
    return (
        <Card>
            <CardHeader>
                <CardTitle className="flex items-center gap-2">
                    Server
                    <Badge className="ml-auto bg-emerald-600 text-white">online</Badge>
                </CardTitle>
                <CardDescription>heimdall {server.version}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
                <Row label="Uptime">{formatUptime(server.uptime_s)}</Row>
                <Row label="Frames today">{db.frames_today.toLocaleString()}</Row>
                <Row label="Database size">{formatBytes(db.size_bytes)}</Row>
            </CardContent>
        </Card>
    );
}

function PlayersList({ players }: { players: MediaPlayer[] }) {
    if (players.length === 0) {
        return <span className="text-sm text-muted-foreground">no media players detected</span>;
    }
    return (
        <ul className="space-y-1.5">
            {players.map((p) => (
                <li key={p.name} className="flex items-center justify-between gap-4">
                    <span className="truncate text-sm">{p.name}</span>
                    <Badge variant={p.status === "playing" ? "default" : "secondary"}>
                        {p.status}
                    </Badge>
                </li>
            ))}
        </ul>
    );
}

function CaptureCard({ status }: { status: ServerStatus }) {
    const { alive, last_event_ts, players } = status.capture;
    const lastEvent = formatDateTime(last_event_ts);
    return (
        <Card>
            <CardHeader>
                <CardTitle className="flex items-center gap-2">
                    Capture
                    {alive ? (
                        <Badge className="ml-auto bg-emerald-600 text-white">running</Badge>
                    ) : (
                        <Badge variant="destructive" className="ml-auto">
                            not running
                        </Badge>
                    )}
                </CardTitle>
                <CardDescription>
                    {alive
                        ? "capture daemon is alive"
                        : "the capture daemon isn't recording; start it alongside the server"}
                </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
                <Row label="Last event">{lastEvent ?? "never"}</Row>
                <div>
                    <div className="mb-1.5 text-sm text-muted-foreground">Media players</div>
                    <PlayersList players={players} />
                </div>
            </CardContent>
        </Card>
    );
}

function LlmCard({ status }: { status: ServerStatus }) {
    const { reachable } = status.llama;
    return (
        <Card>
            <CardHeader>
                <CardTitle>LLM (llama)</CardTitle>
            </CardHeader>
            <CardContent>
                <div className="flex items-center justify-between gap-4">
                    <span className="text-sm text-muted-foreground">Recap / breakdown model</span>
                    {reachable ? (
                        <Badge className="bg-emerald-600 text-white">reachable</Badge>
                    ) : (
                        <Badge variant="secondary">unreachable</Badge>
                    )}
                </div>
            </CardContent>
        </Card>
    );
}

function MediaCard({ status }: { status: ServerStatus }) {
    const session = status.media.last_session;
    return (
        <Card>
            <CardHeader>
                <CardTitle>Last watch session</CardTitle>
                <CardDescription>most recent media tracked by heimdall</CardDescription>
            </CardHeader>
            <CardContent>
                {session ? (
                    <div className="space-y-1.5 text-sm">
                        <p className="font-medium leading-snug">{session.media_title}</p>
                        <p className="text-muted-foreground">{session.player}</p>
                        <p className="text-xs text-muted-foreground">
                            {formatDateTime(session.ts_start)}
                            {session.ts_end ? ` – ${formatTime(session.ts_end)}` : ""}
                        </p>
                    </div>
                ) : (
                    <p className="text-sm text-muted-foreground">no watch sessions yet</p>
                )}
            </CardContent>
        </Card>
    );
}

export function StatusView({ baseUrl }: { baseUrl: string }) {
    const health = useHealth(baseUrl);
    const status = useStatus(baseUrl);

    if (health.isError) {
        return <OfflineCard baseUrl={baseUrl} />;
    }
    if (health.isLoading || status.isLoading || !status.data) {
        return <StatusSkeleton />;
    }

    return (
        <div className="grid gap-4 sm:grid-cols-2">
            <ServerCard status={status.data} />
            <CaptureCard status={status.data} />
            <LlmCard status={status.data} />
            <MediaCard status={status.data} />
        </div>
    );
}