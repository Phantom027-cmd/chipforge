"""DSP blocks that are loop-aware: every effect has a circular mode so loops never click."""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import scipy.fft as sfft
import scipy.signal as ss


def fold(x: np.ndarray, n: int) -> np.ndarray:
    """Wrap everything past sample n back to the start (seamless loop tails)."""
    y = x[:n].copy()
    tail = x[n:]
    for start in range(0, len(tail), n):   # very long tails keep wrapping
        chunk = tail[start:start + n]
        y[: len(chunk)] += chunk
    return y


@lru_cache(maxsize=256)
def sos(kind: str, f, sr: int, order: int = 2, f2=None, gain: float = 1.0):
    """Butterworth low/high/band, or an RBJ shelf: kind 'highshelf' / 'lowshelf' with linear `gain`."""
    if kind == "band":
        return ss.butter(order, [f, f2], "band", fs=sr, output="sos")
    if kind in ("highshelf", "lowshelf"):
        A = np.sqrt(max(gain, 1e-6))
        w0 = 2 * np.pi * f / sr
        cw, sw = np.cos(w0), np.sin(w0)
        alpha = sw / 2 * np.sqrt(2.0)            # shelf slope 1
        s_ = 1.0 if kind == "highshelf" else -1.0
        b0 = A * ((A + 1) + s_ * (A - 1) * cw + 2 * np.sqrt(A) * alpha)
        b1 = -2 * s_ * A * ((A - 1) + s_ * (A + 1) * cw)
        b2 = A * ((A + 1) + s_ * (A - 1) * cw - 2 * np.sqrt(A) * alpha)
        a0 = (A + 1) - s_ * (A - 1) * cw + 2 * np.sqrt(A) * alpha
        a1 = 2 * s_ * ((A - 1) - s_ * (A + 1) * cw)
        a2 = (A + 1) - s_ * (A - 1) * cw - 2 * np.sqrt(A) * alpha
        return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]])
    return ss.butter(order, f, kind, fs=sr, output="sos")


def filt(x: np.ndarray, s, circular: bool) -> np.ndarray:
    """IIR filter; in circular mode the filter state is warmed with one pass so the seam is clean."""
    if x.ndim == 2:
        return np.stack([filt(x[:, i], s, circular) for i in range(x.shape[1])], axis=1)
    if not circular:
        return ss.sosfilt(s, x)
    # warm the filter state on the last stretch of the loop (long enough for any audio filter to settle)
    warm = x[-min(len(x), 4 * 44100):]
    _, zf = ss.sosfilt(s, warm, zi=np.zeros((s.shape[0], 2)))
    y, _ = ss.sosfilt(s, x, zi=zf)
    return y


def lowpass(x, f, sr, circular, order=2):
    return filt(x, sos("low", float(f), sr, order), circular)


def highpass(x, f, sr, circular, order=2):
    return filt(x, sos("high", float(f), sr, order), circular)


def bandpass(x, lo, hi, sr, circular, order=2):
    return filt(x, sos("band", float(lo), sr, order, float(hi)), circular)


def delay(x: np.ndarray, samples: int, circular: bool) -> np.ndarray:
    if samples == 0:
        return x
    if circular:
        return np.roll(x, samples, axis=0)
    y = np.zeros_like(x)
    y[samples:] = x[:-samples]
    return y


def echo(x: np.ndarray, d: int, circular: bool, taps=(0.30, 0.20, 0.10, 0.06)) -> np.ndarray:
    """Ping-pong echo. Returns stereo (n, 2): odd taps left, even taps right."""
    out = np.zeros((len(x), 2))
    for k, g in enumerate(taps, start=1):
        out[:, (k - 1) % 2] += g * delay(x, k * d, circular)
    return out


@lru_cache(maxsize=16)
def reverb_ir(sr: int, seconds: float, decay: float, lp_hz: float, predelay: float, seed: int) -> np.ndarray:
    r = np.random.default_rng(seed)
    n = int(seconds * sr)
    t = np.arange(n) / sr
    ir = r.standard_normal(n) * np.exp(-t / decay)
    ir = ss.sosfilt(sos("low", lp_hz, sr), ir)
    ir[: int(predelay * sr)] = 0
    return ir / np.sqrt(np.sum(ir ** 2))


def convolve(x: np.ndarray, ir: np.ndarray, circular: bool) -> np.ndarray:
    """Convolution with an impulse response. Circular mode = linear convolution at a fast FFT length
    with the tail folded back to the start, which equals circular convolution for any loop length
    (an awkward-length direct circular FFT can be 10x slower)."""
    n = len(x)
    y = ss.fftconvolve(x, ir)
    if not circular:
        return y[:n]
    return fold(y, n)


def duck_curve(n: int, kicks: list[tuple[int, float]], sr: int, release: float, circular: bool) -> np.ndarray:
    """0..1 envelope: 1 right after each kick, decaying with `release`. Multiply by depth and
    subtract from 1 to get a sidechain gain."""
    e = np.zeros(n)
    L = int(release * 4 * sr)
    shape = np.exp(-np.arange(L) / sr / release)
    for i, v in kicks:
        idx = i + np.arange(L)
        if circular:
            idx = idx % n
        else:
            idx = idx[idx < n]
        np.maximum.at(e, idx, v * shape[: len(idx)])
    return e


def saturate(x: np.ndarray, drive: float) -> np.ndarray:
    return np.tanh(drive * x) / drive if drive > 0 else x


def soft_clip(x: np.ndarray, drive: float = 1.2) -> np.ndarray:
    return np.tanh(drive * x) / np.tanh(drive)


def trim_tail(x: np.ndarray, sr: int, floor_db: float = -70.0, pad: float = 0.05) -> np.ndarray:
    """Cut a one-shot after its tail has decayed below floor_db (+ a short pad)."""
    mag = np.max(np.abs(x), axis=1) if x.ndim == 2 else np.abs(x)
    thr = 10 ** (floor_db / 20)
    above = np.nonzero(mag > thr)[0]
    if len(above) == 0:
        return x[: int(0.1 * sr)]
    end = min(len(x), above[-1] + int(pad * sr))
    y = x[:end].copy()
    f = min(end, int(0.02 * sr))
    y[-f:] *= np.linspace(1, 0, f)[:, None] if y.ndim == 2 else np.linspace(1, 0, f)
    return y
