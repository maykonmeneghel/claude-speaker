---
description: Pick the ElevenLabs voice by id or name, and say whether the plan can use it
argument-hint: [voice-id-or-name]
allowed-tools: Bash(bash:*)
---

```
!`SPK=""; for c in "$CLAUDE_PLUGIN_ROOT/bin/speak" "$HOME/claude-speaker/bin/speak" $(find "$HOME/.claude/plugins/cache" -maxdepth 5 -path "*speaker*/bin/speak" 2>/dev/null | sort -r); do [ -x "$c" ] && SPK="$c" && break; done; [ -n "$SPK" ] || { echo "claude-speaker not found"; exit 1; }; A="$ARGUMENTS"; if [ -n "$A" ]; then "$SPK" voice "$A"; else "$SPK" voices; fi`
```

With an argument, confirm in one line which voice is now set, and repeat any
warning about the plan verbatim — a voice library voice on a free account is
listed but refused by the API, and the macOS voice is what you would hear.
Without an argument the list above is the account's voices: report how many
there are, which one is current, and that `[needs a paid plan]` marks the ones
the account cannot synthesize. Suggest `/speaker:test` to hear the choice.
