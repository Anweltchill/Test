# Studio Reels UGC (motion design Instagram 9:16)

Projet **indépendant** du reste du dépôt (les PDF à la racine n'ont rien à voir : ne pas y toucher).
Tout le travail se fait dans `reels-ugc/`.

- Parler **français simple** à l'utilisateur (travaille depuis une tablette), avancement en une phrase,
  vidéos finies **envoyées dans le chat**.
- Pipeline complet : **`.claude/skills/reel-ugc/SKILL.md`** — à lire avant toute action (script, brand, Reel, rendu).
- Nouvelle session : lancer `tools/setup.sh` (modèle ASR, dépendances Python, outil de captures).
- Moteur vidéo : HyperFrames, version épinglée dans `tools/HYPERFRAMES_VERSION`
  (`npx --yes hyperframes@<version> …`). Skills officiels dans `.agents/skills/` (liens dans `.claude/skills/`).
- **Brand** : fourni par l'utilisateur uniquement (`brand/`). Ne jamais inventer palette, police ou logo ;
  demander ce qui manque. Logo toujours en image, tel quel.

## Arborescence
```
brand/            identité (frame.md, logo/, fonts/) — en attente de l'utilisateur
tools/            setup.sh, new-reel.sh, asr.py, music.py, sfx.py, contact.py, mix.sh, grade.sh, deliver.sh, split.sh
assets/vendor/    gsap.min.js (local, jamais de CDN)
reels/IDEES.md    calendrier de contenus
reels/<NN-slug>/  script.md, voix-off.txt, audio/, STORYBOARD.md, index.html, compositions/frames/, renders/ (ignoré)
models/           modèle Parakeet (ignoré, re-téléchargé par setup.sh)
```
`reels/00-test/` : test de bout en bout (noir et blanc, sans brand) — modèle de structure qui passe lint/check.

## Git
Commiter/pousser le code après chaque étape importante ; jamais les vidéos ni les `.wav`.
