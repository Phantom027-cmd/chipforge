"""Chip profiles, authentic-mode rules and oscillator switching."""
import numpy as np
import pytest

from chipforge import SongError, loads
from chipforge.render import render
from tests.conftest import MINI


def test_authentic_nes_rejects_sine_and_polyphony():
    with pytest.raises(SongError) as e:
        loads(MINI.replace("seed: 3", "seed: 3\nmode: authentic").replace("bass.tri", "bass.sub"))
    assert "sine" in str(e.value) and "mode: enhanced" in str(e.value)


def test_authentic_nes_channel_limit():
    text = MINI.replace("seed: 3", "seed: 3\nmode: authentic").replace(
        "  bass: {preset: bass.tri}", "  bass: {preset: bass.tri}\n  l2: {preset: lead.pulse50}\n  l3: {preset: lead.pulse12}")
    with pytest.raises(SongError) as e:
        loads(text)
    assert "2 pulse channel" in str(e.value)


def test_authentic_nes_renders_mono():
    song = loads(MINI.replace("seed: 3", "seed: 3\nmode: authentic"))
    r = render(song, stems=False)
    assert np.array_equal(r.mix[:, 0], r.mix[:, 1])


def test_gameboy_authentic_hard_pan():
    text = MINI.replace("seed: 3", "seed: 3\nmode: authentic\nchip: gameboy").replace(
        "lead: {preset: lead.pulse25}", "lead: {preset: lead.pulse25, pan: 0.6}").replace("kit.nes", "kit.gameboy")
    r = render(loads(text), stems=False)
    assert not np.array_equal(r.mix[:, 0], r.mix[:, 1])


def test_clean_osc_has_less_aliasing():
    base = MINI.replace("arrangement: [A, A]", "arrangement: [A]").replace("  bass: {preset: bass.tri}\n  drums: {preset: kit.nes}\n", "")
    base = base.replace('    bass: {gen: riff, steps: "0 . 0 . 12 . 0 .", low: a1}\n    drums: {k: "x...x...", s: "....x...", h: "x.x.x.x."}\n', "")
    base = base.replace('lead: "o5 a8 c8 e8 a8 g4 e4 | f8 a8 c4 a8 f8 e4"', 'lead: "o7 a1 | a1"')
    naive = render(loads(base), stems=False).mix[:, 0]
    clean = render(loads(base.replace("lead: {preset: lead.pulse25}", "lead: {preset: lead.pulse25, osc: clean}")), stems=False).mix[:, 0]

    def hf_ratio(x):
        X = np.abs(np.fft.rfft(x)) ** 2
        f = np.fft.rfftfreq(len(x), 1 / 44100)
        # energy between harmonics of A6 (1760 Hz) in the 2-8 kHz band is aliasing / noise
        harm = np.zeros_like(f, dtype=bool)
        for k in range(1, 6):
            harm |= np.abs(f - 1760 * k) < 40
        band = (f > 2000) & (f < 8000)
        return X[band & ~harm].sum() / X[band & harm].sum()
    assert hf_ratio(clean) < hf_ratio(naive)


def test_sid_and_fm_profiles_render():
    for chip, preset in [("sid", "lead.sid_saw"), ("fm", "lead.fm_brass"), ("gameboy", "lead.gb_organ"), ("gm", "lead.gm_square")]:
        song = loads(MINI.replace("seed: 3", f"seed: 3\nchip: {chip}").replace("lead.pulse25", preset))
        r = render(song, stems=False)
        assert np.isfinite(r.mix).all() and np.abs(r.mix).max() > 0.1
