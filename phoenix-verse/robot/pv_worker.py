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
import shutil, argparse, json, os, subprocess, sys, urllib.parse, urllib.request

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
    pip = [sys.executable, "-m", "pip", "install", "-q", "librosa", "soundfile", "numpy"]
    if subprocess.run(pip, capture_output=True).returncode:
        subprocess.run(pip + ["--break-system-packages"], capture_output=True)
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


def _rollmed(x, n):
    import numpy as np
    pad = np.pad(x, (n, n), mode="edge")
    return np.array([np.median(pad[i:i + 2 * n + 1]) for i in range(len(x))])


def cmd_moments(a):
    """Repère les MOMENTS FORTS (ruptures) : pic de son par rapport au bruit ambiant, à-coup de mouvement,
    changement brutal d'image. La conduite ou la marche (mouvement régulier) ne ressort pas.
    Produit des planches numérotées que le robot regarde pour garder seulement les moments viraux."""
    import numpy as np
    dur, loud, mot, bri = profile(a.video)
    n = len(loud)
    if n < 20:
        raise SystemExit("vidéo trop courte")
    z = lambda x: (x - np.median(x)) / (np.percentile(x, 90) - np.percentile(x, 10) + 1e-6)
    loud_jump = loud - _rollmed(loud, 20)              # coup de feu, choc, cri : au-dessus du fond sonore des 10 s autour
    mot_jump = mot - _rollmed(mot, 12)                 # à-coup de mouvement (pas le défilement régulier d'une route)
    spike = 1.2 * z(loud_jump) + 0.9 * z(mot_jump) + 0.4 * z(loud)
    spike = np.convolve(spike, [0.25, 0.5, 0.25], "same")
    spike[(bri < 22) | (loud < -50)] = -9              # écran noir, menus, silence
    sep = 10                                           # 5 s minimum entre deux moments
    order, taken, cands = np.argsort(-spike), np.zeros(n, bool), []
    limit = int(min(a.max, max(12, dur / 7)))
    for i in order:
        if len(cands) >= limit or spike[i] < a.min_score:
            break
        if taken[max(0, i - sep):i + sep + 1].any():
            continue
        taken[i] = True
        t = i / 2
        cands.append({"id": len(cands), "peak": round(t, 2), "start": round(max(0, t - 3.0), 2),
                      "end": round(min(dur - 0.2, t + 2.5), 2), "spike": round(float(spike[i]), 2)})
    cands.sort(key=lambda c: c["peak"])
    for k, c in enumerate(cands):
        c["id"] = k
    os.makedirs(a.out, exist_ok=True)
    json.dump({"video": a.video, "duration": dur, "moments": cands}, open(f"{a.out}/moments.json", "w"), indent=1)
    # planches : 8 moments par image, 4 vues par moment (avant, pic, juste après, après) - ffmpeg seul
    font = f"{ROOT}/assets/Anton-Regular.ttf"
    tmp = f"{a.out}/_f"
    sheets = []
    for s0 in range(0, len(cands), 8):
        group = cands[s0:s0 + 8]
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        k = 0
        for c in group:
            for off in (-2.0, -0.5, 0.5, 2.0):
                p = f"{tmp}/{k:03d}.png"
                lab = f"#{c['id']}  {c['peak']:.0f}s" if off == -2.0 else ""
                vf = "scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2"
                if lab and os.path.exists(font):
                    vf += f",drawbox=x=0:y=0:w=150:h=40:color=black@0.75:t=fill,drawtext=fontfile={font}:text='{lab}':x=8:y=5:fontsize=28:fontcolor=0xff2d95"
                subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{max(0, c['peak'] + off):.2f}", "-i", a.video,
                                "-frames:v", "1", "-vf", vf, p], capture_output=True)
                if not os.path.exists(p):
                    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180",
                                    "-frames:v", "1", p], capture_output=True)
                k += 1
        p = f"{a.out}/sheet_{s0 // 8:02d}.jpg"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-framerate", "1", "-i", f"{tmp}/%03d.png",
                        "-vf", f"tile=4x{len(group)}:padding=4:color=0x140a1e", "-frames:v", "1", "-q:v", "4", p], capture_output=True)
        sheets.append(p)
    shutil.rmtree(tmp, ignore_errors=True)
    print(json.dumps({"duration": round(dur), "moments": len(cands), "sheets": sheets}))


