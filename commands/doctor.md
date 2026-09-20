---
description: Diagnose the whole pipeline: key, voice, tty, focus detection, daemon, hooks
allowed-tools: Bash(bash:*)
---

```
!`SPK=""; for c in "$CLAUDE_PLUGIN_ROOT/bin/speak" "$HOME/claude-speaker/bin/speak" $(find "$HOME/.claude/plugins/cache" -maxdepth 5 -path "*speaker*/bin/speak" 2>/dev/null | sort -r); do [ -x "$c" ] && SPK="$c" && break; done; [ -n "$SPK" ] || { echo "claude-speaker not found"; exit 1; }; "$SPK" doctor`
```

Walk the user through any line marked `!!`, in order, with the exact command that fixes it. If everything is `ok`, say so in one line and do not repeat the whole report.
