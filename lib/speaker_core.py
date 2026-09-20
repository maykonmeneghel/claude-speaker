"""Core helpers shared by claude-speaker hooks, daemon and CLI.

Stdlib only, macOS oriented. State lives outside the plugin directory so that
reinstalling or updating the plugin never wipes the queue or the config.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

STATE_DIR = Path(os.environ.get("CLAUDE_SPEAKER_HOME", Path.home() / ".claude-speaker"))
QUEUE_DIR = STATE_DIR / "queue"
CACHE_DIR = STATE_DIR / "cache"
SESSIONS_DIR = STATE_DIR / "sessions"
NOTES_DIR = STATE_DIR / "notes"
LOG_FILE = STATE_DIR / "speaker.log"
CONFIG_FILE = STATE_DIR / "config.json"
PID_FILE = STATE_DIR / "speakerd.pid"
DISABLED_FLAG = STATE_DIR / "disabled"
NOW_PLAYING = STATE_DIR / "now-playing.json"

KEYCHAIN_SERVICE = "claude-speaker-elevenlabs"
ELEVEN_BASE = "https://api.elevenlabs.io/v1"

DEFAULT_CONFIG = {
    # engine: auto (ElevenLabs when a key exists, else macOS say) | elevenlabs | say
    "engine": "auto",
    "voice_id": "",
    "voice_name": "",
    "model_id": "eleven_turbo_v2_5",
    "language_code": "pt",
    "output_format": "mp3_44100_128",
    "say_voice": "Luciana",
    "say_rate": 190,
    # text handling
    "max_chars": 700,
    "strip_paths": True,
    # what gets spoken out of a long answer: full | smart (summary + decisions) | manual
    "summary_mode": "smart",
    "summary_chars": 420,
    # sessions with no explicit on/off of their own: on | off
    "pin_ttl_days": 30,
    "session_default": "on",
    # queue behaviour: latest (speak only the newest pending item) | all
    "queue_policy": "latest",
    "notifications": True,
    "speak_when_focused": True,
    "stop_on_blur": True,
    # submitting a new prompt cuts whatever this session is still saying
    "stop_on_prompt": True,
    # so does the microphone going live: dictation must not transcribe the voice
    "stop_on_mic": True,
    "prefetch": True,
    # focus detection: auto | tty | app
    "focus_strategy": "auto",
    "poll_interval": 0.6,
    "idle_exit_seconds": 3600,
    "volume": 1.0,
    "queue_ttl_seconds": 1800,
}

TERMINAL_BUNDLES = {
    "com.apple.Terminal": "terminal",
    "com.googlecode.iterm2": "iterm2",
    "com.mitchellh.ghostty": "ghostty",
    "com.github.wez.wezterm": "wezterm",
    "net.kovidgoyal.kitty": "kitty",
    "org.alacritty": "alacritty",
    "dev.warp.Warp-Stable": "warp",
    "com.microsoft.VSCode": "vscode",
    "com.visualstudio.code.oss": "vscode",
}


# --------------------------------------------------------------------------- #
# state / config
# --------------------------------------------------------------------------- #

def ensure_dirs() -> None:
    # 0700/0600 throughout: queue items and notes hold what Claude just said,
    # which is nobody else's business on a shared machine
    for d in (STATE_DIR, QUEUE_DIR, CACHE_DIR, SESSIONS_DIR, NOTES_DIR):
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            d.chmod(0o700)
        except OSError:
            pass
    _harden_existing()


def _private(path: Path) -> Path:
    """chmod 0600, ignoring a filesystem that will not do it."""
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def _harden_existing() -> None:
    """One-off pass over state written before 0600 was the rule.

    Files already on disk keep their old mode until something rewrites them,
    and a session file or a queue item can sit there for a long time. The
    marker keeps this to a single pass instead of a walk on every call.
    """
    marker = STATE_DIR / ".perms-v1"
    if marker.exists():
        return
    for path in STATE_DIR.rglob("*"):
        if path.is_file():
            _private(path)
    try:
        marker.touch()
        marker.chmod(0o600)
    except OSError:
        pass


def log(msg: str) -> None:
    ensure_dirs()
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {msg}\n")
        _private(LOG_FILE)
        if LOG_FILE.stat().st_size > 2_000_000:
            tail = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-2000:]
            LOG_FILE.write_text("\n".join(tail) + "\n", encoding="utf-8")
    except OSError:
        pass


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg: dict) -> None:
    ensure_dirs()
    keep = {k: v for k, v in cfg.items() if k in DEFAULT_CONFIG or k == "api_key"}
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(keep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(CONFIG_FILE)
    try:
        CONFIG_FILE.chmod(0o600)
    except OSError:
        pass


def global_enabled() -> bool:
    """The master switch: off here means no session speaks, whatever it asked for."""
    return not DISABLED_FLAG.exists()


def set_enabled(on: bool) -> None:
    ensure_dirs()
    if on:
        DISABLED_FLAG.unlink(missing_ok=True)
    else:
        DISABLED_FLAG.write_text(time.strftime("%Y-%m-%d %H:%M:%S") + "\n", encoding="utf-8")


def session_state(session_id: str) -> str:
    """'on' / 'off' when the session decided for itself, '' when it never did."""
    value = str(read_session(session_id).get("speak", "")).lower()
    return value if value in ("on", "off") else ""


def set_session_enabled(session_id: str, on: bool | None) -> str:
    """on=True/False pins this session; on=None drops back to session_default."""
    state = "" if on is None else ("on" if on else "off")
    register_session(session_id, {"speak": state})
    return state


def enabled(session_id: str | None = None) -> bool:
    """Master switch, then this session's own choice, then session_default."""
    if not global_enabled():
        return False
    if not session_id:
        return True
    state = session_state(session_id)
    if state:
        return state == "on"
    return str(load_config().get("session_default", "on")).lower() != "off"


