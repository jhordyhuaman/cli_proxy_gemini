#!/usr/bin/env bash
# Empaqueta mgm en un .zip limpio para llevarlo a otra máquina.
#
# Deja fuera lo que NO debe viajar: entornos virtuales (son del sistema que los
# creó), cachés, y sobre todo .mgm/ — que es donde vive tu cookie.
set -euo pipefail

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
destino="${1:-$HOME/Desktop/mgm.zip}"

cd "$raiz"
rm -f "$destino"
zip -r -q "$destino" . \
    -x '*.venv/*' -x '.venv/*' \
    -x 'venv/*' \
    -x '*__pycache__/*' \
    -x '*.pyc' \
    -x '.pytest_cache/*' \
    -x '*.egg-info/*' \
    -x '.mgm/*' \
    -x '.git/*' \
    -x '*.DS_Store'

echo "[OK] Paquete listo: $destino"
echo "     $(du -h "$destino" | cut -f1)"
echo
echo "En la otra máquina:"
echo "  1. Descomprime el zip donde quieras."
echo "  2. Ejecuta:  instalar.bat        (Windows)"
echo "               installer/instalar.sh  (mac/Linux)"
echo "  3. Abre una terminal NUEVA y prueba:  mgm --diagnostico"
