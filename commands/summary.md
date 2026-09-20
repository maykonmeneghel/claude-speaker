---
description: Choose how much of each answer is spoken: smart summary, full text or manual notes
allowed-tools: Bash(bash:*)
---

```
!`SPK=""; for c in "$CLAUDE_PLUGIN_ROOT/bin/speak" "$HOME/claude-speaker/bin/speak" $(find "$HOME/.claude/plugins/cache" -maxdepth 5 -path "*speaker*/bin/speak" 2>/dev/null | sort -r); do [ -x "$c" ] && SPK="$c" && break; done; [ -n "$SPK" ] || { echo "claude-speaker not found"; exit 1; }; A="$ARGUMENTS"; if [ -n "$A" ]; then "$SPK" set summary_mode "$A"; else "$SPK" status | head -5; fi`
```

`smart` (default) speaks the summary section of the answer plus whatever decision it
asks for; `full` speaks the whole answer; `manual` speaks only what Claude leaves with
`speak note`. Either way it is spoken in full, in fragments of `summary_chars`, up to
`max_total_chars`. Confirm the mode in one line.
