#!/usr/bin/env python3
"""Sous-titres mot à mot (style Reels) à partir de audio/mots.json.

Usage : python3 tools/captions.py reels/<NN-slug> --end 36 [--fix "mot=Remplacement" ...] [--insert "mot@temps:avant_mot"]
- fusionne la ponctuation isolée de l'ASR, applique les corrections d'orthographe (--fix, exact sur le mot ASR),
- groupe par phrase (≤ 4 mots / 24 caractères, sinon paquets de 3 équilibrés),
- écrit compositions/captions.html (composition "cap") et audio/sous-titres.json.
"""
import argparse, json, os, re
HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("reel"); ap.add_argument("--end", type=float, required=True)
ap.add_argument("--fix", action="append", default=[]); ap.add_argument("--insert", action="append", default=[])
a = ap.parse_args()
d = json.load(open(os.path.join(a.reel, "audio", "mots.json"), encoding="utf-8"))
fix = dict(f.split("=", 1) for f in a.fix)
ws = []
for w in d["words"]:
    t = w["word"]
    if re.fullmatch(r"[?!.,;:]+", t):
        if ws: ws[-1][0] += (" " + t) if t in "?!" else t
        continue
    nt = fix.get(t, t)
    if nt == "":
        continue  # mot ASR parasite supprimé (--fix "mot=")
    ws.append([nt, w["start"]])
for ins in a.insert:  # "nom :@5.36:l'UGC."
    word, rest = ins.split("@", 1); tm, before = rest.split(":", 1)
    i = next(k for k, w in enumerate(ws) if w[0] == before)
    ws.insert(i, [word.replace(" :", " :"), float(tm)])
for w in ws:
    w[0] = re.sub(r" ([?!:])", " \\1", w[0])
phr, cur = [], []
for w in ws:
    cur.append(w)
    if w[0][-1] in ".,?!:": phr.append(cur); cur = []
if cur: phr.append(cur)
L = lambda g: sum(len(x[0]) for x in g) + len(g) - 1
groups = []
for ph in phr:
    if len(ph) <= 4 and L(ph) <= 24: groups.append(ph); continue
    k = -(-len(ph) // 3); n = len(ph)
    sizes = [n // k + (1 if i < n % k else 0) for i in range(k)]
    i = 0
    for sz in sizes: groups.append(ph[i:i + sz]); i += sz
data = [[[x[0], round(x[1], 2)] for x in g] for g in groups]
tpl = open(os.path.join(HERE, "captions-template.html"), encoding="utf-8").read()
out = tpl.replace("__DATA__", json.dumps(data, ensure_ascii=False)).replace("__END__", str(a.end))
open(os.path.join(a.reel, "compositions", "captions.html"), "w", encoding="utf-8").write(out)
json.dump(ws, open(os.path.join(a.reel, "audio", "sous-titres.json"), "w", encoding="utf-8"), ensure_ascii=False)
print(" | ".join(" ".join(x[0] for x in g) for g in groups))
