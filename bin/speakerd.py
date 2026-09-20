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


def save_item(item: dict, **fields) -> bool:
    """Write `fields` back into the queued item. False when the item is gone.

    A retry must never resurrect something that was dropped in the meantime —
    writing the file back would recreate it."""
    path = Path(item.get("_path", ""))
    if not path.exists():
        return False
    item.update(fields)
    try:
        path.write_text(json.dumps({k: v for k, v in item.items() if k != "_path"},
                                   ensure_ascii=False), encoding="utf-8")
    except OSError:
        core.drop_queue_item(item)
        return False
    return True


class BlurWatch:
    """Decides whether playback should keep going, one poll at a time.

    Playback is only cut once several consecutive polls agree that the tab is
    no longer in front. A single negative reading is a notification banner
    stealing focus for an instant, or lsappinfo hiccuping — neither is the user
    walking away, and cutting on one of them truncates the answer for nothing.
    A poll macOS refused to answer counts for neither side."""

    def __init__(self, item: dict, cfg: dict):
        self.item = item
        self.cfg = cfg
        self.grace = max(1, int(cfg.get("blur_grace_polls", 3)))
        self.streak = 0

    def __call__(self) -> bool:
        if not self.cfg.get("stop_on_blur", True):
            return True
        kind, tty, answered = core.focus_state_ex(self.cfg)
        if not answered:
            return True
        if core.item_has_focus(self.item, self.cfg, kind, tty):
            self.streak = 0
            return True
        self.streak += 1
        return self.streak < self.grace


def speak_item(item: dict, cfg: dict) -> None:
    """Speak one queued item and decide what becomes of it."""
    text = item.get("text", "")
    fragments = core.split_for_speech(text, core.spoken_limit(cfg))
    if not fragments:
        core.drop_queue_item(item)
        return
    start = min(int(item.get("spoken_upto", 0)), len(fragments) - 1)
    attempts = int(item.get("attempts", 0)) + 1
    max_attempts = max(1, int(cfg.get("max_attempts", 6)))
    session_id = item.get("session_id", "")

    core.log(f"speaking session={session_id[:8] or '?'} kind={item.get('kind')} "
             f"tty={item.get('tty')} chars={len(text)} fragments={len(fragments)}"
             + (f" resuming at {start + 1}" if start else ""))
    result, spoken_upto = core.speak_sequence(
        fragments, cfg, BlurWatch(item, cfg), session_id=session_id, start=start)

    left = f"{spoken_upto + 1}/{len(fragments)}"
    if result == "done":
        core.drop_queue_item(item)
    elif result == "cancelled":
        # A new prompt: the rest describes the wrong question now.
        core.drop_queue_item(item)
        core.log("cut by a new prompt, item dropped")
    elif result == "muted":
        # The microphone went live, so the user is dictating — they did not
        # ask for the summary to be thrown away. Keep the rest and stand back
        # rather than fighting the dictation for the speaker.
        backoff = float(cfg.get("mute_backoff_seconds", 5.0))
        if save_item(item, spoken_upto=spoken_upto, muted_until=time.time() + backoff):
            core.log(f"muted by the microphone at fragment {left}, will resume")
    elif result == "aborted" and attempts < max_attempts:
        if save_item(item, spoken_upto=spoken_upto, attempts=attempts):
            core.log(f"playback aborted (focus lost) at fragment {left}, "
                     f"will resume on refocus")
        else:
            core.log("playback aborted, but the item is already gone")
        time.sleep(0.4)
    else:
        core.drop_queue_item(item)
        core.log(f"item dropped: {result} at fragment {left} "
                 f"after {attempts} attempt(s)")


def cycle(cfg: dict, state: dict) -> bool:
    """One pass over the queue. False asks the daemon to exit."""
    core.prune_queue(float(cfg.get("queue_ttl_seconds", 1800)))
    items = core.list_queue()

    if not items:
        if claude_running():
            state["no_claude_since"] = None
        else:
            state["no_claude_since"] = state["no_claude_since"] or time.time()
            if time.time() - state["no_claude_since"] > 120:
                core.log("no claude session and empty queue, exiting")
                return False
        if time.time() - state["last_activity"] > float(cfg.get("idle_exit_seconds", 3600)):
            core.log("idle timeout, exiting")
            return False
        return True

    state["no_claude_since"] = None
    kind, tty = core.focus_state(cfg)
    for item in pick_items(items, cfg, kind, tty):
        if STOP:
            break
        if float(item.get("muted_until", 0)) > time.time():
            continue
        if not core.enabled(item.get("session_id", "")):
            core.drop_queue_item(item)
            core.log(f"dropped item: session={item.get('session_id','?')[:8]} is off")
            continue
        # An acknowledgement exists to answer a prompt the user just typed, so
        # of course the tab was in front: speak_when_focused must not silence it.
        if (not cfg.get("speak_when_focused", True)
                and item.get("focused_at_creation")
                and not item.get("always")):
            core.drop_queue_item(item)
            continue
        if item.get("kind") == "ack":
            age = time.time() - float(item.get("created_at", 0))
            if age > float(cfg.get("ack_ttl_seconds", 20)):
                core.drop_queue_item(item)
                core.log(f"dropped a stale ack ({age:.0f}s old)")
                continue
        speak_item(item, cfg)
        state["last_activity"] = time.time()
    return True


def main() -> int:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    if not acquire_pidfile():
        return 0

    core.log(f"daemon up pid={os.getpid()}")
    state = {"last_activity": time.time(), "no_claude_since": None}

    try:
        while not STOP:
            cfg = core.load_config()
            interval = float(cfg.get("poll_interval", 0.6))
            try:
                if not core.global_enabled():
                    time.sleep(max(interval, 1.0))
                    if time.time() - state["last_activity"] > float(
                            cfg.get("idle_exit_seconds", 3600)):
                        break
                    continue
                if not cycle(cfg, state):
                    break
            except Exception as exc:
                # One bad item, a vanished cache file, a CoreAudio hiccup: the
                # daemon logs it and keeps its queue rather than dying and
                # taking every pending summary with it.
                core.log(f"daemon loop error: {exc!r}")
                time.sleep(1.0)
            time.sleep(interval)
    finally:
        core.PID_FILE.unlink(missing_ok=True)
        core.NOW_PLAYING.unlink(missing_ok=True)
        core.log("daemon down")
    return 0


if __name__ == "__main__":
    sys.exit(main())
