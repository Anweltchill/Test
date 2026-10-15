---
name: reel-ugc
description: Pipeline complet de la chaîne Reels UGC (motion design 9:16, voix off ElevenLabs) — script, voix-off.txt, calage au mot (ASR local), storyboard, scènes HyperFrames, musique, bruitages, mixage -14 LUFS, contrôle qualité, rendu, étalonnage, livraison dans le chat. À lire en premier pour toute demande de Reel, de script, de brand ou de rendu dans reels-ugc/.
---

# Studio Reels UGC — pipeline

Tout se passe dans `reels-ugc/` (sous-dossier du dépôt). Répondre **en français simple**, donner l'avancement
en une phrase régulièrement, **envoyer chaque vidéo finie dans le chat** (SendUserFile).
Ce skill prime sur l'entretien d'intention du skill `hyperframes` : on ne pose pas ses questions, on suit ce pipeline.
Les skills HyperFrames servent de référence technique (`hyperframes-core`, `hyperframes-animation`,
`hyperframes-keyframes`, `faceless-explainer`, `media-use`, `hyperframes-cli`).

## 0. Environnement (chaque nouvelle session)
`tools/setup.sh` — pip (numpy pillow soundfile sherpa-onnx), modèle Parakeet dans `models/parakeet`
(GitHub releases ; Hugging Face peut être bloqué), playwright-core dans `/tmp/reels-qc`.
CLI épinglé : `npx --yes hyperframes@$(cat tools/HYPERFRAMES_VERSION) …` (jamais `@latest` pour un rendu).
Chromium : `/opt/pw-browsers` (ne pas lancer `playwright install`).
Ne pas envoyer de rapport `hyperframes feedback` (canal public) sans accord.

## 1. Brand — fourni par l'utilisateur, jamais inventé
- Pas de brand reçu → pas de vraie vidéo (tests en noir et blanc seulement).
- Réception : logo/icône **tels quels** dans `brand/logo/`, polices en `.woff2` dans `brand/fonts/`
  (convertir avec `fonttools` : `pip install fonttools brotli` puis `pyftsubset … --flavor=woff2` ou `fontTools.ttLib`),
  couleurs relevées exactement → `brand/frame.md` (couleurs, typo, composants : cartes, pastilles, boutons,
  curseur, notifications, mockups téléphone/DM/e-mail/facture/contrat) **uniquement à partir du brand reçu**.
- Montrer une **planche de contrôle** (logo + couleurs + polices + 2 composants) avant usage.
- Info manquante → la **demander**. Logo toujours en `<img>`, jamais retapé, redessiné ni recoloré.

## 2. Script (par Reel)
Stratégie Phoenix Pro (consigne cliente) : s'appuyer sur `contenu/BASE-CONNAISSANCES.md` sans s'y limiter ;
**donner envie sans livrer le « comment » final** (pas de modèles complets, listes de noms, tarifs détaillés) ;
boucle ouverte + CTA (lien en bio, ou mot-clé en message privé) ; ~45 s. Cible surtout féminine (« créatrice »).

