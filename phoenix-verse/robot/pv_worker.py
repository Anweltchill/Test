"""Phoenix Verse - robot de traitement (lancé par la tâche planifiée, environnement « Phoenix Verse »).

Commandes :
  setup                                   prépare /tmp/pvw (code, polices, bibliothèque de sons, dépendances)
  plan     --video F --duration-hint S --max-clips N --music ID[,ID...] --out plan.json
  render   --plan plan.json --clip I [--title T] [--hooks "A|B|C"] --out clip.mp4
  publish  --file clip.mp4 --clip-id UUID --when ISO --title T --desc D --ig ACC --yt ACC [--dry-run]
  stats    --ig ACC --yt ACC --posts ID[,ID...]      (lecture seule)

Clés : jamais dans ce fichier. Supabase (stockage) et Zernio sont injectés par le proxy de l'environnement :
on envoie des valeurs factices dans les en-têtes.
"""
import argparse, json, math, os, subprocess, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone

ROOT = "/tmp/pvw"
ROBOT_DIR = os.path.dirname(os.path.abspath(__file__))   # dossier du dépôt (code versionné)
SUPA = "https://fzgxowamjhfhkgvgvsry.supabase.co/storage/v1"
BUCKET = "phoenix-verse-gta"
ZERNIO = "https://zernio.com/api/v1"


def sh(cmd, check=True):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(" ".join(cmd[:3]) + " : " + r.stderr[-800:])
    return r.stdout


def http(method, url, body=None, headers=None, raw=None, timeout=120):
    h = dict(headers or {})
    data = None
    if raw is not None:
        data = raw
    elif body is not None:
        data = json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read()
            return r.status, (json.loads(txt) if txt[:1] in (b"{", b"[") else txt)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:1500]


def supa_get(path, dest):
    st, data = http("GET", f"{SUPA}/object/{BUCKET}/{path}", headers={"apikey": "x"}, timeout=600)
    if st != 200:
        raise RuntimeError(f"téléchargement {path} : HTTP {st}")
    open(dest, "wb").write(data if isinstance(data, bytes) else json.dumps(data).encode())


def supa_list(prefix):
    out, off = [], 0
    while True:
        st, r = http("POST", f"{SUPA}/object/list/{BUCKET}", {"prefix": prefix, "limit": 100, "offset": off}, {"apikey": "x"})
        if st != 200:
            raise RuntimeError(f"liste {prefix} : HTTP {st}")
        out += [o["name"] for o in r if o.get("id")]
        if len(r) < 100:
            return out
        off += 100


# ---------------------------------------------------------------- setup
def cmd_setup(a):
    os.makedirs(f"{ROOT}/assets", exist_ok=True)
    for d in ("sfx", "music", "maps"):
        os.makedirs(f"{ROOT}/{d}", exist_ok=True)
    supa_get("worker/sfx_index.json", f"{ROOT}/sfx_index.json")   # données uniquement (index des bruitages)
    for f in ("gsap.min.js", "Anton-Regular.ttf", "logo.png"):
        supa_get(f"worker/assets/{f}", f"{ROOT}/assets/{f}")
    from concurrent.futures import ThreadPoolExecutor
    jobs = [(f"worker/sfx/{n}", f"{ROOT}/sfx/{n}") for n in supa_list("worker/sfx")]
    jobs += [(f"worker/maps/{n}", f"{ROOT}/maps/{n}") for n in supa_list("worker/maps")]
    with ThreadPoolExecutor(12) as ex:
        list(ex.map(lambda j: os.path.exists(j[1]) or supa_get(*j), jobs))
    # chemins locaux de la bibliothèque de bruitages
    idx = json.load(open(f"{ROOT}/sfx_index.json"))
    for x in idx:
        x["file"] = f"{ROOT}/sfx/{x['id']}.wav"
    json.dump([x for x in idx if os.path.exists(x["file"])], open(f"{ROOT}/sfx_index.json", "w"))
    sh([sys.executable, "-m", "pip", "install", "-q", "librosa", "soundfile", "numpy", "pillow"], check=False)
    sh(["npx", "--yes", "hyperframes@0.8.137", "--version"])
    print(json.dumps({"ok": True, "sfx": len(os.listdir(f"{ROOT}/sfx")), "maps": len(os.listdir(f"{ROOT}/maps"))}))


