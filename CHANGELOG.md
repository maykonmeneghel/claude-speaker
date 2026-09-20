# Changelog

Versions follow the `version` field in `.claude-plugin/plugin.json`, which is
the single source of truth: bump it in a pull request, and merging that pull
request tags `speaker--v<version>` and publishes the release. The section a
release uses for its notes is the one whose heading matches its version.

## 0.9.0

- **A long summary is spoken in full instead of being cut off.** The Stop hook
  trimmed the answer to `summary_chars` (420) and, because the trim backed up to
  the last sentence boundary, it often kept far less than that: measured over a
  day of real turns, one summary in five lost text, the worst of them 574 of its
  859 characters. It ended on a complete sentence, so it did not sound truncated
  — it sounded like the voice had stopped halfway through, which is exactly what
  it was.

  Long answers are now split at sentence boundaries into fragments of
  `summary_chars` and spoken in order. The limit sizes a fragment; it no longer
  decides how much of the answer is heard. `max_total_chars` (3000) is the new
  ceiling on a whole spoken answer, so nothing runs away. The prefetch warms the
  cache fragment by fragment, in speaking order, so playback still starts at
  once.

- **Interrupted playback resumes where it stopped.** A queued item remembers the
  fragment it reached, so leaving the tab and coming back no longer restarts the
  whole summary — the log used to show the same 153 characters spoken three
  times over.

- **Losing focus for an instant no longer cuts the voice.** A single poll
  deciding the tab was not in front was enough to stop playback, which meant a
  notification banner stealing focus, or `lsappinfo` hiccuping, truncated the
  answer. `blur_grace_polls` (3) consecutive polls must now agree, and a focus
  query macOS refused to answer counts for neither side: a failed query is not
  the user walking away.

- **The microphone check reads the input scope.** It asked for
  `kAudioDevicePropertyDeviceIsRunningSomewhere` on the global scope of the
  default input device. On a headset — one device with both an input and an
  output — our own playback turns that true, so every utterance cut itself short
  a second in. It now asks about the input scope, needs `mic_grace_polls` (2)
  consecutive readings, and what it interrupts is kept: the rest waits
  `mute_backoff_seconds` and resumes, rather than being counted as spoken and
  dropped. A new prompt still discards the summary, which by then answers the
  wrong question.

- **An item is never given up on in silence.** Exhausting the retries dropped
  the summary without a line in the log, which is the one case where the log is
  worth having. Every drop is now logged with the result and the fragment it
  reached, and `max_attempts` (6) replaces the hard-coded 3 — attempts no longer
  cost the whole summary, since progress survives them.

- **The daemon survives a bad cycle.** An exception anywhere in the loop — a
  cache file pruned from under it, a CoreAudio hiccup — ended the process and
  took every pending summary with it. The loop now logs the error and carries
  on. The synthesis temp file also carries the writer's pid, so the hook's
  prefetch and the daemon can no longer collide on a shared `.part` and fail
  each other's write.

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
