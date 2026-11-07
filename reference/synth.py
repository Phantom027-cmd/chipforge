#!/usr/bin/env python3
"""Factory boss fight — chiptune loop synthesizer.
E minor / F minor, 160 BPM, 40 bars = exactly 60.0 s, seamless loop.
NES-style pulse/triangle/LFSR-noise voices (4-bit volume steps, 60 Hz frame
envelopes) layered over a modern sine sub-bass with kick sidechain.
"""
import sys, os
import numpy as np
import scipy.signal as ss
import scipy.io.wavfile as wavfile
import mido

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
os.makedirs(OUT, exist_ok=True)

SR = 44100
BPM = 160
STEP = 60 / BPM / 4                     # 16th note
BARS = 40
N = int(round(BARS * 16 * STEP * SR))   # 2,646,000 samples = 60 s
TAIL = int(3 * SR)
rng = np.random.default_rng(7)

# ----------------------------------------------------------------- helpers
def mtof(m):
    return 440.0 * 2 ** ((np.asarray(m, dtype=float) - 69) / 12)

PC = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
def nn(s):
    pc, i = PC[s[0]], 1
    if s[i] in '#b':
        pc += 1 if s[i] == '#' else -1
        i += 1
    return 12 * (int(s[i:]) + 1) + pc

def T(bar, step=0.0):
    return (bar * 16 + step) * STEP

buses = {}
def add(name, t0, sig):
    b = buses.setdefault(name, np.zeros(N + TAIL))
    i = int(round(t0 * SR))
    j = min(i + len(sig), len(b))
    b[i:j] += sig[:j - i]

MIDI = []   # (track, t0, dur, note, vel)
def mev(track, t0, dur, note, vel=0.8):
    MIDI.append((track, t0, dur, int(note), vel))

def qframe(t):            # NES updates envelopes/pitch once per 60 Hz frame
    return np.floor(t * 60) / 60

def q16(v):               # 4-bit volume
    return np.round(np.clip(v, 0, 1) * 15) / 15

def lfsr(short):
    reg, out = 1, np.empty(32767)
    tap = 6 if short else 1
    for k in range(32767):
        bit = (reg ^ (reg >> tap)) & 1
        reg = (reg >> 1) | (bit << 14)
        out[k] = 1.0 if reg & 1 else -1.0
    return out

NL, NS = lfsr(False), lfsr(True)

def noise(n, rate, short=False):
    seq = NS if short else NL
    rate = np.broadcast_to(np.asarray(rate, float), (n,))
    idx = np.floor(np.cumsum(rate) / SR).astype(np.int64) % len(seq)
    return seq[idx]

def pulse_wave(freq, duty):
    ph = np.cumsum(freq) / SR
    return np.where((ph % 1.0) < duty, 1.0, -1.0)

TRI = np.concatenate([np.arange(15, -1, -1), np.arange(0, 16)]) / 7.5 - 1
def tri_wave(freq):
    ph = np.cumsum(freq) / SR
    return TRI[(np.floor(ph * 32) % 32).astype(int)]

