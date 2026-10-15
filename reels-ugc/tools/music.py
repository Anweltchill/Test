#!/usr/bin/env python3
"""Fond musical libre de droits, synthétisé (numpy), style Reels.

Usage :
  python3 tools/music.py out.wav --duration 45 [--bpm 118] [--seed 7]
         [--sections "0:intro,4:drop,20:break,24:drop,40:outro"] [--key A]

Sections (temps en secondes -> énergie) :
  intro  : pad + hats légers          drop  : kick, clap, hats, basse, accords
  break  : pad + basse douce          build : drop sans basse + roulement montant
  outro  : drop allégé qui s'éteint, fin propre sur la mesure
Sans --sections : intro 1 mesure, drop, break au milieu, outro sur les 2 dernières mesures.
Le niveau sort volontairement bas (crête -6 dB) : le mixage (tools/mix.sh) fait le ducking.
"""
import argparse

import numpy as np
import soundfile as sf

SR = 44100
NOTES = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
# progression vi-IV-I-V (pop, positive), en degrés depuis la tonique majeure
PROG = [(9, "m"), (5, "M"), (0, "M"), (7, "M")]


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def env(n, a=0.005, r=0.2):
    t = np.arange(n) / SR
    e = np.minimum(1, t / max(a, 1e-4)) * np.exp(-t / max(r, 1e-4))
    return e


def kick(n):
    t = np.arange(n) / SR
    f = 50 + 110 * np.exp(-t * 30)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.exp(-t * 7) * 0.9


def clap(n, rng):
    noise = rng.standard_normal(n)
    t = np.arange(n) / SR
    e = np.exp(-t * 22) + 0.5 * np.exp(-((t - 0.012) % 0.011) * 300) * (t < 0.035)
    # passe-bande grossier : différence de deux lissages
    hp = noise - np.convolve(noise, np.ones(8) / 8, mode="same")
    return hp * e * 0.35


def hat(n, rng, open_=False):
    noise = rng.standard_normal(n)
    hp = noise - np.convolve(noise, np.ones(3) / 3, mode="same")
    t = np.arange(n) / SR
    return hp * np.exp(-t * (14 if open_ else 60)) * 0.12


def saw(f, n, detune=0.0):
    t = np.arange(n) / SR
    out = np.zeros(n)
    for d in (-detune, 0, detune):
        ph = (t * f * (1 + d)) % 1.0
        out += 2 * ph - 1
    return out / 3


def lowpass(x, k):
    if k <= 1:
        return x
    return np.convolve(x, np.ones(k) / k, mode="same")


def chord_notes(root_midi, deg, q):
    r = root_midi + deg
    third = 3 if q == "m" else 4
    return [r, r + third, r + 7, r + 12]


def parse_sections(s, dur, bar):
    if s:
        out = []
        for part in s.split(","):
            t, name = part.split(":")
            out.append((float(t), name.strip()))
        return sorted(out)
    mid = dur / 2
    return [(0, "intro"), (bar, "drop"), (mid - bar, "break"), (mid, "drop"), (max(mid + bar, dur - 2 * bar), "outro")]


def section_at(secs, t):
    cur = secs[0][1]
    for st, name in secs:
        if t >= st - 1e-6:
            cur = name
    return cur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--bpm", type=float, default=118)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--key", default="A")
    ap.add_argument("--sections", default="")
    a = ap.parse_args()

    rng = np.random.default_rng(a.seed)
    beat = 60.0 / a.bpm
    bar = 4 * beat
    # durée arrondie à la mesure supérieure pour finir proprement, puis coupée
    nbars = int(np.ceil(a.duration / bar))
    total = int((nbars * bar + 1.5) * SR)
    L = np.zeros(total)
    R = np.zeros(total)
    secs = parse_sections(a.sections, a.duration, bar)
    root = 45 + NOTES[a.key.upper()] % 12  # tonique grave (A2 = 45)

    def add(sig, t, gl=1.0, gr=1.0):
        i = int(t * SR)
        if i >= total:
            return
        sig = sig[: total - i]
        L[i:i + len(sig)] += sig * gl
        R[i:i + len(sig)] += sig * gr

    for b in range(nbars):
        t0 = b * bar
        deg, q = PROG[b % len(PROG)]
        notes = chord_notes(root + 12, deg, q)
        sec = section_at(secs, t0)
        last = b == nbars - 1
        # pad (toujours), plus doux en drop
        n = int(bar * SR)
        pad = sum(saw(hz(m), n, 0.004) for m in notes) / len(notes)
        pad = lowpass(pad, 24 if sec in ("intro", "break") else 14)
        pe = np.minimum(1, np.arange(n) / (0.25 * SR)) * np.minimum(1, (n - np.arange(n)) / (0.1 * SR))
        lvl = {"intro": 0.22, "break": 0.24, "drop": 0.14, "build": 0.16, "outro": 0.14}.get(sec, 0.15)
        add(pad * pe * lvl, t0, 0.9, 1.0)
        for k in range(4):
            tb = t0 + k * beat
            s_here = section_at(secs, tb)
            full = s_here in ("drop", "build", "outro")
            if s_here == "outro" and last and k > 0:
                continue  # fin nette : un dernier temps fort puis la queue du pad
            if full:
                add(kick(int(0.4 * SR)), tb)
                if k in (1, 3):
                    add(clap(int(0.25 * SR), rng), tb, 0.95, 1.0)
            # hats en croches
            if s_here != "break":
                for h in range(2):
                    th = tb + h * beat / 2
                    o = h == 1 and full
                    add(hat(int(0.15 * SR), rng, open_=o) * (1.0 if full else 0.6), th, 0.8 if h else 1.0, 1.0 if h else 0.8)
            # basse : croches sur la fondamentale, pompée par le kick
            if s_here in ("drop", "outro", "break"):
                for h in range(2):
                    th = tb + h * beat / 2
                    nb = int(beat / 2 * SR)
                    f = hz(root + deg - (12 if deg > 6 else 0))
                    tt = np.arange(nb) / SR
                    bs = np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(4 * np.pi * f * tt)
                    bs *= env(nb, 0.01 if h else 0.06, 0.25) * (0.35 if s_here == "break" else 0.45)
                    add(bs, th)
        # roulement de build sur la dernière mesure avant un drop
        if sec == "build":
            for k in range(16):
                add(clap(int(0.12 * SR), rng) * (0.3 + k / 20), t0 + k * bar / 16)
        # pluck mélodique léger en drop (arpège)
        if sec == "drop":
            for k in range(8):
                m = notes[[0, 2, 1, 3, 2, 1, 3, 2][k]] + 12
                nb = int(0.3 * SR)
                tt = np.arange(nb) / SR
                pl = np.sin(2 * np.pi * hz(m) * tt) * env(nb, 0.003, 0.12) * 0.08
                add(pl, t0 + k * beat / 2, 1.0 if k % 2 else 0.6, 0.6 if k % 2 else 1.0)

    mix = np.stack([L, R], axis=1)
    end = int(a.duration * SR)
    mix = mix[:end]
    # fondu de sortie court pour finir proprement
    fade = int(min(1.2, a.duration / 4) * SR)
    mix[-fade:] *= np.linspace(1, 0, fade)[:, None] ** 2
    peak = np.abs(mix).max() or 1.0
    mix = mix / peak * 10 ** (-6 / 20)
    sf.write(a.out, mix.astype(np.float32), SR, subtype="PCM_16")
    print(f"musique {a.duration:.1f}s @ {a.bpm:.0f} BPM -> {a.out} ; sections : {secs}")


if __name__ == "__main__":
    main()
