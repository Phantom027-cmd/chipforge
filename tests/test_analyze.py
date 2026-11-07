"""The ears: metrics, findings, images, compare, and golden-metric regression for the examples."""
import json
from pathlib import Path

import numpy as np
import pytest

from chipforge import loads
from chipforge.analyze import analyze, compare, semantic_tags
from chipforge.export import write_all
from chipforge.render import render
from tests.conftest import EXAMPLES, MINI, ROOT

GOLDEN = ROOT / "tests" / "golden"
TOL = {"lufs": 0.6, "true_peak": 1.5, "lra": 1.0, "centroid_rel": 0.2, "stereo_correlation": 0.12,
       "stereo_width": 0.1, "band_db": 2.5, "onsets_per_second": 1.5}


def test_analyze_song_file(tmp_path):
    p = tmp_path / "mini.yml"
    p.write_text(MINI)
    rep = analyze(p, out_dir=tmp_path)
    m = rep.metrics
    for k in ("lufs", "true_peak", "lra", "bands_db", "centroid_hz", "stereo_correlation", "seam", "tempo_detected",
              "onset_grid_fraction", "clipped_samples", "dc_offset_db", "silent_regions"):
        assert k in m, k
    assert m["clipped_samples"] == 0 and m["seam"]["step_ratio"] < 1.5
    assert rep.sections and "notes_per_second" in rep.sections[0]
    assert Path(rep.json_path).exists() and Path(rep.png).exists()
    assert not rep.high


def test_analyze_audio_with_sidecar(tmp_path):
    song = loads(MINI)
    r = render(song, stems=True, stems_by="group")
    paths = write_all(r, tmp_path, stems=True)
    rep = analyze(paths["wav"], out_dir=tmp_path, png=False)
    assert rep.metrics["loop"] and rep.metrics["tempo_score"] == 150
    assert [s["label"] for s in rep.sections] == ["A", "A"]
    assert rep.sections[0]["notes"] > 0            # from the MIDI next to the audio
    assert rep.metrics["masking"] == [] or all("margin_db" in x for x in rep.metrics["masking"])


def test_findings_fire_on_bad_audio(tmp_path):
    import soundfile as sf
    sr = 44100
    t = np.arange(sr * 4) / sr
    x = np.stack([np.sign(np.sin(2 * np.pi * 220 * t)) * 1.0 + 0.1] * 2, 1)     # clipped, DC, mono, no highs
    sf.write(str(tmp_path / "bad.wav"), np.clip(x, -1, 1), sr)
    rep = analyze(tmp_path / "bad.wav", png=False)
    codes = {f["code"] for f in rep.findings}
    assert {"clipping", "true_peak", "dc_offset"} <= codes


def test_compare(tmp_path):
    a = tmp_path / "a.yml"; a.write_text(MINI)
    b = tmp_path / "b.yml"; b.write_text(MINI.replace("seed: 3", "seed: 3\nmix: {hf: 0.6}"))
    r = compare(a, b, out_dir=tmp_path)
    rows = {x["metric"]: x for x in r["rows"]}
    assert rows["band_air"]["delta"] < 0 and Path(r["png"]).exists()


def test_semantic_tags_degrade_gracefully(tmp_path):
    out = semantic_tags(str(tmp_path / "none.wav"))
    assert "tags" in out and "note" in out


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_examples_match_golden_metrics(path):
    gp = GOLDEN / f"{path.stem}.json"
    assert gp.exists(), f"no golden file for {path.stem}; run python tests/golden/update.py"
    g = json.loads(gp.read_text(encoding="utf-8"))
    rep = analyze(path, png=False)
    m = rep.metrics
    assert not rep.high, [f["message"] for f in rep.high]
    for k in ("lufs", "true_peak", "lra", "stereo_correlation", "stereo_width", "onsets_per_second"):
        assert abs(m[k] - g[k]) <= TOL[k], f"{k}: {m[k]} vs golden {g[k]}"
    assert abs(m["centroid_hz"] - g["centroid_hz"]) <= TOL["centroid_rel"] * g["centroid_hz"]
    for band, v in g["bands_db"].items():
        assert abs(m["bands_db"][band] - v) <= TOL["band_db"], f"band {band}: {m['bands_db'][band]} vs {v}"
    if g.get("seam"):
        assert m["seam"]["step_ratio"] < 1.5 and m["seam"]["flux_ratio"] < 2.5
