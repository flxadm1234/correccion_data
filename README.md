# Corrección de datos

Aplicación de escritorio (Tkinter) para:
- Consultar DNIs desde una tabla MySQL.
- Consultar datos vía endpoint web (JSON-RPC).
- Actualizar campos en MySQL y exportar resultados a Excel.

## Ejecución (Linux / Raspberry Pi)

Requisitos del sistema:
- Python 3
- Tkinter (`python3-tk`)

Clona el repo en:
- `/home/framirez/proyectos/correccion_datos`

Instalación rápida (Raspberry Pi OS):

```bash
chmod +x scripts/setup_pi.sh
./scripts/setup_pi.sh
```

Ejecución manual:

```bash
cd /home/framirez/proyectos/correccion_datos
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m correccion_datos
```

## Configuración

La app toma valores por defecto desde variables de entorno (opcionalmente desde un archivo `.env`).

Variables principales:
- `CD_API_BASE_URL` (por defecto: `http://seaap.minsa.gob.pe/`)
- `CD_DB_HOST` (por defecto: `31.220.84.86`)
- `CD_DB_USER` (por defecto: `felix`)
- `CD_DB_PASSWORD` (recomendado: setearlo en `.env`, no en el repo)
- `CD_DB_NAME` (por defecto: `compromiso_uno`)

## Icono en el escritorio

El instalador crea:
- `~/Desktop/Corrección de datos.desktop`

Si necesitas hacerlo manualmente:

```bash
cp launcher/correccion_datos.desktop "$HOME/Desktop/Corrección de datos.desktop"
chmod +x "$HOME/Desktop/Corrección de datos.desktop"
```

## Publicación en GitHub

Si estás iniciando el repo desde cero (en tu PC):

```bash
git init
git add .
git commit -m "Inicial"
git branch -M main
git remote add origin git@github.com:flxadm1234/correccion_data.git
git push -u origin main
```

Luego en la Raspberry Pi:

```bash
mkdir -p /home/framirez/proyectos
cd /home/framirez/proyectos
git clone git@github.com:flxadm1234/correccion_data.git correccion_datos
cd correccion_datos
./scripts/setup_pi.sh
```