def music_file(mid):
    p = f"{ROOT}/music/{mid}.mp3"
    if not os.path.exists(p):
        supa_get(f"library/music/{mid}.mp3", p)
    m = f"{ROOT}/maps/{mid}.json"
    if not os.path.exists(m):
        beat_map(p, m)
    return p, m


def beat_map(mp3, out):
    """Grille des temps + énergie par seconde (format compatible avec hf_build2.py)."""
    import librosa, numpy as np
    y, sr = librosa.load(mp3, sr=22050, mono=True)
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
    rms = librosa.feature.rms(y=y, hop_length=sr)[0]
    e = (rms - rms.min()) / (rms.max() - rms.min() + 1e-9)
    phases = [{"start": float(i), "end": float(i + 1), "energy": round(float(v), 3)} for i, v in enumerate(e)]
    bpm = float(np.atleast_1d(tempo)[0])
    json.dump({"tempo": {"bpm": round(bpm, 1), "downbeat_phase": 0}, "grid": {"beats_sec": [round(float(b), 3) for b in beats]},
               "energy_phases": phases}, open(out, "w"))


# ---------------------------------------------------------------- plan
def profile(video):
    """Volume (dB) et mouvement par demi-seconde."""
    import numpy as np
    dur = float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video]).strip())
    sr = 8000
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", video, "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                         capture_output=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    step = sr // 2
    n = len(a) // step
    loud = 20 * np.log10(np.sqrt((a[:n * step].reshape(n, step) ** 2).mean(1)) + 1e-6) if n else np.zeros(1)
    w, h = 160, 90
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", video, "-vf", "fps=2,scale=160:90,format=gray", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8).astype(np.float32)
    k = len(fr) // (w * h)
    fr = fr[:k * w * h].reshape(k, w * h)
    mot = np.concatenate([[0], np.abs(np.diff(fr, axis=0)).mean(1)]) if k > 1 else np.zeros(1)
    bri = fr.mean(1) if k else np.zeros(1)
    m = min(len(loud), len(mot))
    return dur, loud[:m], mot[:m], bri[:m]


