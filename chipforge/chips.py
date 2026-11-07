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
    noise_short: str = "nes93"   # short-LFSR flavour used by noise voices
    clean: bool = False          # band-limited oscillators by default (enhanced mode)
    mono: bool = True            # authentic output is mono
    pan_steps: int = 0           # authentic pan quantization (3 = hard L/C/R like the Game Boy)


PROFILES: dict[str, ChipProfile] = {
    "nes": ChipProfile(
        "nes", "Nintendo 2A03: 2 pulse (4 duties), 32-step triangle, 15-bit LFSR noise (long/short), DPCM.",
        60, 4, 32, {"pulse": 2, "tri": 1, "noise": 1, "dpcm": 1}, (0.125, 0.25, 0.5, 0.75)),
    "gameboy": ChipProfile(
        "gameboy", "Game Boy DMG: 2 pulse, 4-bit 32-sample wave channel, 7/15-bit noise. Hard left/centre/right panning only.",
        64, 4, 32, {"pulse": 2, "wave": 1, "noise": 1}, (0.125, 0.25, 0.5, 0.75), "gb7", False, False, 3),
    "sid": ChipProfile(
        "sid", "Commodore 64 SID-style: 3 voices of pulse/saw/tri/noise with PWM, ring mod, hard sync and a resonant multimode filter.",
        50, 4, 0, {"sid": 3}, (), "nes15", True),
    "fm": ChipProfile(
        "fm", "Genesis-style: 6 four-operator FM voices plus a PSG (3 pulse + noise). Basses, brass, bells, metallic hits.",
        60, 7, 0, {"fm": 6, "pulse": 3, "noise": 1}, (0.5,), "nes15", True),
    "gm": ChipProfile(
        "gm", "General-MIDI-style 16-bit palette: band-limited wavetables and FM, 16 voices, stereo.",
        60, 7, 0, {"any": 16}, (), "nes15", True, False),
}

# which hardware slot a voice occupies in authentic mode (None = no such channel on the chip)
SLOT = {"pulse": "pulse", "grit": "pulse", "drone": "pulse", "siren": "pulse", "eerie": "pulse", "groan": "pulse",
        "tri": "tri", "noise": "noise", "gbwave": "wave", "wave": "wave", "sine": None, "sid": "sid", "fm": "fm",
        "kick": "noise", "snare": "noise", "hat": "noise", "clank": "noise", "crash": "noise", "hiss": "noise", "tom": "noise"}
# slot aliases: what a profile accepts in place of a slot
ACCEPTS = {"sid": {"pulse", "tri", "noise", "sid"}, "any": set(SLOT) | {"pulse", "tri", "wave", "noise", "sid", "fm"},
           "wave": {"wave", "tri"}}


def get(name: str) -> ChipProfile:
    return PROFILES[name]
