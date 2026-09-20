---
description: Speak a test phrase immediately, bypassing the focus check
argument-hint: [text to speak]
allowed-tools: Bash(bash:*)
---

```
!`SPK=""; for c in "$CLAUDE_PLUGIN_ROOT" "$HOME/claude-speaker" "$HOME"/.claude/plugins/cache/*/claude-speaker/*; do [ -x "$c/bin/speak" ] && SPK="$c/bin/speak" && break; done; [ -n "$SPK" ] || { echo "claude-speaker not found"; exit 1; }; "$SPK" test $ARGUMENTS`
```

If the result is `done`, confirm the audio played and name the engine used. If it is `failed`, read the last lines of the log with `speak log` and tell the user what is broken.
