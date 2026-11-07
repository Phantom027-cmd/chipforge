# Agent workflow

The loop a model follows to produce a track. Every step is a CLI command or an MCP tool
(`INTEGRATIONS.md`); nothing requires hearing the audio.

```
pick template -> write song -> validate -> render -> analyze -> fix findings -> preview -> human feedback -> iterate
```

1. **Read `QUICKREF.md`** (`get_quickref`). It is the whole format. `CUE_GUIDE.md` has the tempo,
   key, instrumentation and length for the cue you were asked for.
2. **Start from the template** for the cue: `new_song_from_template(cue, path, title, key, tempo, chip)`
   or copy `chipforge/templates/<cue>.yml`. Keep the channel set; change melodies, chords, drum lanes
   and the arrangement. Changing `key:` does not transpose MML - write the notes in the new key or
   use `transpose:` on arrangement items.
3. **Validate**: `chipforge validate song.yml` / `validate_song`. Errors are `file:line path: message`
   with a hint; fix exactly what it says. A pattern's MML or riff must fill the bars or divide them
   evenly - the most common mistake is a bar that is one step short or long.
4. **Render**: `chipforge render song.yml -o out -f ogg` / `render_song`. Read the loudness line
   (target hit? limiter working hard = too hot a mix) and the file list.
5. **Analyze**: `render_song` already returns the summary and the image; otherwise
   `chipforge analyze song.yml`. Look at the image first: the spectrogram shows whether the lead
   line is visible as a bright melodic trace in 500 Hz-4 kHz, whether the bass region (second panel)
   has a clear note pattern, whether sections differ, and whether the loop marker lands on a busy
   downbeat. Then read the findings, highest severity first:
   - `clipping`, `true_peak`, `seam_click`: fix before anything else.
   - `band_*`: the message names the knob (`mix.hf`, channel `vol`, `lp`, presets).
   - `masking`: lower the arp/harmony in that section (`channels: {arp: {vol: 0.6}}` on the
     arrangement item) or move the lead up an octave.
   - `contrast`: mute a channel or layer in one section, or add one.
   - `seam_flux`: make the last bar lead into bar 1 (same instrumentation, V chord).
   - `density`: thin arps (`every: 4`) or shorten the harmony.
6. **Iterate** until there are no high findings and the mediums are deliberate. Use
   `chipforge compare old.wav new.wav` / `compare_versions` to confirm a change moved the metric
   you meant to move and nothing else.
7. **Preview for the human**: `chipforge review song.yml` / `build_review_page`. The page plays the
   loop with the real loop points, has a seam button and A/B versions. Ask the human to leave
   timestamped notes and a verdict.
8. **Read feedback**: `read_feedback(song)`; notes carry the version, time position and rating.
   Apply them in the song file (a note at 23.4 s in a 160 BPM song is bar 16 - the JSON sidecar's
   `bar_seconds` converts), re-render, and repeat from step 5. Mention in the next hand-off which
   note each change answers.

## Conventions that keep iterations cheap

- One song file per cue, versioned by the review page (`<out>/versions/`), so A/B is free.
- Change one thing between renders when chasing a finding; `compare` tells you what moved.
- Prefer arrangement-level fixes (`mute`, `channels: {x: {vol}}`, `transpose`) over editing notes.
- Keep `seed:` fixed while iterating; change it only to re-roll noise/ambience/reverb texture.
- Keep the section labels stable (`as:`) so feedback positions stay meaningful across versions.

## What "done" looks like

- `validate` ok; `analyze` has no high findings; loudness within 1 LU of the cue target.
- The loop seam: step ratio < 1.2 and flux ratio < 1.5 (or a deliberate section change).
- The human's last verdict in `feedback.json` is `approve`.
- Outputs: OGG with loop tags (or WAV with `smpl`), stems if the game is adaptive, JSON sidecar.
