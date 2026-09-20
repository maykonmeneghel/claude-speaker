---
description: Turn Claude's voice on for this session (add --global for every session)
allowed-tools: Bash(bash:*)
---

```
!`SPK=""; for c in "$CLAUDE_PLUGIN_ROOT/bin/speak" "$HOME/claude-speaker/bin/speak" $(find "$HOME/.claude/plugins/cache" -maxdepth 5 -path "*speaker*/bin/speak" 2>/dev/null | sort -r); do [ -x "$c" ] && SPK="$c" && break; done; [ -n "$SPK" ] || { echo "claude-speaker not found"; exit 1; }; "$SPK" on $ARGUMENTS`
```

Confirm in one line: speaking is on **for this session only** (other sessions keep
whatever they had), and Claude speaks its summary when this terminal tab regains focus.
If the output says the master switch is off, say that `/speaker:on --global` fixes it.
