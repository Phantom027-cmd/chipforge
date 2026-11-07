"""Write renders to disk: WAV/OGG/MP3, preview, stems, MIDI, and loop metadata."""
from __future__ import annotations

import json
import struct
from pathlib import Path

import mido
import numpy as np
import soundfile as sf

from . import presets as _presets
from .render import RenderResult


def _slug(s: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in s).strip("_")


def write_audio(path: Path, x: np.ndarray, sr: int, loop: tuple[int, int] | None = None, bits: int = 16):
    """Write WAV (with smpl loop chunk) / OGG (with LOOPSTART/LOOPLENGTH) / MP3 by extension."""
    path = Path(path)
    x = np.clip(x, -1, 1)
    ext = path.suffix.lower()
    if ext == ".wav":
        sf.write(str(path), x, sr, subtype="PCM_24" if bits == 24 else "PCM_16")
        if loop:
            _add_smpl_chunk(path, sr, loop[0], loop[1])
    elif ext == ".ogg":
        with sf.SoundFile(str(path), "w", sr, x.shape[1] if x.ndim == 2 else 1, format="OGG", subtype="VORBIS") as f:
            for i in range(0, len(x), sr):          # chunked: libsndfile's vorbis encoder crashes on huge writes
                f.write(x[i:i + sr])
        if loop:
            _patch_ogg_loop_tags(path, loop)
    elif ext == ".mp3":
        try:
            sf.write(str(path), x, sr, format="MP3")
        except Exception:
            import shutil, subprocess, tempfile
            if not shutil.which("ffmpeg"):
                raise RuntimeError("MP3 needs libsndfile>=1.1 with MPEG support or ffmpeg on PATH")
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td) / "tmp.wav"
                sf.write(str(tmp), x, sr, subtype="PCM_16")
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp), "-b:a", "192k", str(path)], check=True)
    else:
        raise ValueError(f"unsupported audio format {ext}")


def _add_smpl_chunk(path: Path, sr: int, start: int, end: int):
    """Append a RIFF 'smpl' chunk with one forward loop (what samplers and game engines read)."""
    data = path.read_bytes()
    smpl = struct.pack("<IIIIIIIII", 0, 0, int(1e9 / sr), 60, 0, 0, 0, 1, 0)
    smpl += struct.pack("<IIIIII", 0, 0, start, max(start, end - 1), 0, 0)
    chunk = b"smpl" + struct.pack("<I", len(smpl)) + smpl
    data = data + chunk
    data = data[:4] + struct.pack("<I", len(data) - 8) + data[8:]
    path.write_bytes(data)


def _patch_ogg_loop_tags(path: Path, loop: tuple[int, int]):
    """Add LOOPSTART/LOOPLENGTH Vorbis comments (the RPG Maker / Godot / Unity-plugin convention)."""
    import mutagen.oggvorbis
    f = mutagen.oggvorbis.OggVorbis(str(path))
    f["LOOPSTART"] = str(loop[0])
    f["LOOPLENGTH"] = str(loop[1] - loop[0])
    f.save()


def write_midi(path: Path, res: RenderResult):
    """One track per channel (plus a meta track with tempo, time signature and loop markers)."""
    song, tl = res.song, res.timeline
    tpb = 480
    tick = lambda t: int(round(t / (60 / song.tempo) * tpb))
    mf = mido.MidiFile(ticks_per_beat=tpb)
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("track_name", name=song.title, time=0))
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(song.tempo), time=0))
    meta.append(mido.MetaMessage("time_signature", numerator=song.beats, denominator=song.beat_unit, time=0))
    last = 0
    marks = [(tick(s.start), s.label) for s in tl.sections]
    if tl.loop_start is not None:
        marks += [(tick(tl.loop_start), "loopStart"), (tick(tl.length), "loopEnd")]
    for tk, name in sorted(marks):
        meta.append(mido.MetaMessage("marker", text=name, time=tk - last))
        last = tk
    mf.tracks.append(meta)
    chan_no = 0
    for name, ch in song.channels.items():
        preset = _presets.get(ch.preset)
        is_kit = preset["kind"] == "kit"
        midi_ch = 9 if is_kit else chan_no
        if not is_kit:
            chan_no += 1
            if chan_no == 9:
                chan_no += 1
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("track_name", name=name, time=0))
        if not is_kit:
            tr.append(mido.Message("program_change", channel=midi_ch, program=ch.overrides.get("gm", preset.get("gm", 80)), time=0))
        evs = []
        for e in tl.channel_events(name):
            if is_kit:
                piece = preset["pieces"].get(e.piece, {})
                note = int(e.params.get("note") or piece.get("gm", 38))
                dur = e.params.get("dur", 0.1) if e.piece and len(e.piece) > 1 else 0.1
            else:
                if e.midi is None:
                    continue
                note, dur = int(round(e.midi)), e.dur
            note = max(0, min(127, note))
            v = max(1, min(127, int(e.vel * 100)))
            evs.append((tick(e.t), 1, mido.Message("note_on", channel=midi_ch, note=note, velocity=v)))
            evs.append((tick(e.t + dur), 0, mido.Message("note_off", channel=midi_ch, note=note, velocity=0)))
        evs.sort(key=lambda x: (x[0], x[1]))
        last = 0
        for tk, _, msg in evs:
            msg.time = tk - last
            last = tk
            tr.append(msg)
        mf.tracks.append(tr)
    mf.save(str(path))


