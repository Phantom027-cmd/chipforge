"""Procedural, seamless environment beds rendered as a separate stem under the music."""
from __future__ import annotations

import numpy as np

from . import fx
from .synth import Ctx, crush, mtof, noise, pulse_wave

BEDS = ["factory", "cave", "forest", "rain", "wind", "machinery", "water", "crowd"]


class _Amb:
    def __init__(self, song, tl, space, ctx: Ctx):
        self.song, self.tl, self.space, self.ctx = song, tl, space, ctx
        self.sr = song.sr
        self.n = space.n
        seed = (song.ambience or {}).get("seed")
        self.rng = np.random.default_rng(song.seed * 31 + 11 if seed is None else seed)
        self.dry = np.zeros((self.n + int(4 * self.sr), 2))
        self.wet = np.zeros((self.n + int(4 * self.sr), 2))
        self.loop_len = (space.n - (space.l0 or 0)) if space.circular else space.n

    def event(self, t: float, sig: np.ndarray, pan: float = 0.0, wet: float = 0.5):
        i = int(round(t * self.sr))
        j = min(i + len(sig), len(self.dry))
        if j <= i:
            return
        s = sig[: j - i]
        gl, gr = (1 - pan) / 2 * 2, (1 + pan) / 2 * 2
        self.dry[i:j, 0] += s * gl * (1 - wet)
        self.dry[i:j, 1] += s * gr * (1 - wet)
        self.wet[i:j, 0] += s * gl * wet
        self.wet[i:j, 1] += s * gr * wet

    def loopf(self, f: float) -> float:
        """Snap a continuous oscillator so it completes whole cycles per loop."""
        L = self.loop_len / self.sr
        return round(f * L) / L if self.space.circular else f

    def bed_noise(self, lo, hi, gain, lfo_cycles, lfo_depth, seed_off):
        r = np.random.default_rng(int(self.rng.integers(1 << 30)) + seed_off)
        x = fx.bandpass(r.standard_normal(self.n), lo, hi, self.sr, self.space.circular)
        if lfo_cycles:
            t = np.arange(self.n) / self.sr
            L = self.loop_len / self.sr
            x = x * (1 - lfo_depth + lfo_depth * np.sin(2 * np.pi * (lfo_cycles / L) * t + seed_off))
        return x * gain

    def finish(self, lp_hz: float, hp_hz: float, beds: np.ndarray, ir_size=2.6, ir_decay=0.55, wet_gain=0.9) -> np.ndarray:
        dry = self.space.fold(self.dry) if self.space.circular else self.dry[: self.n]
        wet = self.space.fold(self.wet) if self.space.circular else self.wet[: self.n]
        s = self.song.seed
        ir_l = fx.reverb_ir(self.sr, ir_size, ir_decay, 3500, 0.012, s * 7 + 5)
        ir_r = fx.reverb_ir(self.sr, ir_size, ir_decay, 3500, 0.012, s * 7 + 6)
        out = np.zeros((self.n, 2))
        out[:, 0] = dry[:, 0] + wet_gain * self.space.conv(wet[:, 0] + 0.3 * wet[:, 1], ir_l) + beds[:, 0]
        out[:, 1] = dry[:, 1] + wet_gain * self.space.conv(wet[:, 1] + 0.3 * wet[:, 0], ir_r) + beds[:, 1]
        out = self.space.filt(out, fx.sos("low", lp_hz, self.sr))
        out = self.space.filt(out, fx.sos("high", hp_hz, self.sr))
        return out


# ------------------------------------------------------------------ one-shot sources
def piston(sr):
    n = int(0.45 * sr)
    t = np.arange(n) / sr
    thunk = noise(n, 3500, sr) * np.exp(-t / 0.045)
    chuff = noise(n, 16000, sr, offset=777) * np.clip((t - 0.06) / 0.03, 0, 1) * np.exp(-np.clip(t - 0.06, 0, None) / 0.12)
    return crush(thunk * 0.9 + chuff * 0.35, 3)


def stamp(sr):
    n = int(1.4 * sr)
    t = np.arange(n) / sr
    x = sum(np.sin(2 * np.pi * f * t) * np.exp(-t / (0.55 / (k + 1) ** 0.5))
            for k, f in enumerate([173, 251, 389, 547, 733, 1013])) / 3
    x += noise(n, 9000, sr) * np.exp(-t / 0.03) * 0.6
    return crush(x, 2)


def clang(sr, base):
    n = int(2.0 * sr)
    t = np.arange(n) / sr
    return sum(np.sin(2 * np.pi * base * r * t) * np.exp(-t / (0.9 / r)) for r in [1, 1.59, 2.14, 2.83, 3.71]) / 3


def vent(sr, rng, dur=1.8):
    n = int(dur * sr)
    t = np.arange(n) / sr
    env = np.clip(t / 0.15, 0, 1) * np.exp(-t / (dur * 0.35))
    return noise(n, 18000, sr, offset=int(rng.integers(30000))) * env


