#!/usr/bin/env bash
# Étalonnage doux (pas de boost de saturation, oranges/jaunes calmés).
# Usage : tools/grade.sh <entree.mp4> <sortie.mp4>
# GRADE_VF pour remplacer le réglage (montrer un avant/après sur 3 images si on le change).
set -euo pipefail
[ $# -eq 2 ] || { sed -n 2,4p "$0"; exit 1; }
VF=${GRADE_VF:-"eq=contrast=1.03,huesaturation=saturation=-0.18:colors=r+y:strength=1,vibrance=intensity=0.08"}
ffmpeg -v error -y -i "$1" -vf "$VF" -c:v libx264 -crf 16 -preset slow -g 60 -keyint_min 30 -pix_fmt yuv420p -c:a copy -movflags +faststart "$2"
echo "étalonnage OK -> $2"
