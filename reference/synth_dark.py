#!/usr/bin/env python3
"""Factory boss fight — DARK version.
E phrygian / harmonic minor, 128 BPM, 32 bars = exactly 60.0 s, seamless loop.
Heavier bass, detuned pulse drones, half-time drums, circular reverb,
and a factory ambience bed mixed underneath the music.
"""
import sys, os
import numpy as np
import scipy.signal as ss
import scipy.io.wavfile as wavfile
import mido

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
os.makedirs(OUT, exist_ok=True)

SR = 44100
BPM = 128
STEP = 60 / BPM / 4
BARS = 32
N = int(round(BARS * 16 * STEP * SR))   # 2,646,000 samples = 60 s
LOOP_S = N / SR
TAIL = int(4 * SR)
rng = np.random.default_rng(13)

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

MIDI = []
def mev(track, t0, dur, note, vel=0.8):
    MIDI.append((track, t0, dur, int(note), vel))

def qframe(t): return np.floor(t * 60) / 60
def q16(v):    return np.round(np.clip(v, 0, 1) * 15) / 15

def lfsr(short):
    reg, out = 1, np.empty(32767)
    tap = 6 if short else 1
    for k in range(32767):
        bit = (reg ^ (reg >> tap)) & 1
        reg = (reg >> 1) | (bit << 14)
        out[k] = 1.0 if reg & 1 else -1.0
    return out
NL, NS = lfsr(False), lfsr(True)

def noise(n, rate, short=False, offset=0):
    seq = NS if short else NL
    rate = np.broadcast_to(np.asarray(rate, float), (n,))
    idx = (np.floor(np.cumsum(rate) / SR).astype(np.int64) + offset) % len(seq)
    return seq[idx]

def pulse_wave(freq, duty):
    ph = np.cumsum(freq) / SR
    return np.where((ph % 1.0) < duty, 1.0, -1.0)

TRI = np.concatenate([np.arange(15, -1, -1), np.arange(0, 16)]) / 7.5 - 1
def tri_wave(freq):
    ph = np.cumsum(freq) / SR
    return TRI[(np.floor(ph * 32) % 32).astype(int)]

