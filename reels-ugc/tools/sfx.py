#!/usr/bin/env python3
"""Piste de bruitages à partir des listes de scènes.

Usage :
  python3 tools/sfx.py out.wav --duration 45 compositions/frames/01-hook.sfx.json:0 02-x.sfx.json:6.4 ...

Chaque fichier .sfx.json : [{"t": 1.20, "sound": "whoosh", "vol": 0.5}, ...]
  - t     : temps LOCAL à la scène (s) ; l'offset après ":" est le début de la scène dans la vidéo
  - sound : nom d'un fichier de la bibliothèque (sans .mp3) ou chemin vers un fichier audio
  - vol   : 0..1 (gain linéaire, 0.3–0.6 = subtil)
Bibliothèque : .agents/skills/media-use/audio/assets/sfx (licence Pixabay, voir CREDITS.md).
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np
import soundfile as sf

SR = 44100
HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", ".agents", "skills", "media-use", "audio", "assets", "sfx")
_cache = {}


def load(sound):
    if sound in _cache:
        return _cache[sound]
    path = sound if os.path.exists(sound) else os.path.join(LIB, sound + ".mp3")
    if not os.path.exists(path):
        sys.exit(f"bruitage introuvable : {sound} (dispo : {', '.join(sorted(f[:-4] for f in os.listdir(LIB) if f.endswith('.mp3')))})")
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"],
                         check=True, capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).copy()
    _cache[sound] = x
    return x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("lists", nargs="+", help="fichier.sfx.json[:offset]")
    a = ap.parse_args()

    n = int(a.duration * SR)
    out = np.zeros((n, 2), dtype=np.float32)
    count = 0
    for spec in a.lists:
        path, _, off = spec.rpartition(":") if ":" in spec else (spec, "", "0")
        if not path:
            path, off = spec, "0"
        offset = float(off)
        with open(path, encoding="utf-8") as f:
            events = json.load(f)
        for e in events:
            x = load(e["sound"]) * float(e.get("vol", 0.5))
            i = int(round((offset + float(e["t"])) * SR))
            if i < 0 or i >= n:
                continue
            seg = x[: n - i]
            out[i:i + len(seg)] += seg
            count += 1
    peak = float(np.abs(out).max())
    if peak > 0.98:
        out *= 0.98 / peak
    sf.write(a.out, out, SR, subtype="PCM_16")
    print(f"{count} bruitages -> {a.out}")


if __name__ == "__main__":
    main()
