"""Outputs: loop metadata round-trips, stems modes, intro/loop split, MIDI markers, sidecar."""
import json

import mido
import numpy as np
import pytest
import soundfile as sf

from chipforge import loads
from chipforge.export import read_ogg_loop, read_wav_loop, write_all
from chipforge.render import render
from tests.conftest import MINI


@pytest.fixture(scope="module")
def intro_song():
    return loads(MINI.replace("seed: 3", "seed: 3\nloop: {from: body}")
                 .replace("arrangement: [A, A]", "arrangement: [A, {use: A, as: body}]"))


def test_wav_and_ogg_loop_points_round_trip(tmp_path, intro_song):
    r = render(intro_song, stems=False)
    paths = write_all(r, tmp_path, formats=("wav", "ogg"), stems=False, midi=False)
    loop = (r.loop_start, r.loop_end)
    assert read_wav_loop(paths["wav"]) == loop
    assert read_ogg_loop(paths["ogg"]) == loop
    assert sf.info(paths["wav"]).frames == len(r.mix)
    assert sf.info(paths["ogg"]).frames == len(r.mix)


def test_intro_and_loop_files(tmp_path, intro_song):
    r = render(intro_song, stems=False)
    paths = write_all(r, tmp_path, stems=False, midi=False)
    assert sf.info(paths["intro"]).frames == r.loop_start
    assert sf.info(paths["loop"]).frames == r.loop_end - r.loop_start
    assert read_wav_loop(paths["loop"]) == (0, r.loop_end - r.loop_start)
    pv = sf.info(paths["preview"]).frames
    assert pv == len(r.mix) + (r.loop_end - r.loop_start)


def test_24bit_and_mp3(tmp_path, mini):
    r = render(mini, stems=False)
    paths = write_all(r, tmp_path, formats=("wav", "mp3"), stems=False, midi=False, bits=24)
    assert sf.info(paths["wav"]).subtype == "PCM_24"
    assert abs(sf.info(paths["mp3"]).duration - len(r.mix) / r.sr) < 0.1


@pytest.mark.parametrize("by,expected", [("layer", {"layer1"}), ("group", {"lead", "bass", "drums"}),
                                         ("channel", {"lead", "bass", "drums"})])
def test_stem_modes(tmp_path, mini, by, expected):
    r = render(mini, stems=True, stems_by=by)
    assert set(r.stems) == expected
    total = sum(r.stems.values())
    # stems sum back to the mix exactly (nonlinear stages are shared as gain curves)
    assert np.abs(total - r.mix).max() < 1e-3


def test_midi_markers_and_tracks(tmp_path, intro_song):
    r = render(intro_song, stems=False)
    paths = write_all(r, tmp_path, stems=False, preview=False)
    m = mido.MidiFile(paths["midi"])
    markers = [msg.text for msg in m.tracks[0] if msg.type == "marker"]
    assert markers == ["A", "body", "loopStart", "loopEnd"] or markers == ["A", "loopStart", "body", "loopEnd"]
    names = [msg.name for t in m.tracks[1:] for msg in t if msg.type == "track_name"]
    assert names == ["lead", "bass", "drums"]
    assert any(msg.type == "note_on" and msg.channel == 9 for msg in m.tracks[3])


def test_sidecar_fields(tmp_path, intro_song):
    r = render(intro_song, stems=True)
    paths = write_all(r, tmp_path, stems=True, midi=False)
    j = json.loads(open(paths["json"], encoding="utf-8").read())
    assert j["loop"]["start_samples"] == r.loop_start and j["loop"]["end_samples"] == len(r.mix)
    assert j["loop"]["start_seconds"] == pytest.approx(r.loop_start / r.sr)
    assert [s["label"] for s in j["sections"]] == ["A", "body"]
    assert j["layers"][0]["channels"] == ["lead", "bass", "drums"]
    assert "stem_layer1" in j["stems"] and j["loudness"]["target_lufs"] == -14
    assert j["bars"] == 4 and j["bar_seconds"] == pytest.approx(1.6)


def test_one_shot_has_no_loop_files(tmp_path):
    song = loads(MINI.replace("seed: 3", "seed: 3\nloop: false"))
    r = render(song, stems=False)
    paths = write_all(r, tmp_path, formats=("wav", "ogg"), stems=False, midi=False)
    assert "preview" not in paths and "loop" not in paths
    assert read_wav_loop(paths["wav"]) is None and read_ogg_loop(paths["ogg"]) is None