def crush(x, factor):
    idx = (np.arange(len(x)) // factor) * factor
    return x[idx]

def fold(x):
    y = x[:N].copy()
    y[:TAIL] += x[N:N + TAIL]
    return y

def circ(x, sos):
    return ss.sosfilt(sos, np.tile(x, 3))[N:2 * N]

def loopf(f):  # snap a continuous oscillator so it completes whole cycles per loop
    return round(f * LOOP_S) / LOOP_S

def bp(lo, hi, order=2): return ss.butter(order, [lo, hi], 'band', fs=SR, output='sos')
def lp(f, order=2):      return ss.butter(order, f, 'low', fs=SR, output='sos')
def hp(f, order=2):      return ss.butter(order, f, 'high', fs=SR, output='sos')

# ----------------------------------------------------------------- voices
def pulse_note(m, dur, duty=0.5, vib=0.3, slide=None, slide_t=0.06,
               rel=0.12, sus=0.7, dec=0.25, vib_rate=5.0):
    n = int((dur + rel) * SR)
    t = np.arange(n) / SR
    tq = qframe(t)
    semis = np.full(n, float(m))
    if slide is not None:
        semis = slide + (m - slide) * np.clip(tq / slide_t, 0, 1)
    if vib and dur > 0.3:
        depth = np.clip((tq - 0.3) / 0.4, 0, 1) * vib
        semis = semis + depth * np.sin(2 * np.pi * vib_rate * tq)
    d = np.where(tq < 2 / 60, 0.25, duty) if duty == 0.5 else duty
    w = pulse_wave(mtof(semis), d)
    lvl = sus + (1 - sus) * np.exp(-dur / dec)
    env = np.where(tq < dur, sus + (1 - sus) * np.exp(-tq / dec),
                   lvl * np.clip(1 - (tq - dur) / rel, 0, 1))
    return w * q16(env)

def arp_note(chord, dur, rate=3, duty=0.125, decay=0.2):
    n = int((dur + 0.02) * SR)
    t = np.arange(n) / SR
    tq = qframe(t)
    k = np.floor(t * 60 / rate).astype(int) % len(chord)
    env = np.where(tq < dur, 0.25 + 0.75 * np.exp(-tq / decay), 0)
    return pulse_wave(mtof(np.asarray(chord)[k]), duty) * q16(env)

def tri_note(m, dur):
    n = int((dur + 0.006) * SR)
    w = tri_wave(np.full(n, mtof(m)))
    g = np.ones(n); r = int(0.006 * SR)
    g[-r:] = np.linspace(1, 0, r)
    return w * g

def grit_note(m, dur):
    n = int((dur + 0.02) * SR)
    t = np.arange(n) / SR
    f = mtof(m) * (1 + 0.03 * np.exp(-t / 0.02))           # tiny pitch "bite"
    w = 0.6 * pulse_wave(f, 0.25) + 0.4 * pulse_wave(f * 1.004, 0.5)
    env = np.where(t < dur, 0.55 + 0.45 * np.exp(-t / 0.12),
                   0.55 * np.clip(1 - (t - dur) / 0.02, 0, 1))
    return w * env

def sub_note(m, dur, attack=0.005, rel=0.06):
    n = int((dur + rel) * SR)
    t = np.arange(n) / SR
    w = np.sin(2 * np.pi * mtof(m) * t)
    env = np.clip(t / attack, 0, 1) * np.where(t < dur, 1, np.clip(1 - (t - dur) / rel, 0, 1))
    return w * env

def drone_note(m, dur, att=0.35, rel=0.5):
    """two detuned PWM pulses + fifth: slow beating dread"""
    n = int((dur + rel) * SR)
    t = np.arange(n) / SR
    tq = qframe(t)
    duty = 0.5 + 0.18 * np.sin(2 * np.pi * 0.21 * t)
    f = mtof(m)
    w = (pulse_wave(np.full(n, f * 0.9965), duty) + pulse_wave(np.full(n, f * 1.0035), 1 - duty)
         + 0.55 * pulse_wave(np.full(n, mtof(m + 7) * 1.002), 0.5))
    env = np.clip(tq / att, 0, 1) * np.where(tq < dur, 1, np.clip(1 - (tq - dur) / rel, 0, 1))
    env *= 0.8 + 0.2 * np.sin(2 * np.pi * 0.37 * tq)
    return w * q16(env) / 2.55

def eerie(ms, dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    tq = qframe(t)
    w = sum(pulse_wave(mtof(m + 0.12 * np.sin(2 * np.pi * 4.3 * tq + i)), 0.125) for i, m in enumerate(ms))
    env = np.sin(np.pi * np.clip(tq / dur, 0, 1)) ** 1.5
    return w * q16(env) / len(ms)

def groan(m0, m1, dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    tq = qframe(t)
    semis = m0 + (m1 - m0) * (tq / dur) ** 0.6 + 0.7 * np.sin(2 * np.pi * 6 * tq)
    w = pulse_wave(mtof(semis), 0.5) * 0.65 + noise(n, mtof(semis) * 93 / 4, True) * 0.35
    env = np.clip(tq / 0.15, 0, 1) * np.clip(1 - tq / dur, 0, 1) ** 0.7
    return w * q16(env)

def kick(v=1.0):
    n = int(0.5 * SR)
    t = np.arange(n) / SR
    f = 38 + (170 - 38) * np.exp(-t / 0.03)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.30)
    click = tri_wave(np.full(n, 250.0)) * np.exp(-t / 0.005)
    return np.round((body + 0.35 * click) * 24) / 24 * v

def snare(v=1.0):
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    tq = qframe(t)
    nz = noise(n, 13000) * q16(np.exp(-tq / 0.12))
    tone = tri_wave(150 * np.exp(-t / 0.1)) * np.exp(-t / 0.05)
    return crush(nz * 0.8 + tone * 0.7, 2) * v

def tick(v=1.0):
    n = int(0.03 * SR)
    t = np.arange(n) / SR
    x = np.diff(noise(n, 44100), prepend=0) * 0.5
    return x * np.exp(-t / 0.008) * v

def clank(v=1.0):
    n = int(0.3 * SR)
    t = np.arange(n) / SR
    tq = qframe(t)
    ring = pulse_wave(np.full(n, 311.0), 0.5) * pulse_wave(np.full(n, 467.0), 0.5)
    metal = noise(n, 30000, True)
    return crush((ring * 0.6 + metal * 0.4) * q16(np.exp(-tq / 0.08)), 2) * v

def crash():
    n = int(2.2 * SR)
    t = np.arange(n) / SR
    return noise(n, 20000) * q16(np.exp(-qframe(t) / 0.7))

def hiss(dur=0.6, up=False):
    n = int(dur * SR)
    t = np.arange(n) / SR
    tq = qframe(t)
    a, b = (2000, 20000) if up else (20000, 2000)
    rate = a * (b / a) ** (tq / dur)
    env = np.clip(tq / 0.03, 0, 1) * (tq / dur if up else np.exp(-tq / (dur * 0.4)))
    return noise(n, rate) * q16(env)

# ----------------------------------------------------------------- music data
CH = {'Em': (4, 'm'), 'C': (0, 'M'), 'Am': (9, 'm'), 'B': (11, 'M'), 'F': (5, 'M')}
def chord_tones(name, base):
    pc, q = CH[name]
    r = base + (pc - base) % 12
    return [r, r + (3 if q == 'm' else 4), r + 7, r + 12]
def tri_root(name): return 40 + (CH[name][0] - 4) % 12   # E2..D#3
def sub_root(name): return 28 + (CH[name][0] - 4) % 12   # E1..D#2

E_HM = [4, 5, 7, 9, 11, 0, 3]   # E phrygian-dominant-ish colour (b2, #7)
def third_below(m, scale):
    if m % 12 not in scale:
        return m - 3
    i = scale.index(m % 12)
    pc = scale[(i - 2) % 7]
    return m - ((m - pc) % 12 or 12)

def parse(bar_str):
    out, s = [], 0
    for tok in bar_str.split():
        slide = tok.startswith('~')
        name, ln = tok.lstrip('~').split(':')
        ln = float(ln)
        if name != 'r':
            out.append((s, ln, nn(name), slide))
        s += ln
    assert abs(s - 16) < 1e-9, (bar_str, s)
    return out

MEL = [
    "E4:6 F4:2 E4:4 D4:2 B3:2",
    "E4:12 r:4",
    "A4:6 G4:2 F4:4 E4:4",
    "F4:12 r:4",
    "B4:6 C5:2 B4:4 A4:2 G4:2",
    "G4:8 F#4:4 E4:4",
    "C5:6 B4:2 G4:4 E4:4",
    "D#4:8 F#4:4 A4:4",
]
MEL2 = list(MEL)
MEL2[1] = "E4:8 ~F4:4 E4:4"
MEL2[3] = "F4:8 ~E4:4 F4:4"
MEL2[7] = "D#4:4 F#4:4 A4:4 B4:4"
TURN = ["E4:6 F4:2 E4:4 D4:2 B3:2", "F4:6 A4:2 G4:4 F4:4",
        "C5:6 B4:2 G4:4 E4:4", "D#4:8 F#4:4 A4:4"]

SECTIONS = (['Em', 'Em', 'Em', 'F'] +                                   # 0-3   intro
            ['Em', 'Em', 'F', 'F', 'Em', 'Em', 'C', 'B'] +             # 4-11  A
            ['Em', 'Em', 'F', 'F', 'Em', 'Em', 'C', 'B'] +             # 12-19 A'
            ['C', 'C', 'B', 'B', 'Am', 'Am', 'F', 'B'] +               # 20-27 break
            ['Em', 'F', 'C', 'B'])                                       # 28-31 turnaround
assert len(SECTIONS) == BARS

RIFF_E = [(0, 3, 0), (3, 3, 0), (6, 2, 12), (8, 3, 0), (11, 3, 1), (14, 2, 0)]   # tresillo + b2
RIFF_P = [(0, 3, 0), (3, 3, 0), (6, 2, 12), (8, 6, 0), (14, 2, -1)]

# ----------------------------------------------------------------- writers
def play_lead(bar, bar_str, harm=False, bus='lead'):
    prev = None
    for s, ln, m, slide in parse(bar_str):
        t0, dur = T(bar, s), ln * STEP * 0.95
        add(bus, t0, pulse_note(m, dur, 0.5, 0.32, slide=prev if slide else None, slide_t=0.12))
        mev('Lead', t0, dur, m, 0.8)
        if harm:
            h = third_below(m, E_HM)
            add('harm', t0, pulse_note(h, dur, 0.25, 0.25))
            mev('Harmony', t0, dur, h, 0.6)
        prev = m

def play_bass(bar, name, hits=None):
    if hits is None:
        hits = RIFF_E if name == 'Em' else RIFF_P
    r = tri_root(name)
    for s, ln, off in hits:
        t0, dur = T(bar, s), ln * STEP * 0.88
        add('tri', t0, tri_note(r + off, dur))
        add('grit', t0, grit_note(r + off, dur))
        mev('Bass', t0, dur, r + off, 0.85)

def play_sub(bar, name, attack=0.005):
    m = sub_root(name)
    add('sub', T(bar), sub_note(m, 16 * STEP * 0.98, attack))
    mev('Sub', T(bar), 16 * STEP * 0.98, m, 0.9)

def play_arp(bar, name, every=4, rate=3, duty=0.125, vol=1.0, base=52):
    ch = chord_tones(name, base)
    for s in range(0, 16, every):
        t0, dur = T(bar, s), every * STEP * 0.85
        add('arp', t0, arp_note(ch, dur, rate, duty) * vol)
        mev('Arp', t0, dur, ch[(s // every) % 4], 0.5 * vol)

# drones: merge consecutive identical chords into long held notes
runs, i = [], 0
while i < BARS:
    j = i
    while j + 1 < BARS and SECTIONS[j + 1] == SECTIONS[i]:
        j += 1
    runs.append((i, j - i + 1, SECTIONS[i]))
    i = j + 1
for b0, nb, name in runs:
    m = tri_root(name)
    add('drone', T(b0), drone_note(m, nb * 16 * STEP + 0.05))
    mev('Drone', T(b0), nb * 16 * STEP, m, 0.6)
    mev('Drone', T(b0), nb * 16 * STEP, m + 7, 0.5)

KICKS = []
DR = {'K': 36, 'S': 38, 'H': 42, 'M': 56}
def drums(bar, **pats):
    for key, pat in pats.items():
        for s, c in enumerate(pat):
            if c == '.':
                continue
            v = {'x': 1.0, 'o': 0.55, 'g': 0.3}[c]
            t0 = T(bar, s)
            if key == 'K':
                add('kick', t0, kick(v)); KICKS.append((t0, v))
            elif key == 'S':
                add('snare', t0, snare(v))
            elif key == 'H':
                add('hat', t0, tick(v))
            elif key == 'M':
                add('clank', t0, clank(v))
            mev('Drums', t0, 0.1, DR[key], 0.35 + 0.55 * v)

def roll(bar, start=8, ramp=(0.2, 1.0), every=1):
    steps = list(range(start, 16, every))
    for i, s in enumerate(steps):
        v = ramp[0] + (ramp[1] - ramp[0]) * i / max(1, len(steps) - 1)
        add('snare', T(bar, s), snare(v)); mev('Drums', T(bar, s), 0.1, 38, 0.3 + 0.6 * v)

def hit_crash(bar):
    add('crash', T(bar), crash()); mev('Drums', T(bar), 0.5, 49, 0.8)

def hit_hiss(bar, step=0, dur=0.6, up=False):
    add('hiss', T(bar, step), hiss(dur, up)); mev('Drums', T(bar, step), dur, 52, 0.5)

# ----------------------------------------------------------------- arrangement
# Intro 0-3: the furnace wakes
add('groan', T(0), groan(40, 28, 3.6)); mev('FX', T(0), 3.6, 40, 0.8)
for b in range(4):
    play_sub(b, SECTIONS[b], attack=1.2 if b == 0 else 0.005)
drums(1, K="x..o............")
for b in (2, 3):
    play_bass(b, SECTIONS[b])
    drums(b, K="x..o......x.....", H="..g...g...g...g.")
for b, (a, z) in ((2, ('E4', 'F4')), (3, ('E4', 'F4'))):     # low dark alarm
    add('siren', T(b), pulse_note(nn(z), 16 * STEP * 0.95, 0.125, 0, slide=nn(a), slide_t=0.9, sus=0.8))
    mev('Siren', T(b), 16 * STEP * 0.95, nn(z), 0.4)
roll(3, 12, (0.2, 0.7))
hit_hiss(3, 8, 8 * STEP, up=True)

# A 4-11, A' 12-19
for i in range(8):
    for b, mel, harm in ((4 + i, MEL[i], False), (12 + i, MEL2[i], True)):
        name = SECTIONS[b]
        play_lead(b, mel, harm)
        play_bass(b, name)
        play_sub(b, name)
        if harm:
            drums(b, K="x.....o.x.x.....", S="........x.......", H="g.g.g.g.g.g.g.g.",
                  M=".....o........x.")
            if b >= 16:
                play_arp(b, name)
        else:
            drums(b, K="x.......x.x.....", S="........x.......", H="..g...g...g...g.",
                  M=".....o........o.")
hit_crash(4); hit_crash(12)
roll(11, 14, (0.3, 0.6))
roll(19, 12, (0.3, 0.9))

# Break 20-27: only the machine's heartbeat
for i in range(8):
    b = 20 + i
    name = SECTIONS[b]
    play_bass(b, name, [(0, 12, 0), (12, 4, 12)] if b < 26 else None)
    play_sub(b, name)
    if b >= 22:
        play_arp(b, name, every=2, rate=4, duty=0.25, vol=0.7, base=52)
    if b < 26:
        drums(b, K="x..o............", M="..........o.....")
add('eerie', T(20), eerie([nn('E5'), nn('F5')], 6 * 16 * STEP)); mev('Eerie', T(20), 6 * 16 * STEP, nn('E5'), 0.4)
add('groan', T(20), groan(48, 33, 3.2)); mev('FX', T(20), 3.2, 48, 0.8)
add('groan', T(24), groan(45, 30, 3.2)); mev('FX', T(24), 3.2, 45, 0.8)
hit_crash(20)
drums(26, K="x...x...x...x...", S="........x.......", H="..g...g...g...g.")
drums(27, K="x...x...x...x...", H="g.g.g.g.g.g.g.g.")
roll(27, 0, (0.15, 1.0), every=2)
roll(27, 8, (0.4, 1.0))
hit_hiss(27, 0, 16 * STEP, up=True)

# Turnaround 28-31: full weight, back into the intro
for i in range(4):
    b = 28 + i
    name = SECTIONS[b]
    play_lead(b, TURN[i], harm=True)
    play_bass(b, name)
    play_sub(b, name)
    play_arp(b, name, every=2, rate=3)
    drums(b, K="x.....o.x.x...o.", S="....x.......x...", H="g.g.g.g.g.g.g.g.",
          M=".....o........x.")
hit_crash(28)
roll(31, 8, (0.3, 1.0))

# ----------------------------------------------------------------- factory ambience
AMB_L, AMB_R = [], []
def amb_event(t0, sig, pan=0.0, wet=0.5):
    """place an ambience one-shot, folded into the loop"""
    for name, g in (('ambL', (1 - pan) / 2), ('ambR', (1 + pan) / 2)):
        add(name, t0, sig * g * (1 - wet) * 2)
        add(name + '_wet', t0, sig * g * wet * 2)

def piston():
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    thunk = noise(n, 3500) * np.exp(-t / 0.045)
    chuff = noise(n, 16000, offset=777) * np.clip((t - 0.06) / 0.03, 0, 1) * np.exp(-np.clip(t - 0.06, 0, None) / 0.12)
    return crush(thunk * 0.9 + chuff * 0.35, 3)

def stamp():
    n = int(1.4 * SR)
    t = np.arange(n) / SR
    fr = [173, 251, 389, 547, 733, 1013]
    x = sum(np.sin(2 * np.pi * f * t) * np.exp(-t / (0.55 / (k + 1) ** 0.5)) for k, f in enumerate(fr)) / 3
    x += noise(n, 9000) * np.exp(-t / 0.03) * 0.6
    return crush(x, 2)

def distant_clang(base):
    n = int(2.0 * SR)
    t = np.arange(n) / SR
    ratios = [1, 1.59, 2.14, 2.83, 3.71]
    return sum(np.sin(2 * np.pi * base * r * t) * np.exp(-t / (0.9 / r)) for r in ratios) / 3

def vent(dur=1.8):
    n = int(dur * SR)
    t = np.arange(n) / SR
    env = np.clip(t / 0.15, 0, 1) * np.exp(-t / (dur * 0.35))
    return noise(n, 18000, offset=int(rng.integers(30000))) * env

def rattle(v):
    n = int(0.02 * SR)
    t = np.arange(n) / SR
    return np.diff(noise(n, 44100, offset=int(rng.integers(30000))), prepend=0) * np.exp(-t / 0.004) * v

# pistons on beats 2 & 4 (8-step period divides the loop -> seamless)
for s in range(4, BARS * 16, 8):
    amb_event(s * STEP, piston() * 0.8, pan=-0.35, wet=0.45)
# heavy press stamp every 2 bars, off the grid of the kick/snare
for b in range(1, BARS, 2):
    amb_event(T(b, 6), stamp() * 0.6, pan=0.4, wet=0.65)
# conveyor rattle: 16th ticks with random intensity
for s in range(BARS * 16):
    amb_event(s * STEP + rng.uniform(0, 0.006), rattle(rng.uniform(0.15, 0.6)), pan=0.6, wet=0.2)
# distant metal clangs at irregular times
t = 1.3
while t < LOOP_S - 0.5:
    amb_event(t, distant_clang(rng.uniform(260, 620)) * rng.uniform(0.4, 0.8),
              pan=rng.uniform(-0.8, 0.8), wet=0.9)
    t += rng.uniform(3.2, 6.0)
# steam vents
for b in (6, 14, 22, 30):
    amb_event(T(b, 8), vent(), pan=rng.choice([-0.7, 0.7]), wet=0.4)

# continuous beds (generated full-length and filtered circularly -> seamless)
tt = np.arange(N) / SR
def bed(seed):
    r = np.random.default_rng(seed)
    rumble = circ(r.standard_normal(N), bp(90, 280)) * (0.8 + 0.2 * np.sin(2 * np.pi * (3 / LOOP_S) * tt))
    air = circ(r.standard_normal(N), bp(400, 1500)) * 0.25 * (0.7 + 0.3 * np.sin(2 * np.pi * (5 / LOOP_S) * tt + seed))
    return rumble * 3.0 + air
hum_f = loopf(mtof(52))   # electrical hum tuned to E3 so it sits in key
hum = (pulse_wave(np.full(N, hum_f), 0.5) * 0.5 + np.sin(2 * np.pi * 2 * hum_f * tt) * 0.3) \
      * (0.85 + 0.15 * np.sin(2 * np.pi * (7 / LOOP_S) * tt))
hum = circ(hum, bp(140, 900))
buses['bedL'] = np.concatenate([bed(1) + hum * 0.35, np.zeros(TAIL)])
buses['bedR'] = np.concatenate([bed(2) + hum * 0.35, np.zeros(TAIL)])

# ----------------------------------------------------------------- mixdown
for k in list(buses):
    buses[k] = fold(buses[k])
def B(k): return buses.get(k, np.zeros(N))

# circular convolution reverb (seamless by construction)
def make_ir(sec, decay, seed):
    r = np.random.default_rng(seed)
    n = int(sec * SR)
    t = np.arange(n) / SR
    ir = r.standard_normal(n) * np.exp(-t / decay)
    ir = ss.sosfilt(lp(3500), ir)
    ir[:int(0.012 * SR)] = 0                     # pre-delay
    return ir / np.sqrt(np.sum(ir ** 2))
IR_L, IR_R = make_ir(2.6, 0.55, 3), make_ir(2.6, 0.55, 4)
def reverb(x, ir):
    h = np.zeros(N); h[:len(ir)] = ir
    return np.fft.irfft(np.fft.rfft(x) * np.fft.rfft(h), N)

# kick sidechain (circular)
gain = np.ones(N)
L = int(0.3 * SR)
ta = np.arange(L) / SR
for t0, v in KICKS:
    idx = (int(round(t0 * SR)) + np.arange(L)) % N
    gain[idx] = np.minimum(gain[idx], 1 - 0.45 * v * np.exp(-ta / 0.09))

drone = circ(B('drone'), lp(1100, 4))
grit = circ(B('grit'), lp(520, 4))
low = (0.50 * B('sub') * gain + 0.24 * B('tri') + 0.34 * grit * gain
       + 0.60 * B('kick') + 0.30 * drone * (0.6 + 0.4 * gain))
low = np.tanh(1.7 * low) / 1.7

lead = circ(B('lead'), lp(2600))
harm = circ(B('harm'), lp(2200))
arp = circ(B('arp'), lp(2400))
groan_ = circ(B('groan'), lp(1500))
d = int(round(3 * STEP * SR))
echoL = 0.32 * np.roll(lead, d) + 0.12 * np.roll(lead, 3 * d)
echoR = 0.22 * np.roll(lead, 2 * d) + 0.07 * np.roll(lead, 4 * d)

send = (0.30 * lead + 0.25 * harm + 0.35 * arp + 0.6 * B('snare') + 0.8 * B('clank')
        + 0.2 * drone + 0.25 * groan_ + 0.25 * B('eerie') + 0.4 * B('siren') + 0.3 * B('crash'))
revL, revR = reverb(send, IR_L), reverb(send, IR_R)

common = (low + 0.17 * lead + 0.16 * groan_ + 0.26 * B('snare') + 0.05 * B('eerie')
          + 0.06 * circ(B('siren'), lp(2000)) + 0.06 * circ(B('crash'), lp(6000)) + 0.05 * B('hiss'))
musL = common + 0.14 * echoL + 0.07 * harm * 1.3 + 0.06 * arp * 0.7 + 0.05 * B('hat') * 1.2 \
       + 0.09 * B('clank') * 0.8 + 0.16 * revL
musR = common + 0.14 * echoR + 0.07 * harm * 0.7 + 0.06 * arp * 1.3 + 0.05 * B('hat') * 0.8 \
       + 0.09 * B('clank') * 1.2 + 0.16 * revR

# ambience bus: dry + its own (bigger) reverb, darkened, kept well under the music
amb_lp = lp(5000)
ambL = circ(B('ambL') + 0.9 * reverb(B('ambL_wet') + B('ambR_wet') * 0.3, IR_L) + B('bedL'), amb_lp)
ambR = circ(B('ambR') + 0.9 * reverb(B('ambR_wet') + B('ambL_wet') * 0.3, IR_R) + B('bedR'), amb_lp)
ambL = circ(ambL, hp(70)); ambR = circ(ambR, hp(70))      # keep it out of the sub range

def rms(x): return np.sqrt(np.mean(x ** 2))
AMB_DB = -19.0   # ambience level relative to the music
g_amb = 10 ** (AMB_DB / 20) * rms(musL + musR) / rms(ambL + ambR)
ambL *= g_amb; ambR *= g_amb

hpm = hp(24)
def master(L_, R_, g=None):
    m = np.stack([circ(L_, hpm), circ(R_, hpm)], axis=1)
    m = np.tanh(1.15 * m) / np.tanh(1.15)
    if g is None:
        g = 0.70 / np.max(np.abs(m))
    return m * g, g

full, g = master(musL + ambL, musR + ambR)
music_only, _ = master(musL, musR, g)
amb_only, _ = master(ambL, ambR, g)

def wr(name, x):
    wavfile.write(os.path.join(OUT, name), SR, np.round(np.clip(x, -1, 1) * 32767).astype(np.int16))
wr("factory_boss_dark_loop.wav", full)
wr("factory_boss_dark_music_only.wav", music_only)
wr("factory_ambience_loop.wav", amb_only)
wr("factory_boss_dark_preview_2x.wav", np.concatenate([full, full]))
print("music rms", rms(musL + musR), "amb rms", rms(ambL + ambR), "gain", g)

# ----------------------------------------------------------------- MIDI
PROGS = {'Lead': (0, 80), 'Harmony': (1, 80), 'Arp': (2, 80), 'Bass': (3, 38),
         'Sub': (4, 38), 'Drone': (5, 89), 'Siren': (6, 80), 'Eerie': (7, 97),
         'FX': (8, 87), 'Drums': (9, 0)}
TPB = 480
def tk(t): return int(round(t / (60 / BPM) * TPB))
mf = mido.MidiFile(ticks_per_beat=TPB)
meta = mido.MidiTrack()
meta.append(mido.MetaMessage('track_name', name='Factory Boss (Dark)', time=0))
meta.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(BPM), time=0))
meta.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
meta.append(mido.MetaMessage('marker', text='loopStart', time=0))
meta.append(mido.MetaMessage('marker', text='loopEnd', time=tk(LOOP_S)))
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
        evs.append((tk(t0), 1, mido.Message('note_on', channel=chn, note=note, velocity=v)))
        evs.append((tk(t0 + dur), 0, mido.Message('note_off', channel=chn, note=note, velocity=0)))
    evs.sort(key=lambda e: (e[0], e[1]))
    last = 0
    for tick_, _, msg in evs:
        msg.time = tick_ - last; last = tick_
        tr.append(msg)
    mf.tracks.append(tr)
mf.save(os.path.join(OUT, "factory_boss_dark.mid"))
print("rendered", N / SR, "s; notes:", len(MIDI))