def sidecar(res: RenderResult, paths: dict[str, str] | None = None) -> dict:
    """Everything a game engine or a tool needs to use the render: tempo grid, loop points in samples
    and seconds, sections with transition exits, intensity layers and their channels, stems, loudness."""
    from . import __version__
    song, tl, sr = res.song, res.timeline, res.sr
    n = len(res.mix)
    layers = sorted({c.layer for c in song.channels.values()})
    d = {
        "chipforge": __version__, "format": 1,
        "title": song.title, "cue": song.cue, "tempo": song.tempo, "time": f"{song.beats}/{song.beat_unit}",
        "key": song.raw.get("key", "C"), "chip": song.chip, "mode": song.mode, "seed": song.seed,
        "sample_rate": sr, "channels": 2, "length_samples": n, "length_seconds": round(n / sr, 6),
        "bars": round(tl.length / (song.step_s * song.steps_per_bar), 3),
        "beat_seconds": round(60 / song.tempo, 6), "bar_seconds": round(song.step_s * song.steps_per_bar, 6),
        "loop": None if res.loop_start is None else {
            "start_samples": res.loop_start, "end_samples": res.loop_end,
            "start_seconds": res.loop_start / sr, "end_seconds": res.loop_end / sr,
            "length_samples": res.loop_end - res.loop_start},
        "sections": [{"label": s.label, "pattern": s.pattern, "start": round(s.start, 4), "end": round(s.end, 4),
                      "start_samples": int(round(s.start * sr)), "exits": [round(x, 4) for x in s.exits],
                      "layers": s.layers} for s in tl.sections],
        "layers": [{"layer": L, "channels": [n_ for n_, c in song.channels.items() if c.layer == L],
                    "stem": f"layer{L}"} for L in layers],
        "channels": {n_: {"preset": c.preset, "layer": c.layer} for n_, c in song.channels.items()},
        "stems": {k: v for k, v in (paths or {}).items() if k.startswith("stem_")},
        "files": {k: v for k, v in (paths or {}).items() if not k.startswith("stem_")},
        "loudness": {k: res.stats[k] for k in ("target_lufs", "lufs_after", "true_peak", "gain_db", "limited_db") if k in res.stats},
        "render": {"seconds": round(res.seconds, 3), "notes": res.stats.get("notes"), "parts": res.stats.get("parts")},
    }
    return d


def write_all(res: RenderResult, out_dir: str | Path, *, formats=("wav",), stems: bool = True, preview: bool = True,
              midi: bool = True, bits: int = 16, split_intro: bool = True) -> dict[str, str]:
    """Write every output for a render. Returns {kind: path}.

    Files: <title>.<fmt> (with loop metadata), <title>_preview.<fmt> (loop played twice), <title>_intro /
    <title>_loop (for engines that chain an intro into a loop file), <title>_stems/<stem>.<fmt>,
    <title>.mid, <title>.json."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    base = _slug(res.song.title)
    sr = res.sr
    loop = (res.loop_start, res.loop_end) if res.loop_start is not None else None
    paths: dict[str, str] = {}
    for f in formats:
        p = out / f"{base}.{f}"
        write_audio(p, res.mix, sr, loop, bits)
        paths[f] = str(p)
    fmt0 = formats[0]
    if preview and loop:
        pv = np.concatenate([res.mix, res.mix[res.loop_start:]])
        p = out / f"{base}_preview.{fmt0}"
        write_audio(p, pv, sr, None, bits)
        paths["preview"] = str(p)
    if split_intro and loop and res.loop_start > 0:
        pi, pl = out / f"{base}_intro.{fmt0}", out / f"{base}_loop.{fmt0}"
        write_audio(pi, res.mix[: res.loop_start], sr, None, bits)
        write_audio(pl, res.mix[res.loop_start:], sr, (0, res.loop_end - res.loop_start), bits)
        paths["intro"], paths["loop"] = str(pi), str(pl)
    if stems:
        sd = out / f"{base}_stems"
        sd.mkdir(exist_ok=True)
        if res.ambience is not None:
            write_audio(sd / f"music.{fmt0}", res.music, sr, loop, bits)
            paths["stem_music"] = str(sd / f"music.{fmt0}")
        for name, x in res.stems.items():
            write_audio(sd / f"{name}.{fmt0}", x, sr, loop, bits)
            paths[f"stem_{name}"] = str(sd / f"{name}.{fmt0}")
    if midi:
        p = out / f"{base}.mid"
        write_midi(p, res)
        paths["midi"] = str(p)
    p = out / f"{base}.json"
    paths["json"] = str(p)
    p.write_text(json.dumps(sidecar(res, paths), indent=1), encoding="utf-8")
    return paths


def read_wav_loop(path: str | Path) -> tuple[int, int] | None:
    """Read the first loop of a WAV 'smpl' chunk: (start, end_exclusive) in samples, or None."""
    data = Path(path).read_bytes()
    pos = 12
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        if cid == b"smpl":
            body = data[pos + 8:pos + 8 + size]
            n_loops = struct.unpack("<I", body[28:32])[0]
            if n_loops:
                start, end = struct.unpack("<II", body[44:52])
                return start, end + 1
            return None
        pos += 8 + size + (size & 1)
    return None


def read_ogg_loop(path: str | Path) -> tuple[int, int] | None:
    import mutagen.oggvorbis
    f = mutagen.oggvorbis.OggVorbis(str(path))
    if "LOOPSTART" in f and "LOOPLENGTH" in f:
        s_, l_ = int(f["LOOPSTART"][0]), int(f["LOOPLENGTH"][0])
        return s_, s_ + l_
    return None
