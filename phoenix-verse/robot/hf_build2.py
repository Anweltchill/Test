"""Phoenix Verse - moteur de montage v2 (HyperFrames, 1080x1920).

Nouveautés v2 :
  - musique choisie dans les favoris, démarrée sur son passage le plus intense ;
  - coupes calées sur les VRAIS temps du morceau (grille de analyze-beatgrid.py du skill music-to-video) ;
  - sous-titres mot à mot calés sur la voix (transcription horodatée), mot actif surligné ;
  - musique baissée automatiquement quand la voix est présente ;
  - bruitages discrets choisis selon la transition, volume harmonisé.

Plan JSON :
{"name": "...", "video": "...", "transcript": "scribe.json", "music": "x.mp3", "music_map": "x.json",
 "sfx_index": "sfx_index.json", "title": "...", "endcard": true, "seed": 1,
 "cuts": [{"src": 12.0, "beats": 4, "tr": "slide|punch|whip|flash", "voice": true, "zoom": 1.12}, ...]}
"""
import html as H, json, os, shutil, subprocess, sys, zlib

_AS = os.environ.get("PV_ASSETS")
GSAP = os.path.join(_AS, "gsap.min.js") if _AS else "/home/user/phoenix-terminal/.agents/skills/talking-head-recut/assets/vendor/gsap.min.js"
LIB = os.path.dirname(os.path.abspath(__file__))
PVLIB = "/tmp/claude-0/-home-user-Test/cec51034-2f27-5af8-8dca-62c208c00870/scratchpad/pv/library"
FONT = os.path.join(_AS, "Anton-Regular.ttf") if _AS else os.path.join(PVLIB, "fonts", "Anton-Regular.ttf")
LOGO = os.path.join(_AS, "logo.png") if _AS else os.path.join(PVLIB, "brand", "logo_phoenix_transparent.png")
W, H_, FPS = 1080, 1920, 30
PURPLE, PINK, GOLD = "#7b2cff", "#ff2d95", "#ffd23f"
FG_TOP, FG_H = 500, 780          # zone du jeu (format paysage mis en valeur)
CAP_TOP = 1330                   # sous-titres sous le jeu


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-1500:])
    return r.stdout


def pick_music_window(m, n_beats):
    """Premier temps du passage le plus intense qui contient n_beats temps."""
    beats = m["grid"]["beats_sec"]
    phases = m["energy_phases"]
    dph = m["tempo"].get("downbeat_phase", 0) % 4

    def energy_at(t):
        for p in phases:
            if p["start"] <= t < p["end"]:
                return p["energy"]
        return 0.0

    best, best_i = -1, 0
    for i in range(0, max(1, len(beats) - n_beats - 1)):
        if (i - dph) % 4:
            continue  # démarrer sur un premier temps de mesure
        seg = beats[i:i + n_beats + 1]
        e = sum(energy_at(t) for t in seg) / len(seg)
        if e > best:
            best, best_i = e, i
    return best_i, best


def sfx_for(tr, i, idx, seed):
    cats = {"slide": ["swoosh", "whoosh"], "whip": ["whoosh", "swoosh"], "punch": ["swoosh", "whoosh"], "flash": ["camera shutter", "glitch"]}[tr]
    pool = [x for x in idx if x["cat"] in cats and x["dur"] <= (1.3 if tr != "flash" else 0.9) and x["mean_db"] > -30]
    if not pool:
        return None
    pool.sort(key=lambda x: zlib.crc32((x["id"] + str(seed)).encode()))
    return pool[i % len(pool)]


