#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-tk python3-pip

cd "$PROJECT_DIR"

if [ ! -f "$PROJECT_DIR/requirements.txt" ]; then
  echo "ERROR: No existe requirements.txt en: $PROJECT_DIR"
  echo "Ruta actual: $(pwd)"
  echo "Contenido de la carpeta:"
  ls -la
  echo "Sugerencia: ejecuta 'git pull' dentro del proyecto y vuelve a correr este script."
  exit 1
fi

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r "$PROJECT_DIR/requirements.txt"

if [ ! -f .env ]; then
  cp .env.example .env
fi

cp launcher/correccion_datos.desktop "$HOME/Desktop/Corrección de datos.desktop"
chmod +x "$HOME/Desktop/Corrección de datos.desktop"
