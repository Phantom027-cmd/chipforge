"""Regenerate the golden metrics for every example:  python tests/golden/update.py"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from chipforge.analyze import analyze  # noqa: E402

KEEP = ["lufs", "true_peak", "lra", "centroid_hz", "stereo_correlation", "stereo_width", "bands_db", "seam",
        "onsets_per_second", "tempo_detected"]
for p in sorted((ROOT / "examples").glob("*.yml")):
    rep = analyze(p, png=False)
    g = {k: rep.metrics[k] for k in KEEP if k in rep.metrics}
    g["high_findings"] = [f["code"] for f in rep.high]
    g["sections"] = [{"label": r["label"], "lufs": r["lufs"]} for r in rep.sections]
    (ROOT / "tests" / "golden" / f"{p.stem}.json").write_text(json.dumps(g, indent=1), encoding="utf-8")
    print("updated", p.stem, g["lufs"], g["bands_db"])
