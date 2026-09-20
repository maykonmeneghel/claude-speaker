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

UserPromptSubmit hook ──► cuts what is playing, drops what is unspoken
                     └──► queues a short "got it" so the turn starts out loud
microphone goes live ──► cuts mid-sentence (dictation must not hear the voice)
```

A queued summary only stays worth hearing while you are away. Three rules keep
it from describing the wrong turn: a notification — a generic "waiting for your
input" line — never supersedes a summary that has not been spoken yet;
submitting a new prompt drops that session's pending summary outright, since
you are demonstrably back and asking about something else; and that same prompt
cuts a summary already being spoken, mid-sentence, counting it as heard rather
than retrying it later. A pending permission notification survives all three,
because it is still true.

Cutting costs nothing and touches nothing else on the machine: the daemon owns
the player it started, so the session only leaves a timestamp for it to read on
its next poll — at most a quarter of a second. The mark is a timestamp and not
a flag precisely so that an utterance which begins *after* you hit Enter is
left alone. Set `stop_on_prompt` to `false` to let every summary finish.

Claude Code has no hook on a keystroke, so the earliest moment anything can
react to you is `UserPromptSubmit`, which fires when the prompt is submitted —
not while you type it.

## Dictation

That limit matters if you talk to Claude instead of typing. Press the dictation
key while the voice is still speaking and the microphone transcribes *it*, so
your prompt arrives with a sentence of Claude's own answer glued to the front;
by the time `UserPromptSubmit` could cut the audio, the damage is already in the
transcript.

So the plugin watches the microphone rather than the keyboard. CoreAudio
publishes `kAudioDevicePropertyDeviceIsRunningSomewhere` for the default input
device, which turns true the moment *any* process starts capturing. Reading it
is a property query and not a recording: it needs no microphone permission and
puts nothing in the menu bar. The voice stops when you start talking, whatever
you are dictating with — Claude Code, macOS dictation, or an app of your own.

Only a rising edge during an utterance counts. A microphone that was already
capturing when playback started — a call, a recording left running — is left
alone, because silencing the plugin for the length of a meeting is not what
anyone asked for. And where CoreAudio will not answer, nothing is cut at all;
`speak doctor` says whether this machine can tell. Set `stop_on_mic` to `false`
to turn it off.

## Requirements

- macOS (uses `lsappinfo`, `osascript`, `afplay`, `say`)
- Python 3.9+ (stdlib only)
- An ElevenLabs API key — optional: without one the plugin falls back to the
  built-in macOS voice (`say -v Luciana`), so it works before you configure anything.

## Install

```bash
claude plugin marketplace add maykonmeneghel/claude-speaker
claude plugin install speaker@meneghel-local
```

Or, from a local clone:

```bash
git clone https://github.com/maykonmeneghel/claude-speaker.git ~/claude-speaker
claude plugin marketplace add ~/claude-speaker
claude plugin install speaker@meneghel-local
```

Then, inside Claude Code:

```
/speaker:setup <your-elevenlabs-key>   # stores it in the login keychain
/speaker:doctor                        # end-to-end check
/speaker:test                          # hear the voice now
```

The key goes into the macOS keychain (service `claude-speaker-elevenlabs`), or
comes from `ELEVENLABS_API_KEY`. It is never written into this repository.

The first time the daemon asks Terminal/iTerm2 which tab is selected, macOS
shows an automation prompt. Approve it (System Settings → Privacy & Security →
Automation) — without it, focus detection falls back to "the terminal app is in
front", which speaks in the wrong tab when several sessions run side by side.

## ElevenLabs: key, voice and plan

Everything the plugin sends to ElevenLabs goes through three endpoints:
`GET /v1/voices` (the list), `GET /v1/user/subscription` (the plan) and
`POST /v1/text-to-speech/{voice_id}` (the audio).

### The key

Create it at **elevenlabs.io → Settings → API Keys**. The key travels in the
`xi-api-key` header, and ElevenLabs lets you restrict it when you create it:
limit the scope to text-to-speech and voice reading, set a credit quota, and add
an IP allowlist if the machine has a fixed address. A key scoped that way cannot
be used to change the account if it ever leaks.

Store it with `/speaker:setup <key>`. It goes into the **login keychain**, under
the service `claude-speaker-elevenlabs`, and is handed to `security` over stdin —
never as a command argument, which any process on the machine could read with
`ps`. It is never written to a file in the repository or in the plugin directory.

The key is looked up in this order:

1. `ELEVENLABS_API_KEY` or `ELEVEN_API_KEY` in the environment
2. the login keychain (where `/speaker:setup` puts it)
3. `api_key` in `~/.claude-speaker/config.json` — only if you put it there by
   hand; `speak set` refuses that key, precisely so it does not end up on disk

To rotate, run `/speaker:setup` with the new key (it overwrites). To remove it:
`security delete-generic-password -s claude-speaker-elevenlabs`. With no key at
all the plugin still works — it speaks with the macOS voice (`say -v Luciana`).

### Picking the voice

```
/speaker:voices          # what the account can see, with the current one marked *
/speaker:voice <id|name> # store it
/speaker:test            # hear it
```

The choice lands in `~/.claude-speaker/config.json` as `voice_id` (what the API
actually uses) and `voice_name` (only so the listings read well). A voice id is
the 20-character string in the first column, the same one in the voice's URL on
elevenlabs.io. If you know the id already, `speak voice <id>` accepts it without
a key configured and validates it on the next call.

### What a free account can and cannot use

This is the trap worth knowing before you pick a voice by ear:

| Voice | `category` | Free plan |
| --- | --- | --- |
| the ones bundled with every account | `premade` | works |
| anything added from the **Voice Library** | `professional`, `cloned`, `generated` | **listed, but refused** |

`GET /v1/voices` returns library voices to a free account, so they show up in
`/speaker:voices` and can be selected — but the synthesis call answers
`402 paid_plan_required`: *"Free users cannot use library voices via the API"*.
The plugin then falls back to the macOS voice, which looks like "ElevenLabs
stopped working". `/speaker:voices` marks those with `[needs a paid plan]`, and
`/speaker:voice` warns when you pick one; `speak log` shows the 402.

Voice cloning (instant and professional) is a paid feature too, so a cloned voice
of your own is not an option on the free plan. A free account also gets 10,000
characters a month. The plugin is built to spend little of it: what is spoken is
a summary capped at `summary_chars` (420 by default, `max_chars` 700 in `full`
mode), identical text is served from the local mp3 cache instead of being billed
twice, and nothing is synthesized while the session is silenced.

### Model and audio

`model_id` defaults to `eleven_turbo_v2_5`; `eleven_flash_v2_5` is cheaper and
faster with slightly flatter prosody. `language_code` (`pt` by default) is only
accepted by the turbo and flash models, and the plugin drops it for any other
model rather than having the call rejected. `output_format` defaults to
`mp3_44100_128`, played by `afplay`.

## Commands

| Command | What it does |
| --- | --- |
| `/speaker:status` | engine, voice, daemon, focused tab, pending queue |
| `/speaker:on` / `/speaker:off` | speak / stay quiet **in this session**; add `--global` for all |
| `/speaker:sessions` | every known session and whether it speaks |
| `/speaker:summary [smart\|full\|manual]` | how much of each answer is spoken |
| `/speaker:stop` | stop the audio playing right now |
| `/speaker:test [text]` | speak immediately, ignoring focus |
| `/speaker:voices` | list the voices on the account, marking what the plan allows |
| `/speaker:voice <id\|name>` | pick the voice |
| `/speaker:setup` | store the API key and pick a voice |
| `/speaker:doctor` | diagnose key, tty, focus, daemon, hooks |
| `/speaker:shortcuts [install\|uninstall]` | the same commands as `/speaker-*`, without the prefix |

### Without the `speaker:` prefix

Plugin commands are namespaced, so they read `/speaker:on`. If you would rather
type `/speaker-on`, install personal copies into `~/.claude/commands`:

```
/speaker:shortcuts install     # or: speak shortcuts install
```

Both forms then work. `speak shortcuts uninstall` removes them again — it only
deletes files this plugin generated, so a command of yours with the same name is
left alone.

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
available. A session's pin lives in its file under `sessions/` and survives the end of the
session: a resumed session speaks exactly as you left it, and the pin of a session that never
comes back is dropped after `pin_ttl_days` (30). `speak sessions` shows those as
`ended … pin kept for a resume`.

## What gets spoken

`summary_mode` decides how much of the answer reaches the voice:

| Mode | Spoken |
| --- | --- |
| `smart` (default) | the section titled Resumo / Decisões / Próximos passos if there is one, otherwise the opening line, the questions left for you and the closing paragraph — capped at `summary_chars` (420) |
| `full` | the whole answer, capped at `max_chars` (700) |
| `manual` | nothing, unless Claude left a line with `speak note "..."` |

Separately from the modes, a prompt is acknowledged the moment it is submitted:
a one-line "Ok, deixa comigo" while the turn gets going, so a long answer does
not feel like nothing was heard. The line is drawn at random from
`ack_phrases` — the built-in set follows `language_code` — never repeating the
one before it. Nothing is synthesized in the hook, which runs before Claude
sees the prompt: the daemon speaks it a moment later, and from the mp3 cache
once each phrase has been heard once, so a fixed set of lines is billed once
and never again. An acknowledgement older than `ack_ttl_seconds` (20) is
dropped unspoken, because arriving late it says the opposite of what it means,
and a real summary always outranks one still waiting. Set `ack` to `false` to
turn it off.

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
| `pin_ttl_days` | `30` | how long the pin of an ended session is kept for a resume; `0` keeps it forever |
| `queue_policy` | `latest` | `latest` speaks only the newest message per session, except that a notification never discards an unspoken summary; `all` speaks every one |
| `notifications` | `true` | also speak permission prompts and idle notifications |
| `speak_when_focused` | `true` | `false` = only speak messages produced while the tab was *not* in front |
| `stop_on_blur` | `true` | leaving the tab interrupts the audio (it retries on return, up to 3×) |
| `stop_on_prompt` | `true` | submitting a new prompt cuts what this session is saying, and counts it as spoken |
| `stop_on_mic` | `true` | the microphone going live cuts what is being said, so dictation does not transcribe the voice |
| `ack` | `true` | say a short line when a prompt is submitted, before the turn's own answer |
| `ack_phrases` | – | your own lines to draw from; empty means the built-in set for `language_code` |
| `ack_ttl_seconds` | `20` | an acknowledgement older than this is dropped unspoken |
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

## State, and what leaves the machine

Nothing mutable is written inside the plugin or the repository. Everything lives
in `~/.claude-speaker/`, created `0700` with every file `0600`, because the queue
and the notes hold what Claude just said:

```
~/.claude-speaker/
  config.json     every key from the Configuration table   (0600)
  queue/          one json per pending utterance: the text, the session, its tty
  cache/          synthesized mp3, keyed by text+voice+model; newest 400 kept
  sessions/       session -> tty map and the per-session on/off pin
  notes/          a line left by `speak note`, consumed by the next turn
  speaker.log     timestamps, session ids, character counts — never the text
  speakerd.pid    the running daemon
```

The API key is not in there: it is in the login keychain (see *ElevenLabs*).
Upgrading from a version before 0.3.0 tightens the modes of files already on
disk, once, on the first run.

**What is sent to ElevenLabs**: the text to be spoken — that is, a trimmed
summary of Claude's answer — plus the voice id and model. Code blocks, tables and
URLs are stripped before that (see *How the text is prepared*). Nothing else
leaves the machine: no prompt, no file content, no session id. With no key
configured, nothing leaves the machine at all, since `say` is local.

Uninstalling the plugin leaves `~/.claude-speaker/` untouched; delete it by hand
to reset, and remove the key with
`security delete-generic-password -s claude-speaker-elevenlabs`.

## Known limits

- macOS only.
- Exact-tab detection works on Terminal.app and iTerm2. Ghostty, kitty, WezTerm,
  Alacritty and Warp have no tab-tty scripting API, so those fall back to
  app-level focus (`focus_strategy=app`).
- `tmux`/`screen` panes report the tty of the outer terminal, so a session inside
  a multiplexer is matched at window level, not pane level.
