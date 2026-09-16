#!/usr/bin/env bash
# Instalador de mgm para macOS y Linux — sin sudo, todo en tu usuario.
set -euo pipefail

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv="$raiz/.venv"
bin_dir="$HOME/.mgm/bin"

echo "=== Instalando mgm (sin sudo) ==="
echo "Carpeta del proyecto: $raiz"

python=""
for candidato in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidato" >/dev/null 2>&1; then
        version="$("$candidato" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
        mayor="${version%%.*}"; menor="${version##*.}"
        if [ "$mayor" -eq 3 ] && [ "$menor" -ge 11 ]; then
            python="$candidato"; echo "[OK] Python $version ($candidato)"; break
        fi
    fi
done
if [ -z "$python" ]; then
    echo "[ERROR] Necesitas Python 3.11 o superior." >&2
    exit 1
fi

# Un .venv copiado desde otro sistema no sirve aquí: se detecta y se rehace.
if [ -d "$venv" ] && [ ! -x "$venv/bin/python" ]; then
    echo "[AVISO] El .venv de esta carpeta es de otro sistema. Lo rehago."
    rm -rf "$venv"
fi
[ -d "$venv" ] || { echo "Creando entorno virtual..."; "$python" -m venv "$venv"; }
"$venv/bin/python" -m pip install --upgrade pip --quiet
"$venv/bin/python" -m pip install -e "$raiz" --quiet
echo "[OK] Paquete instalado."

mkdir -p "$bin_dir"
cat > "$bin_dir/mgm" <<LANZADOR
#!/usr/bin/env bash
exec "$venv/bin/python" -m mgm.cli "\$@"
LANZADOR
chmod +x "$bin_dir/mgm"
echo "[OK] Lanzador en $bin_dir/mgm"

case ":$PATH:" in
    *":$bin_dir:"*) echo "[OK] El PATH ya incluye $bin_dir" ;;
    *)
        for perfil in "$HOME/.zshrc" "$HOME/.bashrc"; do
            [ -f "$perfil" ] || continue
            grep -q "\.mgm/bin" "$perfil" || echo "export PATH=\"\$HOME/.mgm/bin:\$PATH\"" >> "$perfil"
        done
        echo "[OK] PATH actualizado. Abre una terminal nueva."
        ;;
esac

echo
echo "=== Listo ==="
echo "    mgm --version"
echo "    mgm --cookie 'TU_COOKIE_DE_GEMINI'"
echo "    mgm"
