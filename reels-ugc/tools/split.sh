#!/usr/bin/env bash
# Découpe SANS recompression en morceaux < 27 Mo, coupés sur des images clés.
# Usage : tools/split.sh <maitre.mp4> <dossier_sortie> [taille_Mo=27]
# Sortie : <nom>-01-sur-NN.mp4 ... à recoller dans l'ordre (CapCut).
set -euo pipefail
[ $# -ge 2 ] || { sed -n 2,4p "$0"; exit 1; }
IN=$1; DIR=$2; MB=${3:-27}; mkdir -p "$DIR"
NAME=$(basename "${IN%.*}")
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$IN")
SIZE=$(stat -c %s "$IN")
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
# coupe sur images clés : si un morceau dépasse, on recommence avec des morceaux plus courts
for k in 0.85 0.7 0.55 0.4 0.3; do
  rm -f "$TMP"/*
  SEG=$(python3 -c "print(max(1.0, $DUR * $MB*1e6*$k / $SIZE))")
  ffmpeg -v error -y -i "$IN" -map 0 -c copy -f segment -segment_time "$SEG" -reset_timestamps 1 "$TMP/part-%02d.mp4"
  big=0; for f in "$TMP"/*.mp4; do [ "$(stat -c %s "$f")" -lt $((MB*1000*1000)) ] || big=1; done
  [ $big -eq 0 ] && break
done
[ $big -eq 0 ] || echo "ATTENTION : un morceau dépasse encore ${MB} Mo (images clés trop espacées : repasser par tools/grade.sh)"
N=$(ls "$TMP" | wc -l); i=0
for f in $(ls "$TMP" | sort); do
  i=$((i+1)); dst=$(printf "%s/%s-%02d-sur-%02d.mp4" "$DIR" "$NAME" $i $N)
  mv "$TMP/$f" "$dst"
  echo "$dst  $(du -h "$dst" | cut -f1)"
done