def chunk_words(words):
    """Groupes de 1 à 3 mots, coupés aux pauses et à la ponctuation."""
    chunks, cur = [], []
    for w in words:
        if cur and (len(cur) >= 3 or w["start"] - cur[-1]["end"] > 0.35 or w["end"] - cur[0]["start"] > 1.3):
            chunks.append(cur)
            cur = []
        cur.append(w)
        if w["text"].rstrip().endswith((".", "?", "!")):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def build(plan, out):
    A = lambda n: os.path.join(out, "assets", n)
    os.makedirs(os.path.join(out, "assets"), exist_ok=True)
    for s, d in [(GSAP, "gsap.min.js"), (FONT, "Anton-Regular.ttf"), (LOGO, "logo.png")]:
        shutil.copy(s, A(d))
    seed = plan.get("seed", 1)

    # ---- musique : fenêtre la plus intense, coupes sur les vrais temps
    m = json.load(open(plan["music_map"]))
    beats = m["grid"]["beats_sec"]
    n_beats = sum(c["beats"] for c in plan["cuts"])
    b0, e = pick_music_window(m, n_beats + 2)
    t_music0 = beats[b0]
    bounds = [0.0]
    acc = 0
    for c in plan["cuts"]:
        acc += c["beats"]
        bounds.append(beats[b0 + acc] - t_music0)
    end_cut = bounds[-1]
    # mode « continu » : plans consécutifs d'une même fenêtre, une seule piste voix (aucun clic aux coupes)
    if plan.get("continuous"):
        w0 = float(plan["window_start"])
        for i, c in enumerate(plan["cuts"]):
            c["src"] = w0 + bounds[i]
            c["voice"] = False
    endcard = 1.3 if plan.get("endcard", True) else 0
    total = end_cut + endcard
    # extrait normalisé (-16 LUFS), fondus propres
    run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{t_music0:.3f}", "-t", f"{total + 0.5:.3f}", "-i", plan["music"],
         "-af", f"loudnorm=I=-16:TP=-2:LRA=11,afade=t=in:d=0.05,afade=t=out:st={max(0, total - 1.0):.3f}:d=1.0",
         "-ar", "44100", "-ac", "2", A("music.wav")])

    words_all = []
    if plan.get("transcript"):
        sc = json.load(open(plan["transcript"]))
        words_all = [w for w in sc["words"] if w.get("type") == "word"]

    idx = json.load(open(plan["sfx_index"])) if plan.get("sfx_index") else []
    html, js, audio, used_sfx = [], [], [], {}
    music_pts = []
    for i, c in enumerate(plan["cuts"]):
        t0, t1 = bounds[i], bounds[i + 1]
        d = t1 - t0
        sp = c.get("speed", 1.0)
        vis = d + (0.12 if i < len(plan["cuts"]) - 1 else 0)
        voice = bool(c.get("voice"))
        seg = f"seg{i:02d}.mp4"
        run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{c['src']:.3f}", "-i", plan["video"], "-t", f"{vis * sp + 0.3:.3f}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-r", "30", "-g", "15", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", A(seg)])
        vend = None
        if voice and c.get("voice_end"):
            vend = max(0.3, min(d, (c["voice_end"] - c["src"]) / sp))
        if voice and vend is not None and vend < d - 0.05:
            vl = json.dumps({"version": 1, "lanes": [{"target": "volume", "points": [{"t": 0, "v": 1}, {"t": round(vend, 3), "v": 1}, {"t": round(min(d, vend + 0.12), 3), "v": 0}]}]})
            aud = f"data-has-audio=\"true\" data-volume=\"1\" data-automation='{vl}'"
        else:
            aud = 'data-has-audio="true" data-volume="1"' if voice else "muted"
        html.append(f'''
      <div class="cut" id="c{i}" style="z-index:{10 + i}">
        <video id="bg{i}" class="clip bgv" src="assets/{seg}" data-start="{t0:.3f}" data-duration="{vis:.3f}" data-media-start="0"
          data-playback-rate="{sp}" data-track-index="{i * 2}" muted playsinline></video>
        <div class="fgbox" id="fgbox{i}"><div class="punch" id="punch{i}"><video id="fg{i}" class="clip fgv" src="assets/{seg}"
          data-start="{t0:.3f}" data-duration="{vis:.3f}" data-media-start="0" data-playback-rate="{sp}" data-track-index="{i * 2 + 1}"
          {aud} playsinline></video></div></div>
      </div>''')
        tr = c.get("tr", "slide")
        sel = f"#c{i}"
        if i == 0:
            js.append(f'tl.set("{sel}",{{opacity:1}},0);')
        elif tr == "slide":
            js.append(f'tl.fromTo("{sel}",{{x:{W},opacity:1}},{{x:0,duration:0.22,ease:"expo.out",immediateRender:false}},{t0:.3f});')
            js.append(f'tl.to("#c{i-1}",{{x:-260,duration:0.22,ease:"expo.out"}},{t0:.3f});')
        elif tr == "punch":
            js.append(f'tl.fromTo("{sel}",{{scale:1.35,opacity:0}},{{scale:1,opacity:1,duration:0.18,ease:"expo.out",immediateRender:false}},{t0:.3f});')
        elif tr == "whip":
            js.append(f'tl.fromTo("{sel}",{{x:-{W},opacity:1,filter:"blur(28px)"}},{{x:0,filter:"blur(0px)",duration:0.22,ease:"expo.out",immediateRender:false}},{t0:.3f});')
            js.append(f'tl.to("#c{i-1}",{{x:{W // 3},filter:"blur(24px)",duration:0.22,ease:"expo.out"}},{t0:.3f});')
        elif tr == "flash":
            js.append(f'tl.set("{sel}",{{opacity:1}},{t0:.3f});')
            js.append(f'tl.fromTo("#flash",{{opacity:0.75}},{{opacity:0,duration:0.2,ease:"power2.out",immediateRender:false}},{t0:.3f});')
        if i > 0:
            js.append(f'tl.set("#c{i-1}",{{opacity:0}},{t0 + 0.26:.3f});')
        z = c.get("zoom", 1.1)
        js.append(f'tl.fromTo("#fgbox{i}",{{scale:1.0}},{{scale:{1 + (z - 1) * 0.6:.3f},duration:{d:.3f},ease:"none"}},{t0:.3f});')
        # punch-in sur le 3e temps d'un plan long (temps réel du morceau)
        if c["beats"] >= 4:
            tp = beats[b0 + sum(x["beats"] for x in plan["cuts"][:i]) + 2] - t_music0
            js.append(f'tl.fromTo("#punch{i}",{{scale:1}},{{scale:{z:.3f},duration:0.08,ease:"power4.out",immediateRender:false}},{tp:.3f});')
            js.append(f'tl.to("#punch{i}",{{scale:1,duration:0.4,ease:"power2.out"}},{tp + 0.08:.3f});')
        # textes d'impact (marque) : en haut et en bas
        for kind, key in (("top", "top"), ("lab", "label")):
            if c.get(key):
                eid = f"{kind}{i}"
                col = c.get(key + "_color", PINK if (i % 2) else "#ffffff")
                html.append(f'      <div class="{kind}" id="{eid}" style="color:{col}">{H.escape(c[key])}</div>')
                js.append(f'tl.fromTo("#{eid}",{{opacity:0,scale:1.7,rotation:-3}},{{opacity:1,scale:1,rotation:0,duration:0.18,ease:"expo.out",immediateRender:false}},{t0 + 0.05:.3f});')
                js.append(f'tl.to("#{eid}",{{scale:1.06,duration:0.1,yoyo:true,repeat:1}},{t0 + 0.3:.3f});')
                js.append(f'tl.to("#{eid}",{{opacity:0,y:-25,duration:0.12}},{t1 - 0.14:.3f});')
        # bruitage de transition (discret)
        if i > 0 and i % plan.get("sfx_every", 1) == 0:
            s = sfx_for(tr, i + seed, idx, seed)
            if s:
                name = f"sfx_{s['id'][:8]}.wav"
                if name not in used_sfx:
                    shutil.copy(s["file"], A(name))
                    used_sfx[name] = s
                g = 0.16 if voice else 0.24
                audio.append(f'<audio id="sfx{i}" src="assets/{name}" data-start="{max(0, t0 - 0.06):.3f}" data-duration="{min(1.2, s["dur"]):.2f}" '
                             f'data-track-index="{60 + i}" data-volume="{g}"></audio>')
        # sous-titres mot à mot (voix)
        if voice and words_all:
            src0, src1 = c["src"], min(c["src"] + d * sp, c.get("voice_end", 1e9) + 0.1)
            ws = [w for w in words_all if src0 - 0.05 <= w["start"] < src1 - 0.12 and any(ch.isalnum() for ch in w["text"])]
            chunks = chunk_words(ws)
            for k, ch in enumerate(chunks):
                ta = t0 + max(0, (ch[0]["start"] - src0) / sp)
                nxt = t0 + (chunks[k + 1][0]["start"] - src0) / sp if k + 1 < len(chunks) else t1
                tb = min(t1 - 0.02, max(ta + 0.35, t0 + (ch[-1]["end"] - src0) / sp + 0.12), nxt)
                if ta >= t1 - 0.15 or tb <= ta + 0.1:
                    continue  # groupe hors du plan : jamais affiché
                cid = f"cap{i}_{k}"
                spans = "".join(f'<span id="{cid}w{j}">{H.escape(w["text"].upper())}</span> ' for j, w in enumerate(ch))
                html.append(f'      <div class="cap" id="{cid}">{spans.strip()}</div>')
                js.append(f'tl.fromTo("#{cid}",{{opacity:0,scale:0.7,y:20}},{{opacity:1,scale:1,y:0,duration:0.12,ease:"back.out(2.4)",immediateRender:false}},{ta:.3f});')
                js.append(f'tl.set("#{cid}",{{opacity:0}},{tb:.3f});')
                for j, w in enumerate(ch):
                    tw = t0 + max(0, (w["start"] - src0) / sp)
                    js.append(f'tl.set("#{cid}w{j}",{{color:"{PINK}"}},{tw:.3f});')
                    if j + 1 < len(ch):
                        js.append(f'tl.set("#{cid}w{j}",{{color:"#ffffff"}},{t0 + max(0, (ch[j + 1]["start"] - src0) / sp):.3f});')
        # niveau de musique : baissée sous la voix
        hi, lo = plan.get("music_level", 0.85), plan.get("music_under_voice", 0.28)
        if voice:
            ve = t0 + (vend if vend is not None else d)
            music_pts += [{"t": round(t0 + (0.06 if i else 0), 3), "v": lo}, {"t": round(max(t0 + 0.07, min(ve, t1 - 0.06)), 3), "v": lo}]
            if ve < t1 - 0.25:
                music_pts += [{"t": round(ve + 0.15, 3), "v": hi}, {"t": round(t1 - 0.06, 3), "v": hi}]
        else:
            music_pts += [{"t": round(t0 + (0.06 if i else 0), 3), "v": hi}, {"t": round(max(t0 + 0.07, t1 - 0.06), 3), "v": hi}]

    # carte de fin
    if endcard:
        e0 = end_cut
        html.append('''
      <div id="end" style="z-index:100"><img id="endlogo" src="assets/logo.png"/><div id="endname">PHOENIX VERSE</div><div id="endsub">ABONNE-TOI</div></div>''')
        js += [f'tl.set("#c{len(plan["cuts"])-1}",{{opacity:0}},{e0 + 0.02:.3f});',
               f'tl.fromTo("#end",{{opacity:0}},{{opacity:1,duration:0.12,immediateRender:false}},{e0:.3f});',
               f'tl.fromTo("#endlogo",{{scale:0.4,opacity:0}},{{scale:1,opacity:1,duration:0.4,ease:"back.out(2)",immediateRender:false}},{e0 + 0.05:.3f});',
               f'tl.fromTo("#endname",{{y:40,opacity:0}},{{y:0,opacity:1,duration:0.3,ease:"power3.out",immediateRender:false}},{e0 + 0.2:.3f});',
               f'tl.fromTo("#endsub",{{y:30,opacity:0}},{{y:0,opacity:1,duration:0.3,ease:"power3.out",immediateRender:false}},{e0 + 0.35:.3f});']
        music_pts += [{"t": round(e0 + 0.05, 3), "v": plan.get("music_level", 0.85)}]
    if plan.get("title"):
        js.append('tl.fromTo("#title",{y:-50,opacity:0,scale:0.92},{y:0,opacity:1,scale:1,duration:0.3,ease:"back.out(2)"},0.05);')
        js.append(f'tl.to("#title",{{opacity:0,y:-30,duration:0.2}},{min(2.4, end_cut - 0.3):.3f});')

    if plan.get("continuous"):
        run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{float(plan['window_start']):.3f}", "-i", plan["video"], "-t", f"{end_cut:.3f}",
             "-vn", "-af", f"loudnorm=I=-16:TP=-2:LRA=11,afade=t=out:st={max(0, end_cut - 0.4):.3f}:d=0.4", "-ar", "44100", "-ac", "2", A("voice.wav")])
        audio.append(f'<audio id="voice" src="assets/voice.wav" data-start="0" data-duration="{end_cut:.3f}" data-track-index="51" data-volume="1"></audio>')
    lane = json.dumps({"version": 1, "lanes": [{"target": "volume", "points": music_pts}]})
    audio.insert(0, f"<audio id=\"music\" src=\"assets/music.wav\" data-start=\"0\" data-duration=\"{total:.3f}\" data-track-index=\"50\" data-volume=\"1\" data-automation='{lane}'></audio>")

    page = f'''<!doctype html>
<html lang="fr"><head><meta charset="UTF-8" /><meta name="viewport" content="width={W}, height={H_}" />
<script src="assets/gsap.min.js"></script>
<style>
@font-face {{ font-family: "Anton"; src: url("assets/Anton-Regular.ttf"); }}
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ width:{W}px; height:{H_}px; overflow:hidden; background:#0b0614; }}
#root {{ position:relative; width:{W}px; height:{H_}px; overflow:hidden; font-family:"Anton", sans-serif; }}
.cut {{ position:absolute; left:0; top:0; width:{W}px; height:{H_}px; opacity:0; overflow:hidden; }}
.bgv {{ position:absolute; left:-120px; top:-120px; width:{W + 240}px; height:{H_ + 240}px; object-fit:cover; filter:blur(40px) brightness(0.5) saturate(1.35); }}
.fgbox {{ position:absolute; left:0; top:{FG_TOP}px; width:{W}px; height:{FG_H}px; overflow:hidden; transform-origin:50% 50%; box-shadow:0 0 80px 8px rgba(123,44,255,0.45); }}
.punch {{ width:100%; height:100%; transform-origin:50% 50%; }}
.fgv {{ width:100%; height:100%; object-fit:cover; }}
.cap {{ position:absolute; left:40px; width:{W - 80}px; top:{CAP_TOP}px; text-align:center; font-size:92px; line-height:1.05; color:#fff; z-index:80;
        -webkit-text-stroke:11px {PURPLE}; paint-order:stroke fill; text-shadow:0 9px 0 rgba(0,0,0,0.6); opacity:0; }}
.top {{ position:absolute; left:40px; width:{W - 80}px; top:270px; text-align:center; font-size:96px; line-height:1.02; z-index:75; opacity:0;
        -webkit-text-stroke:10px #12081f; paint-order:stroke fill; text-shadow:0 8px 0 rgba(0,0,0,0.5); text-transform:uppercase; }}
.lab {{ position:absolute; left:40px; width:{W - 80}px; top:{CAP_TOP}px; text-align:center; font-size:120px; line-height:1; z-index:76; opacity:0;
        -webkit-text-stroke:11px {PURPLE}; paint-order:stroke fill; text-shadow:0 9px 0 rgba(0,0,0,0.6); text-transform:uppercase; }}
#title {{ position:absolute; left:40px; width:{W - 80}px; top:250px; text-align:center; font-size:92px; line-height:1.02; color:#fff; z-index:60;
         -webkit-text-stroke:8px {PURPLE}; paint-order:stroke fill; text-shadow:0 8px 0 rgba(0,0,0,0.5); opacity:0; text-transform:uppercase; }}
#wm {{ position:absolute; left:36px; top:1640px; width:96px; z-index:70; opacity:0.85; }}
#wmt {{ position:absolute; left:142px; top:1658px; font-size:36px; color:#fff; z-index:70; letter-spacing:1px; text-shadow:0 3px 0 rgba(0,0,0,.6); }}
#flash {{ position:absolute; inset:0; background:#fff; z-index:90; opacity:0; }}
#end {{ position:absolute; inset:0; background:radial-gradient(circle at 50% 40%, #2a0f4f 0%, #0b0614 70%); opacity:0; }}
#endlogo {{ position:absolute; left:290px; top:430px; width:500px; }}
#endname {{ position:absolute; left:0; width:{W}px; top:1030px; text-align:center; font-size:120px; color:#fff; -webkit-text-stroke:8px {PURPLE}; paint-order:stroke fill; }}
#endsub {{ position:absolute; left:0; width:{W}px; top:1190px; text-align:center; font-size:78px; color:{PINK}; }}
</style></head><body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{total:.3f}" data-width="{W}" data-height="{H_}">
{''.join(html)}
  <div id="title">{H.escape(plan.get("title", ""))}</div>
  <img id="wm" src="assets/logo.png" /><div id="wmt">PHOENIX VERSE</div>
  <div id="flash"></div>
  {chr(10).join(audio)}
</div>
<script>
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{ paused: true }});
{chr(10).join(js)}
window.__timelines["main"] = tl;
tl.seek(0);
</script></body></html>
'''
    open(os.path.join(out, "index.html"), "w", encoding="utf-8").write(page)
    json.dump({"$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
               "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
               "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
               "media": {"autoProxy": True}}, open(os.path.join(out, "hyperframes.json"), "w"), indent=2)
    json.dump({"name": plan["name"], "version": "1"}, open(os.path.join(out, "meta.json"), "w"))
    credits = [{"title": x["title"], "creator": x["creator"], "license": x["license"], "attribution": x["attribution"]}
               for x in used_sfx.values() if x.get("license") == "by"]
    json.dump({"music_start": t_music0, "music_energy": e, "bpm": m["tempo"]["bpm"], "total": total,
               "sfx": [x["title"] for x in used_sfx.values()], "sfx_credits_by": credits},
              open(os.path.join(out, "build_info.json"), "w"), ensure_ascii=False, indent=1)
    print(f"{plan['name']}: {len(plan['cuts'])} plans, {total:.1f}s, musique à {t_music0:.1f}s ({m['tempo']['bpm']} BPM, énergie {e:.2f}), {len(used_sfx)} bruitages")


if __name__ == "__main__":
    build(json.load(open(sys.argv[1])), sys.argv[2])
