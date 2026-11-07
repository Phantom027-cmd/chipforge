"""Loudness metering (ITU-R BS.1770-4 / EBU R128) and a vectorized look-ahead true-peak limiter.

No external dependency: K-weighting, gated integrated loudness, short-term / momentary loudness,
loudness range (EBU Tech 3342) and 4x-oversampled true peak are implemented here, so the core
engine and the analysis module share one meter.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import scipy.signal as ss


@lru_cache(maxsize=8)
def _k_weight(sr: int):
    """Pre-filter (high shelf) + RLB high-pass, as biquads. Coefficients designed for 48 kHz in the
    spec; here they are re-derived for any sample rate using the spec's analogue prototypes."""
    # stage 1: high shelf, +4 dB above ~1.5 kHz
    f0, G, Q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    K = np.tan(np.pi * f0 / sr)
    Vh = 10 ** (G / 20)
    Vb = Vh ** 0.4996667741545416
    a0 = 1 + K / Q + K * K
    b = [(Vh + Vb * K / Q + K * K) / a0, 2 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0]
    a = [1.0, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0]
    # stage 2: RLB high-pass at ~38 Hz
    f0, Q = 38.13547087602444, 0.5003270373238773
    K = np.tan(np.pi * f0 / sr)
    a0 = 1 + K / Q + K * K
    b2 = [1 / a0, -2 / a0, 1 / a0]
    a2 = [1.0, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0]
    return np.array([b + a, b2 + a2])


def k_weighted(x: np.ndarray, sr: int) -> np.ndarray:
    return ss.sosfilt(_k_weight(sr), x, axis=0)


def _block_power(x: np.ndarray, sr: int, block: float, hop: float) -> np.ndarray:
    """Mean square per block (summed over channels, as BS.1770 does for L/R)."""
    y = k_weighted(np.atleast_2d(x.T).T if x.ndim == 1 else x, sr)
    n, step = int(block * sr), int(hop * sr)
    if len(y) < n:
        y = np.concatenate([y, np.zeros((n - len(y),) + y.shape[1:])])
    e = y ** 2
    cs = np.cumsum(np.concatenate([np.zeros((1,) + e.shape[1:]), e]), axis=0)
    starts = np.arange(0, len(y) - n + 1, step)
    pw = (cs[starts + n] - cs[starts]) / n
    return pw.sum(axis=1) if pw.ndim == 2 else pw


def _lk(power) -> np.ndarray:
    return -0.691 + 10 * np.log10(np.maximum(power, 1e-20))


def integrated(x: np.ndarray, sr: int) -> float:
    """Gated integrated loudness in LUFS (absolute gate -70, relative gate -10 LU)."""
    pw = _block_power(x, sr, 0.4, 0.1)
    lk = _lk(pw)
    keep = lk > -70
    if not keep.any():
        return -np.inf
    rel = _lk(pw[keep].mean()) - 10
    keep &= lk > rel
    if not keep.any():
        return -np.inf
    return float(_lk(pw[keep].mean()))


def short_term(x: np.ndarray, sr: int) -> np.ndarray:
    """Short-term loudness (3 s window, 1 s hop... we use 0.1 s hop for resolution)."""
    return _lk(_block_power(x, sr, 3.0, 0.1))


def momentary(x: np.ndarray, sr: int) -> np.ndarray:
    return _lk(_block_power(x, sr, 0.4, 0.1))


def loudness_range(x: np.ndarray, sr: int) -> float:
    """EBU Tech 3342 LRA: 10th-95th percentile spread of gated short-term loudness."""
    st = short_term(x, sr)
    st = st[st > -70]
    if len(st) < 2:
        return 0.0
    rel = _lk(np.mean(10 ** ((st + 0.691) / 10))) - 20
    st = st[st > rel]
    if len(st) < 2:
        return 0.0
    return float(np.percentile(st, 95) - np.percentile(st, 10))


