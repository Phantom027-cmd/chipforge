# ChipForge quick reference (one page)

A song is a YAML file: metadata, **channels** (instrument presets), **patterns** (bars of music),
and an **arrangement** (ordered pattern uses). Notes are MML strings; drums are step lanes; bass,
arps and pads can be generated from chord symbols. The engine guarantees seamless loops.

```yaml
chipforge: 1
title: Cave Theme
cue: dungeon            # boss combat overworld dungeon ambience menu shop victory death gameover credits
tempo: 110
time: 4/4                # a bar = 16 grid steps (16ths); 3/4 = 12 steps, 6/8 = 12
key: Dm                  # C, Em, F#m, Bb, "E phrygian" ...
chip: nes                # nes gameboy sid fm gm
mode: enhanced           # enhanced = stereo + reverb + sub; authentic = raw hardware mono, channel limits enforced
seed: 1
loop: {from: A}          # true = everything loops; false = one-shot sting; {from: X} = intro before X
ambience: {bed: cave, level: -19}      # factory cave forest rain wind machinery water crowd; dB under the music
# loudness: -14          # LUFS target; default per cue (boss/combat -12, overworld -14, dungeon/menu -16 ...)
# mix: {hf: 0.95}        # master high shelf (0.95 = highs 5% quieter), drive, low_drive, reverb: {size, decay}

channels:                # name -> preset (+ vol, pan -1..1, layer, echo, reverb, duck, lp, hp, transpose, osc: clean)
  lead:  {preset: lead.pulse25, pan: 0.2}
  harm:  {preset: lead.harmony50, layer: 2}        # layer 2+ = adaptive intensity stems
  arp:   {preset: arp.pulse12, layer: 2}
  bass:  {preset: bass.tri_grit}
  sub:   {preset: bass.sub}
  drums: {preset: kit.nes}

patterns:
  intro:
    bars: 2
    chords: "Dm | A7"
    bass: {gen: root, low: d2}
    drums: {k: "x.......", events: [{at: "2:9", roll: s, len: 8, ramp: [0.3, 1]}]}
  A:
    bars: 4
    chords: "Dm | Bb | Gm | A7"                     # one chord per bar; "Dm Bb | ..." splits a bar
    lead: "o5 l8 d e f g a4 r8 a | b- a g f e4 r8 e | d4. e8 f4 g4 | a2 r2"
    harm: {gen: harmony, of: lead, interval: -2}   # a diatonic third below the lead
    bass: {gen: riff, steps: "0:2 . 0 . 12:2 7", low: d2}       # semitones from the chord root; one token = one 16th, n:len holds
    sub:  {gen: root, low: d1, retrig: [0, 8]}
    arp:  {gen: arp, tones: [0, 1, 2, 3], rate: 1, every: 2, low: d4}
    drums:
      k: "x...x...x...x..."
      s: "....x.......x..."
      h: "x.o.x.o.x.o.x.o."
      events: [{at: "1:1", hit: c}]
    exits: [2, 4]                                  # bars where an adaptive transition may jump

arrangement:
  - intro
  - A
  - {use: A, transpose: 5, as: A_up, layers: [1, 2], vol: 1.1}
  - {use: A, mute: [drums], channels: {lead: {vol: 0.7}}}
```

## MML (melodic channels)
| token | meaning | token | meaning |
|---|---|---|---|
| `c d e f g a b` | notes; `+`/`#` sharp, `-` flat | `r` | rest |
| `c4 c8 c16 c2 c1` | length (4 = quarter); default from `l` | `c4.` `c8&c8` | dotted, tied |
| `o5` `<` `>` | octave set / down / up (o4 = middle C) | `l8` | default length |
| `v12` | volume 0-15 | `q6` | gate 1-8 (8 = legato) |
| `~g4` | slide (portamento) into g from the previous note | `[c8 d8]3` | repeat 3x |
| `@d(0.25)` | pulse duty | `@vib(depth,rate,delay)` | vibrato in semitones |
| `@arp(0,4,7)` | chord-arpeggio macro on following notes | `@sweep(-12,0.5)` | pitch sweep |
| `@env(dec,sus,rel)` | envelope override | `@off` | clear macros |
| `\|` | bar line (ignored; keep for readability) | | |

A string shorter than the pattern repeats if it divides it evenly. Longer is an error.