def crush(x, factor):     # sample-and-hold rate reduction (bytebeat grit)
    idx = (np.arange(len(x)) // factor) * factor
    return x[idx]

# ----------------------------------------------------------------- voices
def pulse_note(m, dur, duty=0.25, vib=0.28, slide=None, slide_t=0.05,
               rel=0.07, sus=0.72, dec=0.12):
    n = int((dur + rel) * SR)
    t = np.arange(n) / SR
    tq = qframe(t)
    semis = np.full(n, float(m))
    if slide is not None:
        k = np.clip(tq / slide_t, 0, 1)
        semis = slide + (m - slide) * k
    if vib and dur > 0.25:
        depth = np.clip((tq - 0.2) / 0.25, 0, 1) * vib
        semis = semis + depth * np.sin(2 * np.pi * 5.8 * tq)
    d = np.where(tq < 2 / 60, 0.125, duty)   # "pluck" duty flick on attack
    w = pulse_wave(mtof(semis), d)
    lvl = sus + (1 - sus) * np.exp(-dur / dec)
    env = np.where(tq < dur, sus + (1 - sus) * np.exp(-tq / dec),
                   lvl * np.clip(1 - (tq - dur) / rel, 0, 1))
    return w * q16(env)

def arp_note(chord, dur, rate=1, duty=0.125, decay=0.18):
    n = int((dur + 0.02) * SR)
    t = np.arange(n) / SR
    tq = qframe(t)
    k = np.floor(t * 60 / rate).astype(int) % len(chord)
    f = mtof(np.asarray(chord)[k])
    env = np.where(tq < dur, 0.3 + 0.7 * np.exp(-tq / decay), 0)
    return pulse_wave(f, duty) * q16(env)

def tri_note(m, dur):
    n = int((dur + 0.006) * SR)
    w = tri_wave(np.full(n, mtof(m)))
    g = np.ones(n)
    g[-int(0.006 * SR):] = np.linspace(1, 0, int(0.006 * SR))
    return w * g

def grit_note(m, dur):
    n = int((dur + 0.015) * SR)
    t = np.arange(n) / SR
    w = pulse_wave(np.full(n, mtof(m)), 0.25)
    env = np.where(t < dur, 0.45 + 0.55 * np.exp(-t / 0.08),
                   0.45 * np.clip(1 - (t - dur) / 0.015, 0, 1))
    return w * env

def sub_note(m, dur):
    n = int((dur + 0.04) * SR)
    t = np.arange(n) / SR
    w = np.sin(2 * np.pi * mtof(m) * t)
    env = np.clip(t / 0.004, 0, 1) * np.where(t < dur, 1, np.clip(1 - (t - dur) / 0.04, 0, 1))
    return w * env

def groan(m0, m1, dur):
    """mechanical roar: pulse dive with wobble + metallic short-noise"""
    n = int(dur * SR)
    t = np.arange(n) / SR
    tq = qframe(t)
    semis = m0 + (m1 - m0) * (tq / dur) ** 0.7 + 0.6 * np.sin(2 * np.pi * 7 * tq)
    w = pulse_wave(mtof(semis), 0.5) * 0.7 + noise(n, mtof(semis) * 93 / 4, True) * 0.3
    env = np.clip(tq / 0.06, 0, 1) * np.clip(1 - tq / dur, 0, 1) ** 0.8
    return w * q16(env)

def kick():
    n = int(0.38 * SR)
    t = np.arange(n) / SR
    f = 42 + (210 - 42) * np.exp(-t / 0.022)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.20)
    click = tri_wave(np.full(n, 330.0)) * np.exp(-t / 0.006)
    x = body + 0.5 * click
    return np.round(x * 24) / 24          # 5-bit-ish crunch

def snare(v=1.0):
    n = int(0.22 * SR)
    t = np.arange(n) / SR
    tq = qframe(t)
    nz = noise(n, 22000) * q16(np.exp(-tq / 0.075))
    tone = tri_wave(190 * np.exp(-t / 0.08)) * np.exp(-t / 0.03)
    return crush(nz * 0.85 + tone * 0.6, 2) * v

def hat(v=1.0, open_=False):
    n = int((0.16 if open_ else 0.045) * SR)
    t = np.arange(n) / SR
    x = noise(n, 44100)
    x = np.diff(x, prepend=0) * 0.5
    return x * np.exp(-t / (0.07 if open_ else 0.014)) * v

def clank(v=1.0):
    n = int(0.22 * SR)
    t = np.arange(n) / SR
    tq = qframe(t)
    ring = pulse_wave(np.full(n, 587.0), 0.5) * pulse_wave(np.full(n, 871.0), 0.5)
    metal = noise(n, 60000, True)
    return crush((ring * 0.6 + metal * 0.4) * q16(np.exp(-tq / 0.06)), 2) * v

def crash():
    n = int(1.8 * SR)
    t = np.arange(n) / SR
    tq = qframe(t)
    return noise(n, 32000) * q16(np.exp(-tq / 0.55))

def hiss(dur=0.6, up=False):
    n = int(dur * SR)
    t = np.arange(n) / SR
    tq = qframe(t)
    a, b = (3000, 26000) if up else (26000, 3000)
    rate = a * (b / a) ** (tq / dur)
    env = np.clip(tq / 0.03, 0, 1) * (tq / dur if up else np.exp(-tq / (dur * 0.4)))
    return noise(n, rate) * q16(env)

# ----------------------------------------------------------------- music data
CH = {'Em': (4, 'm'), 'C': (0, 'M'), 'Am': (9, 'm'), 'B': (11, 'M'), 'D': (2, 'M'),
      'F': (5, 'M'), 'Fm': (5, 'm'), 'Db': (1, 'M'), 'Bbm': (10, 'm')}