def known_sessions(include_ended: bool = False) -> list[dict]:
    """Live sessions, newest first. Ended ones are kept only for their pin."""
    out = []
    for path in SESSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("ended") and not include_ended:
            continue
        out.append(data)
    return sorted(out, key=lambda d: d.get("updated_at", 0), reverse=True)


def prune_session_pins(cfg: dict | None = None) -> None:
    """Forget pins of sessions that ended long enough ago to be irrelevant."""
    cfg = cfg or load_config()
    try:
        days = float(cfg.get("pin_ttl_days", 30))
    except (TypeError, ValueError):
        days = 30.0
    if days <= 0:
        return
    cutoff = time.time() - days * 86400
    for path in SESSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("ended") and float(data.get("ended_at", 0) or 0) < cutoff:
            path.unlink(missing_ok=True)


def resolve_session_id(explicit: str | None = None) -> str:
    """Which Claude session is asking. Explicit id wins, then the env var, then
    the session registered on this terminal tab, then the only one there is."""
    if explicit:
        return explicit
    for var in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID"):
        env = os.environ.get(var, "").strip()
        if env:
            return env
    sessions = known_sessions()
    tty = tty_of_process_chain()
    if tty:
        # a session registered by the SessionStart hook beats a stray entry
        for only_hooks in (True, False):
            for sess in sessions:  # newest first
                if sess.get("tty") != tty:
                    continue
                if only_hooks and sess.get("origin") != "hook":
                    continue
                return sess.get("session_id", "")
    if len(sessions) == 1:
        return sessions[0].get("session_id", "")
    return ""


def keychain_key() -> str:
    """The key as stored in the login keychain, ignoring the environment."""
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVEN_API_KEY") or ""
    if key.strip():
        return key.strip()
    key = keychain_key()
    if key:
        return key
    # last resort, for a key written into the config by hand
    return str(load_config().get("api_key", "") or "").strip()


