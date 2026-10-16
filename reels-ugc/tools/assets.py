#!/usr/bin/env python3
"""Bibliothèque d'images pour les Reels (réseau : seuls npm et raw.githubusercontent.com passent).

  python3 tools/assets.py emoji "Mobile phone" "Woman technologist" ...   -> assets/lib/emoji/<slug>.png
  python3 tools/assets.py logo instagram-icon tiktok-icon canva gmail ... -> assets/lib/logos/<nom>.svg
  python3 tools/assets.py list emoji <mot>                                 -> cherche dans l'index

Sources :
- Illustrations 3D : Microsoft Fluent Emoji (licence MIT), index dans tools/fluent-emoji-3d.txt.
- Logos couleur : @iconify-json/logos (npm) ; repli simple-icons (npm, monochrome + couleur de marque).
  Logos de vraies marques : autorisés par la cliente (usage illustratif dans ses Reels).
"""
import json, os, re, subprocess, sys, tarfile, tempfile, urllib.parse
HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "assets", "lib")
RAW = "https://raw.githubusercontent.com/microsoft/fluentui-emoji/main/"

def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

def emoji(names):
    idx = open(os.path.join(HERE, "fluent-emoji-3d.txt")).read().splitlines()
    os.makedirs(os.path.join(LIB, "emoji"), exist_ok=True)
    for n in names:
        cands = [p for p in idx if p.split("/")[1].lower() == n.lower()]
        if not cands: print(f"?? {n} introuvable (essaie : tools/assets.py list emoji {n.split()[0]})"); continue
        p = sorted(cands, key=len)[0]
        out = os.path.join(LIB, "emoji", slug(n) + ".png")
        subprocess.run(["curl", "-sSfL", "-o", out, RAW + urllib.parse.quote(p)], check=True)
        print("ok", out)

_pkgs = {}
def pkg(name):
    if name in _pkgs: return _pkgs[name]
    d = tempfile.mkdtemp(prefix="npm-")
    tgz = subprocess.run(["npm", "pack", name, "--silent"], cwd=d, capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]
    with tarfile.open(os.path.join(d, tgz)) as t: t.extractall(d, filter="data")
    _pkgs[name] = os.path.join(d, "package"); return _pkgs[name]

def logo(names):
    os.makedirs(os.path.join(LIB, "logos"), exist_ok=True)
    ic = json.load(open(os.path.join(pkg("@iconify-json/logos"), "icons.json")))
    for n in names:
        out = os.path.join(LIB, "logos", n + ".svg")
        if n in ic["icons"]:
            i = ic["icons"][n]; w = i.get("width", ic.get("width", 256)); h = i.get("height", ic.get("height", 256))
            open(out, "w").write(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">{i["body"]}</svg>')
            print("ok", out, "(iconify)"); continue
        si = pkg("simple-icons")
        f = os.path.join(si, "icons", n + ".svg")
        meta = None
        for mf in ("data/simple-icons.json", "_data/simple-icons.json"):
            if os.path.exists(os.path.join(si, mf)):
                meta = json.load(open(os.path.join(si, mf))); break
        if os.path.exists(f):
            hexc = "000000"
            if meta:
                arr = meta if isinstance(meta, list) else meta.get("icons", [])
                for e in arr:
                    if slug(e.get("slug", e["title"])) == n or slug(e["title"]) == n: hexc = e["hex"]; break
            svg = open(f).read().replace("<svg ", f'<svg fill="#{hexc}" ', 1)
            open(out, "w").write(svg); print("ok", out, f"(simple-icons #{hexc})"); continue
        print("?? logo introuvable :", n)

if __name__ == "__main__":
    if len(sys.argv) < 3: sys.exit(__doc__)
    kind, args = sys.argv[1], sys.argv[2:]
    if kind == "emoji": emoji(args)
    elif kind == "logo": logo(args)
    elif kind == "list":
        idx = open(os.path.join(HERE, "fluent-emoji-3d.txt")).read().splitlines()
        print("\n".join(sorted({p.split("/")[1] for p in idx if args[1].lower() in p.lower()})))
