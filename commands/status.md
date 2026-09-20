---
description: Show claude-speaker state: engine, voice, daemon, focused tab and pending speech queue
allowed-tools: Bash(bash:*)
---

```
!`SPK=""; for c in "$CLAUDE_PLUGIN_ROOT/bin/speak" "$HOME/claude-speaker/bin/speak" $(find "$HOME/.claude/plugins/cache" -maxdepth 5 -path "*speaker*/bin/speak" 2>/dev/null | sort -r); do [ -x "$c" ] && SPK="$c" && break; done; [ -n "$SPK" ] || { echo "claude-speaker not found"; exit 1; }; "$SPK" status`
```

Report the state above in one short paragraph: whether THIS session speaks (and the master switch), how much of each answer is spoken (summary_mode), which engine and voice are in use, whether the daemon is running, and whether anything is waiting in the queue. If the daemon is stopped or the ElevenLabs key is missing, say exactly which command fixes it (`/speaker:on` or `/speaker:setup`).
