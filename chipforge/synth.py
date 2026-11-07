"""Voices: oscillators, envelopes and the note/hit renderers. Everything is vectorized NumPy.

Each voice function takes (p, ctx, n_on, midi, ev) and returns a float64 mono array whose length
is n_on plus the voice's release/tail. Velocity is applied by the caller, so results are cacheable.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from .presets import VOICES


@dataclass(frozen=True)
class Ctx:
    sr: int
    frame_hz: int = 60
    vol_bits: int = 4
    tri_steps: int = 32
    enhanced: bool = True
    seed: int = 0
    clean: bool = False          # band-limited (PolyBLEP / wavetable) oscillators instead of naive ones
    noise_short: str = "nes93"   # short LFSR flavour: nes93 (93-step metallic) or gb7 (7-bit, 127-step)


# ------------------------------------------------------------------ primitives
def mtof(m):
    return 440.0 * 2.0 ** ((np.asarray(m, dtype=float) - 69.0) / 12.0)


def frames(n: int, ctx: Ctx) -> np.ndarray:
    """Frame-quantized time axis (NES updates envelopes/pitch once per frame)."""
    t = np.arange(n) / ctx.sr
    return np.floor(t * ctx.frame_hz) / ctx.frame_hz if ctx.frame_hz else t


def quant(env: np.ndarray, bits: int) -> np.ndarray:
    if not bits:
        return np.clip(env, 0, 1)
    levels = 2 ** bits - 1
    return np.round(np.clip(env, 0, 1) * levels) / levels


def _polyblep(t: np.ndarray, dt: np.ndarray) -> np.ndarray:
    """Two-sample polynomial band-limited step correction for a discontinuity at phase 0."""
    out = np.zeros_like(t)
    a = t < dt
    ta = t[a] / dt[a]
    out[a] = ta + ta - ta * ta - 1.0
    b = t > 1.0 - dt
    tb = (t[b] - 1.0) / dt[b]
    out[b] = tb * tb + tb + tb + 1.0
    return out


def pulse_wave(freq, duty, sr: int, phase0: float = 0.0, clean: bool = False) -> np.ndarray:
    """Pulse wave, DC-free for any duty. clean=True applies PolyBLEP to both edges."""
    f = np.asarray(freq, dtype=float)
    ph = (np.cumsum(f) / sr + phase0) % 1.0
    d = np.asarray(duty, dtype=float)
    w = np.where(ph < d, 1.0, -1.0) - (2.0 * d - 1.0)
    if clean:
        dt = np.broadcast_to(f / sr, ph.shape)
        w = w + _polyblep(ph, dt) - _polyblep((ph + 1.0 - d) % 1.0, dt)
    return w


def saw_wave(freq, sr: int, clean: bool = True) -> np.ndarray:
    f = np.asarray(freq, dtype=float)
    ph = (np.cumsum(f) / sr) % 1.0
    w = 2.0 * ph - 1.0
    if clean:
        w = w - _polyblep(ph, np.broadcast_to(f / sr, ph.shape))
    return w


@lru_cache(maxsize=8)
def _tri_table(steps: int) -> np.ndarray:
    h = steps // 2
    return np.concatenate([np.arange(h - 1, -1, -1), np.arange(0, h)]) / (h / 2) - 1.0


def tri_wave(freq, sr: int, steps: int = 32) -> np.ndarray:
    ph = np.cumsum(freq) / sr
    if steps:
        tab = _tri_table(steps)
        return tab[(np.floor(ph * steps) % steps).astype(np.intp)]
    return 2.0 * np.abs(2.0 * (ph % 1.0) - 1.0) - 1.0


@lru_cache(maxsize=4)
def lfsr(kind: str) -> np.ndarray:
    """LFSR sequences (+1/-1). nes15: 15-bit long; nes93: NES short mode (taps bit 6, 93-step metallic
    loop); gb7: Game Boy 7-bit mode (127 steps)."""
    if kind == "gb7":
        reg, out = 0x7F, np.empty(127)
        for k in range(127):
            bit = (reg ^ (reg >> 1)) & 1
            reg = (reg >> 1) | (bit << 6)
            out[k] = -1.0 if reg & 1 else 1.0
        return out
    reg, tap = 1, 6 if kind == "nes93" else 1
    out = np.empty(32767)
    for k in range(32767):
        bit = (reg ^ (reg >> tap)) & 1
        reg = (reg >> 1) | (bit << 14)
        out[k] = 1.0 if reg & 1 else -1.0
    return out


def noise(n: int, rate, sr: int, short=False, offset: int = 0) -> np.ndarray:
    """short: False (long), True / 'nes93' (metallic), or 'gb7'."""
    seq = lfsr("nes15" if not short else ("nes93" if short is True else short))
    rate = np.broadcast_to(np.asarray(rate, dtype=float), (n,))
    idx = (np.floor(np.cumsum(rate) / sr).astype(np.int64) + offset) % len(seq)
    return seq[idx]


def crush(x: np.ndarray, factor: int) -> np.ndarray:
    """Sample-and-hold rate reduction."""
    if factor <= 1:
        return x
    idx = (np.arange(len(x)) // factor) * factor
    return x[idx]


@lru_cache(maxsize=64)
def _wavetable(name: str, max_harm: int) -> np.ndarray:
    """Band-limited single-cycle table with `max_harm` harmonics."""
    L = 2048
    ph = np.arange(L) / L
    out = np.zeros(L)
    for k in range(1, max_harm + 1):
        if name == "saw":
            out += np.sin(2 * np.pi * k * ph) * (-1) ** (k + 1) / k
        elif name == "tri":
            if k % 2:
                out += np.sin(2 * np.pi * k * ph) * (-1) ** ((k - 1) // 2) / k ** 2
        elif name == "pulse":
            if k % 2:
                out += np.sin(2 * np.pi * k * ph) / k
        elif name == "organ":
            if k in (1, 2, 3, 4, 6, 8):
                out += np.sin(2 * np.pi * k * ph) / k ** 0.5
        elif name == "bass":
            out += np.sin(2 * np.pi * k * ph) / k ** 1.5
        elif name == "bell":
            if k in (1, 3, 5, 8, 11):
                out += np.sin(2 * np.pi * k * ph) / k
        elif name == "sine":
            if k == 1:
                out += np.sin(2 * np.pi * ph)
    return out / (np.max(np.abs(out)) or 1.0)


def wave_osc(freq, name: str, sr: int) -> np.ndarray:
    f0 = float(np.max(freq))
    max_harm = max(1, min(256, int((sr / 2) / f0) - 1))
    tab = _wavetable(name, max_harm)
    ph = np.cumsum(freq) / sr
    return tab[(np.floor(ph * len(tab)) % len(tab)).astype(np.intp)]


# ------------------------------------------------------------------ envelopes & modulation
def env_adsr(tq: np.ndarray, dur: float, att: float, dec: float, sus: float, rel: float) -> np.ndarray:
    """Exponential decay to sustain, linear release; evaluated on frame-quantized time."""
    on = sus + (1 - sus) * np.exp(-tq / max(dec, 1e-4))
    if att > 0:
        on = on * np.clip(tq / att, 0, 1)
    lvl = sus + (1 - sus) * np.exp(-dur / max(dec, 1e-4))
    if att > 0:
        lvl *= min(1.0, dur / att)
    off = lvl * np.clip(1 - (tq - dur) / max(rel, 1e-4), 0, 1)
    return np.where(tq < dur, on, off)


def pitch_track(p: dict, ctx: Ctx, tq: np.ndarray, t: np.ndarray, midi: float, dur: float, ev: dict) -> np.ndarray:
    """Semitone track with slide, vibrato, @sweep and @arp applied."""
    n = len(tq)
    semis = np.full(n, float(midi))
    if "arp" in ev:
        tones = np.asarray(ev["arp"], dtype=float)
        rate = ev.get("arp_rate", p.get("arp_rate", 1))
        k = np.floor(t * ctx.frame_hz / rate).astype(np.intp) % len(tones)
        semis = tones[k]
    if ev.get("slide_from") is not None and p.get("slide", 0) > 0:
        semis = ev["slide_from"] + (semis - ev["slide_from"]) * np.clip(tq / p["slide"], 0, 1)
    if "sweep" in ev:
        amt, secs = (list(ev["sweep"]) + [dur])[:2]
        semis = semis + amt * np.clip(tq / max(secs, 1e-3), 0, 1)
    vib = ev["vib"] if "vib" in ev else [p.get("vib", 0.0), p.get("vib_rate", 5.8), p.get("vib_delay", 0.2)]
    depth = float(vib[0]) if vib else 0.0
    if depth and dur > p.get("vib_min", 0.0):
        rate = float(vib[1]) if len(vib) > 1 else p.get("vib_rate", 5.8)
        delay = float(vib[2]) if len(vib) > 2 else p.get("vib_delay", 0.2)
        ramp = p.get("vib_ramp", 0.25)
        d = np.clip((tq - delay) / max(ramp, 1e-3), 0, 1) * depth
        semis = semis + d * np.sin(2 * np.pi * rate * tq)
    return semis


# ------------------------------------------------------------------ melodic voices
def v_pulse(p, ctx: Ctx, n_on: int, midi: float, ev: dict) -> np.ndarray:
    dur = n_on / ctx.sr
    n = n_on + int(p["rel"] * ctx.sr)
    t = np.arange(n) / ctx.sr
    tq = frames(n, ctx)
    semis = pitch_track(p, ctx, tq, t, midi, dur, ev)
    duty = ev["d"][0] if "d" in ev else p["duty"]
    if p.get("pluck") is not None:
        duty = np.where(tq < 2 / ctx.frame_hz, p["pluck"], duty)
    w = pulse_wave(mtof(semis), duty, ctx.sr, clean=ctx.clean)
    if p.get("detune") and ctx.enhanced:
        w = (w + p["detune"] * pulse_wave(mtof(semis) * 1.004, duty, ctx.sr, clean=ctx.clean)) / (1 + p["detune"])
    e = ev["env"] if "env" in ev else None
    dec, sus, rel = (e + [p["sus"], p["rel"]])[:3] if e else (p["dec"], p["sus"], p["rel"])
    env = env_adsr(tq, dur, p["att"], dec, sus, rel)
    return w * quant(env, ctx.vol_bits)


def v_tri(p, ctx: Ctx, n_on: int, midi: float, ev: dict) -> np.ndarray:
    dur = n_on / ctx.sr
    r = max(1, int(p["rel"] * ctx.sr))
    n = n_on + r
    t = np.arange(n) / ctx.sr
    tq = frames(n, ctx)
    semis = pitch_track(p, ctx, tq, t, midi, dur, ev)
    w = tri_wave(mtof(semis), ctx.sr, 0 if ctx.clean else (p["steps"] or ctx.tri_steps))
    g = np.ones(n)
    g[n_on:] = np.linspace(1, 0, r, endpoint=False)
    return w * g


def v_sine(p, ctx: Ctx, n_on: int, midi: float, ev: dict) -> np.ndarray:
    n = n_on + int(p["rel"] * ctx.sr)
    t = np.arange(n) / ctx.sr
    f = mtof(midi)
    w = np.sin(2 * np.pi * f * t)
    if p["harm2"]:
        w = w + p["harm2"] * np.sin(4 * np.pi * f * t)
    env = np.clip(t / max(p["att"], 1e-4), 0, 1) * np.where(np.arange(n) < n_on, 1.0,
                                                               np.clip(1 - (t - n_on / ctx.sr) / max(p["rel"], 1e-4), 0, 1))
    return w * env


def v_grit(p, ctx: Ctx, n_on: int, midi: float, ev: dict) -> np.ndarray:
    dur = n_on / ctx.sr
    n = n_on + int(p["rel"] * ctx.sr)
    t = np.arange(n) / ctx.sr
    f = mtof(midi) * (1 + p["bite"] * np.exp(-t / 0.02))
    w = pulse_wave(f, p["duty"], ctx.sr, clean=ctx.clean)
    if p["detune"]:
        w = 0.6 * w + 0.4 * pulse_wave(f * (1 + p["detune"]), 0.5, ctx.sr, clean=ctx.clean)
    env = np.where(t < dur, p["sus"] + (1 - p["sus"]) * np.exp(-t / p["dec"]),
                   p["sus"] * np.clip(1 - (t - dur) / p["rel"], 0, 1))
    return w * env


def v_drone(p, ctx: Ctx, n_on: int, midi: float, ev: dict) -> np.ndarray:
    dur = n_on / ctx.sr
    n = n_on + int(p["rel"] * ctx.sr)
    t = np.arange(n) / ctx.sr
    tq = frames(n, ctx)
    duty = 0.5 + p["pwm_depth"] * np.sin(2 * np.pi * p["pwm_rate"] * t)
    f = mtof(midi)
    w = pulse_wave(np.full(n, f * (1 - p["detune"])), duty, ctx.sr, clean=ctx.clean) \
        + pulse_wave(np.full(n, f * (1 + p["detune"])), 1 - duty, ctx.sr, clean=ctx.clean)
    norm = 2.0
    if p["fifth"]:
        w = w + p["fifth"] * pulse_wave(np.full(n, mtof(midi + 7) * 1.002), 0.5, ctx.sr, clean=ctx.clean)
        norm += p["fifth"]
    env = np.clip(tq / p["att"], 0, 1) * np.where(tq < dur, 1, np.clip(1 - (tq - dur) / p["rel"], 0, 1))
    env = env * (1 - p["trem"] + p["trem"] * np.sin(2 * np.pi * p["trem_rate"] * tq))
    return w * quant(env, ctx.vol_bits) / norm


def v_noise(p, ctx: Ctx, n_on: int, midi: float, ev: dict) -> np.ndarray:
    dur = n_on / ctx.sr
    n = n_on + int(p["rel"] * ctx.sr)
    tq = frames(n, ctx)
    rate = mtof(midi) * 93 / 4 if p["pitched"] and midi is not None else p["rate"]
    env = env_adsr(tq, dur, 0, p["dec"], p["sus"], p["rel"])
    return noise(n, rate, ctx.sr, ctx.noise_short if p["short"] else False) * quant(env, ctx.vol_bits)


def v_wave(p, ctx: Ctx, n_on: int, midi: float, ev: dict) -> np.ndarray:
    dur = n_on / ctx.sr
    n = n_on + int(p["rel"] * ctx.sr)
    t = np.arange(n) / ctx.sr
    tq = frames(n, ctx)
    semis = pitch_track(p, ctx, tq, t, midi, dur, ev)
    w = wave_osc(mtof(semis), p["table"], ctx.sr)
    env = env_adsr(tq, dur, p["att"], p["dec"], p["sus"], p["rel"])
    return w * quant(env, ctx.vol_bits if not ctx.enhanced else 7)


# ------------------------------------------------------------------ kit voices
def v_kick(p, ctx, n_on, midi, ev):
    n = int(p["len"] * ctx.sr)
    t = np.arange(n) / ctx.sr
    f = p["f1"] + (p["f0"] - p["f1"]) * np.exp(-t / p["pitch_dec"])
    body = np.sin(2 * np.pi * np.cumsum(f) / ctx.sr) * np.exp(-t / p["dec"])
    click = tri_wave(np.full(n, float(p["click_f"])), ctx.sr, ctx.tri_steps) * np.exp(-t / 0.006)
    x = body + p["click"] * click
    if p["crush"]:
        x = np.round(x * p["crush"]) / p["crush"]
    return x


def v_snare(p, ctx, n_on, midi, ev):
    n = int(p["len"] * ctx.sr)
    t = np.arange(n) / ctx.sr
    tq = frames(n, ctx)
    nz = noise(n, p["rate"], ctx.sr, ctx.noise_short if p["short"] else False) * quant(np.exp(-tq / p["dec"]), ctx.vol_bits)
    tone = tri_wave(p["tone_f"] * np.exp(-t / 0.08), ctx.sr, ctx.tri_steps) * np.exp(-t / p["tone_dec"])
    return crush(nz * 0.85 + tone * p["tone"], int(p["crush"]))


def v_hat(p, ctx, n_on, midi, ev):
    n = int(p["len"] * ctx.sr)
    t = np.arange(n) / ctx.sr
    x = np.diff(noise(n, p["rate"], ctx.sr, ctx.noise_short if p["short"] else False), prepend=0.0) * 0.5
    return x * np.exp(-t / p["dec"])


def v_clank(p, ctx, n_on, midi, ev):
    n = int(p["len"] * ctx.sr)
    tq = frames(n, ctx)
    ring = pulse_wave(np.full(n, float(p["f1"])), 0.5, ctx.sr) * pulse_wave(np.full(n, float(p["f2"])), 0.5, ctx.sr)
    metal = noise(n, p["rate"], ctx.sr, ctx.noise_short)
    return crush((ring * 0.6 + metal * 0.4) * quant(np.exp(-tq / p["dec"]), ctx.vol_bits), int(p["crush"]))


def v_crash(p, ctx, n_on, midi, ev):
    n = int(p["len"] * ctx.sr)
    tq = frames(n, ctx)
    return noise(n, p["rate"], ctx.sr, ctx.noise_short if p["short"] else False) * quant(np.exp(-tq / p["dec"]), ctx.vol_bits)


def v_tom(p, ctx, n_on, midi, ev):
    n = int(p["len"] * ctx.sr)
    t = np.arange(n) / ctx.sr
    f = p["f1"] + (p["f0"] - p["f1"]) * np.exp(-t / p["pitch_dec"])
    body = tri_wave(f, ctx.sr, ctx.tri_steps) * np.exp(-t / p["dec"])
    return body + p["noise"] * noise(n, 8000, ctx.sr) * np.exp(-t / 0.02)


def v_hiss(p, ctx, n_on, midi, ev):
    dur = ev.get("dur") or (n_on / ctx.sr if ev.get("len") else p["len"])
    up = ev.get("up", p["up"])
    n = int(dur * ctx.sr)
    tq = frames(n, ctx)
    a, b = (p["f_lo"], p["f_hi"]) if up else (p["f_hi"], p["f_lo"])
    rate = a * (b / a) ** (tq / dur)
    env = np.clip(tq / 0.03, 0, 1) * (tq / dur if up else np.exp(-tq / (dur * 0.4)))
    return noise(n, rate, ctx.sr) * quant(env, ctx.vol_bits)


def v_groan(p, ctx, n_on, midi, ev):
    dur = ev.get("dur", p["len"])
    m0, m1 = ev.get("from", p["from"]), ev.get("to", p["to"])
    n = int(dur * ctx.sr)
    tq = frames(n, ctx)
    semis = m0 + (m1 - m0) * (tq / dur) ** p["curve"] + p["wobble"] * np.sin(2 * np.pi * p["wobble_rate"] * tq)
    f = mtof(semis)
    w = pulse_wave(f, 0.5, ctx.sr) * (1 - p["noise"]) + noise(n, f * 93 / 4, ctx.sr, ctx.noise_short) * p["noise"]
    env = np.clip(tq / p["att"], 0, 1) * np.clip(1 - tq / dur, 0, 1) ** 0.8
    return w * quant(env, ctx.vol_bits)


def v_siren(p, ctx, n_on, midi, ev):
    dur = ev.get("dur") or (n_on / ctx.sr if n_on else p["len"])
    m0, m1 = ev.get("from", p["from"]), ev.get("to", p["to"])
    n = int((dur + 0.07) * ctx.sr)
    tq = frames(n, ctx)
    semis = m0 + (m1 - m0) * np.clip(tq / p["slide"], 0, 1)
    env = env_adsr(tq, dur, 0, 0.12, p["sus"], 0.07)
    return pulse_wave(mtof(semis), p["duty"], ctx.sr) * quant(env, ctx.vol_bits)


def v_eerie(p, ctx, n_on, midi, ev):
    dur = ev.get("dur") or (n_on / ctx.sr if n_on else p["len"])
    notes = ev.get("notes", p["notes"])
    n = int(dur * ctx.sr)
    tq = frames(n, ctx)
    w = sum(pulse_wave(mtof(m + p["wobble"] * np.sin(2 * np.pi * p["wobble_rate"] * tq + i)), p["duty"], ctx.sr)
            for i, m in enumerate(notes))
    env = np.sin(np.pi * np.clip(tq / dur, 0, 1)) ** 1.5
    return w * quant(env, ctx.vol_bits) / len(notes)




# ------------------------------------------------------------------ Game Boy wave channel
GB_TABLES = {
    "saw":    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] * 2,
    "tri":    [0, 2, 4, 6, 8, 10, 12, 14, 15, 13, 11, 9, 7, 5, 3, 1] * 2,
    "sine":   [8, 10, 12, 14, 15, 15, 15, 14, 12, 10, 8, 5, 3, 1, 0, 0, 0, 1, 3, 5] + [8] * 12,
    "square": [15] * 16 + [0] * 16,
    "organ":  [8, 13, 15, 13, 8, 11, 15, 11, 8, 3, 0, 3, 8, 5, 0, 5] * 2,
    "bass":   [15, 15, 14, 12, 10, 8, 6, 4, 2, 1, 0, 0, 1, 2, 4, 6, 8, 10, 12, 14, 15, 15, 14, 12, 10, 8, 6, 4, 2, 1, 0, 0],
    "bell":   [8, 15, 8, 1, 8, 12, 8, 4, 8, 15, 8, 1, 8, 12, 8, 4] * 2,
}


def v_gbwave(p, ctx: Ctx, n_on: int, midi: float, ev: dict) -> np.ndarray:
    """Game Boy 4-bit, 32-step wavetable channel. Volume has 4 hardware levels in authentic mode."""
    dur = n_on / ctx.sr
    n = n_on + int(p["rel"] * ctx.sr)
    t = np.arange(n) / ctx.sr
    tq = frames(n, ctx)
    semis = pitch_track(p, ctx, tq, t, midi, dur, ev)
    tab = p["table"]
    tab = np.asarray(GB_TABLES[tab] if isinstance(tab, str) else list(tab), dtype=float)
    if len(tab) == 16:
        tab = np.repeat(tab, 2)
    tab = tab / 7.5 - 1.0
    ph = np.cumsum(mtof(semis)) / ctx.sr
    w = tab[(np.floor(ph * 32) % 32).astype(np.intp)]
    env = env_adsr(tq, dur, p["att"], p["dec"], p["sus"], p["rel"])
    if not ctx.enhanced:
        env = np.select([env > 0.75, env > 0.375, env > 0.125], [1.0, 0.5, 0.25], 0.0)
    return w * env


# ------------------------------------------------------------------ SID
def _rbj_coeffs(kind: str, f0: float, q: float, sr: int):
    w0 = 2 * np.pi * min(f0, sr * 0.45) / sr
    cw, sw = np.cos(w0), np.sin(w0)
    alpha = sw / (2 * q)
    if kind == "lp":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
    elif kind == "hp":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
    else:
        b = [alpha, 0.0, -alpha]
    a = [1 + alpha, -2 * cw, 1 - alpha]
    return np.array(b) / a[0], np.array(a) / a[0]


def svf_sweep(x: np.ndarray, kind: str, cutoff: np.ndarray, q: float, sr: int, frame: int) -> np.ndarray:
    """Resonant 2-pole filter whose cutoff is updated once per frame (SID-style sweep)."""
    import scipy.signal as ss
    y = np.empty_like(x)
    zi = np.zeros(2)
    for i in range(0, len(x), frame):
        b, a = _rbj_coeffs(kind, float(cutoff[i]), q, sr)
        y[i:i + frame], zi = ss.lfilter(b, a, x[i:i + frame], zi=zi)
    return y


def v_sid(p, ctx: Ctx, n_on: int, midi: float, ev: dict) -> np.ndarray:
    """C64 SID-style voice: pulse/saw/tri/noise with PWM, ring modulation, hard sync and a
    resonant multimode filter with envelope/LFO sweep."""
    dur = n_on / ctx.sr
    n = n_on + int(p["rel"] * ctx.sr)
    t = np.arange(n) / ctx.sr
    tq = frames(n, ctx)
    semis = pitch_track(p, ctx, tq, t, midi, dur, ev)
    f = mtof(semis)
    waves = p["wave"] if isinstance(p["wave"], list) else [p["wave"]]
    duty = ev["d"][0] if "d" in ev else p["duty"]
    if p["pwm"]:
        duty = duty + p["pwm"] * np.sin(2 * np.pi * p["pwm_rate"] * t)
        duty = np.clip(duty, 0.03, 0.97)
    clean = ctx.clean or ctx.enhanced
    ph = np.cumsum(f) / ctx.sr
    if p["sync"]:                       # hard sync: slave phase resets whenever the master wraps
        mph = np.cumsum(f * p["sync"]) / ctx.sr
        wraps = np.diff(np.floor(mph), prepend=0) > 0
        reset_at = np.where(wraps, ph, 0.0)
        ph = ph - np.maximum.accumulate(reset_at)
    phm = ph % 1.0
    w = np.zeros(n)
    for wv in waves:
        if wv == "pulse":
            d = np.broadcast_to(np.asarray(duty, float), (n,))
            x = np.where(phm < d, 1.0, -1.0) - (2 * d - 1)
            if clean:
                dt = f / ctx.sr
                x = x + _polyblep(phm, dt) - _polyblep((phm + 1 - d) % 1.0, dt)
        elif wv == "saw":
            x = 2 * phm - 1
            if clean:
                x = x - _polyblep(phm, f / ctx.sr)
        elif wv == "tri":
            x = 2 * np.abs(2 * phm - 1) - 1
            if p["ring"]:               # ring mod: triangle sign flipped by a second oscillator
                x = x * np.sign(pulse_wave(f * p["ring"], 0.5, ctx.sr) + 1e-9)
        else:
            x = noise(n, f * 16, ctx.sr)
        w += x
    w /= len(waves)
    env = env_adsr(tq if not ctx.enhanced else t, dur, p["att"], p["dec"], p["sus"], p["rel"])
    env = quant(env, ctx.vol_bits) if not ctx.enhanced else env
    w = w * env
    if p["cutoff"]:
        c = p["cutoff"] * np.ones(n)
        if p["fenv"]:
            c = c * 2 ** (p["fenv"] * np.exp(-t / max(p["fdec"], 1e-3)))
        if p["flfo"]:
            c = c * 2 ** (p["flfo"] * np.sin(2 * np.pi * p["flfo_rate"] * t))
        if "sweep_f" in ev:
            c = c * 2 ** (ev["sweep_f"][0] * np.clip(t / dur, 0, 1))
        c = np.clip(c, 30, ctx.sr * 0.45)
        frame = max(32, ctx.sr // ctx.frame_hz)
        w = svf_sweep(w, p["ftype"], c, p["res"], ctx.sr, frame)
    return w


# ------------------------------------------------------------------ 4-operator FM
FM_ALGS = {   # YM2612 algorithms: {op: [modulators]}, carriers
    0: ({2: [1], 3: [2], 4: [3]}, [4]),
    1: ({3: [1, 2], 4: [3]}, [4]),
    2: ({3: [2], 4: [1, 3]}, [4]),
    3: ({2: [1], 4: [2, 3]}, [4]),
    4: ({2: [1], 4: [3]}, [2, 4]),
    5: ({2: [1], 3: [1], 4: [1]}, [2, 3, 4]),
    6: ({2: [1]}, [2, 3, 4]),
    7: ({}, [1, 2, 3, 4]),
}


def _fm_env(t: np.ndarray, dur: float, op: dict) -> np.ndarray:
    att, dec, sus, rel = op.get("att", 0.002), op.get("dec", 0.3), op.get("sus", 0.7), op.get("rel", 0.1)
    on = np.where(t < att, t / max(att, 1e-5), sus + (1 - sus) * np.exp(-(t - att) / max(dec, 1e-4)))
    lvl = sus + (1 - sus) * np.exp(-max(dur - att, 0) / max(dec, 1e-4)) if dur > att else dur / max(att, 1e-5)
    off = lvl * np.exp(-(t - dur) / max(rel, 1e-4))
    return np.where(t < dur, on, off)


def v_fm(p, ctx: Ctx, n_on: int, midi: float, ev: dict) -> np.ndarray:
    """4-operator phase-modulation synth (Genesis/YM2612-style). Operators: ratio, level, detune,
    att/dec/sus/rel; op 1 may feed back on itself."""
    dur = n_on / ctx.sr
    rel = max(op.get("rel", 0.1) for op in p["ops"]) if p["ops"] else 0.1
    n = n_on + int(min(rel * 5, 3.0) * ctx.sr)
    t = np.arange(n) / ctx.sr
    tq = frames(n, ctx)
    semis = pitch_track(p, ctx, tq, t, midi, dur, ev)
    f = mtof(semis)
    mods, carriers = FM_ALGS[int(p["alg"])]
    ops = {i + 1: op for i, op in enumerate(p["ops"])}
    if not any(c in ops for c in carriers):      # fewer than 4 operators: the last one carries
        carriers = [max(ops)]
    out_ops: dict[int, np.ndarray] = {}
    for i in range(1, 5):
        if i not in ops:
            continue
        op = ops[i]
        ph = 2 * np.pi * np.cumsum(f * op.get("ratio", 1.0) * (1 + op.get("detune", 0.0) / 1000)) / ctx.sr
        env = _fm_env(t, dur, op) * op.get("level", 1.0)
        m = sum((out_ops[j] for j in mods.get(i, []) if j in out_ops), np.zeros(n))
        if i == 1 and p["feedback"]:
            y = np.sin(ph)
            for _ in range(3):             # fixed-point iteration of the one-sample feedback loop
                y = np.sin(ph + p["feedback"] * np.pi * np.concatenate([[0.0], y[:-1]]))
            out_ops[i] = y * env
        else:
            out_ops[i] = np.sin(ph + p["mod_depth"] * np.pi * m) * env
    w = sum((out_ops[c] for c in carriers if c in out_ops), np.zeros(n)) / max(1, len([c for c in carriers if c in out_ops]))
    if not ctx.enhanced:
        w = np.round(w * 64) / 64
    return w


# ------------------------------------------------------------------ DPCM-style 1-bit delta encoding
def dpcm(x: np.ndarray, sr: int, rate: float = 33144.0, levels: int = 64) -> np.ndarray:
    """Re-encode a signal as NES DPCM: resample to `rate`, then 1-bit delta modulation with
    `levels` output steps. Small and cached, so a Python loop is fine here."""
    m = int(len(x) * rate / sr)
    if m < 2:
        return x
    xs = np.interp(np.arange(m) * sr / rate, np.arange(len(x)), x)
    step = 2.0 / levels
    y = np.empty(m)
    acc = 0.0
    for i in range(m):
        acc = min(1.0, acc + step) if xs[i] > acc else max(-1.0, acc - step)
        y[i] = acc
    return np.interp(np.arange(len(x)) * rate / sr, np.arange(m), y)


VOICE_FN = {
    "pulse": v_pulse, "tri": v_tri, "sine": v_sine, "grit": v_grit, "drone": v_drone, "noise": v_noise,
    "wave": v_wave, "kick": v_kick, "snare": v_snare, "hat": v_hat, "clank": v_clank, "crash": v_crash,
    "hiss": v_hiss, "groan": v_groan, "siren": v_siren, "eerie": v_eerie,
    "gbwave": v_gbwave, "sid": v_sid, "fm": v_fm, "tom": v_tom,
}
assert set(VOICE_FN) <= set(VOICES)
