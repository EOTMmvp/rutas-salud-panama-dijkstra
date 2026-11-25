#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
python3 src/rutas_salud_panama_floyd.py "$@"
