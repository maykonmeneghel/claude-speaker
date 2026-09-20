---
description: Turn Claude's voice off for this session (add --global to silence every session)
allowed-tools: Bash(bash:*)
---

```
!`SPK=""; for c in "$CLAUDE_PLUGIN_ROOT/bin/speak" "$HOME/claude-speaker/bin/speak" $(find "$HOME/.claude/plugins/cache" -maxdepth 5 -path "*speaker*/bin/speak" 2>/dev/null | sort -r); do [ -x "$c" ] && SPK="$c" && break; done; [ -n "$SPK" ] || { echo "claude-speaker not found"; exit 1; }; "$SPK" off $ARGUMENTS`
```

Confirm in one line that this session is silent now, that other sessions are unaffected,
and that `/speaker:on` brings it back.
