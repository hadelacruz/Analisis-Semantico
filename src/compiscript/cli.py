"""Interfaz de línea de comandos del compilador de Compiscript.

Ejemplos::

    python -m compiscript programa.cps
    python -m compiscript programa.cps --symbols --tree
    python -m compiscript programa.cps --dot arbol.dot
    python -m compiscript programa.cps --json

Código de salida: ``0`` si el programa es semánticamente válido, ``1`` si hay
al menos un error. Las advertencias no cambian el código de salida.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analysis import AnalysisResult, analyze_file
from .diagnostics import Severity

# Colores ANSI; se desactivan si la salida no es una terminal.
_COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "yellow": "\033[33m",
    "green": "\033[32m",
    "cyan": "\033[36m",
}


def _paint(text: str, color: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{_COLORS[color]}{text}{_COLORS['reset']}"


def _print_diagnostics(result: AnalysisResult, color: bool) -> None:
    lines = result.source.splitlines()
    for diagnostic in result.diagnostics:
        is_error = diagnostic.severity is Severity.ERROR
        tag = "error" if is_error else "aviso"
        tone = "red" if is_error else "yellow"

        header = (
            f"{result.filename}:{diagnostic.line}:{diagnostic.column}: "
            f"{_paint(tag, tone, color)} "
            f"{_paint('[' + diagnostic.code + ']', 'dim', color)} "
            f"{diagnostic.message}"
        )
        print(header)

        if 1 <= diagnostic.line <= len(lines):
            source_line = lines[diagnostic.line - 1]
            gutter = f"{diagnostic.line:>5} | "
            print(_paint(gutter, "dim", color) + source_line)
            width = max(1, min(diagnostic.end_column, len(source_line) + 1) - diagnostic.column)
            caret = " " * (len(gutter) + diagnostic.column - 1) + "^" * width
            print(_paint(caret, tone, color))


def _print_summary(result: AnalysisResult, color: bool) -> None:
    errors = len(result.errors)
    warnings = len(result.warnings)
    if errors == 0 and warnings == 0:
        print(_paint("OK  El programa es semanticamente valido.", "green", color))
        return
    parts = []
    if errors:
        parts.append(_paint(f"{errors} error(es)", "red", color))
    if warnings:
        parts.append(_paint(f"{warnings} advertencia(s)", "yellow", color))
    print("Resultado: " + ", ".join(parts) + ".")
    if not result.semantic_ran:
        print(
            _paint(
                "Nota: el analisis semantico no se ejecuto porque el programa "
                "tiene errores de sintaxis.",
                "dim",
                color,
            )
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compiscript",
        description="Analizador sintactico y semantico de Compiscript.",
    )
    parser.add_argument("archivo", help="archivo fuente .cps a analizar")
    parser.add_argument("--symbols", "-s", action="store_true", help="imprime la tabla de simbolos")
    parser.add_argument("--tree", "-t", action="store_true", help="imprime el arbol sintactico")
    parser.add_argument("--tokens", action="store_true", help="imprime el flujo de tokens")
    parser.add_argument("--dot", metavar="ARCHIVO", help="escribe el arbol en formato Graphviz DOT")
    parser.add_argument("--json", action="store_true", help="emite el resultado completo en JSON")
    parser.add_argument("--quiet", "-q", action="store_true", help="solo el codigo de salida")
    parser.add_argument("--no-color", action="store_true", help="desactiva los colores ANSI")
    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows: aseguramos UTF-8 para los mensajes con acentos.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # pragma: no cover
                pass

    args = build_parser().parse_args(argv)
    path = Path(args.archivo)
    if not path.is_file():
        print(f"No se encontro el archivo '{path}'.", file=sys.stderr)
        return 2

    result = analyze_file(path)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return 0 if result.ok else 1

    color = not args.no_color and sys.stdout.isatty()

    if not args.quiet:
        _print_diagnostics(result, color)
        _print_summary(result, color)

        if args.tokens:
            print("\n" + _paint("== TOKENS ==", "cyan", color))
            for token in result.tokens_list():
                print(f"  {token['line']:>4}:{token['column']:<4} {token['type']:<16} {token['text']}")

        if args.tree:
            print("\n" + _paint("== ARBOL SINTACTICO ==", "cyan", color))
            print(result.tree_text())

        if args.symbols:
            print("\n" + _paint("== TABLA DE SIMBOLOS ==", "cyan", color))
            print(result.symbols_text())

    if args.dot:
        Path(args.dot).write_text(result.tree_dot(), encoding="utf-8")
        if not args.quiet:
            print(f"\nArbol escrito en {args.dot}")

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
