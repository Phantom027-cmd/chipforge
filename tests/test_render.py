import numpy as np
import pytest

from chipforge import loads
from chipforge.render import render
from chipforge.score import build
from tests.conftest import MINI


def _seam_ok(x: np.ndarray, loop_start: int) -> tuple[bool, float]:
    """A seam click would be a sample step far outside the file's normal step distribution."""
    steps = np.abs(np.diff(x, axis=0)).max(axis=1)
    wrap = np.abs(x[loop_start] - x[-1]).max()
    thr = np.quantile(steps, 0.9999)
    return wrap <= thr, float(wrap / (thr or 1.0))


def test_timeline(mini):
    tl = build(mini)
    assert tl.length == pytest.approx(2 * 2 * 60 / 150 * 4)
    assert tl.loop_start == 0.0 and len(tl.sections) == 2
    assert all(e.ch in mini.channels for e in tl.events)


def test_render_shape_and_health(mini):
    r = render(mini)
    assert r.mix.shape == (int(round(r.timeline.length * mini.sr)), 2)
    assert np.isfinite(r.mix).all() and np.abs(r.mix).max() <= 0.71
    assert abs(r.mix.mean()) < 3e-3                     # no DC offset (-50 dBFS)
    assert set(r.stems) == {"layer1"}


def test_seam_mini(mini):
    r = render(mini)
    ok, ratio = _seam_ok(r.mix, 0)
    assert ok, f"seam step is {ratio:.1f}x the file's largest normal step"


def test_determinism(mini):
    a, b = render(mini).mix, render(mini).mix
    assert np.array_equal(a, b)


def test_seed_changes_noise_only_where_it_should(mini):
    r1 = render(mini)
    song2 = loads(MINI.replace("seed: 3", "seed: 4"))
    r2 = render(song2)
    # no reverb/noise-seeded element in MINI except nothing: same seed-independent content
    assert np.allclose(r1.mix, r2.mix)


def test_one_shot_trims_tail():
    song = loads(MINI.replace("seed: 3", "seed: 3\nloop: false").replace("arrangement: [A, A]", "arrangement: [A]"))
    r = render(song)
    assert r.loop_start is None
    assert len(r.mix) > r.timeline.length * song.sr          # natural tail kept
    assert len(r.mix) < (r.timeline.length + 4) * song.sr    # but trimmed


def test_intro_then_loop():
    song = loads(MINI.replace("seed: 3", "seed: 3\nloop: {from: body}")
                 .replace("arrangement: [A, A]", "arrangement: [A, {use: A, as: body}]"))
    r = render(song)
    assert r.loop_start == int(round(r.timeline.sections[1].start * song.sr))
    assert r.loop_end == len(r.mix)


def test_examples_render_cleanly(example_renders):
    assert example_renders, "no examples found"
    for name, r in example_renders.items():
        assert np.isfinite(r.mix).all(), name
        assert np.abs(r.mix).max() <= 0.71, name
        assert abs(r.mix.mean()) < 2e-3, name
        if r.loop_start is not None:
            ok, ratio = _seam_ok(r.mix, r.loop_start)
            assert ok, f"{name}: seam step is {ratio:.1f}x the largest normal step"


def test_examples_are_deterministic(example_renders):
    from chipforge import load
    from tests.conftest import EXAMPLES
    p = EXAMPLES[0]
    again = render(load(p))
    assert np.array_equal(again.mix, example_renders[p.stem].mix)


def test_examples_render_fast(example_renders):
    for name, r in example_renders.items():
        assert r.seconds < 8, f"{name} took {r.seconds:.1f} s (target < 3 s on a laptop)"
