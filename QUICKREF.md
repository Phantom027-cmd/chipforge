# ChipForge quick reference (one page)

A song is a YAML file: metadata, **channels** (instrument presets), **patterns** (bars of music),
and an **arrangement** (ordered pattern uses). Notes are MML strings; drums are step lanes; bass,
arps and pads can be generated from chord symbols. The engine guarantees seamless loops.

```yaml
chipforge: 1
title: Cave Theme
cue: dungeon            # boss combat overworld dungeon ambience menu shop victory death gameover credits
tempo: 110
time: 4/4
key: Dm                  # C, Em, F#m, Bb, "E phrygian" ...
chip: nes                # nes gameboy sid fm gm
mode: enhanced           # enhanced = stereo + reverb + sub; authentic = raw hardware mono
seed: 1
loop: {from: A}          # true = everything loops; false = one-shot sting; {from: X} = intro before X
ambience: {bed: cave, level: -19}      # optional environment stem, dB relative to the music

channels:                # name -> preset (+ vol, pan -1..1, layer, echo, reverb, duck, lp, hp, transpose)
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
    bass: {gen: riff, steps: "0 . 0 . 12 . 0 7", low: d2}      # semitones from the chord root
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
One string per piece: `k` kick, `s` snare, `h` hat, `o` open hat, `c` crash, `m` clank (kit-dependent;
`chipforge presets kit` lists pieces). Each character is one grid step (`step: 16` default):
`.` rest, `x` full, `o` 0.55, `g` 0.3 (ghost), `1`-`9` velocity tenths. `|` is ignored.
`events:` places one-shots: `{at: "bar:step", hit: crash}`, sweeps `{at: "1:1", hit: groan, from: 52, to: 40, dur: 1.4}`,
rolls `{at: "4:9", roll: s, len: 8, ramp: [0.3, 1.0]}`. `at` is 1-based `"bar:step"` or a 0-based step number.

## Generators (instead of MML)
| gen | fields | what it plays |
|---|---|---|
| `riff` | `steps: "0 0 12 . 0:3 7:1"`, `low: e2` or `octave`, `gate`, `follow: bass` | semitone offsets from each chord's root; `.` rest, `n:len` held |
| `arp` | `tones: [0,1,2,3]`, `rate` (frames per step), `every` (grid steps), `low`/`octave`, `duty` | classic 60 Hz chord arpeggio |
| `harmony` | `of: lead`, `interval: -2` (scale steps), `scale: harmonic_minor` | harmonizes another channel |
| `root` | `low: e1`, `retrig: [0, 8]`, `gate` | holds the chord root (sub-bass) |
| `pad` | `voicing: [0,1,2]`, `low`/`octave` | held chord tones |
| `drone` | `low: e2`, `fifth: true`, `merge: true` | one long note per chord run |

`low: e2` keeps chord roots in the octave starting at E2 (tonic-anchored); `octave: 2` uses plain octaves.

## Most-used presets (`chipforge presets` for all, PRESETS.md for parameters)
`lead.pulse25` `lead.pulse50` `lead.pulse12` `lead.harmony50` `lead.harmony25` `lead.tri` `lead.saw`
`arp.pulse12` `arp.pulse25` · `bass.tri` `bass.tri_grit` `bass.tri_grit_dark` `bass.sub` `bass.chipstack` `bass.pulse`
`drone.pwm_detuned` `pad.pulse` `fx.eerie` · `kit.nes` `kit.nes_factory` `kit.nes_dark`

## Workflow
`chipforge validate song.yml` → `chipforge render song.yml -o out/` (WAV + preview with the loop
played twice + stems + MIDI + JSON) → `chipforge analyze out/song.wav` → fix findings → repeat.
Keep intros short, end loops on the chord that leads back to the loop start, give every section a
contrast (drop drums, add a layer, change the duty), and leave 1-4 kHz for the lead.
