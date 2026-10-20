#!/usr/bin/env bash
# Mixage final + pose de l'audio sur la vidéo rendue.
# Usage : tools/mix.sh <video.mp4> <voix.mp3|-> <musique.wav|-> <bruitages.wav|-> <sortie.mp4>
# Réglages (variables d'environnement, en dB) :
#   MUSIC_DB=-10   niveau de la musique AVANT ducking (dans les silences)
#   DUCK_RATIO=2   force du ducking sous la voix (≈ -20 à -25 dB sous la voix pendant la parole)
#   SFX_DB=-8      niveau des bruitages
#   VOICE_AF=""    filtre en plus sur la voix, ex. remonter un passage chuchoté :
#                  VOICE_AF="volume=enable='between(t,12.3,14.1)':volume=6dB"
# Limiteur doux sur le mélange (pas d'écrêtage = pas de grésillement), puis
# normalisation finale : -14 LUFS intégrés, crête vraie -1 dBTP (deux passes loudnorm).
set -euo pipefail
[ $# -eq 5 ] || { sed -n 2,10p "$0"; exit 1; }
VIDEO=$1; VOICE=$2; MUSIC=$3; SFX=$4; OUT=$5
MUSIC_DB=${MUSIC_DB:--10}; DUCK_RATIO=${DUCK_RATIO:-2}; SFX_DB=${SFX_DB:--8}; VOICE_AF=${VOICE_AF:-}
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VIDEO")

inputs=(); n=0; graph=""; mixin=""
if [ "$VOICE" != "-" ]; then
  inputs+=(-i "$VOICE"); v=$n; n=$((n+1))
  vf="aresample=48000,aformat=channel_layouts=stereo,highpass=f=80,acompressor=threshold=-20dB:ratio=3:attack=10:release=150:makeup=2"
  [ -n "$VOICE_AF" ] && vf="$vf,$VOICE_AF"
  graph+="[$v:a]$vf,asplit=2[voice][key];"
  mixin+="[voice]"
fi
if [ "$MUSIC" != "-" ]; then
  inputs+=(-i "$MUSIC"); m=$n; n=$((n+1))
  graph+="[$m:a]aresample=48000,aformat=channel_layouts=stereo,volume=${MUSIC_DB}dB[mus0];"
  if [ "$VOICE" != "-" ]; then
    graph+="[mus0][key]sidechaincompress=threshold=0.015:ratio=${DUCK_RATIO}:attack=15:release=400:makeup=1[mus];"
  else
    graph+="[mus0]anull[mus];"
  fi
  mixin+="[mus]"
elif [ "$VOICE" != "-" ]; then graph+="[key]anullsink;"; fi
if [ "$SFX" != "-" ]; then
  inputs+=(-i "$SFX"); s=$n; n=$((n+1))
  graph+="[$s:a]aresample=48000,aformat=channel_layouts=stereo,volume=${SFX_DB}dB[sfx];"
  mixin+="[sfx]"
fi
k=$(grep -o '\[' <<<"$mixin" | wc -l)
graph+="${mixin}amix=inputs=$k:normalize=0:duration=longest,alimiter=limit=0.7:attack=5:release=60:level=false,apad,atrim=0:$DUR[pre]"

ffmpeg -v error -y "${inputs[@]}" -filter_complex "$graph" -map "[pre]" -c:a pcm_s24le "$TMP/pre.wav"
# passe 1 : mesure
M=$(ffmpeg -hide_banner -i "$TMP/pre.wav" -af loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json -f null - 2>&1 | sed -n '/^{/,/^}/p')
g() { python3 -c "import json,sys;print(json.loads(sys.stdin.read())['$1'])" <<<"$M"; }
LN="loudnorm=I=-14:TP=-1.5:LRA=11:measured_I=$(g input_i):measured_TP=$(g input_tp):measured_LRA=$(g input_lra):measured_thresh=$(g input_thresh):offset=$(g target_offset):linear=true"
# passe 2 : normalisation + pose sur la vidéo (image copiée telle quelle)
ffmpeg -v error -y -i "$VIDEO" -i "$TMP/pre.wav" -filter_complex "[1:a]$LN,aresample=48000[a]" \
  -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k -movflags +faststart "$OUT"
L=$(ffmpeg -hide_banner -i "$OUT" -af ebur128=peak=true -f null - 2>&1 | grep -E "^\s+(I:|Peak:)" | tr -s ' ' | tr '\n' ' ')
echo "mix OK -> $OUT  ($L)"
