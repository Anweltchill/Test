/* Phoenix Pro — petits effets motion réutilisables (déterministes, seek-safe). Copié dans chaque Reel : assets/fx.js
   Usage dans une scène :  PX.float(tl, "#s1-img", 0.5, 3, 12);  PX.burst(tl, "#s1-cam", 540, 700, 1.2, { n: 14 });
   Toutes les fonctions ajoutent des tweens à la timeline passée (jamais de repeat:-1, jamais de Math.random). */
(function () {
  const COLORS = ["#E2718D", "#CC7183", "#DB96A1", "#0E1928", "#C2C7DD", "#E6BDC1"];
  function rng(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const q = (s) => (typeof s === "string" ? document.querySelector(s) : s);
  window.PX = {
    rng,
    /* flottement doux (sur un wrapper, pas sur l'élément qui fait son entrée) */
    float(tl, sel, t0, dur, amp, period, rot) {
      amp = amp || 12; period = period || 1.6; rot = rot || 0;
      const n = Math.max(1, Math.floor(dur / (period / 2)));
      tl.fromTo(sel, { y: -amp, rotation: -rot }, { y: amp, rotation: rot, duration: period / 2, ease: "sine.inOut", yoyo: true, repeat: n - 1, immediateRender: false }, t0);
    },
    /* pulsation (bouton, badge) */
    pulse(tl, sel, t0, dur, s, period) {
      s = s || 1.06; period = period || 0.7;
      const n = Math.max(1, Math.floor(dur / (period / 2)));
      tl.fromTo(sel, { scale: 1 }, { scale: s, duration: period / 2, ease: "sine.inOut", yoyo: true, repeat: n - 1, immediateRender: false }, t0);
    },
    /* explosion de particules (cercles + étoiles) depuis (x, y) dans le conteneur */
    burst(tl, parentSel, x, y, t, o) {
      o = Object.assign({ n: 12, r: 220, size: 22, seed: 7, dur: 0.75 }, o || {});
      const parent = q(parentSel), R = rng(o.seed);
      for (let i = 0; i < o.n; i++) {
        const el = document.createElement("div");
        const star = i % 3 === 0, sz = o.size * (0.6 + R() * 0.8);
        el.style.cssText = `position:absolute;left:${x - sz / 2}px;top:${y - sz / 2}px;width:${sz}px;height:${sz}px;opacity:0;pointer-events:none;` +
          (star ? `background:${COLORS[i % COLORS.length]};clip-path:polygon(50% 0,61% 39%,100% 50%,61% 61%,50% 100%,39% 61%,0 50%,39% 39%);`
                : `background:${COLORS[i % COLORS.length]};border-radius:50%;`);
        parent.appendChild(el);
        const a = (i / o.n) * Math.PI * 2 + R() * 0.5, d = o.r * (0.55 + R() * 0.6);
        tl.fromTo(el, { x: 0, y: 0, scale: 0.2, opacity: 1, rotation: 0 },
          { x: Math.cos(a) * d, y: Math.sin(a) * d, scale: 1, rotation: R() * 240 - 120, duration: o.dur, ease: "expo.out", immediateRender: false }, t);
        tl.to(el, { opacity: 0, duration: 0.3, ease: "power1.in" }, t + o.dur * 0.6);
      }
    },
    /* découpe un texte en lettres animables (.ch) ; renvoie la liste */
    split(sel) {
      const el = q(sel), txt = el.textContent; el.textContent = "";
      return Array.from(txt).map((c) => {
        const s = document.createElement("span");
        s.className = "ch"; s.style.display = "inline-block"; s.style.whiteSpace = "pre";
        s.textContent = c; el.appendChild(s); return s;
      });
    },
    /* entrée lettre par lettre */
    letters(tl, sel, t, o) {
      o = Object.assign({ y: 90, stagger: 0.03, dur: 0.5, ease: "back.out(2)" }, o || {});
      const chs = PX.split(sel);
      tl.fromTo(chs, { y: o.y, opacity: 0, rotation: 8 }, { y: 0, opacity: 1, rotation: 0, duration: o.dur, ease: o.ease, stagger: o.stagger }, t);
      return chs;
    },
  };
})();
