#!/usr/bin/env python3
"""Transcription locale mot à mot (Parakeet TDT v3 via sherpa-onnx).

Usage : python3 tools/asr.py <voix.mp3> <mots.json> [--model models/parakeet]

Sortie JSON : {"duration": s, "words": [{"word": "...", "start": s, "end": s}, ...]}
- l'audio est découpé en fenêtres d'environ 20 s, coupées sur les silences ;
- les tokens sont regroupés en mots (un token qui commence par une espace ouvre un mot) ;
- "end" = début du mot suivant (ou fin estimée), utile pour les sous-titres.
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np

SR = 16000
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL = os.path.join(HERE, "..", "models", "parakeet")


def load_audio(path):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def split_points(audio, target=20.0, search=4.0):
    """Points de coupe proches de `target` secondes, placés au creux d'énergie."""
    hop = int(0.01 * SR)
    n = len(audio) // hop
    if n == 0:
        return [0, len(audio)]
    frames = audio[: n * hop].reshape(n, hop)
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    # lissage sur 100 ms pour trouver de vrais silences
    k = 10
    rms = np.convolve(rms, np.ones(k) / k, mode="same")
    cuts = [0]
    pos = 0
    total = len(audio) / SR
    while total - pos / SR > target + search:
        lo = int((pos / SR + target - search) * 100)
        hi = int((pos / SR + target + search) * 100)
        hi = min(hi, n - 1)
        idx = lo + int(np.argmin(rms[lo:hi]))
        pos = idx * hop
        cuts.append(pos)
    cuts.append(len(audio))
    return cuts


def make_recognizer(model_dir):
    import sherpa_onnx

    m = lambda f: os.path.join(model_dir, f)
    return sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=m("encoder.int8.onnx"),
        decoder=m("decoder.int8.onnx"),
        joiner=m("joiner.int8.onnx"),
        tokens=m("tokens.txt"),
        num_threads=max(1, (os.cpu_count() or 2) // 2),
        model_type="nemo_transducer",
        decoding_method="greedy_search",
    )


def to_words(tokens, times, offset):
    words = []
    for tok, t in zip(tokens, times):
        tok = tok.replace("▁", " ")
        if not tok.strip():
            if tok.startswith(" ") and words:
                words.append({"word": "", "start": round(offset + t, 3)})
            continue
        if tok.startswith(" ") or not words or words[-1]["word"] == "":
            if words and words[-1]["word"] == "":
                words[-1]["word"] = tok.strip()
            else:
                words.append({"word": tok.strip(), "start": round(offset + t, 3)})
        else:
            words[-1]["word"] += tok
    return [w for w in words if w["word"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("out")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--window", type=float, default=20.0)
    args = ap.parse_args()

    if not os.path.exists(os.path.join(args.model, "encoder.int8.onnx")):
        sys.exit(f"Modèle introuvable dans {args.model} : lance d'abord tools/setup.sh")

    audio = load_audio(args.audio)
    rec = make_recognizer(args.model)
    cuts = split_points(audio, target=args.window)
    words = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        s = rec.create_stream()
        s.accept_waveform(SR, audio[a:b])
        rec.decode_stream(s)
        r = s.result
        words += to_words(list(r.tokens), list(r.timestamps), a / SR)

    duration = round(len(audio) / SR, 3)
    for i, w in enumerate(words):
        nxt = words[i + 1]["start"] if i + 1 < len(words) else duration
        # un mot dure rarement plus de 0,8 s : au-delà, c'est une pause
        w["end"] = round(min(nxt, w["start"] + 0.8), 3)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"duration": duration, "words": words}, f, ensure_ascii=False, indent=1)
    print(f"{len(words)} mots, {duration:.2f} s -> {args.out}")
    print(" ".join(f"{w['word']}@{w['start']:.2f}" for w in words[:40]))


if __name__ == "__main__":
    main()