def chord_tones(name, base=60):
    pc, q = CH[name]
    r = base + (pc - base) % 12
    third = 3 if q == 'm' else 4
    return [r, r + third, r + 7, r + 12]

def tri_root(name):  return 40 + (CH[name][0] - 4) % 12   # E2..D#3
def sub_root(name):  return 28 + (CH[name][0] - 4) % 12   # E1..D#2 (41-78 Hz)

E_HM = [4, 6, 7, 9, 11, 0, 3]
F_HM = [5, 7, 8, 10, 0, 1, 4]
def third_below(m, scale):
    if m % 12 not in scale:
        return m - 3
    i = scale.index(m % 12)
    pc = scale[(i - 2) % 7]
    return m - ((m - pc) % 12 or 12)

def parse(bar_str, transpose=0):
    out, s = [], 0
    for tok in bar_str.split():
        slide = tok.startswith('~')
        tok = tok.lstrip('~')
        name, ln = tok.split(':')
        ln = float(ln)
        if name != 'r':
            out.append((s, ln, nn(name) + transpose, slide))
        s += ln
    assert abs(s - 16) < 1e-9, (bar_str, s)
    return out

MEL_A = [
    "E5:4 B4:2 E5:2 F#5:2 G5:4 F#5:2",
    "E5:6 D5:2 B4:8",
    "C5:2 E5:2 G5:4 F#5:2 E5:2 D5:2 E5:2",
    "C5:8 D5:4 E5:4",
    "A5:6 G5:2 A5:2 B5:2 C6:4",
    "B5:8 A5:2 G5:2 F#5:2 D#5:2",
    "E5:4 B4:2 E5:2 G5:4 B5:4",
    "A5:2 G5:2 F#5:4 D#5:4 B4:4",
]
MEL_A2 = list(MEL_A)
MEL_A2[0] = "E5:4 B4:2 E5:2 F#5:2 ~G5:4 F#5:2"
MEL_A2[4] = "A5:6 G5:2 A5:2 B5:2 ~C6:4"
MEL_A2[7] = "B5:4 C6:2 B5:2 A5:2 G5:2 F#5:4"
MEL_BREAK = [
    "r:16", "r:16",
    "B4:8 E5:8",
    "G5:8 F#5:4 E5:4",
    "G5:12 E5:4",
    "F#5:8 A5:8",
    "B5:16",
    "D#5:4 F#5:4 A5:4 B5:4",
]

SECTIONS = (['Em', 'Em', 'F', 'B'] +                                   # 0-3 intro
            ['Em', 'Em', 'C', 'C', 'Am', 'B', 'Em', 'B'] +            # 4-11 A
            ['Em', 'Em', 'C', 'C', 'Am', 'B', 'Em', 'B'] +            # 12-19 A'
            ['C', 'D', 'Em', 'Em', 'C', 'D', 'B', 'B'] +              # 20-27 break
            ['Fm', 'Fm', 'Db', 'Db', 'Bbm', 'C', 'Fm', 'C'] +         # 28-35 climax (+1)
            ['C', 'D', 'B', 'B'])                                      # 36-39 turnaround
assert len(SECTIONS) == BARS

OST = [0, 0, 12, 0, 0, 12, 0, 0, 12, 0, 0, 12, 0, 12, 7, 10]

# ----------------------------------------------------------------- writers
def play_lead(bar, bar_str, bus='lead', transpose=0, duty=0.25, harm_scale=None,
              vib=0.28, track='Lead'):
    prev = None
    for s, ln, m, slide in parse(bar_str, transpose):
        t0, dur = T(bar, s), ln * STEP * 0.94
        add(bus, t0, pulse_note(m, dur, duty, vib, slide=prev if slide else None, slide_t=0.06))
        mev(track, t0, dur, m, 0.85)
        if harm_scale is not None:
            h = third_below(m, harm_scale)
            add('harm', t0, pulse_note(h, dur, 0.5, vib * 0.8))
            mev('Harmony', t0, dur, h, 0.65)
        prev = m

def play_bass_ost(bar, name, pattern=OST, gate=0.82):
    r = tri_root(name)
    for s, off in enumerate(pattern):
        t0, dur = T(bar, s), STEP * gate
        add('tri', t0, tri_note(r + off, dur))
        add('grit', t0, grit_note(r + off, dur))
        mev('Bass', t0, dur, r + off, 0.8)

