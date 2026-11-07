"""Render a Song: events -> voices -> parts -> buses -> master. Loop-aware throughout."""
from __future__ import annotations

import time
from dataclasses import dataclass, field, replace

import numpy as np

from . import chips, fx, presets as _presets, score
from .schema import Song
from .synth import VOICE_FN, Ctx, dpcm

TAIL_S = 4.0


@dataclass
class Part:
    """A rendered mono buffer plus its mix settings."""
    name: str          # "lead" or "drums.k"
    ch: str
    buf: np.ndarray
    mix: dict
    layer: int
    voice: str


class Space:
    """Knows where the loop is and makes every effect wrap correctly.

    One-shot: linear everywhere. Loop without intro: fully circular. Loop with intro: the intro is
    processed linearly (its tails bleed into the loop start) and the loop region circularly."""

    def __init__(self, n_total: int, loop_start: int | None, sr: int):
        self.n, self.l0, self.sr = n_total, loop_start, sr
        self.circular = loop_start is not None

    def fold(self, x: np.ndarray) -> np.ndarray:
        if not self.circular:
            return x
        if self.l0 == 0:
            return fx.fold(x, self.n)
        y = x[: self.n].copy()
        loop = fx.fold(x[self.l0:], self.n - self.l0)
        y[self.l0:] = loop
        return y

    def _split(self, fn_lin, fn_circ, x: np.ndarray) -> np.ndarray:
        if not self.circular:
            return fn_lin(x)
        if self.l0 == 0:
            return fn_circ(x)
        intro = fn_lin(np.concatenate([x[: self.l0], np.zeros((self.n - self.l0,) + x.shape[1:])]))
        out = np.zeros((self.n,) + intro.shape[1:])
        out[: self.l0] = intro[: self.l0]
        out[self.l0:] = fn_circ(x[self.l0:]) + intro[self.l0:]
        return out

    def filt(self, x, s):
        return fx.filt(x, s, self.circular)

    def conv(self, x, ir):
        return self._split(lambda a: fx.convolve(a, ir, False), lambda a: fx.convolve(a, ir, True), x)

    def echo(self, x, d, taps):
        return self._split(lambda a: fx.echo(a, d, False, taps), lambda a: fx.echo(a, d, True, taps), x)

    def delay(self, x, k):
        return self._split(lambda a: fx.delay(a, k, False), lambda a: fx.delay(a, k, True), x)

    def duck(self, kicks, release):
        if not kicks:
            return None
        if not self.circular or self.l0 == 0:
            return fx.duck_curve(self.n, kicks, self.sr, release, self.circular)
        intro = fx.duck_curve(self.n, [(i, v) for i, v in kicks if i < self.l0], self.sr, release, False)
        loop = fx.duck_curve(self.n - self.l0, [(i - self.l0, v) for i, v in kicks if i >= self.l0], self.sr, release, True)
        out = intro
        out[self.l0:] = np.maximum(out[self.l0:], loop)
        return out


@dataclass
class RenderResult:
    song: Song
    timeline: score.Timeline
    sr: int
    mix: np.ndarray                 # (n, 2) float, master output
    music: np.ndarray               # (n, 2) music only
    ambience: np.ndarray | None     # (n, 2) ambience stem at its mixed level
    stems: dict[str, np.ndarray]    # name -> (n, 2) post-master stems (per layer / group)
    parts: list[Part]
    loop_start: int | None
    loop_end: int | None
    gain: float
    seconds: float = 0.0
    stats: dict = field(default_factory=dict)


# ------------------------------------------------------------------ voices -> parts
class _NoteCache:
    def __init__(self):
        self.d: dict = {}
        self.hits = self.misses = 0

    def get(self, key, make):
        v = self.d.get(key)
        if v is None:
            v = make()
            self.d[key] = v
            self.misses += 1
        else:
            self.hits += 1
        return v


def _freeze(d):
    """Make nested dict/list params hashable for the note cache."""
    if isinstance(d, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in d.items()))
    if isinstance(d, (list, tuple)):
        return tuple(_freeze(v) for v in d)
    return d


