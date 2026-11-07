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
        ping = np.sin(2 * np.pi * f * tt * (1 + 0.02 * np.exp(-tt / 0.01))) * np.exp(-tt / 0.035) * rng.uniform(0.12, 0.4)
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
    return a.finish(4000, 40, beds, ir_size=3.5, ir_decay=0.9, wet_gain=1.0)




def _sine_chirp(sr, f0, f1, dur, env_curve=1.0):
    n = int(dur * sr)
    t = np.arange(n) / sr
    f = f0 * (f1 / f0) ** (t / dur)
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** env_curve
    return np.sin(2 * np.pi * np.cumsum(f) / sr) * env


def forest(a: _Amb) -> np.ndarray:
    """Leaves in a light wind, bird calls, a far-off woodpecker and a cuckoo-like two-note."""
    sr, rng = a.sr, a.rng
    length = a.tl.length
    t = 0.8
    while t < length - 1:                          # birds: 2-5 chirps, random contour
        base = rng.uniform(2200, 4800)
        for k in range(int(rng.integers(2, 6))):
            d = rng.uniform(0.05, 0.14)
            a.event(t + k * rng.uniform(0.12, 0.22), _sine_chirp(sr, base * rng.uniform(0.8, 1.2), base * rng.uniform(0.7, 1.4), d, 1.5)
                    * rng.uniform(0.15, 0.4), pan=rng.uniform(-0.9, 0.9), wet=0.6)
        t += rng.uniform(1.5, 4.5)
    t = 5.0
    while t < length - 2:                          # woodpecker bursts
        for k in range(int(rng.integers(5, 9))):
            n = int(0.03 * sr)
            tt = np.arange(n) / sr
            tap = fx.bandpass(noise(n, 9000, sr, offset=int(rng.integers(30000))), 1500, 6000, sr, False) * np.exp(-tt / 0.006)
            a.event(t + k * 0.055, tap * 0.5, pan=rng.uniform(-0.6, 0.6), wet=0.7)
        t += rng.uniform(9, 16)
    beds = np.zeros((a.n, 2))
    for c in range(2):                             # leaves: high-passed noise with slow gusts
        beds[:, c] = a.bed_noise(1200, 6000, 0.35, 3, 0.5, c) + a.bed_noise(300, 1200, 0.12, 2, 0.3, c + 10) \
            + a.bed_noise(60, 250, 0.08, 2, 0.3, c + 20)
    return a.finish(9000, 50, beds, ir_size=2.0, ir_decay=0.6, wet_gain=0.8)


def rain(a: _Amb) -> np.ndarray:
    """Steady rain: dense filtered noise bed plus a scatter of individual drops."""
    sr, rng = a.sr, a.rng
    length = a.tl.length
    t = 0.0
    n = int(0.012 * sr)
    tt = np.arange(n) / sr
    while t < length:                              # heavier drops on surfaces
        f = rng.uniform(1500, 5000)
        drop = np.sin(2 * np.pi * f * tt) * np.exp(-tt / 0.0025) * rng.uniform(0.1, 0.35)
        a.event(t, drop, pan=rng.uniform(-1, 1), wet=0.3)
        t += rng.uniform(0.02, 0.09)
    beds = np.zeros((a.n, 2))
    for c in range(2):
        beds[:, c] = a.bed_noise(2000, 9000, 0.6, 5, 0.25, c) + a.bed_noise(500, 2000, 0.25, 3, 0.2, c + 10) \
            + a.bed_noise(100, 500, 0.15, 2, 0.2, c + 20)
    return a.finish(11000, 80, beds, ir_size=1.5, ir_decay=0.4, wet_gain=0.5)


