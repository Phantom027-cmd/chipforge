"""Instrument preset library (data in presets.yml) and the voice parameter specs.

A preset is either `kind: melodic` (one voice, or a `stack` of voices) or `kind: kit`
(named pieces, each a voice, triggered by drum lanes / events).
"""
from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path

import yaml

_DIR = Path(__file__).parent

# Voice parameter specs: name -> {param: (default, doc)}. Used for validation and PRESETS.md.
VOICES: dict[str, dict[str, tuple]] = {
    "pulse": {
        "duty": (0.5, "Pulse width 0.125 / 0.25 / 0.5 / 0.75 (NES) or any 0.05-0.95"),
        "pluck": (None, "Duty used for the first 2 frames (attack flick), e.g. 0.125"),
        "att": (0.0, "Attack seconds"), "dec": (0.12, "Decay seconds to sustain"),
        "sus": (0.72, "Sustain level 0-1"), "rel": (0.07, "Release seconds after note end"),
        "vib": (0.0, "Vibrato depth in semitones (0 = off)"), "vib_rate": (5.8, "Vibrato Hz"),
        "vib_delay": (0.2, "Seconds before vibrato starts"), "vib_ramp": (0.25, "Seconds to reach full depth"),
        "vib_min": (0.25, "Vibrato only on notes longer than this (s)"),
        "slide": (0.06, "Portamento time in seconds for ~slides"),
        "detune": (0.0, "Second detuned oscillator mix 0-1 (enhanced only)"),
        "arp_rate": (1, "Frames per step for @arp macros"),
    },
    "tri": {
        "rel": (0.006, "Release fade seconds (NES triangle has no volume envelope)"),
        "steps": (32, "Wavetable steps (32 = NES, 0 = clean band-limited triangle)"),
        "vib": (0.0, "Vibrato depth in semitones"), "vib_rate": (5.5, "Vibrato Hz"),
        "vib_delay": (0.25, "Seconds before vibrato starts"), "slide": (0.06, "Portamento time (s)"),
    },
    "sine": {
        "att": (0.004, "Attack seconds"), "rel": (0.04, "Release seconds"),
        "harm2": (0.0, "Second-harmonic amount (helps small speakers)"),
    },
    "grit": {
        "duty": (0.25, "Pulse width"), "detune": (0.0, "Second pulse detune ratio, e.g. 0.004"),
        "bite": (0.0, "Attack pitch bite amount (0.03 = subtle)"), "dec": (0.08, "Decay seconds"),
        "sus": (0.45, "Sustain level"), "rel": (0.015, "Release seconds"),
    },
    "drone": {
        "detune": (0.0035, "Detune ratio between the two pulses"), "pwm_rate": (0.21, "PWM LFO Hz"),
        "pwm_depth": (0.18, "PWM LFO depth"), "fifth": (0.55, "Level of the fifth above (0 = off)"),
        "att": (0.35, "Attack seconds"), "rel": (0.5, "Release seconds"),
        "trem": (0.2, "Tremolo depth"), "trem_rate": (0.37, "Tremolo Hz"),
    },
    "noise": {
        "short": (False, "Use the 93-step metallic LFSR"), "rate": (22000, "Noise clock Hz (ignored if pitched)"),
        "pitched": (False, "Follow note pitch (rate = freq * 93/4)"), "dec": (0.1, "Decay seconds"),
        "sus": (0.0, "Sustain level"), "rel": (0.02, "Release seconds"),
    },
    "wave": {
        "table": ("saw", "Wavetable: saw, tri, sine, organ, pulse, bass, bell"),
        "att": (0.0, "Attack seconds"), "dec": (0.1, "Decay seconds"), "sus": (0.8, "Sustain level"),
        "rel": (0.05, "Release seconds"), "vib": (0.0, "Vibrato depth in semitones"),
        "vib_rate": (5.5, "Vibrato Hz"), "vib_delay": (0.2, "Seconds before vibrato"), "slide": (0.06, "Portamento (s)"),
    },
    # ----- kit / fx pieces
    "kick": {"f0": (210, "Start pitch Hz"), "f1": (42, "End pitch Hz"), "pitch_dec": (0.022, "Pitch decay s"),
             "dec": (0.20, "Amplitude decay s"), "click": (0.5, "Click level"), "click_f": (330, "Click pitch Hz"),
             "crush": (24, "Amplitude quantization levels (0 = off)"), "len": (0.38, "Length s")},
    "snare": {"rate": (22000, "Noise clock Hz"), "dec": (0.075, "Noise decay s"), "tone_f": (190, "Tone Hz"),
              "tone_dec": (0.03, "Tone decay s"), "tone": (0.6, "Tone level"), "crush": (2, "Sample-hold factor"),
              "len": (0.22, "Length s")},
    "hat": {"dec": (0.014, "Decay s"), "len": (0.045, "Length s"), "rate": (44100, "Noise clock Hz")},
    "clank": {"f1": (587, "Ring freq A Hz"), "f2": (871, "Ring freq B Hz"), "dec": (0.06, "Decay s"),
              "rate": (60000, "Metal noise clock Hz"), "len": (0.22, "Length s"), "crush": (2, "Sample-hold factor")},
    "crash": {"rate": (32000, "Noise clock Hz"), "dec": (0.55, "Decay s"), "len": (1.8, "Length s")},
    "hiss": {"f_lo": (3000, "Low noise clock Hz"), "f_hi": (26000, "High noise clock Hz"),
             "len": (0.6, "Default length s"), "up": (False, "Sweep upward")},
    "groan": {"len": (1.4, "Default length s"), "from": (52, "Default start MIDI"), "to": (40, "Default end MIDI"),
              "wobble": (0.6, "Wobble depth semitones"), "wobble_rate": (7, "Wobble Hz"), "noise": (0.3, "Metallic noise mix"),
              "curve": (0.7, "Sweep curve exponent"), "att": (0.06, "Attack s")},
    "siren": {"len": (1.0, "Default length s"), "from": (64, "Start MIDI"), "to": (65, "End MIDI"),
              "duty": (0.5, "Pulse width"), "slide": (0.25, "Slide time s"), "sus": (0.8, "Sustain level")},
    "eerie": {"len": (4.0, "Default length s"), "notes": ([76, 77], "MIDI notes (cluster)"),
              "wobble": (0.12, "Pitch wobble semitones"), "wobble_rate": (4.3, "Wobble Hz"), "duty": (0.125, "Pulse width")},
}

