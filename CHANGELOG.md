# Changelog

Versions follow the `version` field in `.claude-plugin/plugin.json`, which is
the single source of truth: bump it in a pull request, and merging that pull
request tags `speaker--v<version>` and publishes the release. The section a
release uses for its notes is the one whose heading matches its version.

## 0.8.0

- **A prompt is now acknowledged out loud as it is submitted.** A turn that
  takes a minute used to pass in silence, which is indistinguishable from not
  having been heard at all — especially when the prompt was dictated. The
  `UserPromptSubmit` hook now queues a short line ("Ok, deixa comigo") that the
  daemon speaks while the turn gets going; the summary still follows at the end,
  unchanged.

  The line is drawn at random from `ack_phrases`, never repeating the previous
  one, and the built-in set follows `language_code`. Nothing is synthesized in
  the hook itself — it runs before Claude sees the prompt, and waiting on the
  API there would delay the turn — so the daemon does it, and from the mp3 cache
  once each phrase has been heard once. A fixed set of lines is therefore billed
  once and never again.

  An acknowledgement is dropped unspoken once it is older than `ack_ttl_seconds`
  (20), because one that arrives late says the opposite of what it means, and a
  real summary always outranks one still waiting. It also ignores
  `speak_when_focused`: the tab was obviously in front, since the user had just
  typed in it. Set `ack` to `false` to turn it off.

## 0.7.0

- **The voice stops when the microphone goes live.** Dictating a prompt while
  Claude was still speaking made the microphone transcribe the voice, so the
  prompt arrived with a sentence of Claude's own answer glued to the front.
  Stopping on `UserPromptSubmit` (0.6.0) cannot help: it fires when the prompt
  is submitted, and by then the audio is already in the transcript. Claude Code
  has no hook on a keystroke, so the keyboard cannot be watched at all.

  The microphone can. CoreAudio publishes
  `kAudioDevicePropertyDeviceIsRunningSomewhere` for the default input device,
  true whenever any process is capturing; reading it is a property query, not a
  recording, so it needs no permission and shows nothing in the menu bar. It
  costs 0.25 ms per poll. This works with any dictation tool, because it watches
  the device rather than the app.

  Only a rising edge during an utterance cuts: a microphone already capturing
  when playback began — a call, a recording — is left alone rather than
  silencing the plugin for its duration. Where CoreAudio does not answer,
  nothing is cut, and `speak doctor` now reports whether the machine can tell.
  Set `stop_on_mic` to `false` to turn it off.

## 0.6.0

- **Submitting a prompt stops the voice.** Until now a summary kept playing
  while you were already typing the next question, and the only way to silence
  it was `speak stop`. A new prompt now cuts the utterance mid-sentence and
  counts it as spoken, so it is not retried later. Set `stop_on_prompt` to
  `false` to keep the old behaviour.

  This is deliberately not a kill: the daemon owns the player it started, so
  the session writes a timestamp and the daemon ends its own process on the
  next poll, within a quarter of a second. Nothing goes looking for `afplay`
  processes to stop, so audio the plugin did not start is never touched.

  Claude Code has no hook on a keystroke — the earliest any of this can happen
  is `UserPromptSubmit`, when the prompt is submitted, not when you start
  typing it.

- An aborted utterance is no longer able to resurrect a queue item that was
  dropped while it played. The retry wrote the item file back unconditionally,
  which recreated it.

## 0.5.1

Two paths let the voice describe the wrong turn, both reproduced from
`speaker.log` before being changed.

- A notification no longer discards an unspoken answer summary. The daemon kept
  the newest queued item per session without looking at its kind, so a generic
  "waiting for your input" line deleted the summary it was queued behind, and
  that generic line is what got spoken. A `stop` item is now replaced only by
  another `stop` item.
- A summary no longer outlives the question it answered. An item queued while
  the tab was out of focus survived until `queue_ttl_seconds` and was spoken
  whenever focus returned, even after the next question had been asked. A new
  `UserPromptSubmit` hook drops that session's pending summaries; a pending
  permission notification survives, because it is still true.

Known limit: audio already playing when a prompt is submitted still finishes.
Cutting it needs a targeted kill on the pid in `now-playing.json`, because
`stop_playback()` currently `pkill`s every `afplay` on the machine.

## 0.5.0 and earlier

Released before this repository kept a changelog, and never published as GitHub
releases. The history is in the commit log.