def cmd_plan(a):
    import numpy as np
    dur, loud, mot, bri = profile(a.video)
    z = lambda x: (x - np.median(x)) / (x.std() + 1e-6)
    score = z(loud) + 0.7 * z(mot)
    score[bri < 22] -= 3          # écrans noirs / menus sombres
    musics = [m for m in a.music.split(",") if m]
    if not musics:
        raise SystemExit("aucune musique favorite")
    # MAXIMUM de clips : autant de fenêtres de ~70 s que la vidéo en contient (sans recouvrement),
    # en écartant seulement les passages vides (écran noir, silence, menus)
    target_len = 70.0
    n_clips = int(max(1 if dur >= 60 else 0, min(a.max_clips, dur // 72)))
    win = int(target_len * 2)
    cum = np.concatenate([[0], np.cumsum(score)])
    empty = ((bri < 22) | (loud < -50)).astype(float)          # écran noir ou silence
    cum_e = np.concatenate([[0], np.cumsum(empty)])
    taken, picks = np.zeros(len(score), bool), []
    while len(picks) < n_clips:
        best, bi = -1e9, None
        for i in range(0, max(1, len(score) - win + 1), 2):
            if taken[i:i + win].any() or (cum_e[min(len(empty), i + win)] - cum_e[i]) / win > 0.6:
                continue
            v = (cum[i + win] - cum[i]) / win
            if v > best:
                best, bi = v, i
        if bi is None:          # plus aucune fenêtre libre et non vide
            break
        picks.append((bi / 2, best))
        taken[max(0, bi - 2):bi + win + 2] = True
    picks.sort()
    clips = []
    for k, (t0, sc) in enumerate(picks):
        mid = musics[k % len(musics)]
        mp, mm = music_file(mid)
        m = json.load(open(mm))
        beat = 60.0 / max(60, min(180, m["tempo"]["bpm"]))
        beats_per_cut = 4 if beat * 4 >= 1.8 else 8          # un plan toutes les ~2-3 s
        n_beats = int(target_len / beat)
        cuts, trs = [], ["slide", "punch", "whip", "flash"]
        for i in range(n_beats // beats_per_cut):
            cuts.append({"beats": beats_per_cut, "tr": trs[i % 4], "zoom": 1.12, "src": 0})
        clips.append({"index": k, "window_start": round(t0, 2), "score": round(float(sc), 2), "music": mid,
                      "music_file": mp, "music_map": mm, "cuts": cuts})
    plan = {"video": a.video, "duration": dur, "clips": clips}
    json.dump(plan, open(a.out, "w"), indent=1)
    # planches pour relecture (titres et accroches) : 6 images par clip
    from PIL import Image
    for c in clips:
        ims = []
        for j in range(6):
            t = c["window_start"] + j * target_len / 6
            raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t:.2f}", "-i", a.video, "-frames:v", "1",
                                  "-vf", "scale=320:-2", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True).stdout
            from io import BytesIO
            try:
                ims.append(Image.open(BytesIO(raw)).convert("RGB"))
            except Exception:
                pass
        if ims:
            W, H = ims[0].size
            sheet = Image.new("RGB", (W * len(ims), H))
            for j, im in enumerate(ims):
                sheet.paste(im.resize((W, H)), (j * W, 0))
            sheet.save(os.path.splitext(a.out)[0] + f"_clip{c['index']}.jpg", quality=80)
    print(json.dumps({"duration": round(dur), "clips": len(clips), "windows": [c["window_start"] for c in clips]}))


# ---------------------------------------------------------------- render
def cmd_render(a):
    plan = json.load(open(a.plan))
    c = plan["clips"][a.clip]
    hooks = [h for h in (a.hooks or "").split("|") if h.strip()]
    cuts = [dict(x) for x in c["cuts"]]
    # accroches réparties APRÈS le titre (qui reste ~2,4 s à l'écran) : jamais superposées
    first = 2 if len(cuts) > 4 else 1
    step = max(1, (len(cuts) - first) // max(1, len(hooks)))
    for i, h in enumerate(hooks):
        j = min(len(cuts) - 1, first + i * step)
        cuts[j]["top"] = h.strip()[:28]
    mp, mm = music_file(c["music"])          # retéléchargée si le clip est monté dans une autre session
    p = {"name": f"pv-clip-{a.clip}", "video": plan["video"], "music": mp, "music_map": mm,
         "sfx_index": f"{ROOT}/sfx_index.json", "title": (a.title or "")[:60], "endcard": True, "seed": a.clip + 3,
         "sfx_every": 2, "continuous": True, "window_start": c["window_start"], "music_level": 0.2, "cuts": cuts}
    work = f"{ROOT}/work/clip{a.clip}"
    os.makedirs(work, exist_ok=True)
    json.dump(p, open(f"{work}/plan.json", "w"))
    env = dict(os.environ, PV_ASSETS=f"{ROOT}/assets")
    r = subprocess.run([sys.executable, os.path.join(ROBOT_DIR, "hf_build2.py"), f"{work}/plan.json", f"{work}/proj"], capture_output=True, text=True, env=env)
    if r.returncode:
        raise SystemExit("montage : " + r.stderr[-1500:])
    os.makedirs(f"{work}/proj/renders", exist_ok=True)
    r = subprocess.run(["npx", "--yes", "hyperframes@0.8.137", "render", ".", "-q", "standard", "-o", "renders/raw.mp4", "--fps", "30"],
                       cwd=f"{work}/proj", capture_output=True, text=True)
    if r.returncode or not os.path.exists(f"{work}/proj/renders/raw.mp4"):
        raise SystemExit("rendu : " + (r.stderr or r.stdout)[-1500:])
    raw = f"{work}/proj/renders/raw.mp4"
    out = sh(["ffmpeg", "-nostdin", "-i", raw, "-af", "ebur128", "-f", "null", "-"], check=False)
    I = -16.0
    for line in subprocess.run(["ffmpeg", "-nostdin", "-i", raw, "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True).stderr.splitlines():
        if line.strip().startswith("I:"):
            I = float(line.split()[1])
    g = round(-14.5 - I, 2)
    sh(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", raw, "-c:v", "copy", "-af",
        f"aresample=96000,volume={g}dB,alimiter=limit=0.6:level=false:attack=1:release=50,aresample=48000",
        "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", a.out])
    d = float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.out]).strip())
    info = json.load(open(f"{work}/proj/build_info.json"))
    print(json.dumps({"file": a.out, "duration": round(d, 1), "music": c["music"], "sfx_credits": info.get("sfx_credits_by", [])}))


# ---------------------------------------------------------------- publication (programmée)
def cmd_publish(a):
    path = f"clips/{a.clip_id}.mp4"
    if a.dry_run:
        print(json.dumps({"dry_run": True, "storage_path": path, "when": a.when, "title": a.title, "desc": a.desc[:200]}))
        return
    st, _ = http("POST", f"{SUPA}/object/{BUCKET}/{path}", raw=open(a.file, "rb").read(),
                 headers={"apikey": "x", "Content-Type": "video/mp4", "x-upsert": "true"}, timeout=900)
    if st != 200:
        raise SystemExit(f"envoi stockage : HTTP {st}")
    st, s = http("POST", f"{SUPA}/object/sign/{BUCKET}/{path}", {"expiresIn": 7 * 86400}, {"apikey": "x"})
    if st != 200:
        raise SystemExit(f"lien signé : HTTP {st}")
    url = SUPA + s["signedURL"]
    body = {"content": a.desc, "scheduledFor": a.when, "timezone": "Europe/Paris",
            "mediaItems": [{"type": "video", "url": url}],
            "platforms": [
                {"platform": "instagram", "accountId": a.ig, "platformSpecificData": {"shareToFeed": True}},
                {"platform": "youtube", "accountId": a.yt, "platformSpecificData": {
                    "title": a.title[:100], "visibility": "public", "madeForKids": False, "categoryId": "20"}}],
            "tags": ["phoenix-verse"]}
    if a.dry_run:
        print(json.dumps({"dry_run": True, "storage_path": path, "body": {**body, "mediaItems": [{"type": "video", "url": "(lien signé)"}]}}))
        return
    st, r = http("POST", f"{ZERNIO}/posts", body, {"Authorization": "Bearer x"})
    if st not in (200, 201):
        raise SystemExit(f"Zernio : HTTP {st} {r}")
    post = r.get("post", r)
    print(json.dumps({"storage_path": path, "zernio_post_id": post.get("_id") or post.get("id"), "status": post.get("status")}))


# ---------------------------------------------------------------- statistiques (lecture seule)
def cmd_stats(a):
    out = {"posts": {}, "accounts": {}}
    for pid in [p for p in (a.posts or "").split(",") if p]:
        st, r = http("GET", f"{ZERNIO}/analytics?postId={urllib.parse.quote(pid)}", headers={"Authorization": "Bearer x"})
        out["posts"][pid] = r if st == 200 else {"error": st}
        st, r = http("GET", f"{ZERNIO}/posts/{urllib.parse.quote(pid)}", headers={"Authorization": "Bearer x"})
        out["posts"][pid + ":post"] = r if st == 200 else {"error": st}
    st, r = http("GET", f"{ZERNIO}/accounts", headers={"Authorization": "Bearer x"})
    out["accounts"]["list"] = r if st == 200 else {"error": st}
    st, r = http("GET", f"{ZERNIO}/analytics/youtube/channel-insights?accountId={a.yt}", headers={"Authorization": "Bearer x"})
    out["accounts"]["youtube_insights"] = r if st == 200 else {"error": st, "detail": str(r)[:300]}
    st, r = http("GET", f"{ZERNIO}/analytics/instagram/account-insights?accountId={a.ig}", headers={"Authorization": "Bearer x"})
    out["accounts"]["instagram_insights"] = r if st == 200 else {"error": st, "detail": str(r)[:300]}
    print(json.dumps(out, ensure_ascii=False)[:60000])


# ---------------------------------------------------------------- utilitaires
def cmd_download(a):
    supa_get(a.path, a.out)
    print(json.dumps({"ok": True, "file": a.out, "bytes": os.path.getsize(a.out)}))


def cmd_delete(a):
    if not (a.path.startswith("clips/") or a.path.startswith("inbox/")):
        raise SystemExit("suppression refusée : seuls clips/ et inbox/ sont autorisés")
    st, r = http("DELETE", f"{SUPA}/object/{BUCKET}", {"prefixes": [a.path]}, {"apikey": "x"})
    print(json.dumps({"ok": st == 200, "status": st}))


def cmd_poststatus(a):
    out = {}
    for pid in [p for p in a.ids.split(",") if p]:
        st, r = http("GET", f"{ZERNIO}/posts/{urllib.parse.quote(pid)}", headers={"Authorization": "Bearer x"})
        post = r.get("post", r) if isinstance(r, dict) else {}
        out[pid] = {"http": st, "status": post.get("status"),
                    "platforms": [{"platform": x.get("platform"), "status": x.get("status"),
                                   "url": x.get("platformPostUrl") or x.get("url") or x.get("permalink"),
                                   "error": x.get("errorMessage") or x.get("error")} for x in post.get("platforms", [])]}
    print(json.dumps(out, ensure_ascii=False))


def cmd_frames(a):
    for k in range(6):
        t = a.start + k * a.length / 6
        sh(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", a.video, "-frames:v", "1", "-vf", "scale=480:-2", f"{a.out}_{k}.jpg"])
    print(json.dumps({"ok": True, "frames": [f"{a.out}_{k}.jpg" for k in range(6)]}))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("setup")
    p = sp.add_parser("plan"); p.add_argument("--video", required=True); p.add_argument("--max-clips", type=int, default=6)
    p.add_argument("--music", required=True); p.add_argument("--out", required=True)
    p = sp.add_parser("render"); p.add_argument("--plan", required=True); p.add_argument("--clip", type=int, required=True)
    p.add_argument("--title"); p.add_argument("--hooks"); p.add_argument("--out", required=True)
    p = sp.add_parser("publish"); p.add_argument("--file", required=True); p.add_argument("--clip-id", required=True)
    p.add_argument("--when", required=True); p.add_argument("--title", required=True); p.add_argument("--desc", required=True)
    p.add_argument("--ig", required=True); p.add_argument("--yt", required=True); p.add_argument("--dry-run", action="store_true")
    p = sp.add_parser("stats"); p.add_argument("--ig", required=True); p.add_argument("--yt", required=True); p.add_argument("--posts")
    p = sp.add_parser("download"); p.add_argument("--path", required=True); p.add_argument("--out", required=True)
    p = sp.add_parser("delete"); p.add_argument("--path", required=True)
    p = sp.add_parser("poststatus"); p.add_argument("--ids", required=True)
    p = sp.add_parser("frames"); p.add_argument("--video", required=True); p.add_argument("--start", type=float, required=True)
    p.add_argument("--length", type=float, default=75); p.add_argument("--out", required=True)
    a = ap.parse_args()
    {"setup": cmd_setup, "plan": cmd_plan, "render": cmd_render, "publish": cmd_publish, "stats": cmd_stats,
     "download": cmd_download, "delete": cmd_delete, "poststatus": cmd_poststatus, "frames": cmd_frames}[a.cmd](a)


if __name__ == "__main__":
    main()
