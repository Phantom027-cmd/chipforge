import pytest

from chipforge import SongError, loads
from tests.conftest import MINI


def _err(text: str) -> SongError:
    with pytest.raises(SongError) as e:
        loads(text, file="song.yml")
    return e.value


def test_mini_loads(mini):
    assert mini.title == "Mini" and mini.steps_per_bar == 16 and mini.loop and mini.loop_from is None


def test_unknown_preset_has_suggestion():
    e = _err(MINI.replace("lead.pulse25", "lead.puls25"))
    assert e.path == "channels.lead.preset" and "lead.pulse25" in (e.hint or "") and e.line


def test_missing_required_field_names_it():
    e = _err(MINI.replace("tempo: 150\n", ""))
    assert "tempo" in e.msg and e.file == "song.yml"


def test_unknown_key_with_line_number():
    e = _err(MINI.replace("seed: 3", "seed: 3\ntempoo: 1"))
    assert e.path == "tempoo" and e.line == 8 and "tempo" in (e.hint or "")


def test_mml_too_long_is_reported_with_pattern_path():
    e = _err(MINI.replace("f8 a8 c4 a8 f8 e4", "f8 a8 c4 a8 f8 e4 c4"))
    assert e.path == "patterns.A.lead" and "steps" in e.msg


def test_unknown_generator():
    e = _err(MINI.replace("gen: riff", "gen: rif"))
    assert e.path == "patterns.A.bass.gen" and "riff" in (e.hint or "")


def test_kit_lane_not_in_kit():
    e = _err(MINI.replace('h: "x.x.x.x."', 'q: "x.x.x.x."'))
    assert e.path == "patterns.A.drums.q" and "lanes:" in (e.hint or "")


def test_bad_chord():
    e = _err(MINI.replace('"Am | F"', '"Am | Hm"'))
    assert e.path == "patterns.A.chords"


def test_unknown_pattern_in_arrangement():
    e = _err(MINI.replace("arrangement: [A, A]", "arrangement: [A, B]"))
    assert e.path == "arrangement.1" and "A" in (e.hint or "")


def test_loop_from_label_checked():
    e = _err(MINI.replace("seed: 3", "seed: 3\nloop: {from: Z}"))
    assert e.path == "loop.from"


def test_yaml_syntax_error_has_line():
    e = _err(MINI.replace("tempo: 150", "tempo: 150\n  bad indent: 1"))
    assert e.line is not None


def test_melodic_channel_given_lanes():
    e = _err(MINI.replace('lead: "o5 a8 c8 e8 a8 g4 e4 | f8 a8 c4 a8 f8 e4"', "lead: {k: 'x...'}"))
    assert e.path == "patterns.A.lead" and "MML" in e.msg