## Drum lanes (kit channels)
One string per piece: `k` kick, `s` snare, `h` hat, `o` open hat, `c` crash in every kit; `t` tom and
`m` clank in some (`kit.nes` has k s h o c; `kit.nes_factory` adds m hiss groan siren; `chipforge presets kit` lists all). Each character is one grid step (`step: 16` default):
`.` rest, `x` full, `o` 0.55, `g` 0.3 (ghost), `1`-`9` velocity tenths. `|` is ignored.
`events:` places one-shots: `{at: "bar:step", hit: crash}`, sweeps `{at: "1:1", hit: groan, from: 52, to: 40, dur: 1.4}`,
rolls `{at: "4:9", roll: s, len: 8, ramp: [0.3, 1.0]}`. `at` is 1-based `"bar:step"` or a 0-based step number.

## Generators (instead of MML)
| gen | fields | what it plays |
|---|---|---|
| `riff` | `steps: "0 0 12 . 0:3 7:1"`, `low: e2` or `octave`, `gate`, `follow: bass` | semitone offsets from each chord's root, one token per 16th step: `.` rest, `n:len` held for len steps; must fill the pattern or divide it evenly |
| `arp` | `tones: [0,1,2,3]`, `rate` (frames per step), `every` (grid steps), `low`/`octave`, `duty` | classic 60 Hz chord arpeggio |
| `harmony` | `of: lead`, `interval: -2` (scale steps), `scale: harmonic_minor` | harmonizes another channel |
| `root` | `low: e1`, `retrig: [0, 8]`, `gate` | holds the chord root (sub-bass) |
| `pad` | `voicing: [0,1,2]`, `low`/`octave` | held chord tones |
| `drone` | `low: e2`, `fifth: true`, `merge: true` | one long note per chord run |

`low: e2` keeps chord roots in the octave starting at E2 (tonic-anchored); `octave: 2` uses plain octaves.

## Most-used presets (`chipforge presets` for all, PRESETS.md for parameters)
| chip | leads / arps | bass / drone / pad | kits |
|---|---|---|---|
| nes | `lead.pulse25` `lead.pulse50` `lead.pulse12` `lead.harmony50` `lead.tri` `arp.pulse12` | `bass.tri_grit` `bass.sub` `bass.chipstack` `bass.pulse` `drone.pwm_detuned` `pad.pulse` | `kit.nes` `kit.nes_factory` `kit.nes_dark` `kit.nes_dpcm` `kit.nes_light` |
| gameboy | `lead.gb_organ` `lead.gb_pulse` `lead.gb_saw` `arp.gb_pulse` | `bass.gb_wave` | `kit.gameboy` |
| sid | `lead.sid_saw` `lead.sid_pwm` `lead.sid_sync` `lead.sid_ring` `arp.sid_pulse` | `bass.sid_saw` `bass.sid_pulse` `drone.sid_sync` `pad.sid_pwm` | `kit.sid` |
| fm | `lead.fm_brass` `lead.fm_bell` `lead.fm_pluck` `lead.fm_epiano` `arp.fm_pluck` | `bass.fm_slap` `bass.fm_sub` `drone.fm_metal` `pad.fm_strings` | `kit.fm` |
| gm | `lead.gm_square` `lead.gm_saw` `lead.gm_flute` `lead.gm_bell` | `bass.gm_pick` `pad.gm_strings` `pad.gm_organ` | `kit.gm` |
| any | `fx.eerie` (pad gen) | | `kit.sfx`: clank steam alarm roar boom zap powerup explosion |

Presets are tuned to sit together at `vol: 1`. Put the bass on the `low` bus (presets do this), keep one lead in 1-4 kHz.

## Workflow
`chipforge validate song.yml` → `chipforge render song.yml -o out/` (WAV + preview with the loop
played twice + stems + MIDI + JSON, normalized to the cue's LUFS target, -1 dBTP) →
`chipforge analyze song.yml` (LUFS, band balance, seam, masking, contrast, density; findings say what to
change) → fix → `chipforge compare old.wav new.wav` → `chipforge review song.yml` (human listens, leaves
timestamped notes in feedback.json) → read the feedback → repeat. `chipforge ambience cave -s 60` renders a bed alone.
Keep intros short, end loops on the chord that leads back to the loop start, give every section a
contrast (drop drums, add a layer, change the duty), and leave 1-4 kHz for the lead.