def wind(a: _Amb) -> np.ndarray:
    """Open wind: band-passed noise whose centre sweeps slowly, with gusts and whistles."""
    sr, rng = a.sr, a.rng
    n = a.n
    L = a.loop_len / sr
    tt = np.arange(n) / sr
    beds = np.zeros((n, 2))
    for c in range(2):
        r = np.random.default_rng(int(rng.integers(1 << 30)))
        x = r.standard_normal(n)
        lo = fx.bandpass(x, 80, 400, sr, a.space.circular)
        mid = fx.bandpass(x, 400, 1600, sr, a.space.circular)
        gust = 0.55 + 0.45 * np.sin(2 * np.pi * (2 / L) * tt + c * 1.3) * np.sin(2 * np.pi * (5 / L) * tt + c)
        beds[:, c] = (lo * 1.2 + mid * 0.5 * gust) * (0.6 + 0.4 * gust)
    t = 2.0
    while t < a.tl.length - 3:                     # whistles through gaps
        a.event(t, _sine_chirp(sr, rng.uniform(600, 1100), rng.uniform(500, 1300), rng.uniform(1.0, 2.5), 2.0) * 0.08,
                pan=rng.uniform(-0.8, 0.8), wet=0.8)
        t += rng.uniform(4, 10)
    return a.finish(6000, 50, beds, ir_size=2.5, ir_decay=0.8, wet_gain=0.6)


def machinery(a: _Amb) -> np.ndarray:
    """Running machinery: motor hum tuned to the key, rhythmic clatter, relays and pressure pops."""
    song, sr, rng = a.song, a.sr, a.rng
    step = song.step_s
    total_steps = int(round(a.tl.length / step))
    n = a.n
    tt = np.arange(n) / sr
    hum_f = a.loopf(mtof(12 * 3 + song.key_root))          # motor fundamental in octave 2
    hum = (0.5 * pulse_wave(np.full(n, hum_f), 0.5, sr) + 0.35 * np.sin(2 * np.pi * 2 * hum_f * tt)
           + 0.2 * np.sin(2 * np.pi * 3 * hum_f * tt)) * (0.8 + 0.2 * np.sin(2 * np.pi * (4 / (a.loop_len / sr)) * tt))
    hum = fx.bandpass(hum, 60, 1200, sr, a.space.circular)
    clatter = noise(int(0.06 * sr), 5000, sr) * np.exp(-np.arange(int(0.06 * sr)) / sr / 0.015)
    for s_ in range(0, total_steps, 2):                     # clatter every 8th
        a.event(s_ * step + rng.uniform(0, 0.004), clatter * rng.uniform(0.25, 0.5), pan=0.5, wet=0.3)
    t = 0.7
    while t < a.tl.length - 0.5:                            # relay clicks
        m = int(0.02 * sr)
        a.event(t, np.diff(noise(m, 20000, sr, offset=int(rng.integers(30000))), prepend=0.0) * np.exp(-np.arange(m) / sr / 0.003) * 0.4,
                pan=rng.uniform(-0.7, 0.7), wet=0.5)
        t += rng.uniform(0.6, 2.2)
    t = 3.0
    while t < a.tl.length - 1.5:                            # pressure pops
        m = int(0.5 * sr)
        tt2 = np.arange(m) / sr
        a.event(t, noise(m, 12000, sr, offset=int(rng.integers(30000))) * np.exp(-tt2 / 0.08) * 0.5, pan=rng.uniform(-0.5, 0.5), wet=0.7)
        t += rng.uniform(5, 11)
    beds = np.zeros((n, 2))
    for c in range(2):
        beds[:, c] = a.bed_noise(100, 350, 2.0, 3, 0.15, c) + hum * 0.6
    return a.finish(6000, 60, beds, ir_size=2.0, ir_decay=0.5, wet_gain=0.8)


