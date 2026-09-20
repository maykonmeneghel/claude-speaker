#!/usr/bin/env python3
"""claude-speaker hook: turn Claude's output into a queued speech item.

Usage (from hooks.json):
    python3 enqueue.py stop          # Stop / SubagentStop payload on stdin
    python3 enqueue.py notification  # Notification payload on stdin
    python3 enqueue.py prompt        # UserPromptSubmit: forget what is stale

The hook never blocks Claude: it always exits 0 and stays silent on stdout.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import speaker_core as core  # noqa: E402


def read_payload() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except (ValueError, OSError):
        return {}


def reversed_lines(path: Path, block: int = 262_144, max_bytes: int = 24_000_000):
    """Yield lines from the end of a file without loading it whole."""
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        pos = fh.tell()
        floor = max(0, pos - max_bytes)
        tail = b""
        while pos > floor:
            step = min(block, pos - floor)
            pos -= step
            fh.seek(pos)
            chunk = fh.read(step) + tail
            parts = chunk.split(b"\n")
            tail = parts.pop(0)
            for line in reversed(parts):
                if line.strip():
                    yield line
        if tail.strip():
            yield tail


def last_assistant_text(transcript: str) -> str:
    path = Path(transcript or "")
    if not path.is_file():
        return ""
    for raw in reversed_lines(path):
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if entry.get("type") != "assistant" or entry.get("isSidechain"):
            continue
        message = entry.get("message") or {}
        if message.get("role") != "assistant":
            continue
        if str(message.get("model", "")).startswith("<"):
            continue  # synthetic / system-injected message
        content = message.get("content")
        if not isinstance(content, list):
            continue
        chunks = [b.get("text", "") for b in content
                  if isinstance(b, dict) and b.get("type") == "text"]
        text = "\n".join(c for c in chunks if c.strip())
        if text.strip():
            return text
        # assistant turn made only of tool calls: keep walking backwards
    return ""


def already_queued(session_id: str, text: str) -> bool:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    sess = core.read_session(session_id)
    if sess.get("last_digest") == digest:
        return True
    core.register_session(session_id, {"last_digest": digest})
    return False


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "stop"
    payload = read_payload()
    session_id = payload.get("session_id") or os.environ.get("CLAUDE_SESSION_ID", "unknown")
    short = session_id[:8]
    cfg = core.load_config()

    if mode == "prompt":
        # The user is back and has asked something new, so a summary of an
        # earlier turn that never got spoken is stale: saying it now describes
        # the wrong question. Notifications are left alone — a pending
        # permission prompt is still true.
        if cfg.get("stop_on_prompt", True):
            # Cut what is playing right now too. This is only a mark on the
            # session; the daemon owns the player and ends it on its next poll,
            # so nothing here kills audio that does not belong to the plugin.
            core.request_cancel(session_id)
        dropped = 0
        for item in core.list_queue():
            if item.get("session_id") == session_id and item.get("kind") == "stop":
                core.drop_queue_item(item)
                dropped += 1
        if dropped:
            core.log(f"prompt hook: session={short} dropped {dropped} stale "
                     f"summary(ies), the user is back")
        return 0

    if not core.enabled(session_id):
        core.log(f"{mode} hook: session={short} not speaking "
                 f"(session={core.session_state(session_id) or 'default'}, "
                 f"global={'on' if core.global_enabled() else 'off'})")
        return 0

    if mode == "notification":
        if not cfg.get("notifications", True):
            return 0
        raw = (payload.get("message") or "").strip()
        if not raw:
            return 0
        text = core.clean_text(raw, 240, cfg.get("strip_paths", True))
        kind = "notification"
    else:
        summary_mode = str(cfg.get("summary_mode", "smart")).lower()
        note = core.take_note(session_id)
        if note:
            text = core.clean_text(note, int(cfg.get("max_chars", 700)),
                                   cfg.get("strip_paths", True))
        elif summary_mode == "manual":
            core.log(f"stop hook: session={short} manual mode and no note, staying quiet")
            return 0
        else:
            raw = last_assistant_text(payload.get("transcript_path", ""))
            if not raw.strip():
                core.log(f"stop hook: session={short} no assistant text in the transcript")
                return 0
            text = core.clean_text(core.speech_digest(raw, cfg),
                                   core.spoken_limit(cfg),
                                   cfg.get("strip_paths", True))
        kind = "stop"

    if not text or len(text) < 3:
        return 0
    if kind == "stop" and already_queued(session_id, text):
        return 0

    item_path = core.enqueue(text, session_id, kind)
    if item_path:
        core.log(f"queued {kind} session={short} chars={len(text)}")
        if cfg.get("prefetch", True) and core.engine_in_use(cfg) == "elevenlabs":
            try:
                core.synthesize(text, cfg)  # warm the cache while the user is away
            except Exception as exc:  # never break the hook over TTS
                core.log(f"prefetch failed: {exc}")
        core.ensure_daemon()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # a hook must never fail the turn
        try:
            core.log(f"enqueue crashed: {exc!r}")
        except Exception:
            pass
        sys.exit(0)
