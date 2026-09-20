---
description: Choose how much of each answer is spoken: smart summary, full text or manual notes
allowed-tools: Bash(bash:*)
---

```
!`SPK=""; for c in "$CLAUDE_PLUGIN_ROOT" "$HOME/claude-speaker" "$HOME"/.claude/plugins/cache/*/claude-speaker/*; do [ -x "$c/bin/speak" ] && SPK="$c/bin/speak" && break; done; [ -n "$SPK" ] || { echo "claude-speaker not found"; exit 1; }; A="$ARGUMENTS"; if [ -n "$A" ]; then "$SPK" set summary_mode "$A"; else "$SPK" status | head -5; fi`
```

`smart` (default) speaks the summary section of the answer plus whatever decision it
asks for; `full` speaks the whole answer up to `max_chars`; `manual` speaks only what
Claude leaves with `speak note`. Confirm the mode in one line.
