#!/usr/bin/env bash
# publicar_pages.sh — publica la web (React + datos) en GitHub Pages, rama gh-pages.
#
#   1. corre los exportadores (salvo --sin-exportar)
#   2. compila la web (npm run build)
#   3. arma el sitio: dist/ + public/observaciones + public/satelite
#   4. lo sube a la rama gh-pages como UN solo commit, reemplazando el anterior
#      (si se acumulara historia, cada día sumaría ~15 MB de imágenes al repo)
#
# La rama main no se toca. Usa las mismas credenciales de git que ya usás para subir a GitHub.
#
# Uso (desde cualquier carpeta):
#   OBSERVATORIO_DATOS="../Estación marítima/data" ./publicar_pages.sh
#   ./publicar_pages.sh --sin-exportar        # solo build + subida, con los datos que ya hay
set -euo pipefail

PROYECTO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAMA="gh-pages"
EXPORTAR=1
[[ "${1:-}" == "--sin-exportar" ]] && EXPORTAR=0

cd "$PROYECTO"
REMOTO="$(git remote get-url origin 2>/dev/null || true)"
if [[ -z "$REMOTO" ]]; then
  echo "ERROR: el proyecto no tiene un remoto 'origin' de git." >&2
  exit 1
fi

if [[ $EXPORTAR -eq 1 ]]; then
  echo "── Exportando datos"
  python pipeline/exportar_observaciones.py
  python pipeline/exportar_satelite.py || echo "  (exportar_satelite terminó con avisos; se publica lo que haya)"
fi

for d in public/observaciones/estaciones.json public/satelite/indice.json; do
  [[ -f "$d" ]] || { echo "ERROR: falta $d — corré los exportadores." >&2; exit 1; }
done

echo "── Compilando la web"
(cd web && npm run build)

echo "── Armando el sitio"
SITIO="$(mktemp -d)"
trap 'rm -rf "$SITIO"' EXIT
cp -r web/dist/. "$SITIO/"
cp -r public/observaciones public/satelite "$SITIO/"
touch "$SITIO/.nojekyll"          # GitHub sirve los archivos tal cual, sin procesarlos con Jekyll
du -sh "$SITIO" | awk '{print "  tamaño del sitio: " $1}'

echo "── Subiendo a la rama $RAMA de $REMOTO"
cd "$SITIO"
git init -q -b "$RAMA"
git add -A
git -c user.name="$(git -C "$PROYECTO" config user.name || echo observatorio)" \
    -c user.email="$(git -C "$PROYECTO" config user.email || echo observatorio@localhost)" \
    commit -q -m "Publicación $(date -u +%Y-%m-%dT%H:%MZ)"
git push -q -f "$REMOTO" "$RAMA"
echo "Listo. En unos minutos se ve en GitHub Pages."
