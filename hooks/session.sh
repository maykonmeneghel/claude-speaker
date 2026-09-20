#!/bin/bash
# claude-speaker hook: register the session's terminal (tty) and keep the
# focus-monitor daemon alive. Always exits 0 so Claude is never blocked.
set -uo pipefail

MODE="${1:-start}"
ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PAYLOAD="$(cat 2>/dev/null || true)"

PY="$(command -v python3 || echo /usr/bin/python3)"

CLAUDE_SPEAKER_PAYLOAD="$PAYLOAD" \
CLAUDE_SPEAKER_MODE="$MODE" \
CLAUDE_PLUGIN_ROOT="$ROOT" \
"$PY" - <<'PYEOF' >/dev/null 2>&1
import json, os, sys
from pathlib import Path
root = Path(os.environ["CLAUDE_PLUGIN_ROOT"])
sys.path.insert(0, str(root / "lib"))
import speaker_core as core

try:
    payload = json.loads(os.environ.get("CLAUDE_SPEAKER_PAYLOAD") or "{}")
except ValueError:
    payload = {}
session_id = payload.get("session_id") or os.environ.get("CLAUDE_SESSION_ID", "unknown")
mode = os.environ.get("CLAUDE_SPEAKER_MODE", "start")

if mode == "end":
    core.forget_session(session_id)
else:
    info = core.register_session(session_id, {"source": payload.get("source", ""), "origin": "hook"})
    core.log(f"session {session_id[:8]} tty={info.get('tty') or '?'} "
             f"term={info.get('term_program') or '?'} "
             f"speak={core.session_state(session_id) or 'default'}")
    if core.enabled(session_id):
        core.ensure_daemon(str(root))
PYEOF

exit 0
