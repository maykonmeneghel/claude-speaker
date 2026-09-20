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


def supersedes(newer: dict, older: dict) -> bool:
    """Whether `newer` replaces `older`, both queued by the same session.

    Newest wins, with one exception: a notification carries a generic line
    ("Claude is waiting for your input"), so it must never discard an answer
    summary that has not been spoken yet — the summary is the whole point."""
    if older.get("kind") == "stop" and newer.get("kind") != "stop":
        return False
    return True


def pick_items(items: list[dict], cfg: dict, kind: str, tty: str) -> list[dict]:
    """Items whose terminal tab is currently in front, oldest first.
    With queue_policy=latest only one item per session survives."""
    focused = [it for it in items if core.item_has_focus(it, cfg, kind, tty)]
    if not focused:
        return []
    if cfg.get("queue_policy", "latest") != "latest":
        return focused
    keep: dict[str, dict] = {}
    for it in focused:  # oldest first, so `it` is always the newer of the pair
        sid = it.get("session_id", "?")
        previous = keep.get(sid)
        if previous is None:
            keep[sid] = it
            continue
        if supersedes(it, previous):
            core.drop_queue_item(previous)
            core.log(f"dropped superseded {previous.get('kind', '?')} item "
                     f"for session={sid[:8]}")
            keep[sid] = it
        else:
            core.drop_queue_item(it)
            core.log(f"dropped {it.get('kind', '?')} item for session={sid[:8]}: "
                     f"an unspoken summary outranks it")
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
                result = core.speak_blocking(text, cfg, still_focused,
                                             session_id=item.get("session_id", ""))
                last_activity = time.time()

                if result in ("done", "cancelled"):
                    core.drop_queue_item(item)
                    if result == "cancelled":
                        core.log("cut playback counted as spoken, item dropped")
                elif result == "aborted" and attempts < 3:
                    # A retry must never resurrect an item something else dropped
                    # in the meantime — writing the file back would recreate it.
                    if not Path(item["_path"]).exists():
                        core.log("playback aborted, but the item is already gone")
                        continue
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