def _render_voice(voice: str, vp: dict, events, ctx: Ctx, n_buf: int, cache: _NoteCache, sr: int,
                  octave_shift: int = 0, piece: str | None = None, post: str | None = None) -> np.ndarray:
    fn = VOICE_FN[voice]
    buf = np.zeros(n_buf)
    vp_key = _freeze(vp)
    for e in events:
        n_on = int(round(e.dur * sr))
        midi = (e.midi + 12 * octave_shift) if e.midi is not None else None
        key = (voice, vp_key, midi, n_on, _freeze(e.params), ctx, post)

        def make():
            sig = fn(vp, ctx, n_on, midi, e.params)
            return dpcm(sig, sr) if post == "dpcm" else sig
        sig = cache.get(key, make)
        i = int(round(e.t * sr))
        j = min(i + len(sig), n_buf)
        if j > i:
            buf[i:j] += sig[: j - i] * e.vel
    return buf


def render_parts(song: Song, tl: score.Timeline, ctx0: Ctx, n_buf: int, cache: _NoteCache) -> tuple[list[Part], list]:
    parts: list[Part] = []
    kicks: list[tuple[int, float]] = []
    sr = song.sr
    prof = chips.get(song.chip)
    by_ch: dict[str, list] = {}
    for e in tl.events:
        by_ch.setdefault(e.ch, []).append(e)
    for name, ch in song.channels.items():
        evs = by_ch.get(name, [])
        preset = _presets.get(ch.preset)
        osc = ch.overrides.get("osc")
        ctx = replace(ctx0, clean=(osc == "clean") if osc else (prof.clean and ctx0.enhanced))
        if not ctx.enhanced and prof.duties:                # authentic: snap duty macros to legal widths
            for e in evs:
                if "d" in e.params:
                    e.params["d"] = [min(prof.duties, key=lambda x: abs(x - e.params["d"][0]))]
        base_mix = {**_presets.MIX_DEFAULTS, **preset.get("mix", {})}
        if preset["kind"] == "melodic":
            is_stack = preset.get("voice") == "stack"
            layers = preset["layers"] if is_stack else [preset]
            for li, layer in enumerate(layers):
                vparams_raw, lmix = _presets.split_mix(layer)
                if not is_stack:
                    lmix = {}          # a plain preset's mix is already in base_mix
                vp = _presets.voice_params(layer["voice"], vparams_raw)
                buf = _render_voice(layer["voice"], vp, evs, ctx, n_buf, cache, sr, layer.get("octave", 0))
                mix = {**base_mix, **lmix}
                mix["vol"] = base_mix["vol"] * lmix.get("vol", 1.0) * ch.vol
                mix["pan"] = float(np.clip(mix["pan"] + ch.pan, -1, 1))
                mix.update(ch.overrides)
                pname = name if len(layers) == 1 else f"{name}.{layer['voice']}{li}"
                parts.append(Part(pname, name, buf, mix, ch.layer, layer["voice"]))
        else:
            for pc, piece in preset["pieces"].items():
                pevs = [e for e in evs if e.piece == pc]
                if not pevs:
                    continue
                vparams_raw, pmix = _presets.split_mix(piece)
                vp = _presets.voice_params(piece["voice"], vparams_raw)
                if piece["voice"] in _presets.MELODIC_VOICES:      # a melodic voice used as a drum/hit
                    defaults = {k: piece[k] for k in ("sweep", "arp_rate", "d") if k in piece}
                    for e in pevs:
                        had_arp = "arp" in e.params
                        e.params = {**defaults, **e.params}
                        if e.midi is None:
                            e.midi = float(e.params.get("note", piece.get("note", 48)))
                        if "arp" in piece and not had_arp:
                            e.params["arp"] = [e.midi + o for o in piece["arp"]]
                        if "len" not in e.params and not e.params.get("dur"):
                            e.dur = float(piece.get("len", 0.2))
                buf = _render_voice(piece["voice"], vp, pevs, ctx, n_buf, cache, sr, 0, pc,
                                    "dpcm" if pmix.get("dpcm") else None)
                mix = {**base_mix, **pmix}
                mix["vol"] = pmix.get("vol", 1.0) * base_mix["vol"] * ch.vol
                mix["pan"] = float(np.clip(mix["pan"] + ch.pan, -1, 1))
                mix.update({k: v for k, v in ch.overrides.items() if k in ("lp", "hp", "duck")})
                parts.append(Part(f"{name}.{pc}", name, buf, mix, ch.layer, piece["voice"]))
                if piece["voice"] == "kick":
                    kicks += [(int(round(e.t * sr)), e.vel) for e in pevs]
    return parts, kicks


