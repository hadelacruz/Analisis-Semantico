"""Puente entre ANTLR y nuestro sistema de diagnósticos.

ANTLR reporta los errores léxicos y sintácticos por consola a través de un
``ErrorListener``. Aquí lo sustituimos por uno que los guarda en el mismo
:class:`~compiscript.diagnostics.ErrorReporter` que usa el análisis semántico,
de modo que el IDE reciba **una sola lista** de problemas, y traducimos los
mensajes de ANTLR al español.
"""
from __future__ import annotations

import re

from antlr4 import CommonTokenStream, InputStream, Lexer
from antlr4.error.ErrorListener import ErrorListener

from .diagnostics import ErrorReporter
from .generated.CompiscriptLexer import CompiscriptLexer
from .generated.CompiscriptParser import CompiscriptParser


def _translate(msg: str) -> str:
    """Traduce al español los mensajes estándar de ANTLR."""
    patterns = [
        (r"^mismatched input (.+) expecting (.+)$",
         r"se encontro \1 pero se esperaba \2"),
        (r"^missing (.+) at (.+)$",
         r"falta \1 antes de \2"),
        (r"^extraneous input (.+) expecting (.+)$",
         r"sobra \1; se esperaba \2"),
        (r"^no viable alternative at input (.+)$",
         r"construccion no valida cerca de \1"),
        (r"^token recognition error at: (.+)$",
         r"caracter no reconocido: \1"),
        (r"^rule (.+) (.+)$", r"regla \1: \2"),
    ]
    for pattern, replacement in patterns:
        new, count = re.subn(pattern, replacement, msg)
        if count:
            return new
    return msg


def span(ctx) -> tuple[int, int, int, int]:
    """``(linea, columna, linea_fin, columna_fin)`` que ocupa ``ctx``.

    Las columnas se devuelven en base 1 (ANTLR las entrega en base 0) porque es
    lo que esperan tanto el editor Monaco del IDE como los mensajes de consola.
    """
    start = ctx.start
    stop = getattr(ctx, "stop", None) or start
    return (
        start.line,
        start.column + 1,
        stop.line,
        stop.column + 1 + len(stop.text or ""),
    )


def token_span(token) -> tuple[int, int, int, int]:
    """Igual que :func:`span` pero para un token suelto."""
    return (
        token.line,
        token.column + 1,
        token.line,
        token.column + 1 + len(token.text or ""),
    )


class CollectingErrorListener(ErrorListener):
    """``ErrorListener`` de ANTLR que vuelca los errores en un ``ErrorReporter``."""

    def __init__(self, reporter: ErrorReporter) -> None:
        super().__init__()
        self.reporter = reporter

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):  # noqa: N802
        code = "E001" if isinstance(recognizer, Lexer) else "E002"
        length = 1
        if offendingSymbol is not None and getattr(offendingSymbol, "text", None):
            length = max(1, len(offendingSymbol.text))
        self.reporter.error(
            code,
            _translate(msg),
            line,
            column + 1,  # ANTLR usa columnas base 0; nosotros base 1
            end_line=line,
            end_column=column + 1 + length,
        )


def parse_source(source: str, reporter: ErrorReporter):
    """Compila ``source`` a un parse tree de ANTLR.

    Devuelve ``(tree, token_stream)``. Los errores léxicos y sintácticos quedan
    en ``reporter``; el árbol se devuelve igual (ANTLR se recupera de los
    errores) para que el IDE pueda mostrarlo aunque haya fallos.
    """
    listener = CollectingErrorListener(reporter)

    lexer = CompiscriptLexer(InputStream(source))
    lexer.removeErrorListeners()
    lexer.addErrorListener(listener)

    tokens = CommonTokenStream(lexer)
    parser = CompiscriptParser(tokens)
    parser.removeErrorListeners()
    parser.addErrorListener(listener)

    tree = parser.program()
    return tree, tokens
