---
description: Speak a test phrase immediately, bypassing the focus check
argument-hint: [text to speak]
allowed-tools: Bash(bash:*)
---

```
!`SPK=""; for c in "$CLAUDE_PLUGIN_ROOT/bin/speak" "$HOME/claude-speaker/bin/speak" $(find "$HOME/.claude/plugins/cache" -maxdepth 5 -path "*speaker*/bin/speak" 2>/dev/null | sort -r); do [ -x "$c" ] && SPK="$c" && break; done; [ -n "$SPK" ] || { echo "claude-speaker not found"; exit 1; }; "$SPK" test $ARGUMENTS`
```

If the result is `done`, confirm the audio played and name the engine used. If it is `failed`, read the last lines of the log with `speak log` and tell the user what is broken.
