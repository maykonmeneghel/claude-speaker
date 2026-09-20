#!/usr/bin/env python3
"""claude-speaker daemon: watches terminal focus and speaks the queue.

One daemon serves every Claude Code session on the machine. It wakes up a few
times per second, asks macOS which terminal tab is in front, and speaks the
pending items that belong to that exact tty. Exits on its own after an idle
period so it never lingers forever.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import speaker_core as core  # noqa: E402

STOP = False


def _handle_signal(signum, _frame):
    global STOP
    STOP = True
    core.log(f"daemon received signal {signum}, shutting down")


def claude_running() -> bool:
    import subprocess
    try:
        out = subprocess.run(["pgrep", "-x", "claude"], capture_output=True, timeout=5)
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return True  # be conservative: stay alive


def acquire_pidfile() -> bool:
    core.ensure_dirs()
    existing = core.daemon_pid()
    if existing and existing != os.getpid():
        return False
    core.PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    return True


def pick_items(items: list[dict], cfg: dict, kind: str, tty: str) -> list[dict]:
    """Items whose terminal tab is currently in front, oldest first.
    With queue_policy=latest only the newest item per session survives."""
    focused = [it for it in items if core.item_has_focus(it, cfg, kind, tty)]
    if not focused:
        return []
    if cfg.get("queue_policy", "latest") != "latest":
        return focused
    keep: dict[str, dict] = {}
    for it in focused:
        sid = it.get("session_id", "?")
        previous = keep.get(sid)
        if previous is not None:
            core.drop_queue_item(previous)  # superseded: Claude spoke again since
            core.log(f"dropped superseded item for session={sid[:8]}")
        keep[sid] = it
    return list(keep.values())


def main() -> int:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    if not acquire_pidfile():
        return 0

    core.log(f"daemon up pid={os.getpid()}")
    last_activity = time.time()
    no_claude_since = None

    try:
        while not STOP:
            cfg = core.load_config()
            interval = float(cfg.get("poll_interval", 0.6))

            if not core.global_enabled():
                time.sleep(max(interval, 1.0))
                if time.time() - last_activity > float(cfg.get("idle_exit_seconds", 3600)):
                    break
                continue

            core.prune_queue(float(cfg.get("queue_ttl_seconds", 1800)))
            items = core.list_queue()

            if not items:
                if claude_running():
                    no_claude_since = None
                else:
                    no_claude_since = no_claude_since or time.time()
                    if time.time() - no_claude_since > 120:
                        core.log("no claude session and empty queue, exiting")
                        break
                if time.time() - last_activity > float(cfg.get("idle_exit_seconds", 3600)):
                    core.log("idle timeout, exiting")
                    break
                time.sleep(interval)
                continue

            no_claude_since = None
            kind, tty = core.focus_state(cfg)
            due = pick_items(items, cfg, kind, tty)
            if not due:
                time.sleep(interval)
                continue

            for item in due:
                if STOP:
                    break
                if not core.enabled(item.get("session_id", "")):
                    core.drop_queue_item(item)
                    core.log(f"dropped item: session={item.get('session_id','?')[:8]} is off")
                    continue
                if not cfg.get("speak_when_focused", True) and item.get("focused_at_creation"):
                    core.drop_queue_item(item)
                    continue

                text = item.get("text", "")
                attempts = int(item.get("attempts", 0)) + 1
                base_kind, base_tty = kind, tty

                def still_focused() -> bool:
                    if not cfg.get("stop_on_blur", True):
                        return True
                    now_kind, now_tty = core.focus_state(cfg)
                    return core.item_has_focus(item, cfg, now_kind, now_tty)

                core.log(f"speaking session={item.get('session_id','?')[:8]} "
                         f"kind={item.get('kind')} tty={item.get('tty')} chars={len(text)}")
                result = core.speak_blocking(text, cfg, still_focused)
                last_activity = time.time()

                if result == "done":
                    core.drop_queue_item(item)
                elif result == "aborted" and attempts < 3:
                    item["attempts"] = attempts
                    try:
                        Path(item["_path"]).write_text(
                            json.dumps({k: v for k, v in item.items() if k != "_path"},
                                            ensure_ascii=False), encoding="utf-8")
                    except OSError:
                        core.drop_queue_item(item)
                    core.log("playback aborted (focus lost), will retry on refocus")
                    time.sleep(0.4)
                else:
                    core.drop_queue_item(item)
                    if result == "failed":
                        core.log("playback failed, item dropped")

            time.sleep(interval)
    finally:
        core.PID_FILE.unlink(missing_ok=True)
        core.NOW_PLAYING.unlink(missing_ok=True)
        core.log("daemon down")
    return 0


if __name__ == "__main__":
    sys.exit(main())
