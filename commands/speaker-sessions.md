---
description: List every known Claude session and whether it speaks
allowed-tools: Bash(bash:*)
---

```
!`SPK=""; for c in "$CLAUDE_PLUGIN_ROOT" "$HOME/claude-speaker" "$HOME"/.claude/plugins/cache/*/claude-speaker/*; do [ -x "$c/bin/speak" ] && SPK="$c/bin/speak" && break; done; [ -n "$SPK" ] || { echo "claude-speaker not found"; exit 1; }; "$SPK" sessions`
```

Report which sessions speak and which are silent, marking the current tab. Mention
`session_default` only if the user would need to change it.
