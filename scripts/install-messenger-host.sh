#!/usr/bin/env bash
# Install the heimdall native-messaging host + build a loadable extension copy.
#
# What this does:
#   1. Generates a signing key (extensions/heimdall-messenger/key.pem) once;
#      the extension id is derived from it, so it stays stable across runs.
#   2. Builds a patched extension copy under ~/.heimdall/extensions/ with the
#      public key in manifest.json (that key pins the id, not the path).
#   3. Writes per-browser NativeMessagingHosts manifests under
#      ~/.config/<chromium|google-chrome>/NativeMessagingHosts/ so the browser
#      can launch the host (the venv python runs heimdall.native_messenger).
#
# The extension itself is still loaded manually (chrome://extensions -> dev
# mode -> Load unpacked -> the built copy) — see the output of this script.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXT_SRC="$ROOT/extensions/heimdall-messenger"
EXT_BUILD="${HOME}/.heimdall/extensions/heimdall-messenger"
HOST_NAME="com.heimdall.messenger"
VENV_PY="$ROOT/.venv/bin/python"
BROWSERS=(chromium google-chrome)

if [ ! -x "$VENV_PY" ]; then
  echo "error: no venv python at $VENV_PY" >&2
  exit 1
fi

KEY="$EXT_SRC/key.pem"
if [ ! -f "$KEY" ]; then
  echo ">> generating extension signing key ($KEY)"
  openssl genrsa -out "$KEY" 2048
  chmod 600 "$KEY"
fi

read -r EXT_ID PUBKEY_B64 <<< "$("$VENV_PY" - "$KEY" <<'PY'
import base64
import hashlib
import subprocess
import sys

key = subprocess.run(
    ["openssl", "rsa", "-in", sys.argv[1], "-pubout", "-outform", "DER"],
    capture_output=True, check=True).stdout
chars = "abcdefghijklmnop"
ext_id = "".join(chars[b >> 4] + chars[b & 0xF] for b in hashlib.sha256(key).digest()[:16])
print(ext_id, base64.b64encode(key).decode())
PY
)"

echo ">> extension id: $EXT_ID"
echo ">> building extension copy at $EXT_BUILD"
rm -rf "$EXT_BUILD"
mkdir -p "$EXT_BUILD"
cp "$EXT_SRC/manifest.json" "$EXT_SRC/background.js" "$EXT_SRC/content.js" "$EXT_BUILD/"

"$VENV_PY" - "$EXT_BUILD/manifest.json" "$PUBKEY_B64" <<'PY'
import json
import sys

path, pubkey = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as fh:
    manifest = json.load(fh)
manifest["key"] = pubkey
with open(path, "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, indent=2)
    fh.write("\n")
PY

HOST_BIN="$HOME/.heimdall/heimdall-messenger-host"
cat > "$HOST_BIN" <<EOF
#!/bin/sh
# Native-messaging host wrapper (#44). Chrome launches the host with the
# extension origin as argv[1] and ignores any manifest "args", so this stub
# discards every argument and execs the real host module.
exec "$VENV_PY" -m heimdall.native_messenger
EOF
chmod +x "$HOST_BIN"
echo ">> wrote host wrapper at $HOST_BIN"

for browser in "${BROWSERS[@]}"; do
  dir="$HOME/.config/$browser/NativeMessagingHosts"
  mkdir -p "$dir"
  cat > "$dir/$HOST_NAME.json" <<EOF
{
  "name": "$HOST_NAME",
  "description": "heimdall native-messaging host: streams YouTube page state to the daemon",
  "path": "$HOST_BIN",
  "type": "stdio",
  "allowed_origins": ["chrome-extension://$EXT_ID/"]
}
EOF
  echo ">> wrote $dir/$HOST_NAME.json"
done

cat <<EOF

Installed. To use it:
  1. Open chrome://extensions (or edge://extensions) in Chromium/Chrome,
     enable Developer mode, click "Load unpacked", and pick:
       $EXT_BUILD
  2. Play a YouTube video in that browser. No debug port, no approval popups:
     the extension streams the page URL + video time straight to the daemon.
  3. The daemon resolves Chromium sessions via this stream by default
     (watch.media_resolver: extension). To keep the old CDP path instead, set
     watch.media_resolver: cdp in ~/.heimdall/config.yaml.
EOF
