/** Tinted app/player tag — colored border + text + subtle fill keyed to an
 * application name (window class or media player). */
export function AppChip({ label, color }: { label: string; color: string }) {
    return (
        <span
            className="shrink-0 rounded-full border px-1.5 py-px text-[9px]"
            style={{ color, borderColor: `${color}40`, backgroundColor: `${color}14` }}
        >
            {label}
        </span>
    );
}