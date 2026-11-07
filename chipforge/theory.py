"""Keys, scales and chord symbols."""
from __future__ import annotations

import re

PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

SCALES = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "harmonic_minor": [0, 2, 3, 5, 7, 8, 11],
    "melodic_minor": [0, 2, 3, 5, 7, 9, 11],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "phrygian_dominant": [0, 1, 4, 5, 7, 8, 10],
    "neapolitan_minor": [0, 1, 3, 5, 7, 8, 11],
    "lydian": [0, 2, 4, 6, 7, 9, 11],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "locrian": [0, 1, 3, 5, 6, 8, 10],
    "pentatonic_major": [0, 2, 4, 7, 9],
    "pentatonic_minor": [0, 3, 5, 7, 10],
    "blues": [0, 3, 5, 6, 7, 10],
    "whole_tone": [0, 2, 4, 6, 8, 10],
    "chromatic": list(range(12)),
}

CHORD_QUALITIES = {
    "": [0, 4, 7], "M": [0, 4, 7], "maj": [0, 4, 7],
    "m": [0, 3, 7], "min": [0, 3, 7], "-": [0, 3, 7],
    "5": [0, 7], "dim": [0, 3, 6], "o": [0, 3, 6], "aug": [0, 4, 8], "+": [0, 4, 8],
    "sus2": [0, 2, 7], "sus4": [0, 5, 7], "sus": [0, 5, 7],
    "7": [0, 4, 7, 10], "m7": [0, 3, 7, 10], "maj7": [0, 4, 7, 11], "M7": [0, 4, 7, 11],
    "dim7": [0, 3, 6, 9], "m7b5": [0, 3, 6, 10], "6": [0, 4, 7, 9], "m6": [0, 3, 7, 9],
    "add9": [0, 4, 7, 14], "madd9": [0, 3, 7, 14], "9": [0, 4, 7, 10, 14], "m9": [0, 3, 7, 10, 14],
}

_CHORD_RE = re.compile(r"^([A-G])([#b]?)(.*?)(?:/([A-G][#b]?))?$")


def parse_pc(name: str) -> int:
    """'F#' -> 6."""
    m = re.match(r"^([A-G])([#b]?)$", name)
    if not m:
        raise ValueError(f"bad note name {name!r}")
    return (PC[m.group(1)] + {"#": 1, "b": -1, "": 0}[m.group(2)]) % 12


def parse_key(key: str) -> tuple[int, str]:
    """'Em' -> (4, 'minor'); 'Bb' -> (10, 'major'); 'E dorian' -> (4, 'dorian')."""
    key = key.strip()
    m = re.match(r"^([A-G][#b]?)\s*(.*)$", key)
    if not m:
        raise ValueError(f"bad key {key!r}; examples: C, Em, F#m, Bb, E phrygian")
    root = parse_pc(m.group(1))
    rest = m.group(2).strip().replace(" ", "_")
    if rest in ("", "maj", "major", "M"):
        return root, "major"
    if rest in ("m", "min", "minor"):
        return root, "minor"
    if rest in SCALES:
        return root, rest
    raise ValueError(f"unknown key mode {rest!r}; use m/major or a scale name: {', '.join(SCALES)}")


class Chord:
    __slots__ = ("root", "tones", "bass", "name")

    def __init__(self, name: str):
        m = _CHORD_RE.match(name.strip())
        if not m:
            raise ValueError(f"bad chord {name!r}; examples: Em, C, A7, F#m7, Bb/D, Gsus4")
        self.name = name.strip()
        self.root = parse_pc(m.group(1) + m.group(2))
        q = m.group(3)
        if q not in CHORD_QUALITIES:
            raise ValueError(f"unknown chord quality {q!r} in {name!r}; known: "
                             + ", ".join(sorted(k for k in CHORD_QUALITIES if k)))
        self.tones = list(CHORD_QUALITIES[q])          # semitone offsets from root
        self.bass = parse_pc(m.group(4)) if m.group(4) else self.root

    def transposed(self, semis: int) -> "Chord":
        c = Chord.__new__(Chord)
        c.name, c.tones = self.name, list(self.tones)
        c.root, c.bass = (self.root + semis) % 12, (self.bass + semis) % 12
        return c

    def tone(self, index: int, base_octave: int, low: int | None = None) -> int:
        """Chord tone by index, wrapping into higher octaves (index 3 of a triad = root+12)."""
        n = len(self.tones)
        oct_, i = divmod(index, n)
        return self.root_midi(base_octave, low) + self.tones[i] + 12 * oct_

    def root_midi(self, octave: int, low: int | None = None) -> int:
        """Root in `octave`, or (if `low` is given) in the octave starting at MIDI note `low`."""
        if low is not None:
            return nearest_in_octave(self.root, low)
        return 12 * (octave + 1) + self.root

    def bass_midi(self, octave: int, low: int | None = None) -> int:
        if low is not None:
            return nearest_in_octave(self.bass, low)
        return 12 * (octave + 1) + self.bass


def note_to_midi(name: str) -> int:
    """'e4' / 'F#2' / 'bb3' -> MIDI number."""
    m = re.match(r"^([A-Ga-g])([#b+\-]?)(-?\d)$", name.strip())
    if not m:
        raise ValueError(f"bad note name {name!r}; use e.g. e4, F#2, bb3")
    pc = PC[m.group(1).upper()] + {"#": 1, "+": 1, "b": -1, "-": -1, "": 0}[m.group(2)]
    return 12 * (int(m.group(3)) + 1) + pc


def nearest_in_octave(pc: int, low: int) -> int:
    """MIDI note with pitch class pc in [low, low+12)."""
    return low + (pc - low) % 12


def scale_step(midi: int, root_pc: int, scale: list[int], steps: int) -> int:
    """Move `steps` scale degrees from midi (negative = down). Non-scale notes move chromatically
    to the nearest scale note first."""
    rel = (midi - root_pc) % 12
    if rel not in scale:
        # snap down to nearest scale note
        below = max([s for s in scale if s < rel], default=scale[-1] - 12)
        midi -= rel - below
        rel = (midi - root_pc) % 12
    i = scale.index(rel)
    n = len(scale)
    oct_, j = divmod(i + steps, n)
    return midi - rel + scale[j] + 12 * oct_
