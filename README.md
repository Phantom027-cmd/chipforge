# ChipForge

A retro game music engine for people and AI models. Write a ~100-line YAML+MML song file, get a
seamless, mastered loop (WAV/OGG/MP3 with loop points, stems, MIDI, JSON) in NES, Game Boy, SID,
FM or 16-bit flavour - plus an analysis layer that turns the audio into metrics, findings and one
image, so a model that cannot hear can still judge and fix what it wrote.

## Install

```bash
pip install -e .                 # core: numpy, scipy, soundfile, mido, pyyaml, mutagen
pip install -e ".[analysis,mcp]" # + matplotlib for analysis images, mcp for the server
```

## Quick start

```bash
chipforge quickref                                    # the one page you need to write a song
chipforge render examples/boss_factory.yml -o out     # ogg/wav with loop tags, preview, stems, midi, json
chipforge analyze examples/boss_factory.yml           # LUFS, bands, seam, masking... + findings + PNG
chipforge review examples/boss_factory.yml            # local page: play, seam audition, A/B, notes -> feedback.json
chipforge ambience cave -s 60 -k E                    # a seamless environment bed on its own
```

MCP for Claude Desktop / Claude Code (see [INTEGRATIONS.md](INTEGRATIONS.md)):

```json
{"mcpServers": {"chipforge": {"command": "uvx", "args": ["--from", "git+https://github.com/Phantom027-cmd/chipforge", "chipforge-mcp"]}}}
```

## Docs

| | |
|---|---|
| [QUICKREF.md](QUICKREF.md) | the song format on one page (what a model reads before composing) |
| [SONG_FORMAT.md](SONG_FORMAT.md) | every field, generated from the schema; outputs and loop metadata per engine |
| [PRESETS.md](PRESETS.md) | 66 instrument presets and voice parameters, generated |
| [CUE_GUIDE.md](CUE_GUIDE.md) | style bible: tempo, keys, instruments, length, loudness and pitfalls per cue |
| [AGENT_WORKFLOW.md](AGENT_WORKFLOW.md) | the compose -> validate -> render -> analyze -> fix -> review loop |
| [SKILL.md](SKILL.md) | the same workflow as an installable agent skill |
| [INTEGRATIONS.md](INTEGRATIONS.md) | MCP setup and third-party DAW / analysis MCP servers |
| [CHANGELOG.md](CHANGELOG.md) | |

`examples/` has 13 finished tracks (every cue type, five chips); `chipforge/templates/` has a
starter per cue; `reference/` keeps the original proof-of-concept scripts.

## Guarantees

Deterministic renders (same file + same version = identical samples), seamless loops (tails,
reverb and filters wrap circularly; a seam test runs on every example), no clipping (-1 dBTP
limiter), LUFS-normalized per cue, no DC, docs that cannot drift (generated from code; every doc
example runs in the test suite; a test fails when generated docs are stale).

## Benchmark

`python benchmark.py` (best of 3). This 2-vCPU cloud container, Python 3.13, NumPy 2.5, 44.1 kHz
stereo, mastering and stems included:

| example | audio | render | realtime |
|---|---|---|---|
| boss_factory (NES, 1873 events) | 60 s | 2.4 s | 25x |
| boss_factory_dark (NES + reverb + factory ambience) | 60 s | 4.4 s | 14x |
| boss_sid (SID filters + machinery ambience) | 55 s | 4.4 s | 13x |
| overworld_gameboy | 54 s | 1.4 s | 40x |
| menu_fm (4-op FM) | 42 s | 1.8 s | 24x |
| shop / victory / death / gameover | 31 / 8 / 7 / 13 s | 0.9 / 0.2 / 0.3 / 0.5 s | 25-36x |

A laptop-class CPU is roughly twice as fast as this container, which puts a plain 60 s track at
about 1-2 s and the heaviest (reverb + ambience + stems) at 2-3 s.