@lru_cache(maxsize=1)
def _os_fir() -> np.ndarray:
    return ss.firwin(49, 0.9 / 4) * 4          # 4x oversampling interpolation filter (12 taps per phase)


def true_peak(x: np.ndarray, sr: int) -> float:
    """True peak in dBTP via 4x oversampling (short polyphase FIR; within ~0.1 dB of the long one)."""
    h = _os_fir()
    chans = [x] if x.ndim == 1 else [np.ascontiguousarray(x[:, c]) for c in range(x.shape[1])]
    peak = max(float(np.max(np.abs(ss.upfirdn(h, c, 4, 1)))) for c in chans)
    return float(20 * np.log10(peak + 1e-12))


def limiter(x: np.ndarray, sr: int, ceiling_db: float = -1.0, lookahead: float = 0.005,
            release: float = 0.08, circular: bool = False, return_gain: bool = False):
    """Look-ahead brick-wall limiter, fully vectorized. Gain = running minimum of the required
    gain over the look-ahead window (attack), then an exponential-in-dB release implemented as a
    cumulative minimum of a sloped line. In circular mode the loop wraps cleanly."""
    ceiling = 10 ** (ceiling_db / 20) * 0.95          # ~0.45 dB headroom for inter-sample peaks
    mag = np.max(np.abs(x), axis=1) if x.ndim == 2 else np.abs(x)
    la = max(1, int(lookahead * sr))
    pad = 4 * la + int(release * 4 * sr)
    if circular:
        mag_p = np.concatenate([mag[-pad:], mag, mag[:pad]])
    else:
        mag_p = np.concatenate([np.zeros(pad), mag, np.zeros(pad)])
    g_db = 20 * np.log10(np.minimum(1.0, ceiling / np.maximum(mag_p, 1e-12)))
    from scipy.ndimage import minimum_filter1d
    need = g_db
    g_db = minimum_filter1d(g_db, size=2 * la, mode="nearest")        # attack / look-ahead
    slope = 20 / (release * sr)                                        # dB per sample recovery
    idx = np.arange(len(g_db))
    g_db = np.minimum.accumulate(g_db - slope * idx) + slope * idx     # release
    g_db = np.minimum(g_db, 0.0)
    # smooth the attack edge a little so gain changes are not stepped, never above what is needed
    from scipy.ndimage import uniform_filter1d
    g = np.minimum(uniform_filter1d(10 ** (g_db / 20), size=la, mode="nearest"), 10 ** (need / 20))
    g = g[pad:pad + len(mag)]
    y = x * (g[:, None] if x.ndim == 2 else g)
    return (y, g) if return_gain else y


def normalize(x: np.ndarray, sr: int, target_lufs: float, ceiling_db: float = -1.0, circular: bool = False,
              max_gain_db: float = 24.0) -> tuple[np.ndarray, dict]:
    """Gain to the target integrated loudness, then limit to the true-peak ceiling. Returns
    (audio, {"gain_db", "lufs_before", "lufs_after", "true_peak", "limited_db"})."""
    before = integrated(x, sr)
    gain_db = float(np.clip(target_lufs - before, -max_gain_db, max_gain_db)) if np.isfinite(before) else 0.0
    y = x * 10 ** (gain_db / 20)
    peak_before = float(20 * np.log10(np.max(np.abs(y)) + 1e-12))
    y, g = limiter(y, sr, ceiling_db, circular=circular, return_gain=True)
    tp = true_peak(y, sr)
    if tp > ceiling_db + 0.05:                                  # belt and braces
        trim = 10 ** ((ceiling_db - tp) / 20)
        y, g = y * trim, g * trim
        tp = ceiling_db
    limited = max(0.0, peak_before - ceiling_db)
    after = integrated(y, sr) if limited > 0.5 else before + gain_db     # re-measure only if the limiter worked
    return y, {"gain_db": round(gain_db, 2), "lufs_before": round(before, 2), "lufs_after": round(after, 2),
               "true_peak": round(tp, 2), "limited_db": round(limited, 2), "gain_curve": g}
