# Integrations

## ChipForge MCP server

`chipforge-mcp` is a stdio MCP server exposing the engine to Claude Desktop, Claude Code and any
MCP client. It needs the `mcp` package (`pip install "chipforge[mcp]"`), or runs with nothing
installed through uv:

```json
{
  "mcpServers": {
    "chipforge": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Phantom027-cmd/chipforge", "chipforge-mcp"]
    }
  }
}
```

(Claude Desktop: `claude_desktop_config.json`. Claude Code: `claude mcp add chipforge -- uvx --from
git+https://github.com/Phantom027-cmd/chipforge chipforge-mcp`. Once the package is on PyPI the
`--from` becomes `chipforge`.) The server has no network access and only touches the paths you pass.

| tool | what it returns |
|---|---|
| `get_quickref` | QUICKREF.md: the one page needed to write a song |
| `list_presets(category)` | presets with one-line descriptions and kit pieces |
| `validate_song(path)` | `ok` + section layout, or the `file:line path: message` error with a hint |
| `render_song(path, out_dir, formats, stems, stems_by, analyze)` | output paths, loudness report, analysis summary with findings, and the composite PNG as image content |
| `analyze_audio(path, out_dir, include_audio)` | metrics + findings + image for an audio or song file; `include_audio` embeds the audio in the JSON for audio-capable clients |
| `compare_versions(path_a, path_b)` | metric deltas + stacked spectrograms |
| `read_feedback(path)` | notes from `feedback.json` written by the review page, newest first |
| `new_song_from_template(cue, path, title, key, tempo, chip)` | a starter song for the cue type |

Tool text is kept short; everything large is a file path or an image.

## Third-party MCP servers that pair with ChipForge

Checked on 2026-11-07. These are independent projects; versions and tools change.

- **[ableton-mcp](https://github.com/ahujasid/ableton-mcp)** (ahujasid, ~3.3k stars). Controls Ableton
  Live 10+ via a Remote Script: creates MIDI/audio tracks and clips, adds notes, loads instruments and
  effects, builds arrangements, transport and tempo. Run with `uvx ableton-mcp` after
  `uvx --from ableton-mcp ableton-mcp-install-script` and enabling the AbletonMCP control surface.
  *Limits:* it does not render or export audio, and there is no "import this .mid file" tool: a model
  must re-enter ChipForge's notes clip by clip (or you import the `.mid` yourself). Good for finishing
  a ChipForge MIDI with real instruments; telemetry is on by default (env var to disable).
- **[reaper-mcp](https://github.com/bonfire-systems/reaper-mcp)** (bonfire-systems, ~180 stars,
  `pip install reaper-mcp-server`, REAPER 7+, Python 3.10+). ~60 tools over python-reapy's distant API
  (enable it with a ReaScript once): tracks, MIDI items with notes / chords / drum patterns, FX,
  mixing, and - unlike Ableton - **rendering** (`render_project`, `render_stems`, `render_regions`)
  and `import_audio_file`. *Limits:* no MIDI-file import tool either; the distant API must be enabled
  and REAPER running; fewer users, so expect rough edges. Other REAPER servers exist
  ([xDarkzx/Reaper-MCP](https://github.com/xDarkzx/Reaper-MCP), [itsuzef](https://playbooks.com/mcp/itsuzef-reaper)).
- **[mcp-music-analysis](https://playbooks.com/mcp/hugohow/mcp-music-analysis)** (hugohow,
  `uvx -n mcp-music-analysis`). librosa tools: `analyze_beat` (tempo/beat times), `duration`, `mfcc`,
  `spectral_centroid`, `onset_times`; takes local files and URLs (incl. YouTube). *Limits:* no
  loudness, no stereo or seam checks, no images; the description mentions Whisper but no such tool
  is listed. ChipForge's `analyze_audio` covers the same ground with findings; use this one to
  cross-check tempo/onsets on third-party audio.

## Optional: SoundFont rendering of the `gm` palette

If `fluidsynth` is on PATH and you have a `.sf2`, the exported MIDI can be rendered with it:
`fluidsynth -ni font.sf2 song.mid -F song_sf.wav -r 44100`. ChipForge does not wrap this: a
SoundFont render has no loop-aware tails, so loop it from the `_loop` region or re-master the result
with `chipforge analyze` as a check.
