#!/usr/bin/env python3
"""Genera el lexer/parser/visitor de ANTLR a partir de grammar/Compiscript.g4.

Uso:
    python tools/generate_parser.py

Requisitos: Java 11+ en el PATH. El .jar de ANTLR se toma de
compiscript/antlr-4.13.1-complete.jar (el que provee el curso) o de la
variable de entorno ANTLR_JAR.

Los archivos generados van a src/compiscript/generated/ y NO deben editarse.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRAMMAR = ROOT / "grammar" / "Compiscript.g4"
OUT_DIR = ROOT / "src" / "compiscript" / "generated"
DEFAULT_JAR = ROOT / "compiscript" / "antlr-4.13.1-complete.jar"


def find_jar() -> Path:
    jar = Path(os.environ.get("ANTLR_JAR", DEFAULT_JAR))
    if not jar.is_file():
        sys.exit(f"[X] No se encontro el jar de ANTLR en {jar}\n"
                 f"    Descargalo de https://www.antlr.org/download/antlr-4.13.1-complete.jar\n"
                 f"    o exporta ANTLR_JAR=/ruta/al/jar")
    return jar


def main() -> int:
    if shutil.which("java") is None:
        sys.exit("[X] 'java' no esta en el PATH. Instala un JDK 11+ o usa Docker.")
    jar = find_jar()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [
        "java", "-jar", str(jar),
        "-Dlanguage=Python3",
        "-visitor",          # genera CompiscriptVisitor (lo usa el checker)
        "-listener",         # genera CompiscriptListener (lo usa el collector)
        "-o", str(OUT_DIR),
        "-Xexact-output-dir",
        str(GRAMMAR),
    ]
    print("[*] " + " ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode != 0:
        return result.returncode

    # Paquete Python valido
    init = OUT_DIR / "__init__.py"
    if not init.exists():
        init.write_text(
            '"""Codigo generado por ANTLR 4.13.1. NO EDITAR A MANO.\n\n'
            'Regenerar con: python tools/generate_parser.py\n"""\n',
            encoding="utf-8",
        )

    produced = sorted(p.name for p in OUT_DIR.glob("Compiscript*"))
    print("[OK] Archivos generados en", OUT_DIR)
    for name in produced:
        print("     -", name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
