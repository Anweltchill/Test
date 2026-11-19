# Phoenix Verse : robot de clips GTA 6

Ce dossier contient le robot qui transforme les sessions de jeu déposées sur https://phoenix-verse.netlify.app en clips verticaux de 1 à 2 minutes, et qui les programme sur Instagram et YouTube via Zernio (6 par jour : 7 h, 10 h, 13 h, 16 h, 19 h et 22 h, heure de Paris).

- `robot/pv_worker.py` : le programme (installation, analyse, montage HyperFrames, programmation Zernio, statistiques).
- `robot/hf_build2.py` : le moteur de montage (plans calés sur la musique, transitions, textes aux couleurs de la marque, piste voix continue).
- `robot/RUNBOOK.md` : la procédure que suit chaque passage horaire.
- `../.claude/settings.json` : autorise seulement la commande du robot et les requêtes sur le schéma `phoenix_verse`.

Aucune clé n'est stockée ici : Supabase (stockage) et Zernio sont injectés par l'environnement cloud « Phoenix Verse ». Les données (bibliothèque de sons, polices, logo) sont dans le bucket privé `phoenix-verse-gta`.
