# 00-test — test de bout en bout (Étape 0)

10 s, noir et blanc, sans brand : texte cinétique masqué, carte UI à ressort avec compteur (setter),
sous-titres mot à mot, whip flouté, coche SVG en stroke-dashoffset, pastilles.
Audio : musique synthétisée (tools/music.py, 120 BPM) + bruitages (sfx.json), mix -14 LUFS.

Commandes :
  python3 ../../tools/music.py audio/musique.wav --duration 10 --bpm 120 --sections "0:intro,1:drop,4.5:break,5:drop,8:outro"
  python3 ../../tools/sfx.py audio/sfx.wav --duration 10 compositions/frames/01-hook.sfx.json:0 compositions/frames/02-ok.sfx.json:5
  npx --yes hyperframes@0.8.159 render -f 30 -q delivery -o renders/video.mp4 .
  ../../tools/mix.sh renders/video.mp4 - audio/musique.wav audio/sfx.wav renders/mix.mp4
  ../../tools/grade.sh renders/mix.mp4 renders/master.mp4
  ../../tools/deliver.sh renders/master.mp4 renders/00-test-chat.mp4