def _fit(ms, target):
    """Ajuste les durées des moments pour remplir exactement `target` secondes (2,5 à 8 s chacun, pic gardé)."""
    for m in ms:
        m["a"], m["b"] = m["start"], m["end"]
    for _ in range(40):
        tot = sum(m["b"] - m["a"] for m in ms)
        diff = target - tot
        if abs(diff) < 0.05:
            break
        free = [m for m in ms if (diff > 0 and m["b"] - m["a"] < 8 and (m["a"] > m.get("min_start", 0) + 0.01 or m["b"] < m["max_end"] - 0.01))
                or (diff < 0 and m["b"] - m["a"] > 2.5)]
        if not free:
            break
        step = diff / len(free)
        for m in free:
            if step > 0:
                add = min(step, 8 - (m["b"] - m["a"]))
                pre = min(add * 0.4, m["a"] - m.get("min_start", 0))
                m["a"] -= pre
                m["b"] = min(m["max_end"], m["b"] + add - pre)
            else:
                cut = min(-step, (m["b"] - m["a"]) - 2.5)
                lead = m["peak"] - m["a"]
                tail = m["b"] - m["peak"]
                ca = min(cut * 0.55, max(0, lead - 0.8))
                m["a"] += ca
                m["b"] -= min(cut - ca, max(0, tail - 0.8))
    return sum(m["b"] - m["a"] for m in ms)


def cmd_extract(a):
    """Banque de moments : découpe chaque moment gardé (fenêtre de 10 s autour du pic) et l'envoie au stockage.
    Les moments de plusieurs vidéos peuvent ensuite former un clip de 40 s."""
    mom = json.load(open(a.moments))
    byid = {m["id"]: m for m in mom["moments"]}
    out = []
    sel = [s for s in json.load(open(a.select)) if s.get("id") in byid and float(s.get("score", 0)) >= a.min_keep]
    peaks = sorted(byid[s["id"]]["peak"] for s in sel)
    for s in sel:
        m = byid[s["id"]]
        i = peaks.index(m["peak"])
        lo = (peaks[i - 1] + m["peak"]) / 2 if i else 0.0                 # jamais la même image dans deux moments
        hi = (m["peak"] + peaks[i + 1]) / 2 if i + 1 < len(peaks) else mom["duration"] - 0.1
        t0 = max(0.0, lo, m["peak"] - 5.0)
        t1 = min(mom["duration"] - 0.1, hi, m["peak"] + 5.0)
        f = f"{ROOT}/moment_{a.video_id}_{m['id']}.mp4"
        sh(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{t0:.3f}", "-i", a.video, "-t", f"{t1 - t0:.3f}",
            "-vf", "fps=30,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-ar", "44100", "-ac", "2", "-movflags", "+faststart", f])
        path = f"moments/{a.video_id}_{m['id']}.mp4"
        st, _ = http("POST", f"{SUPA}/object/{BUCKET}/{path}", raw=open(f, "rb").read(),
                     headers={"apikey": "x", "Content-Type": "video/mp4", "x-upsert": "true"}, timeout=600)
        if st != 200:
            raise SystemExit(f"envoi moment : HTTP {st}")
        size = os.path.getsize(f)
        os.remove(f)
        out.append({"storage_path": path, "size_bytes": size, "duration_s": round(t1 - t0, 3), "peak_s": round(m["peak"] - t0, 3),
                    "score": float(s["score"]), "label": (s.get("label") or "")[:16], "kind": s.get("kind", "")})
    print(json.dumps({"moments": out}, ensure_ascii=False))


def cmd_bank(a):
    """Assemble des moments de la banque (plusieurs vidéos) en une vidéo de travail + moments.json + sélection,
    prêts pour `compose`."""
    items = json.load(open(a.items))
    r = _bank(items, a.out)
    print(json.dumps({"video": r["video"], "moments": len(r["moments"]), "seconds": round(r["duration"], 1),
                      "map": {m["id"]: m["db_id"] for m in r["moments"]}}))


