# claude-speaker

Gives Claude Code a voice. Every time Claude finishes a turn, the plugin queues a
**short spoken version** of the last message — the summary and whatever decision it
is asking for, not the whole answer; the moment the terminal tab running *that*
session regains focus, the text is spoken through ElevenLabs. Come back to the tab
and you hear what Claude did and what it is waiting on, instead of reading it.

Speaking is decided **per session**: `/speaker-on` and `/speaker-off` affect only the
session you run them in, so one tab can talk while the others stay quiet.

```
Stop hook ──► queue item (text + tty of the session)
                      │
SessionStart hook ──► speakerd (one daemon, all sessions)
                      │  polls: which terminal tab is in front?
                      └──► tab tty == item tty ──► ElevenLabs ──► afplay
```

## Requirements

- macOS (uses `lsappinfo`, `osascript`, `afplay`, `say`)
- Python 3.9+ (stdlib only)
- An ElevenLabs API key — optional: without one the plugin falls back to the
  built-in macOS voice (`say -v Luciana`), so it works before you configure anything.

## Install

```bash
claude plugin marketplace add maykonmeneghel/claude-speaker
claude plugin install claude-speaker@meneghel-local
```

Or, from a local clone:

```bash
git clone https://github.com/maykonmeneghel/claude-speaker.git ~/claude-speaker
claude plugin marketplace add ~/claude-speaker
claude plugin install claude-speaker@meneghel-local
```

Then, inside Claude Code:

```
/claude-speaker:speaker-setup <your-elevenlabs-key>   # stores it in the login keychain
/claude-speaker:speaker-doctor                        # end-to-end check
/claude-speaker:speaker-test                          # hear the voice now
```

The key goes into the macOS keychain (service `claude-speaker-elevenlabs`), or
comes from `ELEVENLABS_API_KEY`. It is never written into this repository.

The first time the daemon asks Terminal/iTerm2 which tab is selected, macOS
shows an automation prompt. Approve it (System Settings → Privacy & Security →
Automation) — without it, focus detection falls back to "the terminal app is in
front", which speaks in the wrong tab when several sessions run side by side.

## Commands

| Command | What it does |
| --- | --- |
| `/claude-speaker:speaker-status` | engine, voice, daemon, focused tab, pending queue |
| `/claude-speaker:speaker-on` / `-off` | speak / stay quiet **in this session**; add `--global` for all |
| `/claude-speaker:speaker-sessions` | every known session and whether it speaks |
| `/claude-speaker:speaker-summary [smart\|full\|manual]` | how much of each answer is spoken |
| `/claude-speaker:speaker-stop` | stop the audio playing right now |
| `/claude-speaker:speaker-test [text]` | speak immediately, ignoring focus |
| `/claude-speaker:speaker-voices` | list the voices on the account |
| `/claude-speaker:speaker-setup` | store the API key and pick a voice |
| `/claude-speaker:speaker-doctor` | diagnose key, tty, focus, daemon, hooks |

The same things work from a shell, without Claude: `~/claude-speaker/bin/speak status`,
`speak queue "texto"`, `speak set max_chars 400`, `speak log 50`, `speak daemon restart`.

## Who speaks: three levels

| Level | Command | Meaning |
| --- | --- | --- |
| master switch | `speak on --global` / `off --global` | off here and **nothing** speaks anywhere |
| this session | `speak on` / `speak off` | pins one session; the others are untouched |
| everyone else | `speak default on\|off` | what a session does before anyone pins it |

`speak auto` drops a session's pin so it follows the default again, and `speak sessions`
prints the three levels side by side. Outside a Claude session, `speak` finds the session
by `CLAUDE_CODE_SESSION_ID`, then by the terminal tab it runs in; `--session <id>` is always
available. A session's pin lives in its file under `sessions/` and disappears when it ends.

## What gets spoken

`summary_mode` decides how much of the answer reaches the voice:

| Mode | Spoken |
| --- | --- |
| `smart` (default) | the section titled Resumo / Decisões / Próximos passos if there is one, otherwise the opening line, the questions left for you and the closing paragraph — capped at `summary_chars` (420) |
| `full` | the whole answer, capped at `max_chars` (700) |
| `manual` | nothing, unless Claude left a line with `speak note "..."` |

`speak note "texto"` always wins for the turn it was written in: the Stop hook consumes
the note and speaks it instead of the answer. Code blocks and tables never reach the voice.

## Configuration

`~/.claude-speaker/config.json` (edit with `speak set <key> <value>`):

| Key | Default | Meaning |
| --- | --- | --- |
| `engine` | `auto` | `auto` (ElevenLabs when a key exists) / `elevenlabs` / `say` |
| `voice_id`, `voice_name` | – | chosen ElevenLabs voice |
| `model_id` | `eleven_turbo_v2_5` | `eleven_flash_v2_5` is cheaper and faster |
| `language_code` | `pt` | sent only for turbo/flash models |
| `say_voice` | `Luciana` | fallback macOS voice |
| `max_chars` | `700` | hard cap per utterance (ElevenLabs bills per character) |
| `summary_mode` | `smart` | `smart` / `full` / `manual` — see *What gets spoken* |
| `summary_chars` | `420` | cap for the summary modes |
| `session_default` | `on` | what a session does before anyone runs `speak on`/`off` in it |
| `queue_policy` | `latest` | `latest` speaks only the newest message per session; `all` speaks every one |
| `notifications` | `true` | also speak permission prompts and idle notifications |
| `speak_when_focused` | `true` | `false` = only speak messages produced while the tab was *not* in front |
| `stop_on_blur` | `true` | leaving the tab interrupts the audio (it retries on return, up to 3×) |
| `prefetch` | `true` | synthesize at Stop time so playback is instant when you come back |
| `focus_strategy` | `auto` | `tty` (exact tab, needs AppleScript) / `app` (terminal app in front) |
| `poll_interval` | `0.6` | seconds between focus checks |
| `idle_exit_seconds` | `3600` | daemon exits after this long with nothing to do |
| `queue_ttl_seconds` | `1800` | items older than this are dropped unspoken |
| `volume` | `1.0` | `afplay -v` |

## How the text is prepared

Markdown is turned into something worth listening to before it reaches the API:
code fences become "bloco de código", links and URLs collapse, long paths shrink
to the file name, headings/bullets/tables/emoji are stripped, and the result is
truncated at a sentence boundary within `max_chars`. Identical text is cached on
disk, so repeats and retries cost nothing.

## State

Everything mutable lives in `~/.claude-speaker/`: `config.json`, `queue/`,
`cache/` (mp3), `sessions/` (session → tty map, plus its `speak` pin), `notes/`
(one-turn notes), `speaker.log`, `speakerd.pid`.
Uninstalling the plugin leaves that directory untouched; delete it by hand to
reset.

## Known limits

- macOS only.
- Exact-tab detection works on Terminal.app and iTerm2. Ghostty, kitty, WezTerm,
  Alacritty and Warp have no tab-tty scripting API, so those fall back to
  app-level focus (`focus_strategy=app`).
- `tmux`/`screen` panes report the tty of the outer terminal, so a session inside
  a multiplexer is matched at window level, not pane level.
