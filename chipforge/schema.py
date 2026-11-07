"""Song file schema: loading (with line numbers), validation and typed Song objects.

The SPEC tables below are the single source of truth for the song format; SONG_FORMAT.md is
generated from them (see docgen.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import presets as _presets
from .theory import Chord, SCALES, parse_key

FORMAT_VERSION = 1
CUES = ["boss", "combat", "overworld", "dungeon", "ambience", "menu", "shop", "victory", "death",
        "gameover", "credits", "custom"]
CHIPS = ["nes", "gameboy", "sid", "fm", "gm"]
MODES = ["authentic", "enhanced"]
GENERATORS = ["riff", "arp", "harmony", "pad", "drone", "root"]


class SongError(ValueError):
    """A validation error with file, line and the YAML path that caused it."""

    def __init__(self, msg: str, path: str = "", line: int | None = None, file: str | None = None,
                 hint: str | None = None):
        self.msg, self.path, self.line, self.file, self.hint = msg, path, line, file, hint
        super().__init__(self.format())

    def format(self) -> str:
        loc = f"{self.file or 'song'}" + (f":{self.line}" if self.line else "")
        s = f"{loc} {self.path}: {self.msg}" if self.path else f"{loc}: {self.msg}"
        if self.hint:
            s += f"\n  hint: {self.hint}"
        return s


# ------------------------------------------------------------------ YAML with line numbers
def load_yaml_with_lines(text: str) -> tuple[Any, dict[tuple, int]]:
    """Parse YAML, returning (data, {path_tuple: line_number})."""
    lines: dict[tuple, int] = {}
    try:
        node = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        raise SongError(f"YAML syntax error: {getattr(e, 'problem', e)}",
                        line=(mark.line + 1) if mark else None,
                        hint="check indentation and quote strings that contain ':' or '#'") from None
    if node is None:
        raise SongError("file is empty")

    def build(n, path):
        lines[path] = n.start_mark.line + 1
        if isinstance(n, yaml.MappingNode):
            merged, out = {}, {}
            for k, v in n.value:
                key = k.value if isinstance(k, yaml.ScalarNode) else str(k.value)
                if key == "<<":                       # YAML merge key: explicit keys override merged ones
                    for s in (v.value if isinstance(v, yaml.SequenceNode) else [v]):
                        merged.update(build(s, path))
                    continue
                if key in out:
                    raise SongError(f"duplicate key {key!r}", ".".join(map(str, path)), v.start_mark.line + 1)
                out[key] = build(v, path + (key,))
            return {**merged, **out}
        if isinstance(n, yaml.SequenceNode):
            return [build(v, path + (i,)) for i, v in enumerate(n.value)]
        loader = yaml.SafeLoader("")
        return loader.construct_object(n, deep=True)

    return build(node, ()), lines


# ------------------------------------------------------------------ spec
@dataclass
class F:
    """A field spec. type: 'int' 'num' 'str' 'bool' 'list' 'map' or a tuple of those."""
    type: str | tuple
    doc: str
    default: Any = None
    required: bool = False
    choices: list | None = None
    min: float | None = None
    max: float | None = None
    example: str | None = None


SONG_SPEC: dict[str, F] = {
    "chipforge": F("int", "Format version. Must be 1.", required=True, choices=[FORMAT_VERSION]),
    "title": F("str", "Track title.", required=True, example="Furnace Heart"),
    "cue": F("str", "Cue type; sets loudness and length defaults (see CUE_GUIDE.md).",
             required=True, choices=CUES),
    "tempo": F("num", "Beats per minute.", required=True, min=20, max=400),
    "time": F("str", "Time signature.", default="4/4", example="4/4"),
    "key": F("str", "Key: note + m for minor, or a scale name (used by harmony generator and analysis).",
             default="C", example="Em, Bb, E phrygian"),
    "chip": F("str", "Chip profile.", default="nes", choices=CHIPS),
    "mode": F("str", "authentic = hardware-faithful mono; enhanced = stereo, reverb, extra voices.",
              default="enhanced", choices=MODES),
    "seed": F("int", "Random seed for noise, ambience and reverb; same seed = identical render.", default=0),
    "loudness": F("num", "Target integrated loudness in LUFS. Default comes from the cue type.", min=-40, max=0),
    "loop": F(("bool", "map"), "true = whole arrangement loops; false = one-shot with natural tail; "
              "{from: SECTION} = sections before SECTION are a non-looping intro.", default=True,
              example="{from: A}"),
    "swing": F("num", "Swing amount for off-beat 16ths, 0-0.5.", default=0.0, min=0, max=0.5),
    "sr": F("int", "Sample rate.", default=44100, choices=[22050, 44100, 48000]),
    "ambience": F("map", "Environment bed rendered as a separate stem: {bed: factory, level: -19}."),
    "mix": F("map", "Mix/master overrides: {drive, low_drive, hp, echo: {time, taps}, reverb: {size, decay, tone, predelay}}."),
    "channels": F("map", "Named channels: name -> {preset, vol, pan, layer, ...}.", required=True),
    "patterns": F("map", "Named patterns: name -> {bars, chords, <channel>: MML | generator | lanes}.",
                  required=True),
    "arrangement": F("list", "Ordered pattern uses: names or {use, transpose, vol, layers, mute, as}.",
                     required=True),
}

CHANNEL_SPEC: dict[str, F] = {
    "preset": F("str", "Instrument preset name (see PRESETS.md).", required=True, example="lead.pulse25"),
    "vol": F("num", "Channel gain multiplier.", default=1.0, min=0, max=4),
    "pan": F("num", "Stereo position -1 (left) .. 1 (right). Ignored in authentic mode.", default=0.0, min=-1, max=1),
    "layer": F("int", "Adaptive-intensity layer; 1 always plays, higher layers are separate stems.", default=1, min=1, max=8),
    "echo": F("num", "Echo send 0-2 (overrides preset).", min=0, max=2),
    "reverb": F("num", "Reverb wet level relative to dry, 0-2 (overrides preset).", min=0, max=2),
    "duck": F("num", "Kick sidechain depth 0-1 (overrides preset).", min=0, max=1),
    "lp": F("num", "Low-pass cutoff in Hz (overrides preset).", min=20, max=20000),
    "hp": F("num", "High-pass cutoff in Hz (overrides preset).", min=10, max=20000),
    "transpose": F("int", "Semitone transpose for the whole channel.", default=0, min=-48, max=48),
    "octave": F("int", "Default MML octave for this channel.", min=0, max=8),
    "gm": F("int", "General MIDI program for MIDI export (overrides preset).", min=0, max=127),
    "osc": F("str", "Oscillator quality: naive (aliasing, hardware-like) or clean (band-limited). Default from chip/mode.",
             choices=["naive", "clean"]),
}

PATTERN_SPEC: dict[str, F] = {
    "bars": F("int", "Length in bars.", required=True, min=1, max=256),
    "chords": F("str", "Chord per bar separated by '|'; several chords in one bar split it evenly.",
                example="Em | C | Am B7"),
    "step": F("int", "Grid resolution for drum lanes and generators (16 = sixteenth notes).", default=16,
              choices=[4, 8, 12, 16, 24, 32]),
    "exits": F("list", "Bars (1-based, bar *ends*) where an adaptive transition may jump out.", example="[4, 8]"),
    "octave": F("int", "Default MML octave for this pattern.", min=0, max=8),
}

GEN_SPEC: dict[str, dict[str, F]] = {
    "riff": {
        "steps": F("str", "Semitone offsets from the chord root per step, '.' = rest, 'o:len' = held note.",
                   required=True, example="0 0 12 0 0 12 0 0 | 0:3 0:3 12:2 0:3 1:3 0:2"),
        "octave": F("int", "Root octave.", default=2, min=0, max=7),
        "low": F("str", "Instead of octave: keep roots in the octave starting at this note, e.g. e2.", example="e2"),
        "gate": F("num", "Note length as a fraction of its step(s).", default=0.85, min=0.05, max=1),
        "follow": F("str", "root (default) or bass (use the slash-chord bass note).", default="root", choices=["root", "bass"]),
        "duty": F("num", "Pulse width override for pulse voices.", min=0.05, max=0.95),
    },
    "arp": {
        "tones": F("list", "Chord-tone indexes to cycle (3 = root an octave up on a triad).", default=[0, 1, 2, 3]),
        "rate": F("int", "Frames (1/60 s) per arpeggio step; 1 = classic fast arp.", default=1, min=1, max=16),
        "every": F("int", "Retrigger a new arp note every N grid steps.", default=2, min=1, max=64),
        "octave": F("int", "Base octave.", default=4, min=0, max=7),
        "low": F("str", "Instead of octave: keep chord roots in the octave starting at this note, e.g. e4.", example="e4"),
        "gate": F("num", "Note length fraction.", default=0.9, min=0.05, max=1),
        "duty": F("num", "Pulse width override for pulse voices.", min=0.05, max=0.95),
    },
    "harmony": {
        "of": F("str", "Channel whose notes to harmonize.", required=True, example="lead"),
        "interval": F("int", "Scale steps to move; -2 = a diatonic third below.", default=-2, min=-14, max=14),
        "scale": F("str", "Scale to harmonize in (default: song key).", choices=list(SCALES)),
        "vel": F("num", "Velocity multiplier.", default=0.8, min=0, max=2),
    },
    "pad": {
        "voicing": F("list", "Chord-tone indexes to hold.", default=[0, 1, 2]),
        "octave": F("int", "Base octave.", default=4, min=0, max=7),
        "low": F("str", "Instead of octave: keep chord roots in the octave starting at this note.", example="c4"),
        "gate": F("num", "Note length fraction of each chord span.", default=0.98, min=0.05, max=1),
        "duty": F("num", "Pulse width override for pulse voices.", min=0.05, max=0.95),
    },
    "drone": {
        "octave": F("int", "Root octave.", default=2, min=0, max=7),
        "low": F("str", "Instead of octave: keep roots in the octave starting at this note.", example="e2"),
        "fifth": F("bool", "Add the fifth above.", default=False),
        "merge": F("bool", "Merge consecutive identical chords into one long note.", default=True),
    },
    "root": {
        "octave": F("int", "Root octave.", default=1, min=0, max=7),
        "low": F("str", "Instead of octave: keep roots in the octave starting at this note.", example="e1"),
        "retrig": F("list", "Grid steps within each bar where the note restarts.", default=[0]),
        "gate": F("num", "Note length fraction.", default=0.97, min=0.05, max=1),
        "follow": F("str", "root or bass.", default="root", choices=["root", "bass"]),
    },
}

EVENT_SPEC: dict[str, F] = {
    "at": F(("str", "num"), "Position: 'bar:step' (1-based) or a 0-based step number.", required=True, example="'3:9'"),
    "hit": F("str", "Kit piece to trigger (a lane letter or a named hit like groan).", example="crash"),
    "roll": F("str", "Lane letter to roll (repeated hits with a velocity ramp).", example="s"),
    "len": F("num", "Roll length in grid steps, or hit duration in steps for sustained hits.", min=0),
    "every": F("int", "Roll: steps between hits.", default=1, min=1),
    "ramp": F("list", "Roll velocity [start, end].", default=[0.3, 1.0]),
    "vel": F("num", "Velocity 0-1.", default=1.0, min=0, max=2),
    "note": F("num", "Pitch (MIDI) for pitched hits.", min=0, max=127),
    "from": F("num", "Start pitch (MIDI) for sweeps such as groan or siren.", min=0, max=127),
    "to": F("num", "End pitch (MIDI) for sweeps.", min=0, max=127),
    "dur": F("num", "Duration in seconds for sweeps/hits with a free length.", min=0),
    "up": F("bool", "Sweep direction for hiss-type hits.", default=False),
}

MIX_SPEC: dict[str, F] = {
    "drive": F("num", "Master soft-clip drive (1 = gentle, 2 = crunchy).", default=1.2, min=0.5, max=4),
    "low_drive": F("num", "Low bus tanh glue drive; adds harmonics so bass reads on small speakers.", default=1.5, min=0, max=4),
    "hp": F("num", "Master high-pass Hz.", default=24, min=10, max=120),
    "echo": F("map", "Echo: {time: steps between taps (default 3 = dotted eighth), taps: [gains...]}."),
    "reverb": F("map", "Reverb: {size: seconds, decay: seconds, tone: low-pass Hz, predelay: seconds}."),
    "sidechain": F("num", "Kick sidechain release in seconds.", default=0.07, min=0.01, max=1),
    "hf": F("num", "Master high-shelf gain above 2.5 kHz (0.95 = highs 5% quieter).", default=0.95, min=0.5, max=1.5),
    "hf_freq": F("num", "High-shelf corner frequency in Hz.", default=2500, min=500, max=12000),
    "ceiling": F("num", "True-peak ceiling in dBTP for the limiter.", default=-1.0, min=-12, max=0),
    "normalize": F("bool", "Normalize to the loudness target (false = only the soft clip and ceiling).", default=True),
}

# default integrated loudness per cue type (LUFS). Quiet enough to leave room for game SFX.
CUE_LOUDNESS = {"boss": -12, "combat": -12, "overworld": -14, "dungeon": -16, "ambience": -20, "menu": -16,
                "shop": -15, "victory": -12, "death": -14, "gameover": -15, "credits": -14, "custom": -14}

ARR_SPEC: dict[str, F] = {
    "use": F("str", "Pattern name.", required=True),
    "as": F("str", "Section label for markers and loop points (default: pattern name)."),
    "transpose": F("int", "Semitones.", default=0, min=-24, max=24),
    "vol": F("num", "Gain multiplier for this use.", default=1.0, min=0, max=4),
    "layers": F("list", "Only these intensity layers play (default: all)."),
    "mute": F("list", "Channels muted in this use."),
    "solo": F("list", "Only these channels play in this use."),
    "channels": F("map", "Per-channel overrides: {lead: {vol: 0.5, transpose: 12}}."),
}


# ------------------------------------------------------------------ typed song
@dataclass
class Channel:
    name: str
    preset: str
    vol: float = 1.0
    pan: float = 0.0
    layer: int = 1
    transpose: int = 0
    octave: int | None = None
    overrides: dict = field(default_factory=dict)   # echo reverb duck lp hp gm


@dataclass
class Pattern:
    name: str
    bars: int
    chords: list[tuple[float, float, Chord]]   # (start_step, end_step, chord)
    step: int
    exits: list[int]
    octave: int | None
    lanes: dict[str, Any]        # channel -> str | gen dict | lanes dict | events list
    line: int = 0


@dataclass
class Use:
    pattern: str
    label: str
    transpose: int = 0
    vol: float = 1.0
    layers: list[int] | None = None
    mute: list[str] = field(default_factory=list)
    solo: list[str] | None = None
    channels: dict = field(default_factory=dict)


@dataclass
class Song:
    title: str
    cue: str
    tempo: float
    beats: int
    beat_unit: int
    key_root: int
    key_mode: str
    chip: str
    mode: str
    seed: int
    loudness: float | None
    loop: bool
    loop_from: str | None
    swing: float
    sr: int
    ambience: dict | None
    mix: dict
    channels: dict[str, Channel]
    patterns: dict[str, Pattern]
    arrangement: list[Use]
    source: str | None = None
    raw: dict = field(default_factory=dict)

    @property
    def target_lufs(self) -> float:
        return float(self.loudness if self.loudness is not None else CUE_LOUDNESS[self.cue])

    @property
    def steps_per_bar(self) -> int:
        return int(self.beats * 16 / self.beat_unit)

    @property
    def step_s(self) -> float:
        return 60.0 / self.tempo / 4


# ------------------------------------------------------------------ validation
class _V:
    def __init__(self, lines: dict, file: str | None):
        self.lines, self.file = lines, file

    def err(self, path: tuple, msg: str, hint: str | None = None):
        line = self.lines.get(path) or self.lines.get(path[:-1]) or self.lines.get(path[:1])
        raise SongError(msg, ".".join(map(str, path)), line, self.file, hint)

    def check_map(self, data: Any, spec: dict[str, F], path: tuple, *, extra_ok=False, what="field") -> dict:
        if not isinstance(data, dict):
            self.err(path, f"expected a mapping with keys {', '.join(spec)}, got {type(data).__name__}")
        out = {}
        for key, f in spec.items():
            if key in data:
                out[key] = self.check_field(data[key], f, path + (key,))
            elif f.required:
                self.err(path, f"missing required {what} '{key}' ({f.doc.rstrip('.')})",
                         hint=f"add `{key}: {f.example}`" if f.example else None)
            elif f.default is not None:
                out[key] = f.default
        if not extra_ok:
            for key in data:
                if key not in spec:
                    self.err(path + (key,), f"unknown {what} '{key}'",
                             hint=f"valid: {', '.join(spec)}" + (f"; did you mean '{_near(key, spec)}'?" if _near(key, spec) else ""))
        return out

    def check_field(self, v: Any, f: F, path: tuple):
        types = f.type if isinstance(f.type, tuple) else (f.type,)
        ok = False
        for t in types:
            if t == "int" and isinstance(v, int) and not isinstance(v, bool):
                ok = True
            elif t == "num" and isinstance(v, (int, float)) and not isinstance(v, bool):
                ok = True
            elif t == "str" and isinstance(v, str):
                ok = True
            elif t == "bool" and isinstance(v, bool):
                ok = True
            elif t == "list" and isinstance(v, list):
                ok = True
            elif t == "map" and isinstance(v, dict):
                ok = True
        if not ok:
            self.err(path, f"expected {' or '.join(types)}, got {type(v).__name__} ({v!r})",
                     hint=f"example: {f.example}" if f.example else None)
        if f.choices is not None and v not in f.choices:
            self.err(path, f"{v!r} is not one of: {', '.join(map(str, f.choices))}")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if f.min is not None and v < f.min:
                self.err(path, f"{v} is below the minimum {f.min}")
            if f.max is not None and v > f.max:
                self.err(path, f"{v} is above the maximum {f.max}")
        return v


def _near(key: str, options) -> str | None:
    import difflib
    m = difflib.get_close_matches(str(key), [str(o) for o in options], n=1, cutoff=0.6)
    return m[0] if m else None


def parse_chords(text: str, bars: int, steps_per_bar: int) -> list[tuple[float, float, Chord]]:
    out = []
    bar_texts = [b.strip() for b in text.split("|")]
    if bar_texts and bar_texts[-1] == "":
        bar_texts.pop()
    if not bar_texts:
        raise ValueError("no chords")
    if bars % len(bar_texts) != 0:
        raise ValueError(f"{len(bar_texts)} chord bars do not divide {bars} pattern bars")
    reps = bars // len(bar_texts)
    for rep in range(reps):
        for bi, bt in enumerate(bar_texts):
            names = bt.split()
            if not names:
                raise ValueError(f"empty chord bar {bi + 1}")
            span = steps_per_bar / len(names)
            start = (rep * len(bar_texts) + bi) * steps_per_bar
            for ci, name in enumerate(names):
                out.append((start + ci * span, start + (ci + 1) * span, Chord(name)))
    return out


def validate(data: Any, lines: dict | None = None, file: str | None = None) -> Song:
    """Validate raw YAML data and build a Song. Raises SongError with a precise location."""
    lines = lines or {}
    v = _V(lines, file)
    top = v.check_map(data, SONG_SPEC, (), what="key")
    if top["chipforge"] != FORMAT_VERSION:
        v.err(("chipforge",), f"unsupported format version {top['chipforge']}; this engine reads {FORMAT_VERSION}")
    m = re.match(r"^(\d+)/(\d+)$", str(top["time"]))
    if not m or int(m.group(2)) not in (2, 4, 8, 16):
        v.err(("time",), f"bad time signature {top['time']!r}", hint="use e.g. 4/4, 3/4, 6/8")
    beats, unit = int(m.group(1)), int(m.group(2))
    try:
        key_root, key_mode = parse_key(str(top["key"]))
    except ValueError as e:
        v.err(("key",), str(e))

    # channels
    channels: dict[str, Channel] = {}
    if not top["channels"]:
        v.err(("channels",), "at least one channel is required")
    for name, cdata in top["channels"].items():
        if not re.match(r"^[a-z][a-z0-9_]*$", str(name)):
            v.err(("channels", name), f"channel name {name!r} must be lowercase letters/digits/_")
        if name in PATTERN_SPEC or name == "events":
            v.err(("channels", name), f"'{name}' is a reserved word and cannot be a channel name")
        c = v.check_map(cdata, CHANNEL_SPEC, ("channels", name))
        if not _presets.exists(c["preset"]):
            near = _near(c["preset"], _presets.names())
            v.err(("channels", name, "preset"), f"unknown preset {c['preset']!r}",
                  hint=(f"did you mean '{near}'? " if near else "") + "run `chipforge presets` for the list")
        channels[name] = Channel(name, c["preset"], c["vol"], c["pan"], c["layer"], c["transpose"],
                                 c.get("octave"), {k: c[k] for k in ("echo", "reverb", "duck", "lp", "hp", "gm", "osc") if k in c})

    # patterns
    steps_per_bar = int(beats * 16 / unit)
    patterns: dict[str, Pattern] = {}
    if not top["patterns"]:
        v.err(("patterns",), "at least one pattern is required")
    for pname, pdata in top["patterns"].items():
        ppath = ("patterns", pname)
        if not isinstance(pdata, dict):
            v.err(ppath, "a pattern must be a mapping with `bars:` and one entry per channel")
        p = v.check_map(pdata, PATTERN_SPEC, ppath, extra_ok=True)
        chords: list = []
        if "chords" in p:
            try:
                chords = parse_chords(p["chords"], p["bars"], steps_per_bar)
            except ValueError as e:
                v.err(ppath + ("chords",), str(e))
        for ex in p.get("exits", []):
            if not isinstance(ex, int) or not 1 <= ex <= p["bars"]:
                v.err(ppath + ("exits",), f"exit {ex!r} must be a bar number 1-{p['bars']}")
        lanes: dict[str, Any] = {}
        for key, val in pdata.items():
            if key in PATTERN_SPEC:
                continue
            if key not in channels:
                near = _near(key, list(channels) + list(PATTERN_SPEC))
                v.err(ppath + (key,), f"'{key}' is not a channel or pattern field",
                      hint=f"did you mean '{near}'?" if near else f"channels: {', '.join(channels)}")
            kind = _presets.kind(channels[key].preset)
            lp = ppath + (key,)
            if kind == "kit":
                if isinstance(val, list):
                    val = {"events": val}
                if not isinstance(val, dict):
                    v.err(lp, f"channel '{key}' uses a kit preset, so it needs drum lanes "
                              f"({{k: 'x...x...', s: '....x...'}}) or an events list")
                pieces = _presets.pieces(channels[key].preset)
                for lane, s in val.items():
                    if lane == "events":
                        for i, ev in enumerate(s):
                            e = v.check_map(ev, EVENT_SPEC, lp + ("events", i))
                            if ("hit" in e) == ("roll" in e):
                                v.err(lp + ("events", i), "an event needs exactly one of `hit:` or `roll:`")
                            piece = e.get("hit") or e.get("roll")
                            if piece not in pieces:
                                v.err(lp + ("events", i), f"kit {channels[key].preset!r} has no piece {piece!r}",
                                      hint=f"pieces: {', '.join(pieces)}")
                            _check_at(v, e["at"], p["bars"], steps_per_bar, lp + ("events", i, "at"))
                        continue
                    if lane not in pieces:
                        v.err(lp + (lane,), f"kit {channels[key].preset!r} has no lane {lane!r}",
                              hint=f"lanes: {', '.join(k for k in pieces if len(k) == 1)}")
                    if not isinstance(s, str):
                        v.err(lp + (lane,), "a drum lane must be a string like 'x...x...'")
                    from .mml import parse_lane, lane_length
                    try:
                        parse_lane(s)
                    except ValueError as e:
                        v.err(lp + (lane,), str(e))
                    total = p["bars"] * steps_per_bar * p["step"] // 16
                    n = lane_length(s)
                    if n == 0 or total % n != 0:
                        v.err(lp + (lane,), f"lane has {n} steps; the pattern has {total} "
                                            f"(lanes must fit evenly so they can repeat)")
            else:
                if isinstance(val, str):
                    from .mml import parse_mml, mml_length, MMLError
                    try:
                        notes = parse_mml(val)
                    except MMLError as e:
                        v.err(lp, f"MML error: {e}")
                    ln = mml_length(notes)
                    total = p["bars"] * steps_per_bar
                    if ln > total + 1e-6:
                        v.err(lp, f"MML is {ln:g} steps long but the pattern is {total} "
                                  f"({p['bars']} bars x {steps_per_bar}); shorten it or raise `bars`")
                    if ln > 0 and abs(total / ln - round(total / ln)) > 1e-6:
                        v.err(lp, f"MML is {ln:g} steps; it must fill the pattern ({total}) or divide it evenly to repeat")
                elif isinstance(val, dict) and "gen" in val:
                    g = val["gen"]
                    if g not in GEN_SPEC:
                        v.err(lp + ("gen",), f"unknown generator {g!r}", hint=f"valid: {', '.join(GEN_SPEC)}")
                    gd = v.check_map({k: x for k, x in val.items() if k != "gen"}, GEN_SPEC[g], lp)
                    if g in ("riff", "arp", "pad", "drone", "root") and not chords:
                        v.err(lp, f"generator '{g}' needs `chords:` in pattern '{pname}'")
                    if g == "harmony":
                        if gd["of"] not in channels:
                            v.err(lp + ("of",), f"unknown channel {gd['of']!r}")
                        if gd["of"] == key:
                            v.err(lp + ("of",), "a channel cannot harmonize itself")
                    if g == "riff":
                        try:
                            riff = _parse_riff(gd["steps"])
                        except ValueError as e:
                            v.err(lp + ("steps",), str(e))
                        rlen = sum(ln for _, ln in riff) * 16 / p["step"]
                        total = p["bars"] * steps_per_bar
                        if rlen > total + 1e-6 or (rlen > 0 and abs(total / rlen - round(total / rlen)) > 1e-6):
                            v.err(lp + ("steps",), f"riff is {rlen:g} steps but the pattern has {total} "
                                                   f"({p['bars']} bars x {steps_per_bar}); each token is one grid step, "
                                                   f"'n:len' holds n for len steps - make it fill the pattern or divide it evenly")
                    if gd.get("low") is not None:
                        from .theory import note_to_midi
                        try:
                            note_to_midi(str(gd["low"]))
                        except ValueError as e:
                            v.err(lp + ("low",), str(e))
                    val = {"gen": g, **gd}
                else:
                    v.err(lp, f"channel '{key}' needs an MML string or a generator mapping ({{gen: arp, ...}})",
                          hint=f"generators: {', '.join(GEN_SPEC)}")
            lanes[key] = val
        patterns[pname] = Pattern(pname, p["bars"], chords, p["step"], p.get("exits", []), p.get("octave"),
                                  lanes, lines.get(ppath, 0))

    # arrangement
    arrangement: list[Use] = []
    if not top["arrangement"]:
        v.err(("arrangement",), "arrangement must list at least one pattern")
    for i, item in enumerate(top["arrangement"]):
        ap = ("arrangement", i)
        if isinstance(item, str):
            item = {"use": item}
        a = v.check_map(item, ARR_SPEC, ap)
        if a["use"] not in patterns:
            near = _near(a["use"], patterns)
            v.err(ap, f"unknown pattern {a['use']!r}", hint=f"did you mean '{near}'?" if near else f"patterns: {', '.join(patterns)}")
        for ch in a.get("mute", []) + (a.get("solo") or []) + list(a.get("channels", {})):
            if ch not in channels:
                v.err(ap, f"unknown channel {ch!r}")
        for ch, ov in a.get("channels", {}).items():
            v.check_map(ov, {k: CHANNEL_SPEC[k] for k in ("vol", "pan", "transpose")}, ap + ("channels", ch))
        arrangement.append(Use(a["use"], a.get("as", a["use"]), a["transpose"], a["vol"], a.get("layers"),
                               a.get("mute", []), a.get("solo"), a.get("channels", {})))

    loop, loop_from = top["loop"], None
    if isinstance(loop, dict):
        lf = v.check_map(loop, {"from": F("str", "Section label where the loop starts.", required=True)}, ("loop",))
        loop_from = lf["from"]
        labels = [u.label for u in arrangement]
        if loop_from not in labels:
            v.err(("loop", "from"), f"{loop_from!r} is not a section label in the arrangement",
                  hint=f"labels: {', '.join(labels)}")
        if labels.index(loop_from) == 0:
            loop_from = None
        loop = True
    amb = top.get("ambience")
    if amb is not None:
        amb = v.check_map(amb, {
            "bed": F("str", "Ambience bed name.", required=True, choices=["factory", "cave", "forest", "rain",
                                                                           "wind", "machinery", "water", "crowd", "none"]),
            "level": F("num", "Level relative to the music in dB.", default=-19.0, min=-60, max=0),
            "seed": F("int", "Seed override for the ambience.", min=0),
        }, ("ambience",))

    mix = v.check_map(top.get("mix") or {}, MIX_SPEC, ("mix",))
    mix["echo"] = v.check_map(mix.get("echo") or {}, {
        "time": F("num", "Steps (16ths) between echo taps.", default=3, min=0.25, max=64),
        "taps": F("list", "Tap gains, alternating left/right.", default=[0.30, 0.20, 0.10, 0.06]),
    }, ("mix", "echo"))
    mix["reverb"] = v.check_map(mix.get("reverb") or {}, {
        "size": F("num", "Impulse length in seconds.", default=2.6, min=0.1, max=10),
        "decay": F("num", "Decay time constant in seconds.", default=0.55, min=0.05, max=10),
        "tone": F("num", "Low-pass Hz on the reverb.", default=3500, min=200, max=20000),
        "predelay": F("num", "Seconds before the reverb starts.", default=0.012, min=0, max=0.2),
    }, ("mix", "reverb"))

    song = Song(top["title"], top["cue"], float(top["tempo"]), beats, unit, key_root, key_mode, top["chip"],
                top["mode"], int(top["seed"]), top.get("loudness"), bool(loop), loop_from, float(top["swing"]),
                int(top["sr"]), amb, mix, channels, patterns, arrangement, file, data)
    if song.mode == "authentic":
        check_authentic(song, v)
    return song


def check_authentic(song: Song, v: "_V"):
    """Authentic mode: every channel must fit a hardware slot of the chip, and no polyphony."""
    from . import chips
    prof = chips.get(song.chip)
    used: dict[str, list[str]] = {}
    for name, ch in song.channels.items():
        preset = _presets.get(ch.preset)
        if preset["kind"] == "kit":
            voices = ["noise"]
        elif preset.get("voice") == "stack":
            voices = [l["voice"] for l in preset["layers"]]
        else:
            voices = [preset["voice"]]
        for voice in voices:
            slot = chips.SLOT.get(voice)
            target = None
            for s_name in prof.voices:
                if s_name == slot or slot in chips.ACCEPTS.get(s_name, set()):
                    target = s_name
                    break
            if slot is None or target is None:
                v.err(("channels", name, "preset"),
                      f"preset {ch.preset!r} uses a {voice} voice, which the {song.chip} has no channel for in authentic mode",
                      hint="pick a preset built from " + ", ".join(prof.voices) + " voices, or set `mode: enhanced`")
            used.setdefault(target, []).append(name)
    for slot, names in used.items():
        if len(names) > prof.voices[slot]:
            v.err(("channels",), f"authentic {song.chip} has {prof.voices[slot]} {slot} channel(s) but "
                                 f"{len(names)} are used: {', '.join(names)}",
                  hint="remove or merge channels, or set `mode: enhanced`")
    for pname, pat in song.patterns.items():
        for ch, lane in pat.lanes.items():
            if isinstance(lane, dict) and lane.get("gen") == "pad":
                v.err(("patterns", pname, ch), "the pad generator is polyphonic; authentic chips play one note per channel",
                      hint="use arp or drone, or set `mode: enhanced`")


def _check_at(v: _V, at, bars: int, steps_per_bar: int, path: tuple):
    try:
        parse_at(at, steps_per_bar)
    except ValueError as e:
        v.err(path, str(e))


def parse_at(at, steps_per_bar: int) -> float:
    """'3:9' (1-based bar:step) or a 0-based step number -> step offset."""
    if isinstance(at, (int, float)) and not isinstance(at, bool):
        if at < 0:
            raise ValueError("`at` step must be >= 0")
        return float(at)
    m = re.match(r"^\s*(\d+)\s*:\s*(\d+(?:\.\d+)?)\s*$", str(at))
    if not m:
        raise ValueError(f"bad position {at!r}; use 'bar:step' (1-based, e.g. '2:9') or a 0-based step number")
    bar, step = int(m.group(1)), float(m.group(2))
    if bar < 1 or step < 1:
        raise ValueError("bar and step in 'bar:step' are 1-based")
    return (bar - 1) * steps_per_bar + (step - 1)


def _parse_riff(text: str) -> list[tuple[int | None, float]]:
    """'0 0 12 . 1:3' -> [(offset, length_steps)], None offset = rest."""
    out = []
    for tok in text.replace("|", " ").split():
        if ":" in tok:
            a, b = tok.split(":", 1)
            ln = float(b)
        else:
            a, ln = tok, 1.0
        if a in (".", "r", "-"):
            out.append((None, ln))
        else:
            try:
                out.append((int(a), ln))
            except ValueError:
                raise ValueError(f"bad riff token {tok!r}; use semitone offsets like 0 12 -1, '.' for rest, "
                                 f"or offset:length like 0:3") from None
    if not out:
        raise ValueError("riff steps are empty")
    return out


def load(path: str | Path) -> Song:
    """Load and validate a song file."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise SongError(f"cannot read file: {e}", file=str(p)) from None
    return loads(text, file=str(p))


def loads(text: str, file: str | None = None) -> Song:
    data, lines = load_yaml_with_lines(text)
    if not isinstance(data, dict):
        raise SongError("top level must be a mapping (key: value lines)", file=file, line=1)
    return validate(data, lines, file)
