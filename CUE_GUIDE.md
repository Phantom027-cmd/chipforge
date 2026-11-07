# Cue guide - the style bible

How each kind of game cue is built in ChipForge. Loudness targets are the engine defaults
(`CUE_LOUDNESS` in `chipforge/schema.py`, overridable with `loudness:`). Every example named here is
in `examples/` and passes `chipforge analyze` with no high-severity findings; the matching starter is
in `chipforge/templates/` (`chipforge-mcp new_song_from_template`).

General rules that apply to every cue:

- One idea per section; a loop needs at least one real contrast (drums out, a layer in, a key lift).
  The analyzer flags sections closer than 1.5 LU.
- The lead owns 1-4 kHz. Arps and harmonies go a third below or an octave above, quieter.
- Bass on the `low` bus (the bass presets already are): triangle/pulse for note definition plus a
  sine sub (`bass.sub`, `bass.tri_sub`, `bass.chipstack`) so it reads on phone speakers.
- End the loop on the chord that pulls back to bar 1 (V or bVII) and keep the last bar busy, so the
  seam is a downbeat, not a gap. Intros are for one-shot drama only: `loop: {from: A}`.
- Keep a 16th-note hat or arp running if the drums drop, or the tempo feel disappears.
- Transpose a repeat (`transpose: 1` or `2`) instead of writing a new section when you need lift.

| cue | tempo | keys / modes | instruments | length | loop | LUFS | pitfalls |
|---|---|---|---|---|---|---|---|
| **boss** | 150-175 | minor, harmonic minor, phrygian; semitone lift for the climax | pulse25 lead + harmony50 third below, fast 12.5% arps, `bass.tri_grit` + `bass.sub`, `kit.nes_factory` / `kit.nes_dark`, sfx hits (groan, siren, hiss) at section starts | 48-64 bars, 50-70 s | yes, no intro (the fight starts mid-bar) | -12 | everything at full density from bar 1 (keep a break with half-time drums and a held bass); arps masking the lead; a seam that lands on a rest |
| **combat** | 165-185 | natural/harmonic minor, dorian for heroic | synced saw or 25% pulse lead, 16th arps, saw/pulse bass with filter snap, busy kit with ghost hats | 24-32 bars, 35-45 s | yes | -12 | too similar to boss (combat is lighter: fewer layers, more riff, shorter loop); hats too loud (`air` band finding) |
| **overworld** | 135-160 | major, mixolydian, lydian for wonder | organ / 50% pulse lead, diatonic harmony, bouncing bass (root-fifth-octave riffs), light kit, short 2-bar intro | 32 bars, 50-60 s | intro then loop | -14 | muddy low-mids from pads; forgetting a B section; bass too polite on the Game Boy palette (raise `bass.gb_wave`) |
| **dungeon** | 70-95 | minor, phrygian, neapolitan minor; slow harmonic rhythm | 12.5% pulse or triangle lead with echo + reverb, detuned drone, sparse kick + clank, `ambience: {bed: cave}` | 24 bars, 60-75 s | yes | -16 | too many notes (keep under 3 notes/s); a drone that never changes (merge chords but move once per 4 bars); seam click from a bass attack on a silent bar end (keep the last bar sounding) |
| **ambience** | any | key only for tuned hums | a bed (`ambience:` at -6..0) plus at most a pad and a rare tone; or `chipforge ambience <bed>` alone | 60-120 s | yes | -20 | a bed that loops audibly (use integer LFO cycles - the engine does); music that competes with gameplay |
| **menu** | 85-105 | major 7ths, lydian, mixolydian | soft lead (`lead.pulse_soft`, `lead.fm_epiano`), bell arp, pad, sub root, hats only | 16 bars, 35-45 s | yes | -16 | fatigue: it plays for minutes, so no hooks that nag; a loud seam (the analyzer's `seam_flux`) |
| **shop** | 115-130, swing 0.1-0.15 | major, blues-tinged | chirpy 25% lead, bouncy pulse bass (root-fifth), triangle arp, light kit | 16 bars, 30 s | yes | -15 | too long; identical A/B (mute the harmony in B) |
| **victory** | 130-150 | major; end on I | fanfare rhythm (three short calls), harmony in thirds, arp on the last chord, crash | 2-3 bars, 4-8 s | one-shot, `loop: false` | -12 | tail cut off (the engine keeps it; do not add a rest bar); no bass under the final chord |
| **death** | 100-120 | minor; end on V or a dark chord | falling line, `@sweep(-12, 0.8)` on the last note, groan/boom sfx, one kick | 2 bars, 2-4 s | one-shot | -14 | too long; a bright sound (use 50% duty, lp) |
| **game over** | 65-80 | minor; resolve on i | slow descending lead + harmony, pad, held sub root, sparse kick, long reverb | 3-4 bars, 8-12 s | one-shot | -15 | ending unresolved (last bar must be the tonic chord, 4 beats); drums |
| **credits** | 105-120 | major, with a whole-tone lift halfway | flute/square lead, string pad, bell arp, picked bass, light kit; `chip: gm` or `fm` for the 16-bit feel | 32 bars, 60-75 s | yes | -14 | mid-band pile-up (lead + harmony + pad all at o5: drop the pad an octave or lower it); monotony (mute layers in the first A) |

## Chip choice

- `nes` - punch and nostalgia; two pulses + triangle + noise. Best for boss, combat, shop, stings.
- `gameboy` - thinner, brighter; wave-channel organ/bass. Overworld and menus.
- `sid` - aggressive filters, PWM, sync. Combat, boss, dark dungeons.
- `fm` - basses, brass, bells, e-piano. Menus, credits, Genesis-style boss.
- `gm` - clean 16-bit palette. Credits, calm themes.

Use `mode: enhanced` for the shipping mix (stereo, reverb, sub). `mode: authentic` enforces the
hardware (channel counts, mono, no reverb) when you want a strictly period-correct render.

## Loudness and headroom

Targets leave room for sound effects: boss/combat -12 LUFS, overworld -14, menu/dungeon -16,
ambience -20, with a -1 dBTP ceiling. If a game mixes music at -6 dB anyway, do not compensate
in the song; keep the targets and let the engine mix.
