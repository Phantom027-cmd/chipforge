import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EXAMPLES = sorted((ROOT / "examples").glob("*.yml"))

MINI = """
chipforge: 1
title: Mini
cue: overworld
tempo: 150
key: Am
seed: 3
channels:
  lead: {preset: lead.pulse25}
  bass: {preset: bass.tri}
  drums: {preset: kit.nes}
patterns:
  A:
    bars: 2
    chords: "Am | F"
    lead: "o5 a8 c8 e8 a8 g4 e4 | f8 a8 c4 a8 f8 e4"
    bass: {gen: riff, steps: "0 . 0 . 12 . 0 .", low: a1}
    drums: {k: "x...x...", s: "....x...", h: "x.x.x.x."}
arrangement: [A, A]
"""


@pytest.fixture
def mini():
    from chipforge import loads
    return loads(MINI)


@pytest.fixture(scope="session")
def example_renders():
    """Render every example once per test session."""
    from chipforge import load
    from chipforge.render import render
    return {p.stem: render(load(p)) for p in EXAMPLES}
