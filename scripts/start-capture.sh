#!/usr/bin/env bash
# Event-driven capture daemon: grim (region JPEG) + RapidOCR (OCR worker queue)
# + playerctl (MPRIS tracks) + Hyprland socket2 listener. Foreground; Ctrl-C stops.
#
# Usage:  scripts/start-capture.sh [--config /path/to/config.yaml] [--log-dir ~/.heimdall/logs]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

exec uv run --project "$ROOT" python -m heimdall.capture.daemon "$@"
