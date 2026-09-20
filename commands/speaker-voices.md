---
description: List the ElevenLabs voices on the account and show which one is selected
allowed-tools: Bash(bash:*)
---

```
!`SPK=""; for c in "$CLAUDE_PLUGIN_ROOT" "$HOME/claude-speaker" "$HOME"/.claude/plugins/cache/*/claude-speaker/*; do [ -x "$c/bin/speak" ] && SPK="$c/bin/speak" && break; done; [ -n "$SPK" ] || { echo "claude-speaker not found"; exit 1; }; "$SPK" voices`
```

Present the voices as a short list (name + id + labels) and ask which one to use. When the user answers, set it with `speak voice <id>` via Bash.