1. Sujet donné → proposer **3 angles d'accroche**, attendre le choix.
2. Script : 30–60 s (≈75–150 mots), accroche dans les 2 premières secondes, une idée par phrase, tutoiement,
   concret (étapes, exemples, ordres de grandeur), CTA final (s'abonner / commenter un mot-clé / enregistrer).
   **Jamais** de gains garantis, de faux témoignages, de chiffres inventés présentés comme réels.
   Appliquer partout les corrections d'orthographe/de formulation données par l'utilisateur.
3. `reels/<NN-slug>/voix-off.txt`, prêt à coller dans ElevenLabs :
   - **Eleven v3** (≤ 3 000 caractères) : balises `[excited]`, `[whispers]`, `[pause]`… ; dire de désactiver
     « Baliser automatiquement ». Au-delà → **Multilingual v2** (≤ 10 000) **sans aucune balise**.
   - Nombres en toutes lettres, sigles/anglicismes épelés si besoin (« U-G-C », « D-M »).
   - Réglages conseillés : stabilité ~50 %, vitesse 1.0, voix choisie par l'utilisateur.
   - + légende Instagram + 5 à 10 hashtags (dans `script.md`).
4. L'utilisateur renvoie **un seul MP3 continu** → `audio/voix.mp3`. Ne jamais demander de découpe.

## 3. Fabrication
Créer le dossier : `tools/new-reel.sh NN-slug` (copie GSAP local, polices et logo du brand dans le projet :
le moteur ne sert que le dossier du Reel, donc **tous les chemins sont relatifs au Reel** : `assets/…`).

1. **Calage** : `python3 tools/asr.py audio/voix.mp3 audio/mots.json`. Chaque mot-clé / apparition / bruitage
   tombe sur son mot (±0,05 s) ; les entrées démarrent ~0,15 s avant le mot.
2. **STORYBOARD.md** : scènes de 3–8 s (durée, transition, idée visuelle, mots-clés + temps locaux).
   Sujet nouveau → le montrer en 10 lignes avant de fabriquer ; sinon enchaîner.
3. **Scènes** : `compositions/frames/NN-nom.html` (sous-compositions `<template>`), assemblées dans `index.html`
   (root `data-composition-id="main"`, 1080×1920, voix en `<audio id="voix">` continue pour la prévisualisation).
   Fabriquer en **parallèle avec des sous-agents** (1–3 scènes chacun) avec un brief commun : format, zones de
   sécurité, composants partagés de `brand/frame.md`, règles techniques ci-dessous, temps des mots (`mots.json`).
   Chaque sous-agent rend aussi `NN-nom.sfx.json` : `[{"t": temps_local, "sound": "whoosh", "vol": 0.4}]`.
   Modèle de référence qui passe lint/check : `reels/00-test/`.
4. **Format** 1080×1920 (4K possible au rendu) :
   - Zones de sécurité : rien d'important dans **220 px haut, 380 px bas, 64 px gauche, 120 px droite**
     (zone utile x 64→960, y 220→1540). Fonds/décors peuvent déborder.
   - Typo : mots-chocs 120–220 px, secondaires 52–64 px, étiquettes ≥ 30 px (jamais < 26). 1 à 5 mots à
     l'écran, jamais la phrase entière, un mot en couleur d'accent.
   - **Sous-titres dynamiques mot à mot** calés sur la voix, dans la zone sûre (sauf contre-ordre).
   - Mouvement permanent mais lisible : un point focal, caméra qui pousse/glisse, entrées power4/expo 0,4–0,7 s,
     ressorts (back.out) pour l'UI, transitions nerveuses (whip + flou, zoom-through). Rien de statique > ~1,5 s.
   - Interface montrée **en entier** d'abord, puis zoom sur le détail.
   - Pas de vraies marques / logos (Instagram, Gmail, TikTok…) ni de vraies personnes : marques fictives
     (« Marque cosmétique », « Brand X »), mockups neutres.
5. **Règles techniques (strictes)** :
   - Une timeline GSAP **en pause** par composition dans `window.__timelines["<id>"]` (= `data-composition-id`),
     durée exacte de la scène ; `<style>` et `<script>` (y compris `<script src="assets/gsap.min.js">`) **dans** le `<template>`.
   - Ids et classes préfixés par la scène (`f01-…`), jamais commençant par un chiffre ; root stylé par `#root`.
   - Compteurs : objet à *setter* qui écrit le texte (`set v(x){ el.textContent = … }`), pas de logique seulement dans `onUpdate`.
   - Animer seulement transform, opacity, filter, clip-path, attributs SVG, stroke-dashoffset ; jamais
     letterSpacing, width/height/top/left de texte.
   - `immediateRender:false` sur les `fromTo` répétés d'un même élément ; pas de `tl.set(…, {autoAlpha:0}, 0)`
     sur un élément révélé plus tard ; calques plein écran cachés au départ : `opacity:0` en CSS.
   - Pas de transition/animation CSS, pas de `Math.random` (PRNG à graine), pas de `Date`, pas de `repeat:-1`,
     aucun accès réseau (polices `@font-face` locales, pas de CDN). Pas de clip-path sur un `<g>` SVG.
   - Pas de transform CSS initial sur un élément que GSAP anime (utiliser `fromTo`). Centrer avec flex/inset.
   - ★ ✓ → flèches : SVG inline si la police ne les a pas. Pas de `<br>` dans le texte.
   - Débordements voulus (caméra, masques) : `data-layout-allow-overflow`.
   - Playwright : `page.evaluate(() => { tl.time(t); })` sans retourner la timeline.
6. **Musique** : `python3 tools/music.py audio/musique.wav --duration D --bpm 110-128 --sections "0:intro,1.5:drop,…"`
   (synthèse numpy, libre de droits, varie selon les parties, finit proprement) ou musique libre fournie.
7. **Bruitages** : `python3 tools/sfx.py audio/sfx.wav --duration D compositions/frames/01-x.sfx.json:0 02-y.sfx.json:6.4 …`
   (offset = début de la scène). Bibliothèque `.agents/skills/media-use/audio/assets/sfx` (Pixabay, sans attribution) :
   click, click-soft, whoosh, whoosh-short, whoosh-cinematic, pop, ping, chime, notification, typing, key-press,
   sparkle, riser, impact-bass-1/2, error, glitch-1/2/3. Subtils (vol 0,3–0,6).
8. **Contrôle qualité (obligatoire avant rendu)** : `npx --yes hyperframes@V lint .` + `check .` (0 erreur),
   puis `python3 tools/contact.py reels/NN-slug /tmp/…/planche.jpg --step 2.5` (zones sûres en rouge) et
   **regarder la planche** : aucun écran vide/noir, aucun débordement/chevauchement, rien dans les zones Instagram,
   orthographe parfaite, chaque mot-clé sur son mot. Vérifier les transitions avec `--at` serrés. Corriger avant de rendre.
9. **Rendu** : `npx --yes hyperframes@V render -f 30 -q delivery -o renders/video.mp4 .`
   (`delivery` = qualité finale ; `draft` pour itérer vite). 4K sur demande : `--resolution portrait-4k` (3–4× plus long).
10. **Mixage** : `tools/mix.sh renders/video.mp4 audio/voix.mp3 audio/musique.wav audio/sfx.wav renders/mix.mp4`
    — voix devant, musique en ducking (sidechaincompress, ≈ -20/-25 dB sous la voix, plus présente dans les silences),
    bruitages subtils, **-14 LUFS, crête -1 dBTP**. Passage chuchoté/faible : `VOICE_AF="volume=enable='between(t,a,b)':volume=6dB"`
    et pas d'impact/sub dessus. Réglages : `MUSIC_DB`, `DUCK_RATIO`, `SFX_DB`.
11. **Étalonnage doux** : `tools/grade.sh renders/mix.mp4 renders/master.mp4` (image clé toutes les 2 s pour la découpe ; contraste léger, oranges/jaunes calmés,
    pas de boost de saturation). Changement de réglage (`GRADE_VF`) → montrer un avant/après sur 3 images.
12. **Livraison** (limite chat 30 Mo/fichier) :
    - `tools/deliver.sh renders/master.mp4 renders/chat.mp4` → copie < 29 Mo (H.264 2 passes, AAC 128k) envoyée dans le chat ;
    - maître > 30 Mo (4K) : `tools/split.sh renders/master.mp4 renders/morceaux` → morceaux < 27 Mo sans recompression,
      « 01-sur-NN », à recoller dans l'ordre (CapCut) ;
    - donner le chemin de la version pleine qualité. Pas de Google Drive pour les vidéos.
13. Message de fin : ce qu'il y a dans la vidéo, ce qui a été adapté, les points à valider.

## 4. Séries
`reels/IDEES.md` : calendrier par piliers. Même ouverture, même habillage, mêmes composants d'un Reel à l'autre.

## Git
Commiter et pousser le code après chaque étape importante (branche de travail de la session),
jamais les vidéos rendues ni les `.wav` (voir `.gitignore`).
