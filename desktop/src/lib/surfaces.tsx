import type { ComponentType } from "react";
import { Activity, Grid2x2, Play, Search, Settings } from "lucide-react";

export type SurfaceId = "day" | "search" | "sessions" | "status" | "settings";

export interface Surface {
    id: SurfaceId;
    label: string;
    icon: ComponentType<{ className?: string }>;
    section: "browse" | "system";
}

// The shell builds its sidebar from this registry — adding a surface is one
// entry here plus one render arm in App.
export const surfaces: Surface[] = [
    { id: "day", label: "Day", icon: Grid2x2, section: "browse" },
    { id: "search", label: "Search", icon: Search, section: "browse" },
    { id: "sessions", label: "Sessions", icon: Play, section: "browse" },
    { id: "status", label: "Status", icon: Activity, section: "system" },
    { id: "settings", label: "Settings", icon: Settings, section: "system" },
];

export const surfaceById = new Map(surfaces.map((s) => [s.id, s]));
