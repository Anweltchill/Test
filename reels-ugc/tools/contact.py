#!/usr/bin/env python3
"""Planche contact de contrôle qualité (captures toutes les N secondes).

Usage : python3 tools/contact.py <dossier_reel> <sortie.jpg> [--step 2.5] [--cols 5]
Lance `hyperframes snapshot --at ...` puis assemble les images en planche,
avec le temps et les zones de sécurité Instagram en rouge (220 haut, 380 bas, 64 gauche, 120 droite).
"""
import argparse, json, os, re, subprocess, sys, tempfile
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
VER = open(os.path.join(HERE, "HYPERFRAMES_VERSION")).read().strip()
SAFE = dict(top=220, bottom=380, left=64, right=120)

ap = argparse.ArgumentParser()
ap.add_argument("reel"); ap.add_argument("out")
ap.add_argument("--step", type=float, default=2.5); ap.add_argument("--cols", type=int, default=5)
ap.add_argument("--at", default="", help="temps précis séparés par des virgules (remplace --step)")
a = ap.parse_args()

html = open(os.path.join(a.reel, "index.html"), encoding="utf-8").read()
dur = float(re.search(r'data-composition-id="[^"]+"[^>]*?data-duration="([\d.]+)"', html, re.S).group(1)) if 'data-duration' in html else 10
times = [float(x) for x in a.at.split(",")] if a.at else [round(i * a.step, 2) for i in range(int(dur / a.step) + 1) if i * a.step < dur - 0.05]
tmp = tempfile.mkdtemp(prefix="snap-")
subprocess.run(["npx", "--yes", f"hyperframes@{VER}", "snapshot", a.reel, "-o", tmp, "--keep", "--no-end",
                "--at", ",".join(str(t) for t in times)], check=True, stdout=subprocess.DEVNULL)
files = sorted((f for f in os.listdir(tmp) if f.endswith(".png")), key=lambda f: float(re.findall(r"[\d.]+", f)[0].rstrip(".")))
W, H = 270, 480
cols = a.cols; rows = (len(files) + cols - 1) // cols
sheet = Image.new("RGB", (cols * (W + 10) + 10, rows * (H + 40) + 10), (40, 40, 40))
d = ImageDraw.Draw(sheet)
for i, f in enumerate(files):
    im = Image.open(os.path.join(tmp, f)).convert("RGB")
    sx, sy = W / im.width, H / im.height
    im = im.resize((W, H))
    x, y = 10 + (i % cols) * (W + 10), 10 + (i // cols) * (H + 40)
    sheet.paste(im, (x, y))
    d.rectangle([x + SAFE["left"] * sx, y + SAFE["top"] * sy, x + W - SAFE["right"] * sx, y + H - SAFE["bottom"] * sy], outline=(255, 40, 40))
    d.text((x + 4, y + H + 8), f.replace("at-", "").replace(".png", ""), fill=(255, 255, 255))
sheet.save(a.out, quality=88)
print(f"{len(files)} captures -> {a.out}")
