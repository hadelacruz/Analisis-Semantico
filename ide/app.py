"""Backend del IDE de Compiscript.

Servidor Flask minimalista que expone el analizador por HTTP. El front-end
(editor Monaco) le envía el código y recibe de vuelta, en una sola respuesta,
los diagnósticos, el árbol sintáctico, la tabla de símbolos y los tokens.

Arranque::

    python ide/app.py                 # http://127.0.0.1:5000
    python ide/app.py --port 8080     # otro puerto

El IDE usa exactamente el mismo :func:`compiscript.analyze` que el CLI y que
la batería de tests, así que lo que muestra es siempre el comportamiento real
del compilador.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from flask import Flask, jsonify, render_template, request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from compiscript import analyze                       # noqa: E402
from compiscript.diagnostics import CATALOG           # noqa: E402

EJEMPLOS = Path(__file__).resolve().parent / "ejemplos"

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/analizar")
def api_analizar():
    """Analiza el código enviado y devuelve el resultado completo."""
    payload = request.get_json(silent=True) or {}
    source = payload.get("codigo", "")
    nombre = payload.get("nombre", "editor.cps")

    if not isinstance(source, str):
        return jsonify({"error": "El campo 'codigo' debe ser texto."}), 400

    resultado = analyze(source, filename=nombre)
    return jsonify(resultado.to_dict())


@app.get("/api/reglas")
def api_reglas():
    """Catálogo de reglas semánticas, para el panel de ayuda del IDE."""
    reglas = [
        {"codigo": codigo, "severidad": severidad.value, "categoria": categoria, "descripcion": desc}
        for codigo, (severidad, categoria, desc) in sorted(CATALOG.items())
    ]
    return jsonify(reglas)


@app.get("/api/ejemplos")
def api_ejemplos():
    """Lista de programas de ejemplo que se pueden cargar en el editor."""
    if not EJEMPLOS.is_dir():
        return jsonify([])
    archivos = sorted(EJEMPLOS.glob("*.cps"))
    return jsonify([{"nombre": p.stem.replace("_", " "), "archivo": p.name} for p in archivos])


@app.get("/api/ejemplos/<path:archivo>")
def api_ejemplo(archivo: str):
    """Contenido de un ejemplo concreto."""
    destino = (EJEMPLOS / archivo).resolve()
    # Se impide salir del directorio de ejemplos.
    if EJEMPLOS.resolve() not in destino.parents or not destino.is_file():
        return jsonify({"error": "Ejemplo no encontrado."}), 404
    return jsonify({"archivo": destino.name, "codigo": destino.read_text(encoding="utf-8")})


def main() -> None:
    parser = argparse.ArgumentParser(description="IDE web de Compiscript")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    print(f"\n  IDE de Compiscript -> http://{args.host}:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
