---
description: Diagnose the whole pipeline: key, voice, tty, focus detection, daemon, hooks
allowed-tools: Bash(bash:*)
---

```
!`SPK=""; for c in "$CLAUDE_PLUGIN_ROOT" "$HOME/claude-speaker" "$HOME"/.claude/plugins/cache/*/claude-speaker/*; do [ -x "$c/bin/speak" ] && SPK="$c/bin/speak" && break; done; [ -n "$SPK" ] || { echo "claude-speaker not found"; exit 1; }; "$SPK" doctor`
```

Walk the user through any line marked `!!`, in order, with the exact command that fixes it. If everything is `ok`, say so in one line and do not repeat the whole report.
