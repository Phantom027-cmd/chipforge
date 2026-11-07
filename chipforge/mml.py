"""MML (Music Macro Language) and drum-lane parsers.

Output positions and lengths are in *steps* (16th notes by default), as floats.

MML dialect (see QUICKREF.md):
  c d e f g a b     notes;  '+'/'#' sharp, '-' flat;  optional length (4 = quarter), dots, '&' tie
  r                 rest (same length syntax)
  o4  < >           octave set / down / up          l8   default length
  v12               volume 0-15                     q6   gate 1-8 (8 = legato)
  ~c4               slide (portamento) into this note from the previous one
  [ ... ]3          repeat block
  |                 bar line (ignored)
  @name(args)       macro: @d(0.25) duty, @vib(depth,rate,delay), @arp(0,4,7), @sweep(semis,secs), @env(name)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

NOTE_PC = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}


class MMLError(ValueError):
    def __init__(self, msg: str, pos: int, src: str):
        self.pos, self.src = pos, src
        super().__init__(f"{msg} at char {pos}: ...{src[max(0, pos - 12):pos]}»{src[pos:pos + 12]}...")


@dataclass
class Note:
    start: float          # steps from pattern start
    length: float         # steps (gate applied later)
    midi: int | None      # None = rest
    vel: float = 1.0      # 0..1 (from v0-15)
    gate: float = 0.94    # 0..1 fraction of length
    slide: bool = False   # portamento from previous note
    macros: dict = field(default_factory=dict)   # active @macros at note start


_TOKEN = re.compile(
    r"(?P<ws>\s+)"
    r"|(?P<bar>\|)"
    r"|(?P<note>~?[a-g][+#\-]?\d*\.*(?:&[a-g]?[+#\-]?\d*\.*)*)"
    r"|(?P<rest>r\d*\.*)"
    r"|(?P<oct>o\d+)"
    r"|(?P<up>>)|(?P<down><)"
    r"|(?P<len>l\d+)"
    r"|(?P<vol>v\d+)"
    r"|(?P<gate>q\d+)"
    r"|(?P<open>\[)|(?P<close>\]\d*)"
    r"|(?P<macro>@[a-z_]+(?:\([^)]*\))?)"
)


def _len_to_steps(txt: str, default_len: int, steps_per_whole: float) -> float:
    """'8.' -> 1.5 * (whole/8). Empty -> default length."""
    m = re.match(r"(\d*)(\.*)", txt)
    n = int(m.group(1)) if m.group(1) else default_len
    if n <= 0:
        raise ValueError("length must be positive")
    base = steps_per_whole / n
    dots = len(m.group(2))
    return base * (2 - 0.5 ** dots)


def _parse_macro(txt: str) -> tuple[str, list[float]]:
    m = re.match(r"@([a-z_]+)(?:\((.*)\))?$", txt)
    name, args = m.group(1), m.group(2)
    vals: list[float] = []
    if args:
        for a in args.split(","):
            a = a.strip()
            try:
                vals.append(float(a))
            except ValueError:
                vals.append(a)  # type: ignore[arg-type]  (string arg, e.g. @env(pluck))
    return name, vals


def parse_mml(src: str, *, default_octave: int = 4, default_len: int = 16,
              steps_per_whole: float = 16.0) -> list[Note]:
    """Parse an MML string into Notes with positions in steps."""
    notes: list[Note] = []
    octave, dlen, vel, gate = default_octave, default_len, 1.0, 0.94
    macros: dict = {}
    pos = 0.0
    i = 0
    # repeat stack: (start_index_in_notes, start_pos, src_index_of_open)
    stack: list[tuple[int, float, int]] = []
    while i < len(src):
        m = _TOKEN.match(src, i)
        if not m:
            raise MMLError(f"unexpected character {src[i]!r}", i, src)
        kind = m.lastgroup
        txt = m.group(0)
        i = m.end()
        if kind in ("ws", "bar"):
            continue
        if kind == "note":
            slide = txt.startswith("~")
            body = txt.lstrip("~")
            pc = NOTE_PC[body[0]]
            rest = body[1:]
            if rest[:1] in ("+", "#"):
                pc += 1; rest = rest[1:]
            elif rest[:1] == "-":
                pc -= 1; rest = rest[1:]
            parts = [re.sub(r"^[a-g][+#\-]?", "", p) for p in rest.split("&")]
            try:
                length = sum(_len_to_steps(p, dlen, steps_per_whole) for p in parts)
            except ValueError as e:
                raise MMLError(str(e), m.start(), src) from None
            midi = 12 * (octave + 1) + pc
            if slide and not notes:
                raise MMLError("slide '~' needs a previous note", m.start(), src)
            notes.append(Note(pos, length, midi, vel, gate, slide, dict(macros)))
            pos += length
        elif kind == "rest":
            try:
                length = _len_to_steps(txt[1:], dlen, steps_per_whole)
            except ValueError as e:
                raise MMLError(str(e), m.start(), src) from None
            notes.append(Note(pos, length, None))
            pos += length
        elif kind == "oct":
            octave = int(txt[1:])
            if not 0 <= octave <= 8:
                raise MMLError("octave must be 0-8", m.start(), src)
        elif kind == "up":
            octave += 1
        elif kind == "down":
            octave -= 1
        elif kind == "len":
            dlen = int(txt[1:])
            if dlen <= 0:
                raise MMLError("l needs a positive length", m.start(), src)
        elif kind == "vol":
            v = int(txt[1:])
            if not 0 <= v <= 15:
                raise MMLError("v must be 0-15", m.start(), src)
            vel = v / 15
        elif kind == "gate":
            q = int(txt[1:])
            if not 1 <= q <= 8:
                raise MMLError("q must be 1-8", m.start(), src)
            gate = 0.94 if q == 8 else q / 8
        elif kind == "open":
            stack.append((len(notes), pos, m.start()))
        elif kind == "close":
            if not stack:
                raise MMLError("']' without '['", m.start(), src)
            n = int(txt[1:]) if len(txt) > 1 else 2
            start_idx, start_pos, _ = stack.pop()
            block = notes[start_idx:]
            span = pos - start_pos
            for k in range(1, n):
                for nt in block:
                    notes.append(Note(nt.start + k * span, nt.length, nt.midi, nt.vel, nt.gate,
                                      nt.slide, dict(nt.macros)))
            pos = start_pos + n * span
        elif kind == "macro":
            name, args = _parse_macro(txt)
            if name == "off":
                macros.clear()
            else:
                macros[name] = args
    if stack:
        raise MMLError("'[' without ']'", stack[-1][2], src)
    return notes


# ---------------------------------------------------------------- drum lanes
ACCENT = {"x": 1.0, "X": 1.0, "o": 0.55, "g": 0.3}


@dataclass
class Hit:
    start: float   # steps
    vel: float


def parse_lane(src: str) -> list[Hit]:
    """'x.o.x.o.' -> hits. '.'/'-' rest; x o g accents; 1-9 velocity tenths; '|' ignored."""
    hits: list[Hit] = []
    step = 0
    for ch in src:
        if ch in " |":
            continue
        if ch in ".-":
            step += 1
            continue
        if ch in ACCENT:
            hits.append(Hit(step, ACCENT[ch]))
        elif ch.isdigit() and ch != "0":
            hits.append(Hit(step, int(ch) / 10))
        else:
            raise ValueError(f"bad drum character {ch!r} (use . x o g or 1-9)")
        step += 1
    return hits


def lane_length(src: str) -> int:
    return sum(1 for ch in src if ch not in " |")


def mml_length(notes: list[Note]) -> float:
    return max((n.start + n.length for n in notes), default=0.0)
