"""Turn a validated Song into a timeline of events (seconds), expanding patterns, chords,
generators and the arrangement."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import presets as _presets
from .mml import parse_lane, parse_mml, mml_length, lane_length
from .schema import Pattern, Song, Use, parse_at, _parse_riff
from .theory import Chord, SCALES, note_to_midi, scale_step


@dataclass
class Event:
    ch: str
    t: float                 # start, seconds
    dur: float               # gate length, seconds
    midi: float | None       # None for unpitched kit pieces
    vel: float = 1.0
    piece: str | None = None  # kit piece name
    params: dict = field(default_factory=dict)   # slide_from, duty, vib, arp, sweep, from, to, len, up, note
    section: int = 0


@dataclass
class Section:
    label: str
    pattern: str
    start: float      # seconds
    end: float
    exits: list[float]  # seconds
    layers: list[int] | None = None


@dataclass
class Timeline:
    song: Song
    events: list[Event]
    sections: list[Section]
    length: float            # seconds (end of arrangement)
    loop_start: float | None  # None = one-shot
    step_s: float

    @property
    def loop_length(self) -> float | None:
        return None if self.loop_start is None else self.length - self.loop_start

    def channel_events(self, ch: str) -> list[Event]:
        return [e for e in self.events if e.ch == ch]


def _chord_at(chords: list[tuple[float, float, Chord]], step: float) -> Chord | None:
    for s, e, c in chords:
        if s - 1e-9 <= step < e - 1e-9:
            return c
    return chords[-1][2] if chords else None


def _swing_offset(step: float, swing: float) -> float:
    """Delay odd 16ths by `swing` of a step."""
    if swing <= 0:
        return 0.0
    frac = step - int(step)
    return swing if (int(step) % 2 == 1 and frac < 1e-9) else 0.0


def build(song: Song) -> Timeline:
    spb = song.steps_per_bar
    step_s = song.step_s
    events: list[Event] = []
    sections: list[Section] = []
    cursor = 0.0  # steps
    last_midi: dict[str, float] = {}
    loop_start = None if not song.loop else 0.0

    for si, use in enumerate(song.arrangement):
        pat = song.patterns[use.pattern]
        total = pat.bars * spb
        chords = [(s, e, c.transposed(use.transpose)) for s, e, c in pat.chords]
        sec_start = cursor
        if song.loop_from is not None and use.label == song.loop_from and loop_start == 0.0:
            loop_start = cursor * step_s
        sections.append(Section(use.label, pat.name, cursor * step_s, (cursor + total) * step_s,
                                [(cursor + b * spb) * step_s for b in pat.exits], use.layers))

        def active(ch: str) -> bool:
            c = song.channels[ch]
            if ch in use.mute or (use.solo is not None and ch not in use.solo):
                return False
            if use.layers is not None and c.layer not in use.layers:
                return False
            return True

        def emit(ch: str, step: float, length: float, midi, vel: float, piece=None, params=None, gate=1.0):
            c = song.channels[ch]
            ov = use.channels.get(ch, {})
            t = (sec_start + step + _swing_offset(step, song.swing)) * step_s
            v = vel * use.vol * ov.get("vol", 1.0)
            if midi is not None:
                midi = midi + c.transpose + ov.get("transpose", 0)
            events.append(Event(ch, t, length * gate * step_s, midi, v, piece, dict(params or {}), si))
            return events[-1]

        # melodic + kit lanes first, harmony after (it reads other channels' notes in this use)
        lanes = sorted(pat.lanes.items(), key=lambda kv: isinstance(kv[1], dict) and kv[1].get("gen") == "harmony")
        for ch, lane in lanes:
            if not active(ch):
                continue
            kind = _presets.kind(song.channels[ch].preset)
            if kind == "kit":
                _emit_kit(song, pat, lane, total, emit, ch)
                continue
            if isinstance(lane, str):
                octave = pat.octave or song.channels[ch].octave or 4
                notes = parse_mml(lane, default_octave=octave)
                ln = mml_length(notes)
                reps = int(round(total / ln)) if ln > 0 else 0
                for r in range(reps):
                    for n in notes:
                        if n.midi is None:
                            continue
                        midi = n.midi + use.transpose
                        params = dict(n.macros)
                        if "arp" in params:          # @arp(0,4,7) -> absolute tones for this note
                            params["arp"] = [midi + int(o) for o in params["arp"]]
                        if n.slide and ch in last_midi:
                            params["slide_from"] = last_midi[ch]
                        emit(ch, r * ln + n.start, n.length, midi, n.vel, params=params, gate=n.gate)
                        last_midi[ch] = midi + song.channels[ch].transpose + use.channels.get(ch, {}).get("transpose", 0)
                continue
            gen = lane["gen"]
            g = {k: v for k, v in lane.items() if k != "gen"}
            if gen == "harmony":
                _gen_harmony(song, g, ch, events, si, emit, sec_start, step_s, use)
            else:
                _gen_chords(song, pat, gen, g, ch, chords, total, emit)
        cursor += total

    return Timeline(song, events, sections, cursor * step_s, loop_start, step_s)


# ------------------------------------------------------------------ kits
def _emit_kit(song: Song, pat: Pattern, lane: dict, total: float, emit, ch: str):
    spb = song.steps_per_bar
    grid = 16 / pat.step          # 16ths per grid step
    if isinstance(lane, list):
        lane = {"events": lane}
    for name, s in lane.items():
        if name == "events":
            for ev in s:
                _emit_event(song, pat, ev, emit, ch, grid)
            continue
        hits = parse_lane(s)
        n = lane_length(s)
        reps = int(round(total / (n * grid)))
        for r in range(reps):
            for h in hits:
                emit(ch, (r * n + h.start) * grid, grid, None, h.vel, piece=name)


def _emit_event(song: Song, pat: Pattern, ev: dict, emit, ch: str, grid: float):
    spb = song.steps_per_bar
    at = parse_at(ev["at"], spb)
    if isinstance(ev["at"], (int, float)):
        at *= grid
    vel = ev.get("vel", 1.0)
    if "roll" in ev:
        length = ev.get("len", spb - (at % spb))
        every = ev.get("every", 1)
        ramp = ev.get("ramp", [0.3, 1.0])
        steps = [at + k * every * grid for k in range(int(round(length / every)))]
        for i, s in enumerate(steps):
            v = ramp[0] + (ramp[1] - ramp[0]) * i / max(1, len(steps) - 1)
            emit(ch, s, grid, None, v * vel, piece=ev["roll"])
        return
    params = {k: ev[k] for k in ("from", "to", "dur", "up", "note", "len") if k in ev}
    length = ev.get("len", 1.0)
    emit(ch, at, length * grid, ev.get("note"), vel, piece=ev["hit"], params=params)


# ------------------------------------------------------------------ generators
def _gen_chords(song: Song, pat: Pattern, gen: str, g: dict, ch: str, chords, total: float, emit):
    spb = song.steps_per_bar
    grid = 16 / pat.step
    low = note_to_midi(str(g["low"])) if g.get("low") is not None else None
    extra = {"d": [g["duty"]]} if g.get("duty") is not None else {}
    if gen == "riff":
        riff = _parse_riff(g["steps"])
        rlen = sum(ln for _, ln in riff) * grid
        reps = int(round(total / rlen)) if rlen else 0
        if rlen and abs(total / rlen - reps) > 1e-6:
            # pad: play as far as it fits
            reps = int(total // rlen) + 1
        pos = 0.0
        for _ in range(reps):
            for off, ln in riff:
                if pos >= total - 1e-9:
                    break
                if off is not None:
                    c = _chord_at(chords, pos)
                    root = c.bass_midi(g["octave"], low) if g["follow"] == "bass" else c.root_midi(g["octave"], low)
                    emit(ch, pos, ln * grid, root + off, 1.0, params=extra, gate=g["gate"])
                pos += ln * grid
    elif gen == "arp":
        every = g["every"] * grid
        pos = 0.0
        while pos < total - 1e-9:
            c = _chord_at(chords, pos)
            tones = [c.tone(int(i), g["octave"], low) for i in g["tones"]]
            emit(ch, pos, every, tones[0], 1.0, params={"arp": tones, "arp_rate": g["rate"], **extra}, gate=g["gate"])
            pos += every
    elif gen == "root":
        bounds = sorted({float(b * spb + r * grid) for b in range(pat.bars) for r in g["retrig"]}
                        | {s for s, _, _ in chords} | {total})
        for a, b in zip(bounds[:-1], bounds[1:]):
            c = _chord_at(chords, a)
            m = c.bass_midi(g["octave"], low) if g["follow"] == "bass" else c.root_midi(g["octave"], low)
            emit(ch, a, b - a, m, 1.0, params=extra, gate=g["gate"])
    elif gen == "pad":
        for s, e, c in chords:
            for i in g["voicing"]:
                emit(ch, s, e - s, c.tone(int(i), g["octave"], low), 1.0, params=extra, gate=g["gate"])
    elif gen == "drone":
        runs: list[list] = []
        for s, e, c in chords:
            if runs and g["merge"] and runs[-1][2].root == c.root and runs[-1][2].tones == c.tones:
                runs[-1][1] = e
            else:
                runs.append([s, e, c])
        for s, e, c in runs:
            emit(ch, s, e - s, c.root_midi(g["octave"], low), 1.0, gate=1.0)
            if g["fifth"]:
                emit(ch, s, e - s, c.root_midi(g["octave"], low) + 7, 0.7, gate=1.0)


def _gen_harmony(song: Song, g: dict, ch: str, events: list[Event], si: int, emit, sec_start, step_s, use: Use):
    scale = SCALES[g["scale"]] if g.get("scale") else SCALES[song.key_mode]
    src = [e for e in events if e.ch == g["of"] and e.section == si and e.midi is not None]
    c_src, c_dst = song.channels[g["of"]], song.channels[ch]
    for e in src:
        tr = c_src.transpose + use.transpose + use.channels.get(g["of"], {}).get("transpose", 0)
        base = int(round(e.midi)) - tr                    # harmonize in the written key, then re-transpose
        h = scale_step(base, song.key_root, scale, g["interval"]) + use.transpose
        params = {k: v for k, v in e.params.items() if k != "slide_from"}
        if "slide_from" in e.params:
            params["slide_from"] = scale_step(int(round(e.params["slide_from"])) - tr,
                                              song.key_root, scale, g["interval"]) + use.transpose + c_dst.transpose
        step = e.t / step_s - sec_start
        src_scale = use.vol * use.channels.get(g["of"], {}).get("vol", 1.0)
        emit(ch, step, e.dur / step_s, h, e.vel * g["vel"] / src_scale, params=params, gate=1.0)
