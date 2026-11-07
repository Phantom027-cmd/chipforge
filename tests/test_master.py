"""Loudness meter, limiter, per-cue targets and ambience beds."""
import numpy as np
import pytest

from chipforge import loads, loudness
from chipforge.ambience import BEDS
from chipforge.render import render
from chipforge.schema import CUE_LOUDNESS
from tests.conftest import MINI
from tests.test_render import _seam_ok

SR = 44100


def test_meter_matches_bs1770_sine():
    t = np.arange(SR * 4) / SR
    x = np.stack([0.1 * np.sin(2 * np.pi * 1000 * t)] * 2, 1)        # -20 dBFS per channel
    assert loudness.integrated(x, SR) == pytest.approx(-20.04, abs=0.1)
    assert loudness.true_peak(x, SR) == pytest.approx(-20.0, abs=0.15)


def test_limiter_respects_ceiling():
    import scipy.signal as ss
    rng = np.random.default_rng(1)
    x = ss.sosfilt(ss.butter(4, 6000, fs=SR, output="sos"), rng.standard_normal((SR * 3, 2)) * 0.5, axis=0)
    y = loudness.limiter(x, SR, -1.0)
    assert loudness.true_peak(y, SR) <= -0.8
    assert np.abs(y).max() < np.abs(x).max()


def test_normalize_hits_target():
    rng = np.random.default_rng(2)
    x = rng.standard_normal((SR * 5, 2)) * 0.02
    y, info = loudness.normalize(x, SR, -16.0, -1.0)
    assert loudness.integrated(y, SR) == pytest.approx(-16.0, abs=0.3)
    assert info["true_peak"] <= -0.9


def test_render_lands_on_cue_target(mini):
    r = render(mini, stems=False)
    assert r.stats["target_lufs"] == CUE_LOUDNESS["overworld"]
    assert loudness.integrated(r.mix, mini.sr) == pytest.approx(CUE_LOUDNESS["overworld"], abs=0.5)
    assert loudness.true_peak(r.mix, mini.sr) <= -0.9


def test_explicit_loudness_overrides_cue():
    song = loads(MINI.replace("seed: 3", "seed: 3\nloudness: -20"))
    r = render(song, stems=False)
    assert loudness.integrated(r.mix, song.sr) == pytest.approx(-20, abs=0.5)


def test_hf_shelf_reduces_highs():
    bright = loads(MINI.replace("seed: 3", "seed: 3\nmix: {hf: 1.0, normalize: false}"))
    dull = loads(MINI.replace("seed: 3", "seed: 3\nmix: {hf: 0.7, normalize: false}"))
    a, b = render(bright, stems=False).mix[:, 0], render(dull, stems=False).mix[:, 0]
    fa, fb = np.abs(np.fft.rfft(a)), np.abs(np.fft.rfft(b))
    f = np.fft.rfftfreq(len(a), 1 / SR)
    hi = f > 6000
    assert fb[hi].sum() < 0.85 * fa[hi].sum()


@pytest.mark.parametrize("bed", BEDS)
def test_ambience_bed_is_seamless(bed):
    song = loads(MINI.replace("seed: 3", f"seed: 3\nambience: {{bed: {bed}, level: -12}}"))
    r = render(song, stems=True)
    amb = r.stems["ambience"]
    assert np.isfinite(amb).all() and np.abs(amb).max() > 0.001
    ok, ratio = _seam_ok(amb, 0)
    assert ok, f"{bed}: seam step {ratio:.1f}x"
