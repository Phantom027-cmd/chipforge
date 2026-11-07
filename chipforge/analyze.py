"""The "ears": turn a render into numbers, plain-language findings and one composite image that a
model without audio input can read.

    analyze(song_or_audio) -> Report      (metrics dict, findings list, optional PNG)
    compare(a, b)                          (side-by-side metrics + image)

Works from a song file (renders it, so stems and the score are available) or from an audio file
(uses the JSON sidecar and MIDI next to it when present).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import scipy.signal as ss
import soundfile as sf

from . import loudness

BANDS = [("sub", 20, 60), ("bass", 60, 250), ("low_mid", 250, 500), ("mid", 500, 2000),
         ("presence", 2000, 6000), ("air", 6000, 20000)]

# Healthy band balance (dB relative to the total) learned from the tuned reference tracks;
# findings fire outside [lo, hi].
BAND_RANGES = {"sub": (-14, -3), "bass": (-9, -1), "low_mid": (-14, -3), "mid": (-14, -4),
               "presence": (-26, -9), "air": (-40, -12)}

THRESHOLDS = {
    "seam_ratio": 1.5,          # wrap step vs the file's largest normal step
    "seam_flux": 1.5,           # spectral flux across the wrap vs the file's 95th-percentile flux
    "clip_samples": 10,
    "dc_db": -50,
    "lufs_tolerance": 1.0,
    "true_peak": -0.8,
    "stereo_corr_min": 0.2,     # below: phasey / mono-incompatible
    "contrast_min_lu": 1.5,     # breakdown vs main section
    "masking_db": 3.0,          # accompaniment above lead in 1-4 kHz
    "tempo_tolerance": 2.0,     # BPM
    "onset_grid": 0.6,          # fraction of onsets within 20 ms of the 16th grid
    "density_max": 20.0,        # melodic notes per second per section (drum hits excluded)
}


@dataclass
class Report:
    source: str
    metrics: dict
    findings: list[dict]
    sections: list[dict]
    png: str | None = None
    json_path: str | None = None
    audio_path: str | None = None

    @property
    def high(self) -> list[dict]:
        return [f for f in self.findings if f["severity"] == "high"]

    def summary(self, max_findings: int = 8) -> str:
        m = self.metrics
        lines = [f"{m['lufs']:.1f} LUFS (target {m.get('target_lufs', '?')}), true peak {m['true_peak']:.1f} dBTP, "
                 f"LRA {m['lra']:.1f} LU, stereo corr {m['stereo_correlation']:.2f}, centroid {m['centroid_hz']:.0f} Hz",
                 "bands: " + " ".join(f"{k} {v:+.0f}" for k, v in m["bands_db"].items())]
        if m.get("seam"):
            lines.append(f"seam: step {m['seam']['step_ratio']:.2f}x, flux {m['seam']['flux_ratio']:.2f}x")
        for f in self.findings[:max_findings]:
            lines.append(f"[{f['severity']}] {f['message']}")
        if len(self.findings) > max_findings:
            lines.append(f"... {len(self.findings) - max_findings} more findings in the JSON report")
        return "\n".join(lines)


# ------------------------------------------------------------------ loading
def _load_audio(path: Path):
    x, sr = sf.read(str(path), always_2d=True)
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    return x[:, :2], sr


def _sidecar_for(path: Path) -> dict | None:
    for cand in (path.with_suffix(".json"), path.parent / (path.stem.replace("_preview", "") + ".json")):
        if cand.exists():
            try:
                return json.loads(cand.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
    return None


# ------------------------------------------------------------------ metrics
def band_balance(x: np.ndarray, sr: int) -> dict[str, float]:
    m = x.mean(axis=1)
    X = np.abs(np.fft.rfft(m * np.hanning(len(m)))) ** 2
    f = np.fft.rfftfreq(len(m), 1 / sr)
    total = X[(f >= 20) & (f < 20000)].sum() + 1e-20
    return {name: round(float(10 * np.log10(X[(f >= lo) & (f < hi)].sum() / total + 1e-20)), 1) for name, lo, hi in BANDS}


def spectral_centroid(x: np.ndarray, sr: int) -> float:
    m = x.mean(axis=1)
    f, t, Z = ss.spectrogram(m, sr, nperseg=4096, noverlap=2048)
    mag = Z.sum(axis=1)
    return float((f * mag).sum() / (mag.sum() + 1e-20))


def stereo_metrics(x: np.ndarray) -> dict:
    L, R = x[:, 0], x[:, 1]
    corr = float(np.corrcoef(L, R)[0, 1]) if L.std() > 0 and R.std() > 0 else 1.0
    mid, side = (L + R) / 2, (L - R) / 2
    width = float(np.sqrt(np.mean(side ** 2)) / (np.sqrt(np.mean(mid ** 2)) + 1e-12))
    return {"stereo_correlation": round(corr, 3), "stereo_width": round(width, 3)}


def health(x: np.ndarray, sr: int) -> dict:
    mag = np.abs(x).max(axis=1)
    clipped = int((mag >= 0.999).sum())
    dc = float(np.abs(x.mean(axis=0)).max())
    dc_db = float(20 * np.log10(dc + 1e-12))
    env = ss.convolve(mag, np.ones(int(0.05 * sr)) / int(0.05 * sr), mode="same")
    quiet = env < 10 ** (-60 / 20)
    runs, start = [], None
    for i, q in enumerate(quiet):
        if q and start is None:
            start = i
        elif not q and start is not None:
            if i - start > 0.5 * sr:
                runs.append((round(start / sr, 2), round(i / sr, 2)))
            start = None
    if start is not None and len(quiet) - start > 0.5 * sr:
        runs.append((round(start / sr, 2), round(len(quiet) / sr, 2)))
    return {"clipped_samples": clipped, "dc_offset_db": round(dc_db, 1), "silent_regions": runs,
            "peak_dbfs": round(float(20 * np.log10(mag.max() + 1e-12)), 2)}


def seam_check(x: np.ndarray, sr: int, loop_start: int, boundaries: list[float] = ()) -> dict:
    """Sample-step discontinuity and spectral flux across the wrap. Both are relative: the step to
    the file's largest normal steps, the flux to the larger of the file's big transients and its own
    section changes (a loop that jumps no more than the song's own section boundaries is fine)."""
    steps = np.abs(np.diff(x, axis=0)).max(axis=1)
    wrap = float(np.abs(x[loop_start] - x[-1]).max())
    thr = float(np.quantile(steps, 0.9999)) or 1e-9
    n = 2048
    win = np.hanning(n)
    m = x.mean(axis=1)

    def flux_at(i_prev_end: int, i_next: int) -> float:
        a = np.abs(np.fft.rfft(m[i_prev_end - n:i_prev_end] * win))
        b = np.abs(np.fft.rfft(m[i_next:i_next + n] * win))
        return float(np.sqrt(((b - a) ** 2).sum()))

    flux_wrap = flux_at(len(m), loop_start)
    frames = np.lib.stride_tricks.sliding_window_view(m, n)[::n]
    spec = np.abs(np.fft.rfft(frames * win, axis=1))
    flux = np.sqrt(((np.diff(spec, axis=0)) ** 2).sum(axis=1))
    ref = float(np.quantile(flux, 0.95))
    for bsec in boundaries:
        i = int(round(bsec * sr))
        if n < i < len(m) - n:
            ref = max(ref, flux_at(i, i))
    ref = ref or 1e-9
    return {"step": round(wrap, 5), "step_ratio": round(wrap / thr, 3), "flux_ratio": round(flux_wrap / ref, 3)}


def onsets(x: np.ndarray, sr: int, hop: int = 512) -> tuple[np.ndarray, np.ndarray]:
    """Onset strength envelope (positive spectral flux) and detected onset times."""
    m = x.mean(axis=1)
    f, t, Z = ss.spectrogram(m, sr, nperseg=1024, noverlap=1024 - hop, mode="magnitude")
    logZ = np.log1p(100 * Z)
    flux = np.maximum(np.diff(logZ, axis=1), 0).sum(axis=0)
    flux = flux - ss.medfilt(flux, 31)
    flux = np.maximum(flux, 0)
    thr = flux.mean() + 1.5 * flux.std()
    peaks, _ = ss.find_peaks(flux, height=thr, distance=int(0.05 * sr / hop))
    return flux, t[1:][peaks]


def tempo_estimate(flux: np.ndarray, sr: int, hop: int = 512, lo: float = 60, hi: float = 240) -> float:
    fps = sr / hop
    ac = np.correlate(flux - flux.mean(), flux - flux.mean(), mode="full")[len(flux) - 1:]
    lags = np.arange(len(ac)) / fps
    ok = (lags > 60 / hi) & (lags < 60 / lo)
    if not ok.any():
        return 0.0
    cand = np.where(ok)[0]
    best = cand[np.argmax(ac[cand])]
    return float(60 / lags[best])


def grid_alignment(times: np.ndarray, tempo: float, step_div: int = 4, tol: float = 0.02) -> float:
    if len(times) == 0 or tempo <= 0:
        return 0.0
    step = 60 / tempo / step_div
    off = np.abs(times / step - np.round(times / step)) * step
    return float((off < tol).mean())


def _section_slices(sections: list[dict], sr: int, n: int):
    out = []
    for s in sections:
        a, b = int(round(s["start"] * sr)), min(n, int(round(s["end"] * sr)))
        if b > a + sr // 10:
            out.append((s, slice(a, b)))
    return out


def masking(stems: dict[str, np.ndarray], sr: int, sections: list[dict], lo=1000, hi=4000) -> list[dict]:
    """Lead vs everything else in the 1-4 kHz band, per section, where the lead is active."""
    lead = stems.get("lead")
    if lead is None:
        return []
    others = sum(v for k, v in stems.items() if k not in ("lead", "ambience", "music"))
    if not isinstance(others, np.ndarray):
        return []
    sos = ss.butter(4, [lo, hi], "band", fs=sr, output="sos")
    lb, ob = ss.sosfilt(sos, lead.mean(axis=1)), ss.sosfilt(sos, others.mean(axis=1))
    out = []
    for s, sl in _section_slices(sections, sr, len(lb)):
        l_seg, o_seg = lb[sl], ob[sl]
        if 20 * np.log10(np.sqrt(np.mean(l_seg ** 2)) + 1e-12) < -45:      # lead not really playing here
            continue
        # measure only where the lead is sounding
        env = ss.convolve(np.abs(l_seg), np.ones(int(0.05 * sr)) / int(0.05 * sr), mode="same")
        act = env > 0.2 * env.max()
        if act.sum() < sr // 10:
            continue
        ld = 20 * np.log10(np.sqrt(np.mean(l_seg[act] ** 2)) + 1e-12)
        od = 20 * np.log10(np.sqrt(np.mean(o_seg[act] ** 2)) + 1e-12)
        out.append({"section": s["label"], "lead_db": round(ld, 1), "others_db": round(od, 1), "margin_db": round(ld - od, 1)})
    return out


# ------------------------------------------------------------------ main analysis
def analyze(source: str | Path, *, out_dir: str | Path | None = None, png: bool = True,
            include_audio: bool = False) -> Report:
    """Analyze a song file (rendered in memory) or an audio file (with its sidecar if present)."""
    src = Path(source)
    stems: dict[str, np.ndarray] = {}
    sections: list[dict] = []
    loop_start: int | None = None
    score_events = None
    tempo = None
    target = None
    title = src.stem
    if src.suffix.lower() in (".yml", ".yaml"):
        from .schema import load
        from .render import render
        song = load(src)
        res = render(song, stems=True, stems_by="group")
        x, sr = res.mix, res.sr
        stems = dict(res.stems)
        if res.ambience is not None:
            stems["ambience"] = res.ambience
        sections = [{"label": s.label, "start": s.start, "end": s.end, "exits": s.exits} for s in res.timeline.sections]
        loop_start = res.loop_start
        score_events = [(e.ch, e.t, e.dur, e.midi) for e in res.timeline.events]
        tempo, target, title = song.tempo, song.target_lufs, song.title
        audio_path = None
        if out_dir is not None:
            from .export import write_audio
            audio_path = str(Path(out_dir) / f"{src.stem}.wav")
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            write_audio(audio_path, x, sr, (loop_start, len(x)) if loop_start is not None else None)
    else:
        x, sr = _load_audio(src)
        audio_path = str(src)
        side = _sidecar_for(src)
        if side:
            sections = side.get("sections", [])
            if side.get("loop"):
                loop_start = side["loop"]["start_samples"]
            tempo = side.get("tempo")
            target = side.get("loudness", {}).get("target_lufs")
            title = side.get("title", title)
            for k, p in side.get("stems", {}).items():
                if Path(p).exists():
                    stems[k.replace("stem_", "")] = _load_audio(Path(p))[0]
        mid = src.with_suffix(".mid")
        if mid.exists():
            score_events = _midi_events(mid)
        if loop_start is None:
            from .export import read_wav_loop, read_ogg_loop
            lp = read_wav_loop(src) if src.suffix.lower() == ".wav" else (read_ogg_loop(src) if src.suffix.lower() == ".ogg" else None)
            if lp:
                loop_start = lp[0]
    n = len(x)
    if not sections:
        sections = [{"label": "all", "start": 0.0, "end": n / sr, "exits": []}]

    m: dict = {"title": title, "sample_rate": sr, "seconds": round(n / sr, 3), "loop": loop_start is not None}
    m["lufs"] = round(loudness.integrated(x, sr), 2)
    st = loudness.short_term(x, sr)
    mo = loudness.momentary(x, sr)
    m["lufs_short_term_max"] = round(float(st.max()), 2)
    m["lufs_momentary_max"] = round(float(mo.max()), 2)
    m["lra"] = round(loudness.loudness_range(x, sr), 2)
    m["true_peak"] = round(loudness.true_peak(x, sr), 2)
    if target is not None:
        m["target_lufs"] = target
    m["bands_db"] = band_balance(x, sr)
    m["centroid_hz"] = round(spectral_centroid(x, sr), 1)
    m.update(stereo_metrics(x))
    m.update(health(x, sr))
    if loop_start is not None:
        m["seam"] = seam_check(x, sr, loop_start, [s["start"] for s in sections if s["start"] > 0])
    flux, on_t = onsets(x, sr)
    m["tempo_detected"] = round(tempo_estimate(flux, sr), 1)
    if tempo:
        m["tempo_score"] = tempo
        m["onset_grid_fraction"] = round(grid_alignment(on_t, tempo), 2)
    m["onsets_per_second"] = round(len(on_t) / (n / sr), 2)

    # per section
    sec_rows = []
    for s, sl in _section_slices(sections, sr, n):
        seg = x[sl]
        row = {"label": s["label"], "start": round(s["start"], 2), "end": round(s["end"], 2),
               "lufs": round(loudness.integrated(seg, sr), 2) if len(seg) > sr else None,
               "centroid_hz": round(spectral_centroid(seg, sr), 1),
               "bands_db": band_balance(seg, sr)}
        if score_events:
            cnt = sum(1 for ch, t, d, mi in score_events if s["start"] <= t < s["end"] and mi is not None)
            hits = sum(1 for ch, t, d, mi in score_events if s["start"] <= t < s["end"] and mi is None)
            row["notes"], row["hits"] = cnt, hits
            row["notes_per_second"] = round(cnt / max(1e-6, s["end"] - s["start"]), 2)
        sec_rows.append(row)
    m["masking"] = masking(stems, sr, sections) if stems else []

    findings = _findings(m, sec_rows, target)
    rep = Report(str(src), m, findings, sec_rows, audio_path=audio_path)
    if out_dir is not None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        rep.json_path = str(out / f"{src.stem}_analysis.json")
        if png:
            try:
                rep.png = str(out / f"{src.stem}_analysis.png")
                composite(rep.png, x, sr, stems, sections, loop_start, score_events, st, title, m)
            except ImportError as e:
                rep.png = None
                findings.append({"severity": "info", "code": "no_png", "message": f"composite image skipped: {e}"})
        payload = {"metrics": m, "sections": sec_rows, "findings": findings, "png": rep.png, "audio": audio_path}
        if include_audio and audio_path:
            import base64
            payload["audio_base64"] = base64.b64encode(Path(audio_path).read_bytes()).decode()
        Path(rep.json_path).write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return rep


def _midi_events(path: Path):
    import mido
    mf = mido.MidiFile(str(path))
    tempo = 500000
    out = []
    for tr in mf.tracks:
        name = "?"
        t = 0
        on: dict = {}
        for msg in tr:
            t += msg.time
            if msg.type == "set_tempo":
                tempo = msg.tempo
            elif msg.type == "track_name":
                name = msg.name
            elif msg.type == "note_on" and msg.velocity > 0:
                on[msg.note] = t
            elif msg.type in ("note_off", "note_on"):
                if msg.note in on:
                    t0 = on.pop(msg.note)
                    sec = lambda tk: mido.tick2second(tk, mf.ticks_per_beat, tempo)
                    out.append((name, sec(t0), sec(t - t0), msg.note if msg.channel != 9 else None))
    return out


# ------------------------------------------------------------------ findings
def _findings(m: dict, secs: list[dict], target) -> list[dict]:
    F: list[dict] = []
    T = THRESHOLDS

    def add(sev, code, msg, **kw):
        F.append({"severity": sev, "code": code, "message": msg, **kw})

    if m["clipped_samples"] > T["clip_samples"]:
        add("high", "clipping", f"{m['clipped_samples']} clipped samples; lower `mix.drive` or channel volumes")
    if m["true_peak"] > T["true_peak"]:
        add("high", "true_peak", f"true peak {m['true_peak']:.2f} dBTP is above the -1 dBTP ceiling")
    if m["dc_offset_db"] > T["dc_db"]:
        add("medium", "dc_offset", f"DC offset {m['dc_offset_db']:.0f} dBFS; check for sustained one-sided waveforms")
    for a, b in m["silent_regions"]:
        add("medium", "silence", f"silence from {a:.1f} s to {b:.1f} s")
    if target is not None and abs(m["lufs"] - target) > T["lufs_tolerance"]:
        add("medium", "loudness", f"{m['lufs']:.1f} LUFS is {m['lufs'] - target:+.1f} LU from the {target} target")
    for band, (lo, hi) in BAND_RANGES.items():
        v = m["bands_db"][band]
        if v < lo:
            add("medium" if band in ("bass", "mid") else "low", "band_low",
                f"{band} band is weak ({v:+.0f} dB, healthy {lo:+.0f}..{hi:+.0f}); "
                + {"sub": "add a sub or lower the kick pitch", "bass": "raise the bass channel or use bass.chipstack",
                   "low_mid": "a pad or drone fills this", "mid": "the lead/arps live here",
                   "presence": "brighter duty (0.125/0.25) or less lp on leads", "air": "hats, noise, higher lp cutoffs"}[band])
        elif v > hi:
            add("medium" if band in ("sub", "bass", "low_mid") else "low", "band_high",
                f"{band} band is heavy ({v:+.0f} dB, healthy {lo:+.0f}..{hi:+.0f}); "
                + {"sub": "lower the sub/kick or raise `mix.hp`", "bass": "lower bass channels or add `lp`",
                   "low_mid": "muddy: lower pads/drones or high-pass them", "mid": "crowded: thin the arps/harmony",
                   "presence": "harsh: lower `mix.hf` or lp the leads", "air": "lower hats / noise"}[band])
    if m["stereo_correlation"] < T["stereo_corr_min"]:
        add("medium", "stereo", f"stereo correlation {m['stereo_correlation']:.2f}: wide/phasey, will cancel in mono; reduce `width`/pan")
    if m.get("seam"):
        s = m["seam"]
        if s["step_ratio"] > T["seam_ratio"]:
            add("high", "seam_click", f"loop seam has a {s['step_ratio']:.1f}x discontinuity (click); check intro tails or very long releases")
        if s["flux_ratio"] > T["seam_flux"]:
            add("medium", "seam_flux", f"spectral jump at the loop seam is {s['flux_ratio']:.1f}x the file's biggest transients; end the loop on material that leads into the start")
    if m.get("tempo_score") and m["tempo_detected"]:
        d = m["tempo_detected"]
        cands = [d, d * 2, d / 2, d * 4 / 3, d * 3 / 2]
        if min(abs(c - m["tempo_score"]) for c in cands) > T["tempo_tolerance"]:
            add("low", "tempo", f"detected pulse {d:.0f} BPM does not match the score tempo {m['tempo_score']:.0f}; rhythm may be too sparse or syncopated to read")
        if m.get("onset_grid_fraction", 1) < T["onset_grid"]:
            add("low", "onsets", f"only {m['onset_grid_fraction']:.0%} of onsets sit on the 16th grid (swing or long attacks?)")
    # section contrast
    rows = [r for r in secs if r.get("lufs") is not None and np.isfinite(r["lufs"])]
    if len(rows) >= 2:
        loud = max(rows, key=lambda r: r["lufs"])
        quiet = min(rows, key=lambda r: r["lufs"])
        spread = loud["lufs"] - quiet["lufs"]
        if spread < T["contrast_min_lu"]:
            add("medium", "contrast", f"sections differ by only {spread:.1f} LU ({quiet['label']} vs {loud['label']}); "
                                      "contrast is weak - drop drums or a layer in one section")
        for r in rows:
            if r.get("notes_per_second", 0) > T["density_max"]:
                add("low", "density", f"section {r['label']} has {r['notes_per_second']:.0f} notes/s; dense, consider thinning arps")
    for mk in m.get("masking", []):
        if mk["margin_db"] < -T["masking_db"]:
            add("medium", "masking", f"lead is masked by the accompaniment in section {mk['section']} "
                                     f"by {-mk['margin_db']:.0f} dB in 1-4 kHz; lower arps/harmony or raise the lead")
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    F.sort(key=lambda f: order[f["severity"]])
    return F


# ------------------------------------------------------------------ images
STEM_COLORS = {"lead": "#ffd166", "arp": "#06d6a0", "bass": "#ef476f", "pads": "#8338ec", "drums": "#4cc9f0",
               "fx": "#ff9f1c", "ambience": "#adb5bd", "music": "#dddddd"}


def _spec_image(mono: np.ndarray, sr: int, nperseg: int, fmax: float | None, cols: int = 1600):
    """Log-magnitude spectrogram as an image matrix reduced to ~cols time columns (max-pooled, so
    transients survive). Returns (img[f, t], f, t_edges)."""
    f, t, Z = ss.spectrogram(mono, sr, nperseg=nperseg, noverlap=nperseg // 2)
    if fmax:
        keep = f <= fmax
        f, Z = f[keep], Z[keep]
    db = 10 * np.log10(Z + 1e-12)
    k = max(1, Z.shape[1] // cols)
    if k > 1:
        m = (db.shape[1] // k) * k
        db = db[:, :m].reshape(db.shape[0], -1, k).max(axis=2)
        t = t[: m: k]
    return db, f, t


def composite(path: str, x: np.ndarray, sr: int, stems: dict, sections: list[dict], loop_start, score_events,
              st_lufs: np.ndarray, title: str, m: dict):
    """One PNG a vision model can read: log spectrogram with sections and loop point, bass-region
    spectrogram, waveform with stem envelopes and short-term loudness, and the piano roll."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    from matplotlib.gridspec import GridSpec
    mono = x.mean(axis=1)
    n = len(mono)
    secs = n / sr
    fig = plt.figure(figsize=(16, 12), dpi=100)
    gs = GridSpec(4, 1, height_ratios=[3, 1.4, 1.6, 2.2], hspace=0.3, left=0.05, right=0.97, top=0.95, bottom=0.05)

    # 1. spectrogram, log frequency (rows resampled onto a log grid)
    ax = fig.add_subplot(gs[0])
    db, f, t = _spec_image(mono, sr, 2048, None)
    fl = np.geomspace(30, 16000, 400)
    rows = np.searchsorted(f, fl).clip(0, len(f) - 1)
    ax.imshow(db[rows], aspect="auto", origin="lower", extent=[0, secs, 0, len(fl)], vmin=-105, vmax=-25, cmap="magma")
    ticks = [50, 100, 200, 500, 1000, 2000, 5000, 10000]
    ax.set_yticks([np.searchsorted(fl, v) for v in ticks])
    ax.set_yticklabels(["50", "100", "200", "500", "1k", "2k", "5k", "10k"])
    ax.set_title(f"{title} - {m['lufs']:.1f} LUFS, TP {m['true_peak']:.1f} dBTP, LRA {m['lra']:.1f} LU, "
                 f"corr {m['stereo_correlation']:.2f}, centroid {m['centroid_hz']:.0f} Hz", fontsize=11)
    _mark_sections(ax, sections, loop_start, sr, len(fl) * 0.97)
    ax.set_ylabel("Hz (log)")

    # 2. bass region, linear
    ax = fig.add_subplot(gs[1])
    db, f, t = _spec_image(mono, sr, 8192, 400)
    ax.imshow(db, aspect="auto", origin="lower", extent=[0, secs, 0, 400], vmin=-100, vmax=-20, cmap="magma")
    ax.set_ylabel("bass 0-400 Hz")
    _mark_sections(ax, sections, loop_start, sr, 370, labels=False)

    # 3. waveform with stems + short-term loudness
    ax = fig.add_subplot(gs[2])
    step = max(1, n // 4000)
    tt = np.arange(0, n, step) / sr
    env_mix = np.abs(x[::step]).max(axis=1)
    ax.fill_between(tt, -env_mix, env_mix, color="#333", lw=0, label="mix")
    for name, buf in stems.items():
        if name == "music" or buf is None:
            continue
        ax.plot(tt, np.abs(buf[::step]).max(axis=1), lw=0.8, color=STEM_COLORS.get(name, "#999"), label=name)
    ax.set_ylim(-1, 1)
    ax.set_xlim(0, secs)
    ax.set_ylabel("waveform + stems")
    ax2 = ax.twinx()
    ax2.plot(np.arange(len(st_lufs)) * 0.1, st_lufs, color="#ffffff", lw=1.0, alpha=0.9)
    ax2.set_ylim(-40, 0)
    ax2.set_ylabel("short-term LUFS", color="#888")
    ax.legend(loc="upper right", fontsize=7, ncol=8, framealpha=0.3, labelcolor="#ddd", facecolor="#222")
    _mark_sections(ax, sections, loop_start, sr, 0.9, labels=False)
    ax.set_facecolor("#111")
    ax2.tick_params(colors="#ccc", labelsize=8)

    # 4. piano roll (one LineCollection per channel)
    ax = fig.add_subplot(gs[3])
    if score_events:
        chans = sorted({e[0] for e in score_events})
        palette = ["#ffd166", "#06d6a0", "#ef476f", "#8338ec", "#4cc9f0", "#ff9f1c", "#ff6b6b", "#c8b6ff", "#a3e635"]
        col = {c: palette[i % len(palette)] for i, c in enumerate(chans)}
        for c in chans:
            segs = [[(t0, midi if midi is not None else 30), (t0 + max(d, 0.03), midi if midi is not None else 30)]
                    for ch, t0, d, midi in score_events if ch == c]
            ax.add_collection(LineCollection(segs, colors=col[c], linewidths=2, capstyle="butt",
                                             alpha=0.9 if any(mi is not None for _, _, _, mi in score_events if _ == c) else 0.5))
        for i, c in enumerate(chans):
            ax.text(0.005, 0.95 - i * 0.08, c, transform=ax.transAxes, color=col[c], fontsize=8, va="top")
        ax.set_ylim(26, 100)
        ax.set_yticks([36, 48, 60, 72, 84, 96])
        ax.set_yticklabels(["C2", "C3", "C4", "C5", "C6", "C7"])
    else:
        ax.text(0.5, 0.5, "no score available (analyze the .yml, or keep the .mid next to the audio)",
                ha="center", transform=ax.transAxes, color="#ccc")
    ax.set_xlim(0, secs)
    ax.set_ylabel("piano roll")
    ax.set_xlabel("seconds")
    _mark_sections(ax, sections, loop_start, sr, 98, labels=False)
    ax.set_facecolor("#111")
    fig.patch.set_facecolor("#1b1b1b")
    for a in fig.axes:
        a.tick_params(colors="#ccc", labelsize=8)
        a.yaxis.label.set_color("#ccc"); a.xaxis.label.set_color("#ccc"); a.title.set_color("#eee")
        for sp in a.spines.values():
            sp.set_color("#555")
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)


def _mark_sections(ax, sections, loop_start, sr, y, labels=True):
    for s in sections:
        ax.axvline(s["start"], color="#ffffff", lw=0.6, alpha=0.6, ls="--")
        if labels:
            ax.text(s["start"] + 0.1, y, s["label"], color="#fff", fontsize=8, va="top")
        for e in s.get("exits", []):
            ax.axvline(e, color="#ffd166", lw=0.5, alpha=0.5, ls=":")
    if loop_start:
        ax.axvline(loop_start / sr, color="#06d6a0", lw=1.2, alpha=0.9)


# ------------------------------------------------------------------ compare
def compare(a: str | Path, b: str | Path, out_dir: str | Path | None = None) -> dict:
    ra, rb = analyze(a, out_dir=out_dir, png=False), analyze(b, out_dir=out_dir, png=False)
    keys = ["lufs", "true_peak", "lra", "centroid_hz", "stereo_correlation", "stereo_width", "onsets_per_second"]
    rows = []
    for k in keys:
        va, vb = ra.metrics.get(k), rb.metrics.get(k)
        rows.append({"metric": k, "a": va, "b": vb, "delta": round(vb - va, 3) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else None})
    for band in ra.metrics["bands_db"]:
        va, vb = ra.metrics["bands_db"][band], rb.metrics["bands_db"][band]
        rows.append({"metric": f"band_{band}", "a": va, "b": vb, "delta": round(vb - va, 1)})
    if ra.metrics.get("seam") and rb.metrics.get("seam"):
        for k in ("step_ratio", "flux_ratio"):
            rows.append({"metric": f"seam_{k}", "a": ra.metrics["seam"][k], "b": rb.metrics["seam"][k],
                         "delta": round(rb.metrics["seam"][k] - ra.metrics["seam"][k], 3)})
    result = {"a": ra.source, "b": rb.source, "rows": rows,
              "findings_a": [f["message"] for f in ra.findings], "findings_b": [f["message"] for f in rb.findings]}
    if out_dir is not None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        png = out / f"compare_{Path(a).stem}_vs_{Path(b).stem}.png"
        try:
            _compare_png(png, a, b, ra, rb)
            result["png"] = str(png)
        except ImportError:
            pass
        jp = out / f"compare_{Path(a).stem}_vs_{Path(b).stem}.json"
        jp.write_text(json.dumps(result, indent=1), encoding="utf-8")
        result["json"] = str(jp)
    return result


def _compare_png(path, a, b, ra, rb):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(16, 8), dpi=100)
    for ax, src, rep in zip(axes, (a, b), (ra, rb)):
        xs, sr = (_load_audio(Path(rep.audio_path)) if rep.audio_path else _render_audio(src))
        mono = xs.mean(axis=1)
        f, t, Z = ss.spectrogram(mono, sr, nperseg=2048, noverlap=1536)
        ax.pcolormesh(t, f, 10 * np.log10(Z + 1e-12), vmin=-105, vmax=-25, shading="auto", cmap="magma")
        ax.set_yscale("symlog", linthresh=100); ax.set_ylim(30, 16000)
        ax.set_title(f"{Path(src).name}: {rep.metrics['lufs']:.1f} LUFS, centroid {rep.metrics['centroid_hz']:.0f} Hz, "
                     + " ".join(f"{k} {v:+.0f}" for k, v in rep.metrics["bands_db"].items()), fontsize=9)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _render_audio(src):
    from .schema import load
    from .render import render
    r = render(load(src), stems=False)
    return r.mix, r.sr


# ------------------------------------------------------------------ optional semantic tags (CLAP)
DESCRIPTORS = ["dark", "triumphant", "tense", "calm", "playful", "melancholic", "epic", "mysterious",
               "8-bit chiptune", "boss battle", "overworld theme", "dungeon ambience", "menu music",
               "victory fanfare", "game over", "fast", "slow", "heavy bass", "bright", "muddy"]


def semantic_tags(audio_path: str, descriptors: list[str] | None = None, top: int = 6) -> dict:
    """APPROXIMATE text-audio similarity via a CLAP model (optional extra: pip install chipforge[analysis]
    plus torch + transformers). Returns {"tags": [(descriptor, score)], "note": ...} or an explanation
    when the model is unavailable. Scores are cosine similarities, only meaningful relative to each
    other within one call."""
    descriptors = descriptors or DESCRIPTORS
    try:
        import torch
        from transformers import ClapModel, ClapProcessor
    except ImportError as e:
        return {"tags": [], "note": f"CLAP tagging unavailable ({e}); install torch and transformers"}
    try:
        name = "laion/clap-htsat-unfused"
        model, proc = ClapModel.from_pretrained(name), ClapProcessor.from_pretrained(name)
        x, sr = _load_audio(Path(audio_path))
        import scipy.signal as _ss
        mono = _ss.resample_poly(x.mean(axis=1), 48000, sr) if sr != 48000 else x.mean(axis=1)
        mono = mono[: 48000 * 30]
        with torch.no_grad():
            a = model.get_audio_features(**proc(audios=mono, sampling_rate=48000, return_tensors="pt"))
            t = model.get_text_features(**proc(text=descriptors, return_tensors="pt", padding=True))
            a, t = a / a.norm(dim=-1, keepdim=True), t / t.norm(dim=-1, keepdim=True)
            sims = (a @ t.T)[0].tolist()
        ranked = sorted(zip(descriptors, sims), key=lambda z: -z[1])
        return {"tags": [(d, round(v, 3)) for d, v in ranked[:top]], "all": dict(zip(descriptors, [round(v, 3) for v in sims])),
                "note": "approximate: CLAP cosine similarity, compare within this list only"}
    except Exception as e:  # model download / runtime problems must never break analysis
        return {"tags": [], "note": f"CLAP tagging failed: {e}"}


def format_text(rep: Report) -> str:
    m = rep.metrics
    lines = [f"# {m['title']}  ({m['seconds']:.1f} s, {'loop' if m['loop'] else 'one-shot'})", rep.summary(max_findings=50)]
    if rep.sections and len(rep.sections) > 1:
        lines.append("sections:")
        for r in rep.sections:
            lines.append(f"  {r['label']:<10} {r['start']:6.1f}-{r['end']:6.1f} s  {r['lufs'] if r['lufs'] is not None else '  -  '} LUFS"
                         f"  centroid {r['centroid_hz']:.0f} Hz" + (f"  {r['notes_per_second']} notes/s" if "notes_per_second" in r else ""))
    if rep.png:
        lines.append(f"image: {rep.png}")
    if rep.json_path:
        lines.append(f"json:  {rep.json_path}")
    return "\n".join(lines)
