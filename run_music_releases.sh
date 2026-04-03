#!/bin/bash
# run_music_releases.sh
# Ejecutar cada viernes a las 03:00, añadir a crontab con:
#   0 3 * * 5 /ruta/al/trmnl/run_music_releases.sh >> /ruta/al/trmnl/music_cron.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
XML_PATH="${1:-${SCRIPT_DIR}/app/static/musica/Biblioteca.xml}"

cd "${SCRIPT_DIR}"

echo "[$(date -Iseconds)] Iniciando actualización de lanzamientos musicales..."
echo "[$(date -Iseconds)] Biblioteca: ${XML_PATH}"

# Activar virtualenv si existe
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

python -m app.scripts.music_releases "${XML_PATH}"

echo "[$(date -Iseconds)] ✓ Completado."