def store_api_key(key: str) -> bool:
    """Store the key in the login keychain (never in the plugin directory).

    The key goes in over stdin, not as `-w <key>`: an argument is visible to
    every process on the machine through `ps` for as long as the command runs.
    With `-w` and no value, `security` prompts for the password twice, so the
    key is fed twice. Success is confirmed by reading the key back.
    """
    key = (key or "").strip()
    if not key:
        return False
    try:
        subprocess.run(
            ["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE,
             "-a", os.environ.get("USER", "claude"), "-w"],
            input=f"{key}\n{key}\n", capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return keychain_key() == key


# --------------------------------------------------------------------------- #
# tty / session bookkeeping
# --------------------------------------------------------------------------- #

def _ps_field(pid: int, fmt: str) -> str:
    try:
        out = subprocess.run(["ps", "-o", fmt, "-p", str(pid)],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def tty_of_process_chain(pid: int | None = None, depth: int = 8) -> str:
    """Walk up the parent chain until a real tty shows up (/dev/ttysNNN)."""
    pid = pid or os.getppid()
    for _ in range(depth):
        if pid <= 1:
            break
        tty = _ps_field(pid, "tty=")
        if tty and tty not in ("??", "?"):
            return tty if tty.startswith("/dev/") else f"/dev/{tty}"
        parent = _ps_field(pid, "ppid=")
        if not parent.isdigit():
            break
        pid = int(parent)
    return ""


def session_file(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown")
    return SESSIONS_DIR / f"{safe}.json"


def register_session(session_id: str, extra: dict | None = None) -> dict:
    ensure_dirs()
    path = session_file(session_id)
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
    tty = tty_of_process_chain()
    # a resumed session is live again: clear the flags forget_session left
    data.pop("ended", None)
    data.pop("ended_at", None)
    data.update({
        "session_id": session_id,
        "tty": tty or data.get("tty", ""),
        "term_program": os.environ.get("TERM_PROGRAM", data.get("term_program", "")),
        "term_session_id": os.environ.get("TERM_SESSION_ID", data.get("term_session_id", "")),
        "iterm_session_id": os.environ.get("ITERM_SESSION_ID", data.get("iterm_session_id", "")),
        "cwd": os.environ.get("CLAUDE_PROJECT_DIR", data.get("cwd", "")) or os.getcwd(),
        "updated_at": time.time(),
    })
    if extra:
        data.update(extra)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    _private(path)
    prune_session_pins()
    return data


def read_session(session_id: str) -> dict:
    try:
        return json.loads(session_file(session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def forget_session(session_id: str) -> None:
    """Drop what is only true while the session runs, but keep an explicit pin.

    SessionEnd fires whenever a session ends, and a resumed session comes back
    under the same id — deleting the file threw the user's `speak on` away with
    the tty, so the voice they had turned on came back silent on the default.
    What is kept is the pin alone, flagged as ended so a stale one can be pruned
    and so it does not look like a live session anywhere.
    """
    path = session_file(session_id)
    state = session_state(session_id)
    if state:
        kept = {"session_id": session_id, "speak": state,
                "ended": True, "ended_at": time.time()}
        path.write_text(json.dumps(kept, indent=2, ensure_ascii=False), encoding="utf-8")
        _private(path)
    else:
        path.unlink(missing_ok=True)
    for item in list_queue():
        if item.get("session_id") == session_id:
            drop_queue_item(item)


# --------------------------------------------------------------------------- #
# text cleanup
# --------------------------------------------------------------------------- #

_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF←-⇿⬀-⯿️✅❌]"
)


# --------------------------------------------------------------------------- #
# spoken notes / summary extraction
# --------------------------------------------------------------------------- #

def note_file(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown")
    return NOTES_DIR / f"{safe}.txt"


def put_note(session_id: str, text: str) -> Path:
    """Claude leaves here the exact sentence it wants spoken for this turn."""
    ensure_dirs()
    path = note_file(session_id)
    path.write_text((text or "").strip() + "\n", encoding="utf-8")
    return _private(path)


def take_note(session_id: str) -> str:
    """Read and consume the note: it applies to one turn only."""
    path = note_file(session_id)
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    path.unlink(missing_ok=True)
    return text


_SUMMARY_HEADING = re.compile(
    r"resumo|sum[\u00e1a]rio|summary|decis|conclus|pr[\u00f3o]ximos?\s+passos|"
    r"next\s+steps|tl;?dr|o que (?:falta|muda|fazer|voc[\u00ea])",
    re.IGNORECASE)

_DECISION_HINT = re.compile(
    r"\?|decis|decidir|escolh|confirm|prefere|quer que|aprova|autoriza|"
    r"me diga|qual (?:op[\u00e7c]|caminho)|voc[\u00ea] precisa",
    re.IGNORECASE)


def _drop_heavy_blocks(raw: str) -> str:
    s = re.sub(r"```.*?```", "", raw, flags=re.DOTALL)       # code fences
    s = re.sub(r"(?m)^\s*\|.*\|\s*$\n?", "", s)             # table rows
    return s


def speech_digest(raw: str, cfg: dict | None = None) -> str:
    """Cut a long answer down to what is worth hearing: the summary section if
    the answer has one, otherwise the opening line, the questions left for the
    user, and the closing paragraph. summary_mode=full keeps everything."""
    cfg = cfg or load_config()
    mode = str(cfg.get("summary_mode", "smart")).lower()
    if mode == "full" or not raw.strip():
        return raw
    body = _drop_heavy_blocks(raw)
    sections = re.split(r"(?m)^(?=\s{0,3}#{1,6}\s)", body)
    summary_sections = [sec for sec in sections
                        if _SUMMARY_HEADING.search(sec.split("\n", 1)[0])]
    if summary_sections:
        return "\n".join(sec.strip() for sec in summary_sections)
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    if not paras:
        return ""
    if len(paras) <= 2:
        return "\n".join(paras)
    lead, closing = paras[0], paras[-1]
    asks = [p for p in paras[1:-1] if _DECISION_HINT.search(p)][-2:]
    return "\n".join([lead] + asks + [closing])


def spoken_limit(cfg: dict) -> int:
    mode = str(cfg.get("summary_mode", "smart")).lower()
    if mode == "full":
        return int(cfg.get("max_chars", 700))
    return min(int(cfg.get("summary_chars", 420)), int(cfg.get("max_chars", 700)))


def clean_text(raw: str, max_chars: int = 700, strip_paths: bool = True) -> str:
    if not raw:
        return ""
    s = raw

    # fenced code blocks -> short spoken placeholder
    s = re.sub(r"```[\w+-]*\n.*?```", " (bloco de código) ", s, flags=re.DOTALL)
    s = re.sub(r"```.*?```", " (bloco de código) ", s, flags=re.DOTALL)
    # markdown tables -> comma separated, drop separator rows
    s = re.sub(r"^\s*\|?[\s:|-]{6,}\|?\s*$", "", s, flags=re.MULTILINE)
    s = re.sub(r"[ \t]*\|[ \t]*", ", ", s)
    # links / images
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"<(https?://[^>]+)>", " link ", s)
    s = re.sub(r"https?://\S+", " link ", s)
    # inline code and emphasis
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"__([^_]+)__", r"\1", s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"\1", s)
    s = re.sub(r"~~([^~]+)~~", r"\1", s)
    # headings, quotes, bullets, task boxes
    s = re.sub(r"^\s{0,3}#{1,6}\s*", "", s, flags=re.MULTILINE)
    s = re.sub(r"^\s{0,3}>\s?", "", s, flags=re.MULTILINE)
    s = re.sub(r"^\s*[-*+]\s+\[[ xX]\]\s*", "", s, flags=re.MULTILINE)
    s = re.sub(r"^\s*[-*+]\s+", "", s, flags=re.MULTILINE)
    s = re.sub(r"^\s*\d+[.)]\s+", "", s, flags=re.MULTILINE)
    s = re.sub(r"^\s*[-=_*]{3,}\s*$", "", s, flags=re.MULTILINE)
    # long paths -> basename, so the voice does not spell whole directories
    if strip_paths:
        s = re.sub(r"(?:~|\.{0,2}/)[\w.@+\-]+(?:/[\w.@+\-]+){1,}/?",
                   lambda m: os.path.basename(m.group(0).rstrip("/")) or "arquivo", s)
    s = _EMOJI.sub(" ", s)
    # spoken punctuation cleanup
    s = s.replace("→", " para ").replace("—", ", ").replace("–", ", ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{2,}", "\n", s)
    lines = [ln.strip() for ln in s.split("\n") if ln.strip()]
    s = ". ".join(ln.rstrip(".;:") for ln in lines)
    s = re.sub(r"\.{2,}", ".", s)
    s = re.sub(r"\s+([.,;:!?])", r"\1", s).strip()

    if max_chars and len(s) > max_chars:
        head = s[:max_chars]
        cut = max(head.rfind(". "), head.rfind("! "), head.rfind("? "))
        s = (head[: cut + 1] if cut > max_chars * 0.4 else head.rstrip() + "…")
    return s.strip()


# --------------------------------------------------------------------------- #
# queue
# --------------------------------------------------------------------------- #

def enqueue(text: str, session_id: str, kind: str = "stop", extra: dict | None = None) -> Path | None:
    text = (text or "").strip()
    if not text:
        return None
    ensure_dirs()
    sess = read_session(session_id)
    tty = tty_of_process_chain() or sess.get("tty", "")
    item = {
        "id": f"{time.time():.6f}",
        "kind": kind,
        "text": text,
        "session_id": session_id,
        "tty": tty,
        "term_program": os.environ.get("TERM_PROGRAM", sess.get("term_program", "")),
        "cwd": os.getcwd(),
        "created_at": time.time(),
    }
    if extra:
        item.update(extra)
    cfg = load_config()
    if not cfg.get("speak_when_focused", True):
        # only needed by this mode, and it costs an AppleScript round-trip
        try:
            kind, active = focus_state(cfg)
            item["focused_at_creation"] = item_has_focus(item, cfg, kind, active)
        except Exception:
            item["focused_at_creation"] = False
    path = QUEUE_DIR / f"{item['id']}-{os.getpid()}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
    _private(tmp)
    tmp.replace(path)
    return path


def list_queue() -> list[dict]:
    ensure_dirs()
    items = []
    for path in sorted(QUEUE_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            path.unlink(missing_ok=True)
            continue
        data["_path"] = str(path)
        items.append(data)
    items.sort(key=lambda d: d.get("created_at", 0))
    return items


def drop_queue_item(item: dict) -> None:
    p = item.get("_path")
    if p:
        Path(p).unlink(missing_ok=True)


def prune_queue(ttl: float) -> None:
    if ttl <= 0:
        return
    now = time.time()
    for item in list_queue():
        if now - item.get("created_at", now) > ttl:
            drop_queue_item(item)


# --------------------------------------------------------------------------- #
# focus detection (macOS)
# --------------------------------------------------------------------------- #

def frontmost_bundle() -> str:
    try:
        asn = subprocess.run(["lsappinfo", "front"], capture_output=True, text=True,
                             timeout=5).stdout.strip()
        if not asn:
            return ""
        out = subprocess.run(["lsappinfo", "info", "-only", "bundleID", asn],
                             capture_output=True, text=True, timeout=5).stdout
        m = re.search(r'"CFBundleIdentifier"\s*=\s*"([^"]+)"', out)
        return m.group(1) if m else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _osascript(script: str) -> str:
    try:
        out = subprocess.run(["osascript", "-e", script], capture_output=True,
                             text=True, timeout=8)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def active_tty(bundle: str) -> str:
    """tty of the tab/pane currently selected in the frontmost terminal."""
    if bundle == "com.apple.Terminal":
        return _osascript('tell application "Terminal" to get tty of selected tab of front window')
    if bundle == "com.googlecode.iterm2":
        return _osascript(
            'tell application "iTerm2" to tell current session of current tab of current window to get tty'
        )
    return ""


def focus_state(cfg: dict) -> tuple[str, str]:
    """Returns (terminal_kind, active_tty). terminal_kind is '' when the
    frontmost app is not a known terminal."""
    bundle = frontmost_bundle()
    kind = TERMINAL_BUNDLES.get(bundle, "")
    if not kind:
        return "", ""
    if cfg.get("focus_strategy") == "app":
        return kind, ""
    return kind, active_tty(bundle)


def item_has_focus(item: dict, cfg: dict, kind: str, tty: str) -> bool:
    if not kind:
        return False
    strategy = cfg.get("focus_strategy", "auto")
    item_tty = item.get("tty", "")
    if strategy != "app" and tty and item_tty:
        return os.path.basename(tty) == os.path.basename(item_tty)
    # Terminals without a scripting interface (ghostty, kitty, wezterm...):
    # fall back to "the terminal app that owns this session is frontmost".
    term_program = (item.get("term_program") or "").lower()
    aliases = {
        "terminal": ("apple_terminal",),
        "iterm2": ("iterm.app",),
        "ghostty": ("ghostty",),
        "wezterm": ("wezterm",),
        "kitty": ("kitty",),
        "alacritty": ("alacritty",),
        "warp": ("warpterminal",),
        "vscode": ("vscode",),
    }
    if term_program:
        return term_program in aliases.get(kind, ()) or term_program == kind
    return True


# --------------------------------------------------------------------------- #
# synthesis + playback
# --------------------------------------------------------------------------- #

def engine_in_use(cfg: dict) -> str:
    engine = cfg.get("engine", "auto")
    if engine == "elevenlabs":
        return "elevenlabs"
    if engine == "say":
        return "say"
    return "elevenlabs" if api_key() else "say"


def _ssl_context():
    """Some Python builds (Homebrew) ship without a usable CA bundle, which makes
    every ElevenLabs call die with CERTIFICATE_VERIFY_FAILED. Prefer certifi."""
    try:
        import ssl
    except ImportError:
        return None
    for cafile in (os.environ.get("SSL_CERT_FILE"), _certifi_path()):
        if cafile and os.path.isfile(cafile):
            try:
                return ssl.create_default_context(cafile=cafile)
            except OSError:
                continue
    try:
        return ssl.create_default_context()
    except (OSError, ValueError):
        return None


def _certifi_path() -> str:
    try:
        import certifi
        return certifi.where()
    except Exception:
        return ""


def _eleven_request(path: str, payload: dict | None = None, method: str = "GET",
                    timeout: int = 45) -> tuple[int, bytes, str]:
    key = api_key()
    if not key:
        return 0, b"", "no api key"
    url = f"{ELEVEN_BASE}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("xi-api-key", key)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            return resp.status, resp.read(), ""
    except urllib.error.HTTPError as exc:
        body = exc.read()[:400].decode("utf-8", "replace")
        return exc.code, b"", body
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return 0, b"", str(exc)


def list_voices() -> list[dict]:
    status, body, err = _eleven_request("/voices")
    if status != 200:
        log(f"list_voices failed: {status} {err}")
        return []
    try:
        return json.loads(body).get("voices", [])
    except ValueError:
        return []


def subscription() -> dict:
    """The account's plan, or {} when there is no key or the call fails."""
    status, body, _ = _eleven_request("/user/subscription")
    if status != 200:
        return {}
    try:
        return json.loads(body)
    except ValueError:
        return {}


def voice_usable(voice: dict, sub: dict | None = None) -> bool:
    """Whether the account can actually synthesize with this voice.

    A free account lists library voices in /voices but the TTS call answers
    402 paid_plan_required, and the plugin quietly falls back to `say`. The
    voices bundled with every account (category "premade") always work.
    """
    if (voice.get("category") or "") == "premade":
        return True
    sub = subscription() if sub is None else sub
    return (sub.get("tier") or "free") != "free"


def resolve_voice(cfg: dict) -> str:
    vid = (cfg.get("voice_id") or "").strip()
    if vid:
        return vid
    voices = list_voices()
    if voices:
        vid = voices[0].get("voice_id", "")
        cfg["voice_id"] = vid
        cfg["voice_name"] = voices[0].get("name", "")
        save_config(cfg)
        log(f"voice auto-selected: {cfg['voice_name']} ({vid})")
    return vid


def cache_path(text: str, cfg: dict) -> Path:
    sig = json.dumps({
        "t": text, "v": cfg.get("voice_id"), "m": cfg.get("model_id"),
        "l": cfg.get("language_code"), "f": cfg.get("output_format"),
    }, sort_keys=True, ensure_ascii=False)
    return CACHE_DIR / (hashlib.sha256(sig.encode("utf-8")).hexdigest()[:32] + ".mp3")


def synthesize(text: str, cfg: dict | None = None) -> Path | None:
    """ElevenLabs TTS with on-disk cache. Returns None when unavailable."""
    cfg = cfg or load_config()
    if engine_in_use(cfg) != "elevenlabs":
        return None
    ensure_dirs()
    voice = resolve_voice(cfg)
    if not voice:
        return None
    out = cache_path(text, cfg)
    if out.exists() and out.stat().st_size > 1024:
        return out
    payload = {
        "text": text,
        "model_id": cfg.get("model_id", "eleven_turbo_v2_5"),
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "speed": 1.0},
    }
    lang = (cfg.get("language_code") or "").strip()
    model = payload["model_id"]
    if lang and ("turbo_v2_5" in model or "flash" in model):
        payload["language_code"] = lang  # only these models accept it
    fmt = cfg.get("output_format", "mp3_44100_128")
    status, body, err = _eleven_request(
        f"/text-to-speech/{voice}?output_format={fmt}", payload, method="POST"
    )
    if status != 200 or not body:
        log(f"tts failed ({status}): {err[:200]}")
        return None
    tmp = out.with_suffix(".part")
    tmp.write_bytes(body)
    tmp.replace(out)
    prune_cache()
    return out


def prune_cache(max_files: int = 400) -> None:
    files = sorted(CACHE_DIR.glob("*.mp3"), key=lambda p: p.stat().st_mtime)
    for path in files[:-max_files]:
        path.unlink(missing_ok=True)


def play_file(path: Path, cfg: dict) -> subprocess.Popen | None:
    if not shutil.which("afplay"):
        return None
    vol = str(cfg.get("volume", 1.0))
    return subprocess.Popen(["afplay", "-v", vol, str(path)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def play_say(text: str, cfg: dict) -> subprocess.Popen | None:
    cmd = ["say"]
    voice = cfg.get("say_voice")
    if voice:
        cmd += ["-v", str(voice)]
    rate = cfg.get("say_rate")
    if rate:
        cmd += ["-r", str(rate)]
    cmd.append(text)
    try:
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return None


# --------------------------------------------------------------------------- #
# microphone: is anything capturing right now? (CoreAudio)
# --------------------------------------------------------------------------- #

_CORE_AUDIO: object = "unset"


def _core_audio():
    """The CoreAudio framework, or None where it cannot be loaded."""
    global _CORE_AUDIO
    if _CORE_AUDIO == "unset":
        try:
            _CORE_AUDIO = ctypes.CDLL(
                "/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
        except OSError:
            _CORE_AUDIO = None
    return _CORE_AUDIO


class _AudioAddress(ctypes.Structure):
    _fields_ = [("selector", ctypes.c_uint32),
                ("scope", ctypes.c_uint32),
                ("element", ctypes.c_uint32)]


def _fourcc(code: str) -> int:
    return struct.unpack(">I", code.encode("ascii"))[0]


def _audio_u32(obj: int, selector: int) -> int | None:
    """One UInt32 audio object property, or None if it cannot be read."""
    ca = _core_audio()
    if ca is None:
        return None
    addr = _AudioAddress(selector, _fourcc("glob"), 0)  # scope global, element main
    out = ctypes.c_uint32(0)
    size = ctypes.c_uint32(ctypes.sizeof(out))
    try:
        status = ca.AudioObjectGetPropertyData(
            ctypes.c_uint32(obj), ctypes.byref(addr), ctypes.c_uint32(0), None,
            ctypes.byref(size), ctypes.byref(out))
    except Exception:  # a framework that answers differently must not break audio
        return None
    return out.value if status == 0 else None


def microphone_live() -> bool | None:
    """Whether some process is capturing from the default input device.

    Reading kAudioDevicePropertyDeviceIsRunningSomewhere is a property query,
    not a recording, so it needs no microphone permission and shows nothing in
    the menu bar. None means CoreAudio would not answer — callers must not read
    that as "quiet", or a machine that cannot tell would cut every utterance."""
    device = _audio_u32(1, _fourcc("dIn "))  # system object -> default input
    if not device:
        return None
    running = _audio_u32(device, _fourcc("gone"))
    return None if running is None else bool(running)


def request_cancel(session_id: str) -> None:
    """Record that what this session is being told is no longer wanted.

    A timestamp rather than a flag, so an utterance that starts *after* the
    request is left alone: only playback older than the mark is cut."""
    if not session_id:
        return
    ensure_dirs()
    path = session_file(session_id)
    data = read_session(session_id)
    data["session_id"] = session_id
    data["cancel_at"] = time.time()
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        return
    _private(path)


def cancel_requested(session_id: str, since: float) -> bool:
    """Whether this session asked to be quiet after `since`."""
    if not session_id:
        return False
    try:
        return float(read_session(session_id).get("cancel_at", 0)) > since
    except (TypeError, ValueError):
        return False


def _end_playback(proc) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()


def speak_blocking(text: str, cfg: dict | None = None, should_continue=None,
                   session_id: str = "") -> str:
    """Speak `text`; returns 'done', 'cancelled', 'aborted' or 'failed'.

    `should_continue` is polled while audio plays (used to stop on blur).
    `session_id` lets the session cut its own playback mid-sentence: the daemon
    owns this process, so a new prompt only has to leave a mark for it to read —
    nothing has to go hunting for players to kill."""
    cfg = cfg or load_config()
    audio = synthesize(text, cfg)
    proc = play_file(audio, cfg) if audio else play_say(text, cfg)
    if proc is None:
        return "failed"
    started_at = time.time()
    NOW_PLAYING.write_text(
        json.dumps({"pid": proc.pid, "started_at": started_at,
                    "session_id": session_id}),
        encoding="utf-8")
    _private(NOW_PLAYING)
    last_poll = started_at
    watch_mic = bool(cfg.get("stop_on_mic", True))
    # A microphone already capturing when the utterance starts — a call, a
    # recording — must not silence the plugin outright. Only a rising edge
    # during playback means someone has just started talking to Claude.
    mic_was_live = microphone_live() if watch_mic else None
    try:
        while proc.poll() is None:
            if should_continue and not should_continue():
                _end_playback(proc)
                return "aborted"
            if watch_mic:
                live = microphone_live()
                if live is not None:
                    if live and mic_was_live is False:
                        log("playback cut: the microphone went live")
                        _end_playback(proc)
                        return "cancelled"
                    mic_was_live = live
            now = time.time()
            if session_id and now - last_poll >= 0.25:
                last_poll = now
                if cancel_requested(session_id, started_at):
                    log("playback cut: a new prompt was submitted")
                    _end_playback(proc)
                    return "cancelled"
            time.sleep(0.15)
    finally:
        NOW_PLAYING.unlink(missing_ok=True)
    return "done" if proc.returncode == 0 else "failed"


def stop_playback() -> int:
    killed = 0
    for name in ("afplay", "say"):
        try:
            out = subprocess.run(["pkill", "-x", name], capture_output=True, timeout=5)
            if out.returncode == 0:
                killed += 1
        except (OSError, subprocess.SubprocessError):
            pass
    NOW_PLAYING.unlink(missing_ok=True)
    return killed


# --------------------------------------------------------------------------- #
# daemon lifecycle
# --------------------------------------------------------------------------- #

def daemon_pid() -> int:
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0
    try:
        os.kill(pid, 0)
    except OSError:
        return 0
    return pid


def ensure_daemon(plugin_root: str | None = None) -> int:
    pid = daemon_pid()
    if pid:
        return pid
    root = Path(plugin_root or os.environ.get("CLAUDE_PLUGIN_ROOT")
                or Path(__file__).resolve().parent.parent)
    script = root / "bin" / "speakerd.py"
    if not script.exists():
        log(f"daemon script not found at {script}")
        return 0
    ensure_dirs()
    with open(LOG_FILE, "a") as logfh:
        proc = subprocess.Popen(
            [sys.executable or "python3", str(script)],
            stdout=logfh, stderr=logfh, stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    log(f"daemon started pid={proc.pid}")
    return proc.pid
