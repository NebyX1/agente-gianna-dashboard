#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for command in uv node npm; do
  command -v "$command" >/dev/null || { echo "Falta $command. Revisá docs/instalacion-rapida.md." >&2; exit 1; }
done
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (major !== 22 || minor < 13) { console.error("Gianna necesita Node 22.13 o posterior dentro de la rama 22; recomendado: 22.23.3."); process.exit(1); }'
uv sync --locked --python 3.12
.venv/bin/python -m playwright install --with-deps chromium
.venv/bin/python -m gianna models download
npm --prefix ui ci
npm --prefix ui run build
[[ -f .env ]] || cp .env.example .env
echo 'Gianna instalada. Configurá OLLAMA_API_KEY en .env, iniciá tickets y ejecutá scripts/start.sh.'