def rattle(sr, rng, v):
    n = int(0.02 * sr)
    t = np.arange(n) / sr
    return np.diff(noise(n, 44100, sr, offset=int(rng.integers(30000))), prepend=0.0) * np.exp(-t / 0.004) * v


# ------------------------------------------------------------------ beds
def factory(a: _Amb) -> np.ndarray:
    song, sr, rng = a.song, a.sr, a.rng
    step = song.step_s
    spb = song.steps_per_bar
    total_steps = int(round(a.tl.length / step))
    bars = total_steps // spb
    T = lambda bar, s=0: (bar * spb + s) * step
    pst = piston(sr) * 0.8
    for s in range(4, total_steps, 8):            # pistons on beats 2 & 4
        a.event(s * step, pst, pan=-0.35, wet=0.45)
    stp = stamp(sr) * 0.6
    for b in range(1, bars, 2):                   # heavy press every 2 bars, off the kick grid
        a.event(T(b, 6), stp, pan=0.4, wet=0.65)
    for s in range(total_steps):                  # conveyor rattle
        a.event(s * step + rng.uniform(0, 0.006), rattle(sr, rng, rng.uniform(0.15, 0.6)), pan=0.6, wet=0.2)
    t = 1.3
    while t < a.tl.length - 0.5:                  # distant clangs
        a.event(t, clang(sr, rng.uniform(260, 620)) * rng.uniform(0.4, 0.8), pan=rng.uniform(-0.8, 0.8), wet=0.9)
        t += rng.uniform(3.2, 6.0)
    for b in range(6, bars, 8):                   # steam vents
        a.event(T(b, 8), vent(sr, rng), pan=rng.choice([-0.7, 0.7]), wet=0.4)
    beds = np.zeros((a.n, 2))
    tt = np.arange(a.n) / sr
    hum_f = a.loopf(mtof(12 * 4 + song.key_root))   # electrical hum tuned to the key (octave 3)
    hum = (pulse_wave(np.full(a.n, hum_f), 0.5, sr) * 0.5 + np.sin(2 * np.pi * 2 * hum_f * tt) * 0.3) \
        * (0.85 + 0.15 * np.sin(2 * np.pi * (7 / (a.loop_len / sr)) * tt))
    hum = fx.bandpass(hum, 140, 900, sr, a.space.circular)
    for c in range(2):
        beds[:, c] = (a.bed_noise(90, 280, 3.0, 3, 0.2, c) + a.bed_noise(400, 1500, 0.25, 5, 0.3, c + 10)
                      + hum * 0.35)
    return a.finish(5000, 70, beds)


def cave(a: _Amb) -> np.ndarray:
    """Deep rumble, slow air, water drips with long reverb, the odd distant rock fall."""
    sr, rng = a.sr, a.rng
    length = a.tl.length
    t = 0.4
    while t < length - 0.3:                       # drips: short sine pings, pitch 1-3.5 kHz
        n = int(0.25 * sr)
        tt = np.arange(n) / sr
        f = rng.uniform(1000, 3500)
        ping = np.sin(2 * np.pi * f * tt * (1 + 0.02 * np.exp(-tt / 0.01))) * np.exp(-tt / 0.035) * rng.uniform(0.3, 0.8)
        a.event(t, ping, pan=rng.uniform(-0.9, 0.9), wet=0.85)
        t += rng.uniform(0.6, 2.4)
    t = 3.0
    while t < length - 2:                         # rock falls: low filtered noise bursts
        n = int(1.2 * sr)
        tt = np.arange(n) / sr
        burst = noise(n, 6000, sr, offset=int(rng.integers(30000))) * np.exp(-tt / 0.25) * np.clip(tt / 0.02, 0, 1)
        burst = fx.lowpass(burst, 400, sr, False, 2) * rng.uniform(0.6, 1.2)
        a.event(t, burst, pan=rng.uniform(-0.6, 0.6), wet=0.7)
        t += rng.uniform(7, 14)
    beds = np.zeros((a.n, 2))
    for c in range(2):
        beds[:, c] = a.bed_noise(40, 200, 4.0, 2, 0.25, c) + a.bed_noise(300, 1200, 0.15, 3, 0.4, c + 10)
    return a.finish(4000, 40, beds, ir_size=4.0, ir_decay=1.2, wet_gain=1.2)


BED_FN = {"factory": factory, "cave": cave}


def render(song, tl, space, ctx: Ctx) -> np.ndarray:
    name = song.ambience["bed"]
    if name not in BED_FN:
        raise NotImplementedError(f"ambience bed {name!r} is not implemented yet (available: {', '.join(BED_FN)})")
    return BED_FN[name](_Amb(song, tl, space, ctx))
