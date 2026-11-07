"""Render every example a few times and report the best wall time (what README quotes)."""
import platform
import sys
import time
from pathlib import Path

import numpy as np

from chipforge import load
from chipforge.render import render

runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
print(f"{platform.machine()} {platform.system()} python {platform.python_version()} numpy {np.__version__}")
for p in sorted(Path("examples").glob("*.yml")):
    song = load(p)
    best = min((render(song).seconds for _ in range(runs)))
    t0 = time.perf_counter(); r = render(song, stems=False); no_stems = time.perf_counter() - t0
    secs = len(r.mix) / r.sr
    print(f"{p.stem:<24} {best:5.2f} s  (no stems {no_stems:4.2f} s)  for {secs:5.1f} s audio  "
          f"-> {secs / best:5.1f}x realtime, {r.stats['notes']} events")
