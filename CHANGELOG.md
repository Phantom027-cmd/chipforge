# Changelog

## 0.1.0 - milestone 1: core engine + song format

- Song format v1: YAML structure, MML note strings, drum step lanes, chord symbols with
  `riff` / `arp` / `harmony` / `root` / `pad` / `drone` generators, arrangement with per-use
  transpose / vol / mute / solo / layers, `loop: true | false | {from}` semantics.
- Schema validation with file:line paths, suggestions for misspelled names, and generator /
  lane / MML length checks (`chipforge validate`).
- NES voices: pulse (duty, pluck, 60 Hz 4-bit envelopes, vibrato, slides, @arp/@sweep macros),
  32-step triangle, long/short LFSR noise, sine sub, grit, detuned PWM drone, band-limited
  wavetable; kit pieces kick / snare / hat / clank / crash / hiss / groan / siren / eerie.
- Preset library as data (`presets.yml`, 23 presets) with `extends`.
- Loop-aware mixer: fold tails, warm-started circular filters, circular ping-pong echo and FFT
  convolution reverb, kick sidechain, low-bus tanh glue, master soft clip. Intro + loop and
  one-shot (natural tail, trimmed) modes.
- Ambience beds `factory` and `cave`, rendered as a stem and balanced under the music.
- Outputs: WAV (with `smpl` loop chunk), preview (loop played twice), per-layer stems, MIDI
  (track per channel, section + loop markers), JSON sidecar.
- Examples: `boss_factory` and `boss_factory_dark`, ported from the reference scripts
  (sample correlation with the originals 0.99 / 0.94).
- Generated docs (`SONG_FORMAT.md`, `PRESETS.md`), docs-drift test, docs-examples test,
  loop-seam, determinism and schema tests (39 tests).
