"""Every preset renders: finite, audible, and (for kits) every piece triggers."""
import numpy as np
import pytest

from chipforge import loads, presets
from chipforge.render import render

MELODIC = """
chipforge: 1
title: T
cue: custom
tempo: 120
key: C
channels: {x: {preset: PRESET}}
patterns:
  A: {bars: 1, chords: "C", x: "o4 c4 g4 >c2"}
arrangement: [A]
"""
KIT = """
chipforge: 1
title: T
cue: custom
tempo: 120
key: C
channels: {x: {preset: PRESET}}
patterns:
  A: {bars: 2, x: {events: EVENTS}}
arrangement: [A]
"""


@pytest.mark.parametrize("name", presets.names())
def test_preset_renders(name):
    p = presets.get(name)
    if p["kind"] == "kit":
        evs = [{"at": i * 2, "hit": pc} for i, pc in enumerate(p["pieces"])]
        song = loads(KIT.replace("PRESET", name).replace("EVENTS", str(evs)))
    else:
        song = loads(MELODIC.replace("PRESET", name))
    r = render(song, stems=False)
    assert np.isfinite(r.mix).all()
    assert np.abs(r.mix).max() > 0.05, f"{name} is silent"
    if p["kind"] == "kit":
        for i, pc in enumerate(p["pieces"]):
            seg = r.mix[int(i * 2 * song.step_s * song.sr): int((i * 2 + 1.5) * song.step_s * song.sr)]
            assert np.abs(seg).max() > 0.01, f"{name}.{pc} is silent"


def test_preset_library_is_consistent():
    for n in presets.names():
        assert "doc" in presets.get(n), f"{n} has no doc string"
