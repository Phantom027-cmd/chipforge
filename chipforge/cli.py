"""chipforge command line."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _load(path: str):
    from .schema import SongError, load
    try:
        return load(path)
    except SongError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)


def cmd_validate(a):
    song = _load(a.song)
    from .score import build
    tl = build(song)
    secs = tl.length
    print(f"ok: {song.title!r} ({song.cue}, {song.tempo:g} bpm, {len(tl.events)} events, "
          f"{secs:.2f} s, {'loop' if tl.loop_start is not None else 'one-shot'}"
          + (f" from {tl.loop_start:.2f} s" if tl.loop_start else "") + ")")
    for s in tl.sections:
        print(f"  {s.label:<10} {s.start:7.2f}-{s.end:7.2f} s  ({s.pattern})")


def cmd_render(a):
    song = _load(a.song)
    from .render import render
    from .export import write_all
    res = render(song, stems=not a.no_stems, stems_by=a.stems_by)
    out = a.out or str(Path(a.song).with_suffix("")) + "_out"
    paths = write_all(res, out, formats=tuple(a.format), stems=not a.no_stems, preview=not a.no_preview,
                      midi=not a.no_midi, bits=a.bits)
    st = res.stats
    print(f"rendered {song.title!r} in {res.seconds:.2f} s  ({st['notes']} events, "
          f"cache {st['cache_hits']}/{st['cache_hits'] + st['cache_misses']}, "
          f"{st.get('lufs_after', 0):.1f} LUFS (target {st.get('target_lufs', 0):.0f}), "
          f"true peak {st.get('true_peak', 0):.1f} dBTP, limiter {st.get('limited_db', 0):.1f} dB)")
    for k, p in paths.items():
        print(f"  {k:<12} {p}")


def cmd_presets(a):
    from . import presets
    for cat, names in presets.categories().items():
        if a.category and cat != a.category:
            continue
        print(f"[{cat}]")
        for n in names:
            p = presets.get(n)
            print(f"  {n:<22} {p.get('doc', '')}")


AMBIENCE_SONG = """chipforge: 1
title: {title}
cue: ambience
tempo: 120
key: {key}
seed: {seed}
ambience: {{bed: {bed}, level: 0}}
channels: {{x: {{preset: lead.pulse25, vol: 0}}}}
patterns: {{A: {{bars: {bars}}}}}
arrangement: [A]
"""


def cmd_ambience(a):
    """Render a seamless ambience-only loop."""
    from .schema import loads
    from .render import render
    from .export import write_all
    bars = max(1, int(round(a.seconds / 2.0)))      # 120 bpm 4/4 -> 2 s per bar
    song = loads(AMBIENCE_SONG.format(title=f"{a.bed} ambience", key=a.key, seed=a.seed, bed=a.bed, bars=bars))
    res = render(song, stems=False)
    paths = write_all(res, a.out or f"{a.bed}_ambience", formats=tuple(a.format), stems=False, preview=True, midi=False)
    print(f"rendered {a.bed} ambience, {len(res.mix) / res.sr:.1f} s loop, {res.stats.get('lufs_after', 0):.1f} LUFS")
    for k, p in paths.items():
        print(f"  {k:<12} {p}")


def cmd_quickref(a):
    p = Path(__file__).parent.parent / "QUICKREF.md"
    if not p.exists():
        p = Path(__file__).parent / "data" / "QUICKREF.md"
    print(p.read_text(encoding="utf-8"))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="chipforge", description="Retro game music engine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("validate", help="check a song file and print its structure")
    p.add_argument("song"); p.set_defaults(fn=cmd_validate)
    p = sub.add_parser("render", help="render a song to audio, MIDI and metadata")
    p.add_argument("song"); p.add_argument("-o", "--out")
    p.add_argument("-f", "--format", action="append", default=None, help="wav/ogg/mp3 (repeatable)")
    p.add_argument("--bits", type=int, default=16, choices=[16, 24])
    p.add_argument("--no-stems", action="store_true"); p.add_argument("--no-preview", action="store_true")
    p.add_argument("--no-midi", action="store_true")
    p.add_argument("--stems-by", choices=["layer", "group", "channel"], default="layer",
                   help="stem split: adaptive layers (default), instrument groups, or every channel")
    p.set_defaults(fn=cmd_render)
    p = sub.add_parser("presets", help="list instrument presets"); p.add_argument("category", nargs="?")
    p.set_defaults(fn=cmd_presets)
    p = sub.add_parser("quickref", help="print the one-page song format reference"); p.set_defaults(fn=cmd_quickref)
    p = sub.add_parser("ambience", help="render a seamless environment loop on its own")
    p.add_argument("bed", choices=["factory", "cave", "forest", "rain", "wind", "machinery", "water", "crowd"])
    p.add_argument("-s", "--seconds", type=float, default=60); p.add_argument("-o", "--out")
    p.add_argument("-k", "--key", default="C", help="key for tuned elements (hums)"); p.add_argument("--seed", type=int, default=1)
    p.add_argument("-f", "--format", action="append", default=None)
    p.set_defaults(fn=cmd_ambience)
    a = ap.parse_args(argv)
    if getattr(a, "format", None) is None and a.cmd in ("render", "ambience"):
        a.format = ["wav"]
    a.fn(a)


if __name__ == "__main__":
    main()
