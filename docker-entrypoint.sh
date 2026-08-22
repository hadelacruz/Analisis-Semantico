#!/bin/sh
# Punto de entrada de la imagen de Compiscript.
#   test        -> ejecuta la bateria de tests (por defecto)
#   ide         -> levanta el IDE web en el puerto 5000
#   cli ARCHIVO -> analiza un archivo .cps
#   grammar     -> regenera el lexer/parser desde grammar/Compiscript.g4
#   shell       -> abre una shell dentro del contenedor
set -e

comando="${1:-test}"
shift 2>/dev/null || true

case "$comando" in
  test)
    echo "== Bateria de tests de Compiscript =="
    exec python -m pytest tests/ -v
    ;;
  ide)
    echo "== IDE de Compiscript en http://localhost:5000 =="
    exec python ide/app.py --host 0.0.0.0 --port 5000 "$@"
    ;;
  cli)
    exec python -m compiscript "$@"
    ;;
  grammar)
    exec python tools/generate_parser.py
    ;;
  shell)
    exec /bin/sh
    ;;
  *)
    # Cualquier otra cosa se pasa tal cual (permite 'docker run ... python ...')
    exec "$comando" "$@"
    ;;
esac
