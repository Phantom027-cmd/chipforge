"""Chip profiles: the hardware character each `chip:` value imposes."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ChipProfile:
    name: str
    doc: str
    frame_hz: int            # envelope / pitch update rate (NES: 60 Hz)
    vol_bits: int            # volume resolution (4 = 16 steps)
    tri_steps: int           # triangle wavetable steps (32 = NES)
    voices: dict             # authentic-mode voice limits: voice -> count
    duties: tuple            # legal pulse widths in authentic mode (empty = any)
    noise_rates: tuple = ()  # legal noise clocks in authentic mode (empty = any)


PROFILES: dict[str, ChipProfile] = {
    "nes": ChipProfile(
        "nes", "Nintendo 2A03: 2 pulse (4 duties), 32-step triangle, 15-bit LFSR noise (long/short), DPCM.",
        60, 4, 32, {"pulse": 2, "tri": 1, "noise": 1, "dpcm": 1}, (0.125, 0.25, 0.5, 0.75)),
    "gameboy": ChipProfile(
        "gameboy", "Game Boy DMG: 2 pulse, 4-bit 32-sample wave channel, noise. Stereo on/off panning only.",
        64, 4, 32, {"pulse": 2, "wave": 1, "noise": 1}, (0.125, 0.25, 0.5, 0.75)),
    "sid": ChipProfile(
        "sid", "Commodore 64 SID-style: 3 voices of pulse/saw/tri/noise with ring mod, sync and a resonant multimode filter.",
        50, 4, 0, {"any": 3}, ()),
    "fm": ChipProfile(
        "fm", "Genesis-style 4-operator FM: 6 voices, great basses, brass, bells and metallic hits.",
        60, 7, 0, {"fm": 6}, ()),
    "gm": ChipProfile(
        "gm", "General-MIDI-style 16-bit palette (wavetable voices; optional SoundFont via FluidSynth).",
        60, 7, 0, {"any": 16}, ()),
}


def get(name: str) -> ChipProfile:
    return PROFILES[name]