def water(a: _Amb) -> np.ndarray:
    """A stream: bubbling band-passed noise with a fast random modulation, drips and gurgles."""
    sr, rng = a.sr, a.rng
    n = a.n
    beds = np.zeros((n, 2))
    for c in range(2):
        r = np.random.default_rng(int(rng.integers(1 << 30)))
        x = fx.bandpass(r.standard_normal(n), 600, 4500, sr, a.space.circular)
        mod = fx.lowpass(np.abs(r.standard_normal(n)), 12, sr, a.space.circular)    # bubbling amplitude
        mod = mod / (np.max(mod) or 1)
        beds[:, c] = x * (0.3 + 0.7 * mod) * 0.6 + a.bed_noise(120, 600, 0.3, 2, 0.2, c + 10)
    t = 0.3
    while t < a.tl.length - 0.5:                            # drips and gurgles (rising sine blips)
        f0 = rng.uniform(500, 1600)
        a.event(t, _sine_chirp(sr, f0, f0 * rng.uniform(1.3, 2.2), rng.uniform(0.04, 0.12), 1.0) * rng.uniform(0.15, 0.4),
                pan=rng.uniform(-0.9, 0.9), wet=0.6)
        t += rng.uniform(0.15, 0.9)
    return a.finish(8000, 80, beds, ir_size=1.5, ir_decay=0.5, wet_gain=0.6)


def crowd(a: _Amb) -> np.ndarray:
    """A crowd murmur: many formant-filtered noise voices with speech-rate modulation, plus
    occasional nearer voices, laughs and clinks (tavern / market / arena hallway)."""
    sr, rng = a.sr, a.rng
    n = a.n
    beds = np.zeros((n, 2))
    for c in range(2):
        r = np.random.default_rng(int(rng.integers(1 << 30)))
        murmur = np.zeros(n)
        for f0, f1, g in [(180, 400, 1.0), (400, 900, 0.7), (900, 2200, 0.4), (2200, 4000, 0.15)]:
            band = fx.bandpass(r.standard_normal(n), f0, f1, sr, a.space.circular)
            mod = fx.lowpass(np.abs(r.standard_normal(n)), 4.5, sr, a.space.circular)
            murmur += band * (0.4 + 0.6 * mod / (np.max(mod) or 1)) * g
        beds[:, c] = murmur * 0.5
    t = 0.5
    while t < a.tl.length - 1:                              # nearer voice fragments: short formant sweeps
        dur = rng.uniform(0.25, 0.7)
        m = int(dur * sr)
        tt = np.arange(m) / sr
        f = rng.uniform(140, 260) * (1 + 0.15 * np.sin(2 * np.pi * rng.uniform(3, 6) * tt))
        syll = (0.5 + 0.5 * np.sin(2 * np.pi * rng.uniform(4, 7) * tt)) ** 2
        voice = pulse_wave(f, 0.3, sr) * syll * np.sin(np.pi * np.clip(tt / dur, 0, 1))
        voice = fx.bandpass(voice, rng.uniform(300, 500), rng.uniform(1500, 2800), sr, False)
        a.event(t, voice * rng.uniform(0.15, 0.35), pan=rng.uniform(-0.9, 0.9), wet=0.5)
        t += rng.uniform(0.8, 3.0)
    t = 4.0
    while t < a.tl.length - 1:                              # glass clinks
        a.event(t, _sine_chirp(sr, rng.uniform(2500, 4200), rng.uniform(2400, 4000), 0.35, 0.3) * np.exp(-np.arange(int(0.35 * sr)) / sr / 0.1) * 0.25,
                pan=rng.uniform(-0.8, 0.8), wet=0.8)
        t += rng.uniform(5, 12)
    return a.finish(7000, 100, beds, ir_size=2.2, ir_decay=0.7, wet_gain=0.9)


BED_FN = {"factory": factory, "cave": cave, "forest": forest, "rain": rain, "wind": wind,
          "machinery": machinery, "water": water, "crowd": crowd}


def render(song, tl, space, ctx: Ctx) -> np.ndarray:
    name = song.ambience["bed"]
    if name not in BED_FN:
        raise NotImplementedError(f"ambience bed {name!r} is not implemented yet (available: {', '.join(BED_FN)})")
    return BED_FN[name](_Amb(song, tl, space, ctx))
