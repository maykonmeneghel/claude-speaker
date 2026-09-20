---
description: Turn Claude's voice off for this session (add --global to silence every session)
allowed-tools: Bash(bash:*)
---

```
!`SPK=""; for c in "$CLAUDE_PLUGIN_ROOT" "$HOME/claude-speaker" "$HOME"/.claude/plugins/cache/*/claude-speaker/*; do [ -x "$c/bin/speak" ] && SPK="$c/bin/speak" && break; done; [ -n "$SPK" ] || { echo "claude-speaker not found"; exit 1; }; "$SPK" off $ARGUMENTS`
```

Confirm in one line that this session is silent now, that other sessions are unaffected,
and that `/claude-speaker:speaker-on` brings it back.
