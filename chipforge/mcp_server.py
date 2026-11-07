"""ChipForge MCP server (stdio) for Claude Desktop / Claude Code.

    chipforge-mcp                       # after `pip install chipforge[mcp]`
    uvx --from chipforge chipforge-mcp  # no install

Tools keep their text output short; images come back as MCP image content so the model sees them.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

try:                                   # mcp >= 2
    from mcp.server.mcpserver import Image, MCPServer as _Server
except ImportError:                    # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server, Image  # type: ignore

from . import __version__

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = Path(__file__).resolve().parent / "templates"
CUES = ["boss", "combat", "overworld", "dungeon", "ambience", "menu", "shop", "victory", "death", "gameover", "credits"]

server = _Server(
    "chipforge",
    instructions="Retro game music engine. Workflow: get_quickref -> new_song_from_template -> edit the YAML -> "
                 "validate_song -> render_song (returns paths, a metric summary and the analysis image) -> fix "
                 "findings -> read_feedback after a human review. Song files are plain YAML on disk; edit them "
                 "with your file tools.",
    version=__version__,
)


def _quickref_text() -> str:
    for cand in (ROOT / "QUICKREF.md", Path(__file__).resolve().parent / "data" / "QUICKREF.md"):
        if cand.exists():
            return cand.read_text(encoding="utf-8")
    return "QUICKREF.md not found"


@server.tool()
def get_quickref() -> str:
    """The one-page song format reference (format cheat sheet, minimal example, most-used presets).
    Read this before writing a song."""
    return _quickref_text()


@server.tool()
def list_presets(category: str = "") -> str:
    """List instrument presets, optionally one category: lead, arp, bass, pad, drone, kit, fx."""
    from . import presets
    out = []
    for cat, names in presets.categories().items():
        if category and cat != category:
            continue
        for n in names:
            p = presets.get(n)
            extra = f" [pieces: {' '.join(p['pieces'])}]" if p["kind"] == "kit" else ""
            out.append(f"{n}: {p.get('doc', '')}{extra}")
    return "\n".join(out) or f"no category {category!r}; use lead, arp, bass, pad, drone, kit or fx"


@server.tool()
def validate_song(path: str) -> str:
    """Validate a song file. Returns 'ok' with the section layout, or the exact file:line error and a hint."""
    from .schema import SongError, load
    from .score import build
    try:
        song = load(path)
    except SongError as e:
        return f"error: {e}"
    tl = build(song)
    lines = [f"ok: {song.title!r} ({song.cue}, {song.tempo:g} bpm, {tl.length:.1f} s, "
             f"{'loop' if tl.loop_start is not None else 'one-shot'}, {len(tl.events)} events)"]
    lines += [f"  {s.label:<10} {s.start:6.1f}-{s.end:6.1f} s" for s in tl.sections]
    return "\n".join(lines)


@server.tool()
def render_song(path: str, out_dir: str = "", formats: str = "wav", stems: bool = True, stems_by: str = "layer",
                analyze: bool = True) -> list:
    """Render a song file to audio (+ preview, stems, MIDI, JSON) and analyze it. Returns the output paths,
    a short metric/findings summary and the composite analysis image. formats: comma list of wav/ogg/mp3."""
    from .schema import SongError, load
    try:
        song = load(path)
    except SongError as e:
        return [f"error: {e}"]
    from .export import write_all
    from .render import render
    out = out_dir or str(Path(path).with_suffix("")) + "_out"
    res = render(song, stems=stems, stems_by=stems_by)
    paths = write_all(res, out, formats=tuple(f.strip() for f in formats.split(",") if f.strip()), stems=stems)
    st = res.stats
    text = [f"rendered {song.title!r}: {len(res.mix) / res.sr:.1f} s, {st.get('lufs_after', 0):.1f} LUFS "
            f"(target {st.get('target_lufs')}), true peak {st.get('true_peak', 0):.1f} dBTP, "
            f"limiter {st.get('limited_db', 0):.1f} dB, {res.seconds:.1f} s render time",
            "files: " + ", ".join(f"{k}={v}" for k, v in paths.items() if not k.startswith("stem_")),
            "stems: " + ", ".join(v for k, v in paths.items() if k.startswith("stem_"))]
    content: list = []
    if analyze:
        from .analyze import analyze as _analyze
        rep = _analyze(paths.get("wav") or paths.get("ogg") or path, out_dir=out)
        text.append("analysis: " + rep.summary(max_findings=6).replace("\n", "\n  "))
        if rep.png:
            content.append(Image(path=rep.png))
    return ["\n".join(text)] + content


@server.tool()
def analyze_audio(path: str, out_dir: str = "", include_audio: bool = False) -> list:
    """Analyze an audio file or a song file: loudness, band balance, stereo, seam, masking, contrast,
    density, tempo. Returns a summary with findings plus the composite image. include_audio embeds the
    audio (base64) in the JSON report for audio-capable clients."""
    from .analyze import analyze, format_text
    out = out_dir or (str(Path(path).with_suffix("")) + "_analysis" if Path(path).suffix in (".yml", ".yaml")
                      else str(Path(path).parent))
    try:
        rep = analyze(path, out_dir=out, include_audio=include_audio)
    except Exception as e:
        return [f"error: {e}"]
    content: list = [format_text(rep)]
    if rep.png:
        content.append(Image(path=rep.png))
    return content


@server.tool()
def compare_versions(path_a: str, path_b: str, out_dir: str = "") -> list:
    """Side-by-side metrics (with deltas) and stacked spectrograms for two renders or song files."""
    from .analyze import compare
    r = compare(path_a, path_b, out_dir=out_dir or str(Path(path_b).parent))
    lines = [f"{'metric':<22}{'A':>9}{'B':>9}{'delta':>9}"]
    for row in r["rows"]:
        d = "" if row["delta"] is None else f"{row['delta']:+.2f}"
        lines.append(f"{row['metric']:<22}{str(row['a']):>9}{str(row['b']):>9}{d:>9}")
    for tag in ("a", "b"):
        if r[f"findings_{tag}"]:
            lines.append(f"findings {tag.upper()}: " + " | ".join(r[f"findings_{tag}"][:5]))
    content: list = ["\n".join(lines)]
    if r.get("png"):
        content.append(Image(path=r["png"]))
    return content


@server.tool()
def read_feedback(path: str) -> str:
    """Read human feedback saved by the review page. `path` may be the song file (looks in its _out folder
    and next to it), the output folder, or feedback.json itself. Returns the notes, newest first."""
    p = Path(path)
    if p.is_dir():
        cands = [p / "feedback.json"]
    elif p.name == "feedback.json":
        cands = [p]
    else:
        cands = [Path(str(p.with_suffix("")) + "_out") / "feedback.json", p.parent / "feedback.json",
                 p.parent / "out" / "feedback.json"]
    for c in cands:
        if c.exists():
            try:
                data = json.loads(c.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                return f"feedback.json is not valid JSON: {e}"
            entries = data.get("entries", data if isinstance(data, list) else [])
            if not entries:
                return "no feedback yet"
            out = [f"feedback from {c} ({len(entries)} entries):"]
            for e in sorted(entries, key=lambda x: x.get("time", ""), reverse=True)[:30]:
                where = f" @ {e['at']:.1f}s" if isinstance(e.get("at"), (int, float)) else ""
                ver = f" [{e['version']}]" if e.get("version") else ""
                rating = f" rating {e['rating']}/5" if e.get("rating") else ""
                out.append(f"- {e.get('time', '')[:16]}{ver}{where}{rating}: {e.get('note', '')}")
            return "\n".join(out)
    return "no feedback yet (looked for feedback.json in the song's _out folder, next to the song, and in ./out; pass the folder or file explicitly)"


@server.tool()
def new_song_from_template(cue: str, path: str, title: str = "", key: str = "", tempo: float = 0,
                           chip: str = "") -> str:
    """Create a new song file from the starter template for a cue type (boss, combat, overworld, dungeon,
    ambience, menu, shop, victory, death, gameover, credits), optionally overriding title/key/tempo/chip.
    Returns the path and the next step."""
    if cue not in CUES:
        return f"unknown cue {cue!r}; one of: {', '.join(CUES)}"
    src = TEMPLATES / f"{cue}.yml"
    text = src.read_text(encoding="utf-8")
    import re
    if title:
        text = re.sub(r"^title: .*$", f"title: {title}", text, count=1, flags=re.M)
    if key:
        text = re.sub(r"^key: .*$", f"key: {key}", text, count=1, flags=re.M)
    if tempo:
        text = re.sub(r"^tempo: .*$", f"tempo: {tempo:g}", text, count=1, flags=re.M)
    if chip:
        text = re.sub(r"^chip: .*$", f"chip: {chip}", text, count=1, flags=re.M)
    dst = Path(path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text, encoding="utf-8")
    from .schema import SongError, loads
    try:
        loads(text, file=str(dst))
    except SongError as e:
        return f"wrote {dst} but it does not validate after the overrides: {e}"
    return (f"wrote {dst} from the {cue} template. Next: edit the melodies/chords/patterns (presets fit together at "
            f"vol 1), then validate_song and render_song. Changing `key:` does not transpose MML notes; use "
            f"`transpose:` on arrangement items or rewrite the notes.")


@server.tool()
def build_review_page(path: str, out_dir: str = "") -> str:
    """Snapshot the current render as a new version and (re)build the human review page
    (out_dir/review.html: player, loop-seam audition, A/B versions, stems, timestamped notes, rating).
    Returns the page path and the command that serves it; ask the human to open it and leave notes,
    then call read_feedback."""
    from .review import review
    try:
        page = review(path, out_dir or None, serve_page=False)
    except Exception as e:
        return f"error: {e}"
    return (f"review page: {page}\nServe it with `chipforge review {path}` (opens the browser and saves "
            f"feedback.json automatically), or open the file directly and use 'download feedback.json'.")


def main():
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