def _bank(items, out):
    a = argparse.Namespace(out=out)
    os.makedirs(a.out, exist_ok=True)
    files, moms, sel, t = [], [], [], 0.0
    for k, it in enumerate(items):
        f = f"{a.out}/m{k:03d}.mp4"
        if not os.path.exists(f):
            supa_get(it["storage_path"], f)
        files.append(f)
        d = float(it["duration_s"])
        moms.append({"id": k, "db_id": it["id"], "item": it, "file_start": round(t, 3), "peak": round(t + float(it["peak_s"]), 3), "start": round(t + max(0, float(it["peak_s"]) - 3), 3),
                     "end": round(t + min(d, float(it["peak_s"]) + 2.5), 3), "lo": round(t + 0.05, 3), "hi": round(t + d - 0.1, 3)})
        sel.append({"id": k, "score": it["score"], "label": it.get("label", ""), "kind": it.get("kind", ""), "recent": bool(it.get("recent"))})
        t += d
    open(f"{a.out}/list.txt", "w").write("".join(f"file '{os.path.basename(f)}'\n" for f in files))
    sh(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", f"{a.out}/list.txt", "-c", "copy", f"{a.out}/bank.mp4"])
    json.dump({"video": f"{a.out}/bank.mp4", "duration": t, "moments": moms}, open(f"{a.out}/moments.json", "w"), indent=1)
    json.dump(sel, open(f"{a.out}/select.json", "w"), ensure_ascii=False)
    return {"video": f"{a.out}/bank.mp4", "duration": t, "moments": moms}


def cmd_compose(a):
    """Assemble des clips de ~40 s UNIQUEMENT avec les moments retenus par le robot.
    Chaque clip démarre par son meilleur moment (le hook) ; aucun moment n'est réutilisé."""
    mom = json.load(open(a.moments))
    sel = json.load(open(a.select))
    byid = {m["id"]: m for m in mom["moments"]}
    kept = []
    for s in sel:
        if s.get("id") in byid and float(s.get("score", 0)) >= a.min_keep:
            m = dict(byid[s["id"]])
            m.update({"score": float(s["score"]), "label": (s.get("label") or "")[:16], "kind": s.get("kind", ""), "recent": bool(s.get("recent"))})
            m["max_end"] = mom["duration"] - 0.2
            kept.append(m)
    # aucun chevauchement : chaque moment reste dans sa moitié de l'espace qui le sépare de ses voisins
    kept.sort(key=lambda m: m["peak"])
    for i, m in enumerate(kept):
        m["min_start"] = max(0.0, (kept[i - 1]["peak"] + m["peak"]) / 2) if i else 0.0
        m["max_end"] = min(mom["duration"] - 0.2, (m["peak"] + kept[i + 1]["peak"]) / 2) if i + 1 < len(kept) else mom["duration"] - 0.2
        if "lo" in m:                                   # moment venant de la banque : bornes de son fichier
            m["min_start"], m["max_end"] = max(m["min_start"], m["lo"]), min(m["max_end"], m["hi"])
        m["start"] = max(m["start"], m["min_start"])
        m["end"] = min(m["end"], m["max_end"])
    musics = [m for m in a.music.split(",") if m]
    if not musics:
        raise SystemExit("aucune musique favorite")
    body = a.length - 1.3                               # 1,3 s de carte de fin
    kept.sort(key=lambda m: -m["score"])
    total = sum(min(8, m["max_end"] - m["min_start"]) for m in kept)
    n_clips = int(min(a.max_clips, total // body))
    if n_clips == 0 and len(kept) >= 3 and total >= body - 3:
        n_clips = 1
    groups = [[] for _ in range(n_clips)]
    rec = [m for m in kept if m.get("recent")]
    old = [m for m in kept if not m.get("recent")]
    if n_clips and rec and old:
        # rythme 80/20 : chaque clip = environ 80 % de moments récents (dont le hook) + 20 % d'anciens
        per = max(4, round(body / 6.5))
        n_old = max(1, round(per * 0.2))
        n_clips = max(1, min(n_clips, len(rec) // (per - n_old)))   # assez de récents pour tenir les 80 %
        groups = groups[:n_clips]
        for k in range(n_clips):
            groups[k] = rec[k::n_clips][:per - n_old]
            groups[k] += old[k::n_clips][:per - len(groups[k])]
            if len(groups[k]) < per:                   # complète avec ce qui reste
                rest = [m for m in kept if not any(m is x for g in groups for x in g)]
                groups[k] += rest[:per - len(groups[k])]
    else:
        for k, m in enumerate(kept):                    # serpentin : les meilleurs moments deviennent les hooks
            if not n_clips:
                break
            r, q = divmod(k, n_clips)
            groups[q if r % 2 == 0 else n_clips - 1 - q].append(m)
    clips = []
    for k, g in enumerate(groups):
        # on retire les moments en trop pour tenir dans 40 s (minimum 2,5 s chacun)
        g = sorted(g, key=lambda m: (not m.get("recent"), -m["score"]))   # le hook vient des moments récents
        while len(g) * 2.5 > body:
            g.pop()
        got = _fit(g, body)
        if got < body - 3:
            continue
        hook, rest = g[0], g[1:]
        # le hook frappe tout de suite : l'action arrive ~1 s après le début du clip
        ln = hook["b"] - hook["a"]
        hook["a"] = max(hook.get("min_start", 0), hook["peak"] - 1.0)
        hook["b"] = min(hook["max_end"], hook["a"] + ln)
        if rest and ln - (hook["b"] - hook["a"]) > 0.05:      # temps perdu redonné aux autres moments
            _fit(rest, body - (hook["b"] - hook["a"]))
        payoff = rest.pop(0) if len(rest) >= 3 else None   # 2e meilleur moment gardé pour la fin
        rest.sort(key=lambda m: m["peak"])
        order = [hook] + rest + ([payoff] if payoff else [])
        trs = ["punch", "whip", "flash", "slide"]
        cuts = [{"src": round(m["a"], 3), "dur": round(m["b"] - m["a"], 3), "peak": round(m["peak"] - m["a"], 3),
                 "tr": trs[i % 4], "zoom": 1.14, "label": m["label"], "moment": m["id"], "score": m["score"]}
                for i, m in enumerate(order)]
        extra = {}
        if all("item" in m for m in order):
            extra["bank_items"] = [m["item"] for m in order]
            extra["moment_ids"] = [m["db_id"] for m in order]
            for j, (cu, m) in enumerate(zip(cuts, order)):
                cu["item"], cu["src_rel"] = j, round(cu["src"] - m["file_start"], 3)
        mid = musics[k % len(musics)]
        mp, mm = music_file(mid)
        clips.append({**extra, "index": len(clips), "window_start": round(hook["a"], 2), "score": round(sum(m["score"] for m in g) / len(g), 2),
                      "music": mid, "music_file": mp, "music_map": mm, "moments": [m["id"] for m in order], "cuts": cuts})
    plan = {"video": mom["video"], "duration": mom["duration"], "clips": clips}
    json.dump(plan, open(a.out, "w"), indent=1)
    print(json.dumps({"kept": len(kept), "clips": len(clips),
                      "per_clip": [{"moments": len(c["cuts"]), "hook": c["moments"][0], "start": c["window_start"]} for c in clips]}))


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
    video = plan.get("video")
    if c.get("bank_items"):                  # clip de la banque : vidéo de travail = ses propres moments, dans l'ordre
        b = _bank(c["bank_items"], f"{ROOT}/work/bank_clip{a.clip}_{os.getpid()}")
        video = b["video"]
        starts = [m["file_start"] for m in b["moments"]]
        for cu in cuts:
            cu["src"] = round(starts[cu["item"]] + cu["src_rel"], 3)
    mp, mm = music_file(c["music"])          # retéléchargée si le clip est monté dans une autre session
    p = {"name": f"pv-clip-{a.clip}", "video": video, "music": mp, "music_map": mm,
         "sfx_index": f"{ROOT}/sfx_index.json", "title": (a.title or "")[:60], "endcard": True, "seed": a.clip + 3,
         "sfx_every": 2, "continuous": True, "window_start": c["window_start"], "music_level": 0.13, "cuts": cuts}
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
    if not a.path.startswith(("clips/", "inbox/", "moments/")) or ".." in a.path:
        raise SystemExit("suppression refusée : seuls clips/, inbox/ et moments/ sont autorisés")
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


def cmd_ytcheck(a):
    """Vérifie qu'une vidéo YouTube publiée est VRAIMENT visible publiquement (flux public de la chaîne).
    Une vidéo absente du flux = non répertoriée, privée, bloquée (droits d'auteur) ou encore en traitement."""
    import re
    req = urllib.request.Request(f"https://www.youtube.com/feeds/videos.xml?channel_id={a.channel}", headers={"User-Agent": "Mozilla/5.0"})
    feed = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    public = set(re.findall(r"<yt:videoId>([^<]+)</yt:videoId>", feed))
    print(json.dumps({v: (v in public) for v in a.ids.split(",") if v}))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("setup")
    p = sp.add_parser("moments"); p.add_argument("--video", required=True); p.add_argument("--out", required=True)
    p.add_argument("--max", type=int, default=160); p.add_argument("--min-score", type=float, default=0.6)
    p = sp.add_parser("compose"); p.add_argument("--moments", required=True); p.add_argument("--select", required=True)
    p.add_argument("--music", required=True); p.add_argument("--out", required=True); p.add_argument("--length", type=float, default=40)
    p.add_argument("--max-clips", type=int, default=40); p.add_argument("--min-keep", type=float, default=6)
    p = sp.add_parser("extract"); p.add_argument("--video", required=True); p.add_argument("--video-id", required=True)
    p.add_argument("--moments", required=True); p.add_argument("--select", required=True); p.add_argument("--min-keep", type=float, default=6)
    p = sp.add_parser("bank"); p.add_argument("--items", required=True); p.add_argument("--out", required=True)
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
    p = sp.add_parser("ytcheck"); p.add_argument("--channel", default="UCOje5e9UGi-_WK9Y6hHzL5w"); p.add_argument("--ids", required=True)
    a = ap.parse_args()
    {"setup": cmd_setup, "moments": cmd_moments, "compose": cmd_compose, "extract": cmd_extract, "bank": cmd_bank, "render": cmd_render, "publish": cmd_publish, "stats": cmd_stats,
     "download": cmd_download, "delete": cmd_delete, "poststatus": cmd_poststatus, "frames": cmd_frames, "ytcheck": cmd_ytcheck}[a.cmd](a)


if __name__ == "__main__":
    main()
