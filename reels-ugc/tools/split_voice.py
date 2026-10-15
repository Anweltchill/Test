#!/usr/bin/env python3
"""Découpe UN audio contenant toute une série (les textes lus à la suite) en un fichier par Reel.

Usage :
  python3 tools/split_voice.py <audio1> [audio2 ...] [--serie reels/SERIE-1-VOIX-COMPLETE.txt]

- Plusieurs fichiers sont acceptés (s'ils ont été générés en morceaux) : ils sont mis bout à bout dans l'ordre donné.
- Transcription locale (tools/asr.py), puis alignement mot à mot sur le texte de chaque Reel
  (reels/<NN-slug>/voix-off.txt, balises [..] ignorées).
- Sortie : reels/<NN-slug>/audio/voix.wav (coupé au début du 1er mot − 0,25 s, fin du dernier mot + 0,45 s,
  sans empiéter sur le Reel voisin), + reels/<NN-slug>/audio/mots.json (temps recalés sur le morceau),
  + un rapport de couverture par Reel (mots retrouvés / attendus).
"""
import argparse, difflib, glob, json, os, re, subprocess, sys, tempfile, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
REELS = os.path.join(HERE, "..", "reels")


def norm(w):
    w = unicodedata.normalize("NFD", w.lower())
    w = "".join(c for c in w if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", w)


def script_words(text):
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = text.replace("U-G-C", "UGC").replace("’", "'")
    out = []
    for w in re.split(r"[\s'\-]+", text):
        n = norm(w)
        if n:
            out.append(n)
    return out


def asr_tokens(words):
    """Découpe aussi les mots ASR sur apostrophes/tirets pour coller au découpage du script."""
    out = []
    for i, w in enumerate(words):
        parts = [norm(p) for p in re.split(r"['\-’]+", w["word"])]
        parts = [p for p in parts if p]
        for p in parts:
            out.append((p, i))
    return out


def align(reels, words):
    """reels : [(slug, [mots normalisés])] ; words : sortie ASR. Renvoie {slug: (i_first, i_last, trouvés, attendus)}."""
    seq_s, owner = [], []
    for k, (_, ws) in enumerate(reels):
        seq_s += ws
        owner += [k] * len(ws)
    toks = asr_tokens(words)
    seq_a = [t for t, _ in toks]
    sm = difflib.SequenceMatcher(None, seq_s, seq_a, autojunk=False)
    starts = [sum(len(w) for _, w in reels[:k]) for k in range(len(reels))]
    hits = {}
    for a, b, n in sm.get_matching_blocks():
        for j in range(n):
            k = owner[a + j]
            hits.setdefault(k, []).append((toks[b + j][1], a + j - starts[k]))
    res = {}
    for k, (slug, ws) in enumerate(reels):
        h = hits.get(k, [])
        if not h:
            res[slug] = None
            continue
        first, last = min(h), max(h)
        # mots du script non retrouvés avant le 1er / après le dernier repère (pour ne pas couper la fin)
        res[slug] = (first[0], last[0], len(h), len(ws), first[1], len(ws) - 1 - last[1])
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio", nargs="+")
    ap.add_argument("--only", default="", help="slugs séparés par des virgules (par défaut : tous ceux qui ont un voix-off.txt)")
    ap.add_argument("--min-cover", type=float, default=0.6)
    a = ap.parse_args()

    dirs = sorted(d for d in glob.glob(os.path.join(REELS, "[0-9][0-9]-*")) if os.path.exists(os.path.join(d, "voix-off.txt"))
                  and not os.path.basename(d).startswith("00-"))
    if a.only:
        keep = set(a.only.split(","))
        dirs = [d for d in dirs if os.path.basename(d) in keep]
    reels = [(os.path.basename(d), script_words(open(os.path.join(d, "voix-off.txt"), encoding="utf-8").read())) for d in dirs]

    tmp = tempfile.mkdtemp(prefix="voix-")
    full = os.path.join(tmp, "serie.wav")
    if len(a.audio) == 1:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.audio[0], "-ac", "1", "-ar", "44100", full], check=True)
    else:
        lst = os.path.join(tmp, "l.txt")
        ins = []
        for i, f in enumerate(a.audio):
            o = os.path.join(tmp, f"p{i}.wav")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f, "-ac", "1", "-ar", "44100", o], check=True)
            ins.append(o)
        open(lst, "w").write("".join(f"file '{p}'\n" for p in ins))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", full], check=True)

    mj = os.path.join(tmp, "mots.json")
    subprocess.run([sys.executable, os.path.join(HERE, "asr.py"), full, mj], check=True, stdout=subprocess.DEVNULL)
    data = json.load(open(mj, encoding="utf-8"))
    words, dur = data["words"], data["duration"]

    res = align(reels, words)
    order = [s for s, _ in reels]
    bounds = []
    for s in order:
        r = res[s]
        bounds.append(None if r is None else (words[r[0]]["start"], words[r[1]]["end"]))
    ok = 0
    print(f"{'Reel':32} {'début':>7} {'fin':>7} {'durée':>6}  mots retrouvés")
    for i, s in enumerate(order):
        r = res[s]
        if r is None:
            print(f"{s:32} introuvable dans l'audio")
            continue
        cover = r[2] / max(1, r[3])
        t0 = max(0.0, bounds[i][0] - 0.25 - 0.4 * r[4])
        t1 = min(dur, bounds[i][1] + 0.45 + 0.4 * r[5])
        prev = next((bounds[j] for j in range(i - 1, -1, -1) if bounds[j]), None)
        nxt = next((bounds[j] for j in range(i + 1, len(order)) if bounds[j]), None)
        if prev: t0 = max(t0, (prev[1] + bounds[i][0]) / 2)
        if nxt: t1 = min(t1, (bounds[i][1] + nxt[0]) / 2)
        flag = "" if cover >= a.min_cover else "  ⚠ à vérifier (texte modifié à la lecture ?)"
        print(f"{s:32} {t0:7.2f} {t1:7.2f} {t1-t0:6.1f}  {r[2]}/{r[3]} ({cover:.0%}){flag}")
        out_dir = os.path.join(REELS, s, "audio"); os.makedirs(out_dir, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}", "-i", full,
                        "-af", "afade=t=in:d=0.02,areverse,afade=t=in:d=0.08,areverse", os.path.join(out_dir, "voix.wav")], check=True)
        seg = [dict(w, start=round(w["start"] - t0, 3), end=round(w["end"] - t0, 3)) for w in words[r[0]:r[1] + 1]]
        json.dump({"duration": round(t1 - t0, 3), "words": seg}, open(os.path.join(out_dir, "mots.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        ok += 1
    print(f"\n{ok}/{len(order)} Reels découpés -> reels/<NN-slug>/audio/voix.wav")


if __name__ == "__main__":
    main()