# ------------------------------------------------------------------ mix
def mix_parts(song: Song, parts: list[Part], kicks: list, space: Space, enhanced: bool,
              stems_by: str | None = "layer") -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Parts -> (music (n,2) pre-master, {stem name: (n,2)}). Stems are per intensity layer; the
    low bus is saturated per stem, so stems sum only approximately to the mix."""
    sr, n = song.sr, space.n
    m = song.mix
    duck_env = space.duck(kicks, m["sidechain"]) if enhanced else None
    buses: dict[tuple, np.ndarray] = {}      # (bus, stem) -> (n, 2)
    echo_in = np.zeros(n)
    rev_in = np.zeros(n)
    for p in parts:
        x = p.buf * p.mix["vol"]
        if p.mix.get("lp"):
            x = space.filt(x, fx.sos("low", float(p.mix["lp"]), sr, 4 if p.mix["bus"] == "low" else 2))
        if p.mix.get("hp"):
            x = space.filt(x, fx.sos("high", float(p.mix["hp"]), sr))
        if duck_env is not None and p.mix.get("duck"):
            x = x * (1 - p.mix["duck"] * duck_env)
        key = (p.mix["bus"], f"layer{p.layer}" if stems_by == "layer" else "all")
        bus = buses.get(key)
        if bus is None:
            bus = buses[key] = np.zeros((n, 2))
        if enhanced:
            if p.mix.get("echo"):
                echo_in += x * p.mix["echo"]
            if p.mix.get("reverb"):
                rev_in += x * p.mix["reverb"]
            pan = p.mix["pan"]
            if p.mix.get("width"):
                bus[:, 0] += x * (1 - pan)
                bus[:, 1] += space.delay(x * (1 + pan), int(p.mix["width"] * sr))
            else:
                np.add(bus[:, 0], x * (1 - pan), out=bus[:, 0])
                np.add(bus[:, 1], x * (1 + pan), out=bus[:, 1])
        else:
            prof = chips.get(song.chip)
            if prof.pan_steps:                     # e.g. Game Boy: hard left / centre / right
                pan = float(np.round(p.mix["pan"] * (prof.pan_steps - 1) / 2) * 2 / (prof.pan_steps - 1))
                if pan <= 0:
                    bus[:, 0] += x
                if pan >= 0:
                    bus[:, 1] += x
            else:
                bus[:, 0] += x
                bus[:, 1] += x
    out = np.zeros((n, 2))
    stems: dict[str, np.ndarray] = {}
    for bus in {b for b, _ in buses}:
        total = sum(v for (b, _), v in buses.items() if b == bus)
        out += fx.saturate(total, m["low_drive"]) if bus == "low" else total
    if stems_by:
        for (bus, stem), v in buses.items():
            v = fx.saturate(v, m["low_drive"]) if bus == "low" else v
            stems[stem] = stems[stem] + v if stem in stems else v
    if enhanced:
        d = int(round(m["echo"]["time"] * song.step_s * sr))
        if np.any(echo_in):
            e = space.echo(echo_in, d, tuple(m["echo"]["taps"]))
            out += e
            for k in stems:
                stems[k] += e / len(stems)
        if np.any(rev_in):
            r = m["reverb"]
            ir_l = fx.reverb_ir(sr, r["size"], r["decay"], r["tone"], r["predelay"], song.seed * 7 + 3)
            ir_r = fx.reverb_ir(sr, r["size"], r["decay"], r["tone"], r["predelay"], song.seed * 7 + 4)
            rv = np.stack([space.conv(rev_in, ir_l), space.conv(rev_in, ir_r)], axis=1)
            out += rv
            for k in stems:
                stems[k] += rv / len(stems)
    return out, stems


def master(song: Song, x: np.ndarray, space: Space, gain: float | None = None, hp: bool = True,
           limit: bool = True) -> tuple[np.ndarray, float, dict]:
    """Master chain: high-pass -> soft clip -> high shelf -> loudness normalize -> true-peak limiter.
    With `gain` given (stems), the same gain is applied without re-measuring and without limiting."""
    from . import loudness
    m = song.mix
    y = space.filt(x, fx.sos("high", float(m["hp"]), song.sr)) if hp else x
    y = fx.soft_clip(y, m["drive"])
    if m["hf"] != 1.0:
        y = space.filt(y, fx.sos("highshelf", float(m["hf_freq"]), song.sr, gain=float(m["hf"])))
    info: dict = {}
    if gain is not None:
        return y * gain, gain, info
    if m["normalize"]:
        y, info = loudness.normalize(y, song.sr, song.target_lufs, m["ceiling"], circular=space.circular)
        gain = 10 ** (info["gain_db"] / 20)
    else:
        peak = float(np.max(np.abs(y))) or 1.0
        gain = min(1.0, 10 ** (m["ceiling"] / 20) / peak)
        y = y * gain
        info = {"gain_db": round(20 * np.log10(gain), 2)}
    info["target_lufs"] = song.target_lufs
    return y, gain, info


# ------------------------------------------------------------------ entry point
def render(song: Song, *, stems: bool = True) -> RenderResult:
    t0 = time.perf_counter()
    tl = score.build(song)
    prof = chips.get(song.chip)
    enhanced = song.mode == "enhanced"
    ctx = Ctx(song.sr, prof.frame_hz, prof.vol_bits, prof.tri_steps, enhanced, song.seed,
              prof.clean and enhanced, prof.noise_short)
    sr = song.sr
    n_total = int(round(tl.length * sr))
    loop_start = int(round(tl.loop_start * sr)) if tl.loop_start is not None else None
    tail = int(TAIL_S * sr)
    cache = _NoteCache()
    parts, kicks = render_parts(song, tl, ctx, n_total + tail, cache)
    space = Space(n_total if loop_start is not None else n_total + tail, loop_start, sr)
    for p in parts:
        p.buf = space.fold(p.buf)
    music, layer_stems = mix_parts(song, parts, kicks, space, enhanced, "layer" if stems else None)

    amb = None
    if song.ambience and song.ambience.get("bed", "none") != "none" and enhanced:
        from . import ambience as _amb
        amb = _amb.render(song, tl, space, ctx)
        amb_level = 10 ** (song.ambience["level"] / 20)
        music_rms = _rms(music.sum(1))
        if music_rms > 1e-6:
            amb = amb * amb_level * music_rms / (_rms(amb.sum(1)) or 1.0)   # mono-sum RMS ratio, as tuned
        else:                                                               # ambience-only render
            amb = amb * 0.3 / (np.max(np.abs(amb)) or 1.0)

    # the master high-pass is linear, so apply it per component once and sum
    music = space.filt(music, fx.sos("high", float(song.mix["hp"]), sr))
    if amb is not None:
        amb = space.filt(amb, fx.sos("high", float(song.mix["hp"]), sr))
    full = music + amb if amb is not None else music
    mixed, gain, minfo = master(song, full, space, hp=False)
    music_m = mixed if amb is None else master(song, music, space, gain, hp=False)[0]
    amb_m = master(song, amb, space, gain, hp=False)[0] if amb is not None else None
    stems_out = {k: master(song, v, space, gain, hp=False)[0] for k, v in layer_stems.items()} if stems else {}
    if amb_m is not None and stems:
        stems_out["ambience"] = amb_m
    if loop_start is None:
        end = len(fx.trim_tail(mixed, sr))
        mixed, music_m = mixed[:end], music_m[:end]
        stems_out = {k: v[:end] for k, v in stems_out.items()}
        if amb_m is not None:
            amb_m = amb_m[:end]
    res = RenderResult(song, tl, sr, mixed, music_m, amb_m, stems_out, parts, loop_start,
                       n_total if loop_start is not None else None, gain)
    res.seconds = time.perf_counter() - t0
    res.stats = {"notes": len(tl.events), "cache_hits": cache.hits, "cache_misses": cache.misses,
                 "parts": len(parts), "peak": float(np.max(np.abs(mixed))), **minfo}
    return res


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x ** 2)))