MIX_DEFAULTS = {"vol": 1.0, "pan": 0.0, "bus": "main", "lp": None, "hp": None,
                "echo": 0.0, "reverb": 0.0, "duck": 0.0, "width": 0.0}


class PresetError(ValueError):
    pass


@lru_cache(maxsize=1)
def _library() -> dict[str, dict]:
    raw = yaml.safe_load((_DIR / "presets.yml").read_text(encoding="utf-8"))
    lib: dict[str, dict] = {}

    def resolve(name: str, seen=()) -> dict:
        if name in lib:
            return lib[name]
        if name not in raw:
            raise PresetError(f"preset {name!r} not found")
        if name in seen:
            raise PresetError(f"preset extends loop at {name!r}")
        p = copy.deepcopy(raw[name])
        base = p.pop("extends", None)
        if base:
            b = copy.deepcopy(resolve(base, seen + (name,)))
            for k, val in p.items():
                if isinstance(val, dict) and isinstance(b.get(k), dict):
                    b[k].update(val)
                else:
                    b[k] = val
            p = b
        p.setdefault("kind", "kit" if "pieces" in p else "melodic")
        p.setdefault("mix", {})
        lib[name] = p
        return p

    for n in raw:
        resolve(n)
    for n, p in lib.items():
        _check(n, p)
    return lib


def _check(name: str, p: dict):
    if p["kind"] == "melodic":
        voices = p["layers"] if p.get("voice") == "stack" else [p]
        for v in voices:
            if v.get("voice") not in VOICES or v["voice"] == "stack":
                raise PresetError(f"preset {name!r}: unknown voice {v.get('voice')!r}")
            for k in v:
                if k not in VOICES[v["voice"]] and k not in ("voice", "kind", "doc", "mix", "gm", "layers", "tags", "octave") \
                        and k not in MIX_DEFAULTS:
                    raise PresetError(f"preset {name!r}: voice {v['voice']} has no parameter {k!r}")
    elif p["kind"] == "kit":
        for pc, v in p["pieces"].items():
            if v.get("voice") not in VOICES:
                raise PresetError(f"preset {name!r} piece {pc!r}: unknown voice {v.get('voice')!r}")
            for k in v:
                if k not in VOICES[v["voice"]] and k not in MIX_DEFAULTS and k not in ("voice", "gm", "doc"):
                    raise PresetError(f"preset {name!r} piece {pc!r}: voice {v['voice']} has no parameter {k!r}")
    else:
        raise PresetError(f"preset {name!r}: kind must be melodic or kit")


def get(name: str) -> dict:
    lib = _library()
    if name not in lib:
        raise PresetError(f"unknown preset {name!r}")
    return lib[name]


def exists(name: str) -> bool:
    return name in _library()


def names() -> list[str]:
    return sorted(_library())


def kind(name: str) -> str:
    return get(name)["kind"]


def pieces(name: str) -> list[str]:
    p = get(name)
    return list(p["pieces"]) if p["kind"] == "kit" else []


def voice_params(voice: str, given: dict) -> dict:
    """Fill a voice's parameters with defaults."""
    spec = VOICES[voice]
    out = {k: d for k, (d, _) in spec.items()}
    for k, v in given.items():
        if k in spec:
            out[k] = v
    return out


def split_mix(d: dict) -> tuple[dict, dict]:
    """Split a piece/layer dict into (voice params, mix settings)."""
    voice = {k: v for k, v in d.items() if k not in MIX_DEFAULTS and k not in ("gm", "doc")}
    mix = {k: v for k, v in d.items() if k in MIX_DEFAULTS}
    if "mix" in d:
        voice.pop("mix")
        mix = {**mix, **d["mix"]}
    return voice, mix


def categories() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for n in names():
        out.setdefault(n.split(".")[0], []).append(n)
    return out
