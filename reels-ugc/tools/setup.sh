#!/usr/bin/env bash
# Remet l'environnement en état dans une nouvelle session (idempotent).
# Usage : tools/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
command -v ffmpeg >/dev/null || { apt-get update -qq && apt-get install -y -qq ffmpeg; }
node -e 'process.exit(+process.versions.node.split(".")[0] < 20)' || echo "ATTENTION : Node >= 20 requis"
python3 -c "import numpy, PIL, soundfile, sherpa_onnx" 2>/dev/null || pip install -q numpy pillow soundfile sherpa-onnx
if [ ! -f models/parakeet/encoder.int8.onnx ]; then
  echo "Téléchargement du modèle Parakeet TDT v3 (~650 Mo)…"
  mkdir -p models && curl -sSL https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2 | tar xj -C models
  mv models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8 models/parakeet
fi
QC=${QC_DIR:-/tmp/reels-qc}
[ -d "$QC/node_modules/playwright-core" ] || { mkdir -p "$QC" && (cd "$QC" && npm init -y >/dev/null && npm i -s playwright-core); }
[ -f assets/vendor/gsap.min.js ] || echo "ATTENTION : assets/vendor/gsap.min.js manquant (npm i gsap@3.14.2 puis copier dist/gsap.min.js)"
npx --yes hyperframes@$(cat tools/HYPERFRAMES_VERSION) --version
echo "Environnement prêt."
