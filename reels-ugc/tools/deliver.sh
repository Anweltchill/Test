#!/usr/bin/env bash
# Copie légère pour le chat (< 29 Mo) : H.264 deux passes, AAC 128k.
# Usage : tools/deliver.sh <maitre.mp4> <sortie.mp4> [taille_Mo=28]
set -euo pipefail
[ $# -ge 2 ] || { sed -n 2,3p "$0"; exit 1; }
IN=$1; OUT=$2; MB=${3:-28}
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$IN")
SIZE=$(stat -c %s "$IN")
if [ "$SIZE" -lt $((MB*1000*1000)) ] && ffprobe -v error -select_streams v -show_entries stream=height -of csv=p=0 "$IN" | grep -qx 1920; then
  cp "$IN" "$OUT"; echo "déjà < ${MB} Mo, copie -> $OUT"; exit 0
fi
# débit vidéo = budget total - audio, plafonné à 14 Mb/s
VB=$(python3 -c "print(min(14000, int(($MB*8*1000*0.96)/$DUR - 128)))")
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
SC="scale=1080:1920:flags=lanczos"
ffmpeg -v error -y -i "$IN" -vf "$SC" -c:v libx264 -preset slow -b:v ${VB}k -pass 1 -passlogfile "$TMP/p" -an -f mp4 /dev/null
ffmpeg -v error -y -i "$IN" -vf "$SC" -c:v libx264 -preset slow -b:v ${VB}k -pass 2 -passlogfile "$TMP/p" -pix_fmt yuv420p -c:a aac -b:a 128k -movflags +faststart "$OUT"
echo "copie chat -> $OUT ($(du -h "$OUT" | cut -f1), ${VB} kb/s)"
