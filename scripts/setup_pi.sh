#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/home/framirez/proyectos/correccion_datos"

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-tk python3-pip

cd "$PROJECT_DIR"

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
fi

cp launcher/correccion_datos.desktop "$HOME/Desktop/Corrección de datos.desktop"
chmod +x "$HOME/Desktop/Corrección de datos.desktop"

