---
description: Store the ElevenLabs API key in the macOS keychain and pick a voice
argument-hint: [elevenlabs-api-key]
allowed-tools: Bash(bash:*)
---

Set up ElevenLabs for claude-speaker.

- If `$ARGUMENTS` contains a key, run it through the CLI:
  `SPK=""; for c in "$CLAUDE_PLUGIN_ROOT" "$HOME/claude-speaker" "$HOME"/.claude/plugins/cache/*/claude-speaker/*; do [ -x "$c/bin/speak" ] && SPK="$c/bin/speak" && break; done; "$SPK" setup <key>`
- If `$ARGUMENTS` is empty, ask the user for the key from https://elevenlabs.io/app/settings/api-keys and remind them it is stored in the login keychain (service `claude-speaker-elevenlabs`), never in a file inside the repository or the plugin.

Never echo the key back, never write it into a file, and never include it in a commit.

After the key is stored, show the available voices and set the one the user picks with `"$SPK" voice <id>`. Finish with `"$SPK" test` so the user hears the chosen voice.
