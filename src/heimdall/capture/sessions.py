"""MPRIS -> watch-session state machine (pure, secondary seam, spec #20 / #35).

The tracker is driven by abstract events (play/pause/poll/seek/stop/exit) with
explicit wall clocks, so play/pause/seek/quit/player-exit sequences are fully
deterministic. Positions are video-time microseconds; ts_* are wall ms.

Wall time accrues only while a player is in the playing streak; pauses are
excluded. A pause past `pause_ends_session_s` closes the session (the daemon's
poll loop is the clock that notices); a `Seeked` event splits the video-time
range so skipped segments never count as watched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class WatchSession:
    """One finished watch session, ready for persistence."""

    player: str
    media_title: Optional[str]
    media_source: Optional[str]
    media_id: Optional[str]
    ts_start: int
    ts_end: int
    pos_start: int
    pos_end: int
    length: int
    ranges: list[list[int]] = field(default_factory=list)


@dataclass
class OpenSession:
    """Read-only view of an in-progress session (the live-row sync source).

    Deliberately mirrors `_Open` plus the derived `paused` flag so the daemon
    can persist and display live rows without reaching into tracker internals.
    """

    player: str
    media_title: Optional[str]
    media_source: Optional[str]
    media_id: Optional[str]
    ts_start: int
    pos_start: int
    length: int
    last_pos_us: int
    ranges: list[list[int]]
    paused: bool
    acc_wall_ms: int
    streak_start_wall_ms: Optional[int]
    paused_at_wall_ms: Optional[int]


@dataclass
class _Open:
    """Live tracker state for one player."""

    player: str
    media_title: Optional[str]
    media_source: Optional[str]
    media_id: Optional[str]
    ts_start: int
    pos_start: int
    length: int
    range_start_us: int
    ranges: list[list[int]] = field(default_factory=list)
    acc_wall_ms: int = 0
    streak_start_wall_ms: Optional[int] = None  # None while paused
    paused_at_wall_ms: Optional[int] = None
    last_poll_wall_ms: int = 0
    last_poll_pos_us: int = 0


class SessionTracker:
    """Tracks open watch sessions per MPRIS player, one per player.

    Keyed by the raw player name (``vlc``, ``chromium.instance1``) so the
    daemon can poll positions and detect player exits without ambiguity.
    """

    def __init__(self, pause_ends_session_s: float = 60.0):
        self.pause_ends_session_s = pause_ends_session_s
        self._open: dict[str, _Open] = {}

    def play(self, player: str, *, title, source, position_us: int = 0,
             length_us: int = 0, wall_ms: int = 0, media_id=None) -> Optional[WatchSession]:
        """Open (or resume) a session for the player.

        A play while a session is open is a resume: the streak restarts but the
        current video-time range continues, so a short pause never splits it.
        Returns the WatchSession closed by a mid-play track switch, else None.
        """
        op = self._open.get(player)
        if op is None:
            self._open[player] = _Open(
                player=player,
                media_title=title,
                media_source=source,
                media_id=media_id,
                ts_start=wall_ms,
                pos_start=position_us,
                length=length_us,
                range_start_us=position_us,
                streak_start_wall_ms=wall_ms,
                paused_at_wall_ms=None,
                last_poll_wall_ms=wall_ms,
                last_poll_pos_us=position_us,
            )
            return None
        if title != op.media_title or source != op.media_source:
            # a track switch while still "playing" ends the old session (MPRIS
            # emits no stopped between them); the new track opens a fresh one
            closed = self._close(player, None, wall_ms)
            self._open[player] = _Open(
                player=player,
                media_title=title,
                media_source=source,
                media_id=media_id,
                ts_start=wall_ms,
                pos_start=position_us,
                length=length_us,
                range_start_us=position_us,
                streak_start_wall_ms=wall_ms,
                paused_at_wall_ms=None,
                last_poll_wall_ms=wall_ms,
                last_poll_pos_us=position_us,
            )
            return closed
        op.media_title = title
        op.media_source = source
        op.media_id = media_id
        op.length = length_us
        op.streak_start_wall_ms = wall_ms
        op.paused_at_wall_ms = None
        op.last_poll_wall_ms = wall_ms
        op.last_poll_pos_us = position_us
        return None

    def pause(self, player: str, position_us: int, wall_ms: int) -> None:
        """Close the playing streak; the session stays open."""
        op = self._open.get(player)
        if op is None or op.paused_at_wall_ms is not None:
            return
        op.acc_wall_ms += wall_ms - op.streak_start_wall_ms
        op.streak_start_wall_ms = None
        op.paused_at_wall_ms = wall_ms
        op.last_poll_pos_us = position_us

    def poll(self, player: str, position_us: int, wall_ms: int) -> Optional[WatchSession]:
        """Periodic position poll (30s while a player is active).

        While paused, closes the session once the pause exceeds the threshold.
        While playing, detects jumps (a seek the daemon's Seeked handler missed)
        and splits the range at the old position.
        """
        op = self._open.get(player)
        if op is None:
            return None
        if op.paused_at_wall_ms is not None:
            if wall_ms - op.paused_at_wall_ms > self.pause_ends_session_s * 1000:
                return self._close(player, position_us, wall_ms)
            return None
        elapsed_s = max(0.0, (wall_ms - op.last_poll_wall_ms) / 1000)
        if is_seek(op.last_poll_pos_us, position_us, elapsed_s):
            op.ranges.append([op.range_start_us, op.last_poll_pos_us])
            op.range_start_us = position_us
        op.last_poll_wall_ms = wall_ms
        op.last_poll_pos_us = position_us
        return None

    def seek(self, player: str, position_us: int, wall_ms: int) -> None:
        """A MPRIS Seeked event: split the range, the skipped segment is not
        watched. Safe while paused too — the range just ends where it was."""
        op = self._open.get(player)
        if op is None:
            return
        op.ranges.append([op.range_start_us, op.last_poll_pos_us])
        op.range_start_us = position_us
        op.last_poll_pos_us = position_us
        if op.paused_at_wall_ms is None:
            op.last_poll_wall_ms = wall_ms

    def stop(self, player: str, position_us: int, wall_ms: int) -> Optional[WatchSession]:
        """Close and return the session (MPRIS stopped)."""
        return self._close(player, position_us, wall_ms)

    def exit(self, player: str, wall_ms: int) -> Optional[WatchSession]:
        """Close a session whose player disappeared; no position is known, so
        pos_end is 0 and the last known position closes the final range."""
        return self._close(player, None, wall_ms)

    def open_sessions(self) -> list[str]:
        """Players with an open session (the poll loop iterates these)."""
        return list(self._open)

    def snapshot(self) -> list[OpenSession]:
        """Read-only view of every open session, one per player.

        Pure: never mutates tracker state or closes anything, so reading is
        safe from the daemon's poll and follow threads at any moment.
        """
        return [
            OpenSession(
                player=op.player,
                media_title=op.media_title,
                media_source=op.media_source,
                media_id=op.media_id,
                ts_start=op.ts_start,
                pos_start=op.pos_start,
                length=op.length,
                last_pos_us=op.last_poll_pos_us,
                ranges=list(op.ranges),
                paused=op.paused_at_wall_ms is not None,
                acc_wall_ms=op.acc_wall_ms,
                streak_start_wall_ms=op.streak_start_wall_ms,
                paused_at_wall_ms=op.paused_at_wall_ms,
            )
            for op in self._open.values()
        ]

    def _close(self, player: str, position_us: Optional[int],
               wall_ms: int) -> Optional[WatchSession]:
        op = self._open.get(player)
        if op is None:
            return None
        if op.streak_start_wall_ms is not None:
            op.acc_wall_ms += wall_ms - op.streak_start_wall_ms
        end_pos = position_us if position_us is not None else op.last_poll_pos_us
        ranges = [*op.ranges, [op.range_start_us, end_pos]]
        closed = WatchSession(
            player=op.player,
            media_title=op.media_title,
            media_source=op.media_source,
            media_id=op.media_id,
            ts_start=op.ts_start,
            ts_end=op.ts_start + op.acc_wall_ms,
            pos_start=op.pos_start,
            pos_end=position_us if position_us is not None else 0,
            length=op.length,
            ranges=ranges,
        )
        del self._open[player]
        return closed


def is_seek(old_us: int, new_us: int, elapsed_s: float, tolerance_s: float = 30.0) -> bool:
    """True when the position moved more than linear 1x playback explains.

    Normal playback advances `elapsed_s` video-seconds; anything beyond that
    plus the tolerance is a jump (seek, rewind, 2x+).
    """
    return abs(new_us - old_us) >= (elapsed_s + tolerance_s) * 1_000_000


def normalize_player(player: str) -> str:
    """Chromium instances vary (``chromium.instance1``); collapse to the base."""
    if player.startswith("chromium"):
        return "chromium"
    return player


def fmt_video_time(us: int) -> str:
    """``7_200_000_000 -> \"2:00:00\"``; hours appear only when nonzero."""
    total_s = max(0, int(us // 1_000_000))
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def parse_mpris_line(line: str) -> Optional[dict]:
    """Parse the playerctl follow line into tracker events.

    Format: ``status|artist|title|album|player|position|length|source`` with
    position/length in µs and an empty trailing ``source`` for players that
    expose no URL. Parsing is tolerant: extra empty fields (a blank album, or
    metadata segments playerctl omits) shift the tail, so player/position/
    length/source are read from the END of the line.
    """
    fields = line.split("|")
    if len(fields) < 5:
        return None
    status = fields[0].strip().lower()
    if status not in ("playing", "paused", "stopped"):
        return None

    def _num(value: str) -> int:
        try:
            return int(value)
        except ValueError:
            return 0

    source = fields[-1].strip()
    return {
        "player": fields[-4],
        "status": status,
        "title": fields[2].strip(),
        "position_us": _num(fields[-3]),
        "length_us": _num(fields[-2]),
        "source": source or None,
    }
