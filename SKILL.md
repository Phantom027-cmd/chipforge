---
name: chipforge-compose
description: Compose, render and iterate retro game music (NES / Game Boy / SID / FM / GM) with the ChipForge engine from a short YAML+MML song file; use when asked for chiptune or 8-bit / 16-bit game tracks, loops, stings, fanfares or ambience beds, or to improve one with the analyzer's findings and human feedback.
---

# ChipForge composer

ChipForge turns a ~100-line YAML song file into a seamless, mastered loop with loop metadata,
stems and MIDI, and gives you metrics, findings and an image instead of audio you cannot hear.

## Setup

- CLI: `pip install -e .` in the repo (or `pip install chipforge`). Commands: `chipforge quickref |
  validate | render | analyze | compare | review | ambience | presets`.
- MCP (preferred in Claude Desktop / Code): `uvx --from git+https://github.com/Phantom027-cmd/chipforge chipforge-mcp`;
  tools `get_quickref`, `list_presets`, `new_song_from_template`, `validate_song`, `render_song`,
  `analyze_audio`, `compare_versions`, `build_review_page`, `read_feedback`.

## Procedure

1. Call `get_quickref` (or read `QUICKREF.md`). Do not guess the format from memory.
2. Pick the cue's row in `CUE_GUIDE.md` (tempo, keys, instruments, length, loop or one-shot).
3. `new_song_from_template(cue, path, title, key, tempo, chip)`, then rewrite melodies, chords,
   drum lanes and the arrangement. Original music only; never reproduce existing game themes.
4. `validate_song` → fix the `file:line` error it names → repeat until ok.
5. `render_song` → read the loudness line and the findings; look at the returned image
   (lead visible in 500 Hz-4 kHz, bass pattern clear, sections distinct, loop marker on a downbeat).
6. Fix findings highest severity first using the knob each message names; `compare_versions` to
   confirm. Stop when there are no high findings.
7. `build_review_page` and ask the human to listen (`chipforge review song.yml` serves it); then
   `read_feedback` and apply every note, saying which change answers which note.

## Rules of thumb

- MML and riff strings must fill the pattern or divide it evenly; count 16ths per bar.
- Bass presets already sit on the `low` bus; keep one lead in 1-4 kHz; harmony a third below.
- Loops: end on V, keep the last bar busy, no intro unless `loop: {from: X}`.
- One-shots (`loop: false`): the engine keeps the natural tail; do not pad with rests.
- Change one thing per render while chasing a finding; keep `seed:` fixed.
