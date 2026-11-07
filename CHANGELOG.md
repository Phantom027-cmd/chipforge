# Changelog

## 0.5.0 - milestone 5: the ears

- `chipforge analyze <song.yml | audio>`: JSON report + composite PNG (log spectrogram with section
  and loop markers, 0-400 Hz bass spectrogram, waveform with stem envelopes and short-term loudness,
  piano roll) + plain-language findings with thresholds. Works from a song file (renders with group
  stems and the score) or from an audio file with its sidecar/MIDI.
- Metrics: integrated / short-term / momentary LUFS, true peak, LRA; band balance against healthy
  ranges learned from the tuned references; spectral centroid per section; stereo correlation and
  width; clipping, DC, silence; loop seam (sample step and spectral flux, relative to the song's own
  transients and section changes); lead-vs-accompaniment masking in 1-4 kHz per section; notes per
  second and section loudness contrast; detected tempo vs score tempo and onset grid alignment.
- `chipforge compare A B`: metric deltas and stacked spectrograms.
- Optional, clearly approximate CLAP semantic tags (`--tags`, needs torch + transformers; degrades
  gracefully). The analysis payload has an `include_audio` option for a future audio-capable model.
- Golden-metric regression tests for every example (tolerances, not hashes); examples adjusted from
  what the images and findings showed (Game Boy hats, menu loop seam and contrast).
- Tests: 145.

## 0.4.0 - milestone 4: outputs and loop metadata

- Stems by `layer` (adaptive intensity), `group` (lead / arp / bass / pads / drums / fx) or
  `channel` (`--stems-by`). Stems sum exactly to the mix: the low-bus saturation, master soft clip
  and limiter are shared as per-sample gain curves instead of being re-applied per stem.
- `_intro` + `_loop` files when the song has an intro (for engines that chain two clips);
  MP3 via libsndfile (ffmpeg fallback); 24-bit WAV; OGG stems.
- Loop metadata verified by reading it back: WAV `smpl` chunk and OGG `LOOPSTART`/`LOOPLENGTH`
  round-trip tests; MIDI section + loop markers; `read_wav_loop` / `read_ogg_loop` helpers.
- JSON sidecar: engine version, beat/bar seconds, loop in samples and seconds, sections with exits,
  layers with their channels and stem files, loudness report, output paths.
- SONG_FORMAT.md gains an "Outputs and loop metadata" section with per-engine notes (Godot,
  RPG Maker, Unity, FMOD/Wwise, Web Audio, GameMaker).
- Tests: 135.

## 0.3.0 - milestone 3: mixing and mastering

- `loudness.py`: BS.1770-4 K-weighted integrated / short-term / momentary loudness, EBU loudness
  range, 4x-oversampled true peak (matches pyloudnorm to 0.01 LU) and a vectorized look-ahead
  limiter that wraps cleanly on loops. No new dependencies.
- Master chain: high-pass -> soft clip -> high shelf (`mix.hf`, default 0.95 = highs 5% quieter,
  from listening feedback) -> loudness normalization to the cue target (`CUE_LOUDNESS`: boss/combat
  -12, overworld -14, dungeon/menu -16, ambience -20 ...; `loudness:` overrides) -> true-peak
  limiter at `mix.ceiling` (-1 dBTP). Stems get the same gain without limiting so they sum like the
  mix. The render report shows LUFS, true peak and how much the limiter worked.
- Ambience beds: forest, rain, wind, machinery, water, crowd (plus factory and cave), all seamless;
  `chipforge ambience <bed> -s 60` renders a bed on its own at -20 LUFS.
- Mixer: no per-part stereo allocation (buses accumulate in place); fewer filter passes.
- Tests: meter vs BS.1770 sine, limiter ceiling, cue targets, shelf, every bed seamless (126 tests).

## 0.2.0 - milestone 2: chip profiles and presets

- Chip profiles: `gameboy` (4-bit 32-step wave channel with named tables, 7-bit metallic noise,
  64 Hz frames, hard L/C/R panning in authentic mode), `sid` (pulse/saw/tri/noise voice with PWM,
  ring mod, hard sync, resonant lp/bp/hp filter with envelope and LFO sweeps, 50 Hz frames),
  `fm` (4-operator phase modulation, the 8 YM2612 algorithms, operator feedback, plus a PSG slot
  budget), `gm` (band-limited wavetable palette). NES gains a DPCM-style 1-bit delta encoder for kit
  pieces (`dpcm: true`) and a `tom` voice.
- Oscillators: PolyBLEP pulse and saw. `osc: clean | naive` per channel; sid/fm/gm default to
  clean in enhanced mode, nes/gameboy stay naive (the aliasing is the character).
- Authentic mode: hardware channel budgets are validated (e.g. "authentic nes has 2 pulse
  channel(s) but 3 are used"), voices without a hardware channel are rejected with the fix in the
  hint, duty macros snap to legal widths, output is mono, polyphonic pads are refused.
- Kit pieces can use melodic voices (`voice: fm` kick with `note`, `len`, `sweep`, `arp`).
- Preset library: 23 -> 66 presets (`kit.sfx` with clank / steam / alarm / roar / boom / zap /
  powerup / explosion, GB / SID / FM / GM leads, basses, pads, drones and kits).
- Examples: `overworld_gameboy` (intro + loop), `combat_sid`, `menu_fm`.
- Tests: every preset renders audibly, authentic-mode rules, PolyBLEP aliasing check (112 tests).

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