def play_bass_hits(bar, name, hits):
    r = tri_root(name)
    for s, ln, off in hits:
        t0, dur = T(bar, s), ln * STEP * 0.9
        add('tri', t0, tri_note(r + off, dur))
        add('grit', t0, grit_note(r + off, dur))
        mev('Bass', t0, dur, r + off, 0.8)

def play_sub(bar, name, chunks=(0, 8)):
    m = sub_root(name)
    edges = list(chunks) + [16]
    for a, b in zip(edges[:-1], edges[1:]):
        t0, dur = T(bar, a), (b - a) * STEP * 0.97
        add('sub', t0, sub_note(m, dur))
        mev('Sub', t0, dur, m, 0.9)

def play_arp(bar, name, every=2, rate=1, duty=0.125, vol=1.0, base=64):
    ch = chord_tones(name, base)
    for s in range(0, 16, every):
        t0, dur = T(bar, s), every * STEP * 0.9
        add('arp', t0, arp_note(ch, dur, rate, duty) * vol)
        mev('Arp', t0, dur, ch[(s // every) % 4], 0.6 * vol)

KICKS = []
DR = {'K': 36, 'S': 38, 'H': 42, 'O': 46, 'C': 49, 'M': 56, 'X': 52}
def drums(bar, **pats):
    for key, pat in pats.items():
        for s, c in enumerate(pat):
            if c == '.':
                continue
            v = {'x': 1.0, 'o': 0.55, 'g': 0.3}.get(c, 1.0)
            t0 = T(bar, s)
            if key == 'K':
                add('kick', t0, kick() * v); KICKS.append(t0)
            elif key == 'S':
                add('snare', t0, snare(v))
            elif key == 'H':
                add('hat', t0, hat(v))
            elif key == 'O':
                add('hat', t0, hat(v, True))
            elif key == 'M':
                add('clank', t0, clank(v))
            mev('Drums', t0, 0.1, DR[key], 0.4 + 0.5 * v)

def roll(bar, start=8, ramp=(0.25, 1.0)):
    steps = list(range(start, 16))
    for i, s in enumerate(steps):
        v = ramp[0] + (ramp[1] - ramp[0]) * i / max(1, len(steps) - 1)
        add('snare', T(bar, s), snare(v))
        mev('Drums', T(bar, s), 0.1, 38, 0.3 + 0.6 * v)

def hit_crash(bar, step=0):
    add('crash', T(bar, step), crash()); mev('Drums', T(bar, step), 0.5, 49, 0.9)

def hit_hiss(bar, step=0, dur=0.6, up=False):
    add('hiss', T(bar, step), hiss(dur, up)); mev('Drums', T(bar, step), dur, 52, 0.6)

CLANK = "..x.......o..x.."
HAT8 = "x.o.x.o.x.o.x.o."
HAT16 = "xgogxgogxgogxgog"

# ----------------------------------------------------------------- arrangement
# Intro 0-3: the machine powers up
add('groan', T(0), groan(52, 40, 1.4)); mev('FX', T(0), 1.4, 52, 0.8)
hit_crash(0); hit_hiss(0, 0, 0.8)
for b in range(4):
    name = SECTIONS[b]
    play_bass_ost(b, name)
    play_sub(b, name)
    if b < 2:
        drums(b, K="x...x...x...x...", M=CLANK)
    else:
        drums(b, K="x...x...x...x...", M=CLANK, O="..o...o...o...o.")
hit_hiss(2, 0, 0.6)
# factory alarm siren
for b in (2, 3):
    for s, m0, m1 in ((0, None, nn('E5')), (8, nn('E5'), nn('F5'))):
        add('siren', T(b, s), pulse_note(m1, 8 * STEP * 0.95, 0.5, 0, slide=m0, slide_t=0.25,
                                         sus=0.8))
        mev('Siren', T(b, s), 8 * STEP * 0.95, m1, 0.5)
drums(3, S="....x...")
roll(3, 8)

# A 4-11 and A' 12-19
for i in range(8):
    for b, mel, harm in ((4 + i, MEL_A, None), (12 + i, MEL_A2, E_HM)):
        name = SECTIONS[b]
        play_lead(b, mel[i], duty=0.25 if harm is None else 0.25, harm_scale=harm)
        play_bass_ost(b, name)
        play_sub(b, name)
        drums(b, K="x.....x.x.....x.", S="....x.......x...", H=HAT8, M=CLANK)
        if b >= 8:
            play_arp(b, name, vol=0.6 if b < 12 else 1.0)
hit_crash(4); hit_crash(12)
roll(19, 12, (0.4, 0.9))

# Break 20-27: the abomination looms
for i in range(8):
    b = 20 + i
    name = SECTIONS[b]
    play_lead(b, MEL_BREAK[i], duty=0.5, vib=0.4)
    play_bass_hits(b, name, [(0, 10, 0), (10, 2, 12), (12, 4, 0)])
    play_sub(b, name, (0,))
    play_arp(b, name, every=1, rate=2, duty=0.25, vol=0.75, base=60)
    if b < 26:
        drums(b, K="x.........x.....", S="........x.......", O="..g...g...g...g.",
              M="......x.......o.")
hit_crash(20)
add('groan', T(20), groan(48, 36, 2.4)); mev('FX', T(20), 2.4, 48, 0.8)
add('groan', T(24), groan(48, 36, 2.4)); mev('FX', T(24), 2.4, 48, 0.8)
hit_hiss(22, 0, 0.9); hit_hiss(24, 8, 0.6)
drums(26, K="x...x...x...x...", S="..o...o...o...x.", H=HAT8)
drums(27, K="x...x...x...x...", H=HAT16)
roll(27, 0, (0.2, 1.0))
hit_hiss(27, 0, 16 * STEP, up=True)

# Climax 28-35: key change to F minor
for i in range(8):
    b = 28 + i
    name = SECTIONS[b]
    mel = MEL_A[i] if i < 7 else "C6:4 Bb5:2 Ab5:2 G5:4 E5:4"
    play_lead(b, mel, transpose=1 if i < 7 else 0, duty=0.25, harm_scale=F_HM)
    play_bass_ost(b, name)
    play_sub(b, name)
    play_arp(b, name, vol=1.0)
    drums(b, K="x..x..x.x..x..x.", S="....x.......x...", H=HAT16, M=CLANK)
hit_crash(28); hit_crash(32)
roll(35, 12, (0.5, 1.0))

# Turnaround 36-39: pivot C -> D -> B, back to E
STAB = [0, 3, 6, 10, 12, 14]
TOPS = {'C': ('G5', 'E5'), 'D': ('A5', 'F#5'), 'B': ('B5', 'F#5')}
for b in (36, 37, 38):
    name = SECTIONS[b]
    top, low = TOPS[name]
    for s in STAB:
        add('lead', T(b, s), pulse_note(nn(top), 2 * STEP * 0.9, 0.25, 0)); mev('Lead', T(b, s), 2 * STEP * 0.9, nn(top))
        add('harm', T(b, s), pulse_note(nn(low), 2 * STEP * 0.9, 0.5, 0)); mev('Harmony', T(b, s), 2 * STEP * 0.9, nn(low))
    play_bass_hits(b, name, [(s, 2, 0) for s in STAB])
    play_sub(b, name, (0,))
    k = ['.'] * 16
    for s in STAB: k[s] = 'x'
    drums(b, K=''.join(k), S="....x.......x...", H=HAT8, M=CLANK)
hit_crash(36)
b = 39
play_lead(b, "B5:16", duty=0.25, vib=0.45)
add('harm', T(b), pulse_note(nn('F#5'), 16 * STEP * 0.95, 0.5, 0.35)); mev('Harmony', T(b), 16 * STEP * 0.95, nn('F#5'))
play_bass_ost(b, 'B', [0, 0, 12, 0] * 4)
play_sub(b, 'B', (0,))
play_arp(b, 'B', every=1, rate=1, duty=0.125, vol=0.8)
drums(b, K="x...x...x.x.x.x.")
roll(39, 0, (0.15, 1.0))
hit_hiss(39, 0, 16 * STEP, up=True)

# ----------------------------------------------------------------- mixdown
def fold(x):
    y = x[:N].copy()
    y[:TAIL] += x[N:N + TAIL]
    return y

def circ(x, sos):  # IIR on a loop without a seam transient
    return ss.sosfilt(sos, np.tile(x, 3))[N:2 * N]

for k in list(buses):
    buses[k] = fold(buses[k])
def B(k): return buses.get(k, np.zeros(N))

# kick sidechain (circular)
gain = np.ones(N)
L = int(0.25 * SR)
tt = np.arange(L) / SR
duck = 1 - 0.6 * np.exp(-tt / 0.07)
for t0 in KICKS:
    idx = (int(round(t0 * SR)) + np.arange(L)) % N
    gain[idx] = np.minimum(gain[idx], duck)

lp_grit = ss.butter(4, 750, 'low', fs=SR, output='sos')
lp_groan = ss.butter(2, 1800, 'low', fs=SR, output='sos')
hp_master = ss.butter(2, 24, 'high', fs=SR, output='sos')

low = (0.42 * B('sub') * gain
       + 0.30 * B('tri')
       + 0.20 * circ(B('grit'), lp_grit) * gain
       + 0.62 * B('kick'))
low = np.tanh(1.5 * low) / 1.5        # glue + harmonics so the bass reads on small speakers

lead = B('lead')
d = int(round(3 * STEP * SR))
echoL = 0.30 * np.roll(lead, d) + 0.10 * np.roll(lead, 3 * d)
echoR = 0.20 * np.roll(lead, 2 * d) + 0.06 * np.roll(lead, 4 * d)

harm, arp = B('harm'), B('arp')
siren = B('siren')
groan_ = circ(B('groan'), lp_groan)
mid = 0.20 * lead
Lch = (low + mid + 0.20 * echoL + 0.085 * harm * 1.3 + 0.10 * arp * 0.7 + 0.07 * siren
       + 0.15 * groan_ + 0.30 * B('snare') + 0.075 * B('hat') * 1.2 + 0.11 * B('clank') * 0.8
       + 0.11 * B('crash') + 0.08 * B('hiss'))
Rch = (low + mid + 0.20 * echoR + 0.085 * harm * 0.7 + 0.10 * arp * 1.3 + 0.07 * np.roll(siren, int(0.012 * SR))
       + 0.15 * groan_ + 0.30 * B('snare') + 0.075 * B('hat') * 0.8 + 0.11 * B('clank') * 1.2
       + 0.11 * np.roll(B('crash'), 37) + 0.08 * np.roll(B('hiss'), 53))
mix = np.stack([circ(Lch, hp_master), circ(Rch, hp_master)], axis=1)

mix = np.tanh(1.2 * mix) / np.tanh(1.2)          # gentle master saturation
mix *= 0.70 / np.max(np.abs(mix))                 # peak ~-3 dBFS, leaves room for game SFX
pcm = np.round(mix * 32767).astype(np.int16)
wavfile.write(os.path.join(OUT, "factory_boss_loop.wav"), SR, pcm)
wavfile.write(os.path.join(OUT, "factory_boss_preview_2x.wav"), SR, np.concatenate([pcm, pcm]))

# ----------------------------------------------------------------- MIDI
PROGS = {'Lead': (0, 80), 'Harmony': (1, 80), 'Arp': (2, 81), 'Bass': (3, 38),
         'Sub': (4, 38), 'Siren': (5, 80), 'FX': (6, 87), 'Drums': (9, 0)}
TPB = 480
def tick(t): return int(round(t / (60 / BPM) * TPB))
mf = mido.MidiFile(ticks_per_beat=TPB)
meta = mido.MidiTrack()
meta.append(mido.MetaMessage('track_name', name='Factory Boss', time=0))
meta.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(BPM), time=0))
meta.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
meta.append(mido.MetaMessage('marker', text='loopStart', time=0))
meta.append(mido.MetaMessage('marker', text='loopEnd', time=tick(BARS * 16 * STEP)))
mf.tracks.append(meta)
for name, (chn, prog) in PROGS.items():
    tr = mido.MidiTrack()
    tr.append(mido.MetaMessage('track_name', name=name, time=0))
    if chn != 9:
        tr.append(mido.Message('program_change', channel=chn, program=prog, time=0))
    evs = []
    for (trk, t0, dur, note, vel) in MIDI:
        if trk != name: continue
        v = max(1, min(127, int(vel * 127)))
        evs.append((tick(t0), 1, mido.Message('note_on', channel=chn, note=note, velocity=v)))
        evs.append((tick(t0 + dur), 0, mido.Message('note_off', channel=chn, note=note, velocity=0)))
    evs.sort(key=lambda e: (e[0], e[1]))
    last = 0
    for tk, _, msg in evs:
        msg.time = tk - last; last = tk
        tr.append(msg)
    mf.tracks.append(tr)
mf.save(os.path.join(OUT, "factory_boss.mid"))
print("rendered", N, "samples =", N / SR, "s; notes:", len(MIDI))
