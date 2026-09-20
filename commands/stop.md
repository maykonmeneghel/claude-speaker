---
description: Stop the audio playing right now (keeps the speaker enabled)
allowed-tools: Bash(bash:*)
---

```
!`SPK=""; for c in "$CLAUDE_PLUGIN_ROOT/bin/speak" "$HOME/claude-speaker/bin/speak" $(find "$HOME/.claude/plugins/cache" -maxdepth 5 -path "*speaker*/bin/speak" 2>/dev/null | sort -r); do [ -x "$c" ] && SPK="$c" && break; done; [ -n "$SPK" ] || { echo "claude-speaker not found"; exit 1; }; "$SPK" stop`
```

Confirm in one line that playback was interrupted.
