#!/usr/bin/env bash
# Crée le dossier d'un nouveau Reel.
# Usage : tools/new-reel.sh <NN-slug>      ex. tools/new-reel.sh 01-contacter-une-marque
set -euo pipefail
[ $# -eq 1 ] || { sed -n 2,3p "$0"; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; D="$ROOT/reels/$1"; V=$(cat "$ROOT/tools/HYPERFRAMES_VERSION")
[ -e "$D/index.html" ] && { echo "$D contient déjà une vidéo"; exit 1; }
mkdir -p "$D"/{audio,compositions/frames,assets/fonts,assets/brand,renders}
cp "$ROOT/assets/vendor/gsap.min.js" "$D/assets/"
# polices et logos de la chaîne copiés dans le projet (le moteur ne sert que le dossier du Reel)
[ -d "$ROOT/brand/fonts" ] && cp "$ROOT"/brand/fonts/*.woff2 "$D/assets/fonts/" 2>/dev/null || true
[ -d "$ROOT/brand/logo" ] && cp "$ROOT"/brand/logo/* "$D/assets/brand/" 2>/dev/null || true
cat > "$D/package.json" <<JSON
{
  "name": "reel-$1",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "npx --yes hyperframes@$V preview",
    "check": "npx --yes hyperframes@$V check",
    "render": "npx --yes hyperframes@$V render -f 30 -q delivery -o renders/master.mp4"
  }
}
JSON
cat > "$D/hyperframes.json" <<'JSON'
{
  "paths": { "blocks": "compositions", "components": "compositions/components", "assets": "assets" },
  "media": { "autoProxy": true }
}
JSON
[ -f "$D/script.md" ] || printf "# Script — %s\n\n" "$1" > "$D/script.md"
echo "Reel créé : $D"
