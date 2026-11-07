import pytest

from chipforge.mml import MMLError, parse_lane, parse_mml, mml_length


def test_lengths_and_octaves():
    n = parse_mml("o4 c4 d8 e16 f2 g1 a4. b8&b8")
    assert [x.length for x in n] == [4, 2, 1, 8, 16, 6, 4]
    assert n[0].midi == 60 and n[-1].midi == 71


def test_default_length_rest_and_octave_shift():
    n = parse_mml("l8 c > c < c r4 c")
    assert [x.midi for x in n] == [60, 72, 60, None, 60]
    assert n[3].length == 4 and mml_length(n) == 12


def test_accidentals():
    n = parse_mml("c+ c# d- o5 b")
    assert [x.midi for x in n] == [61, 61, 61, 83]


def test_repeat_block():
    n = parse_mml("[c8 d8]3 e4")
    assert len(n) == 7 and n[-1].start == 12


def test_slide_volume_gate_macros():
    n = parse_mml("v8 q4 c4 ~d4 @d(0.25) @vib(0.3,6,0.1) e4")
    assert n[1].slide and not n[0].slide
    assert abs(n[0].vel - 8 / 15) < 1e-9 and n[0].gate == 0.5
    assert n[2].macros == {"d": [0.25], "vib": [0.3, 6, 0.1]}
    assert n[0].macros == {}


def test_bar_lines_ignored():
    assert mml_length(parse_mml("c4 d4 | e4 f4 | g1")) == 32


@pytest.mark.parametrize("bad", ["c4 ]", "[c4", "~c4", "o9 c", "v16 c", "x", "q0 c"])
def test_errors(bad):
    with pytest.raises(MMLError):
        parse_mml(bad)


def test_lane():
    h = parse_lane("x.o.|g..9")
    assert [(x.start, x.vel) for x in h] == [(0, 1.0), (2, 0.55), (4, 0.3), (7, 0.9)]
    with pytest.raises(ValueError):
        parse_lane("x.?.")
