# ChipForge

A retro game music engine. Write a short YAML+MML song file, get a seamless, mastered loop
(WAV/OGG/MP3, stems, MIDI, loop metadata) with NES / Game Boy / SID / FM chip character and a
modern mix that holds up on phones and laptops - plus an analysis layer that lets AI models
"hear" what they wrote through metrics and images.

## Install

```bash
pip install -e .            # core: numpy, scipy, soundfile, mido, pyyaml
pip install -e ".[analysis]"   # optional: matplotlib for the analysis images (metrics need nothing extra)
```

## MCP (Claude Desktop / Claude Code)

```json
{"mcpServers": {"chipforge": {"command": "uvx", "args": ["--from", "git+https://github.com/Phantom027-cmd/chipforge", "chipforge-mcp"]}}}
```

## Quick start

```bash
chipforge quickref                                 # the one page you need to write a song
chipforge render examples/boss_factory.yml -o out  # wav + preview (loop twice) + stems + midi + json
chipforge render song.yml -f ogg -f mp3 --stems-by group   # loop-tagged OGG, MP3, instrument stems
chipforge analyze examples/boss_factory.yml        # metrics + findings + one PNG a model can read
chipforge compare out/v1.wav out/v2.wav            # side-by-side metrics and spectrograms
chipforge validate mysong.yml                      # precise, line-numbered errors
chipforge presets                                  # instrument library
```

## Docs

- [QUICKREF.md](QUICKREF.md) - song format cheat sheet (what a model reads before composing)
- [SONG_FORMAT.md](SONG_FORMAT.md) - full field reference (generated from the schema)
- [PRESETS.md](PRESETS.md) - instrument presets and voice parameters (generated)
- [INTEGRATIONS.md](INTEGRATIONS.md) - MCP server setup, tools, and third-party MCP servers that pair with it
- [CHANGELOG.md](CHANGELOG.md)
- `examples/` - finished tracks; `reference/` - the original proof-of-concept scripts

## Status

Milestone 6 of 8 (MCP server with eight tools, starter templates per cue). Coming: the human
review page + feedback loop, then finished examples, the cue guide, agent workflow and docs polish.

## Benchmark

`python benchmark.py` renders every example three times and reports the best time.
Container (2 vCPU, Python 3.13, NumPy 2.5), 60 s of 44.1 kHz stereo incl. LUFS mastering and
stems: `boss_factory` 1.6 s, `boss_factory_dark` (reverb + factory ambience) 3.7 s,
`overworld_gameboy` 1.1 s. The container is noisy; laptop numbers to follow.
