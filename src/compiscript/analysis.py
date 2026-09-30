"""Orquestador del front-end: fuente ``.cps`` -> diagnósticos + tabla de símbolos.

Es la API pública del compilador. Tanto el CLI como el backend del IDE y la
batería de tests usan exactamente esta misma función, de modo que los tres ven
siempre el mismo comportamiento.

Flujo::

    codigo fuente
        |
        v
    [ANTLR]  Lexer -> Parser  ------> parse tree     (errores E001 / E002)
        |
        v
    [Pasada 1] DeclarationCollector  clases y funciones (hoisting)
        |
        v
    [Pasada 2] SemanticChecker       tipos, ambitos, flujo... (E1xx..W9xx)
        |
        v
    AnalysisResult (diagnosticos + tabla de simbolos + arbol)
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .checker import SemanticChecker
from .diagnostics import Diagnostic, ErrorReporter, Severity
from .generated.CompiscriptLexer import CompiscriptLexer
from .generated.CompiscriptParser import CompiscriptParser
from .scope import SymbolTable
from .syntax import parse_source
from .tree_export import tree_to_dict, tree_to_dot, tree_to_text


@dataclass
class AnalysisResult:
    """Todo lo que produce el front-end para un programa."""

    source: str
    filename: str
    diagnostics: list[Diagnostic] = field(default_factory=list)
    tree: Any = None
    tokens: Any = None
    symbol_table: Optional[SymbolTable] = None
    checker: Optional[SemanticChecker] = None
    #: ``False`` si hubo errores de sintaxis y no se llegó a la fase semántica.
    semantic_ran: bool = True

    # -- consultas rápidas --------------------------------------------------
    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity is Severity.WARNING]

    @property
    def ok(self) -> bool:
        """``True`` si el programa es válido (puede tener advertencias)."""
        return not self.errors

    def codes(self) -> list[str]:
        return [d.code for d in self.diagnostics]

    def error_codes(self) -> list[str]:
        return [d.code for d in self.errors]

    # -- exportación ----------------------------------------------------------
    @property
    def _node_types(self) -> Optional[dict]:
        return self.checker.node_types if self.checker else None

    def tree_dict(self, compact: bool = False) -> Optional[dict]:
        """Árbol como diccionario. ``compact=True`` colapsa la cascada de
        precedencia de ANTLR (ver :mod:`compiscript.tree_export`)."""
        if self.tree is None:
            return None
        return tree_to_dict(
            self.tree,
            CompiscriptParser.ruleNames,
            node_types=self._node_types,
            compact=compact,
        )

    def tree_text(self, compact: bool = False) -> str:
        if self.tree is None:
            return ""
        return tree_to_text(
            self.tree,
            CompiscriptParser.ruleNames,
            node_types=self._node_types if compact else None,
            compact=compact,
        )

    def tree_dot(self, compact: bool = False) -> str:
        if self.tree is None:
            return ""
        return tree_to_dot(
            self.tree,
            CompiscriptParser.ruleNames,
            title=self.filename,
            node_types=self._node_types,
            compact=compact,
        )

    def symbols_dict(self) -> Optional[dict]:
        return self.symbol_table.to_dict() if self.symbol_table else None

    def symbols_text(self) -> str:
        return self.symbol_table.to_text() if self.symbol_table else ""

    def tokens_list(self) -> list[dict]:
        """Volcado del flujo de tokens (vista léxica del IDE)."""
        if self.tokens is None:
            return []
        self.tokens.fill()
        output: list[dict] = []
        for token in self.tokens.tokens:
            if token.type == -1:  # EOF
                continue
            output.append(
                {
                    "type": _token_name(token.type),
                    "text": token.text,
                    "line": token.line,
                    "column": token.column + 1,
                }
            )
        return output

    def to_dict(self) -> dict:
        """Respuesta JSON completa para el IDE.

        Se envían **los dos** árboles (completo y compacto) para que el
        interruptor "Compacto / Completo" del IDE cambie de vista al instante,
        sin volver a pedir el análisis al servidor.
        """
        return {
            "ok": self.ok,
            "filename": self.filename,
            "semanticRan": self.semantic_ran,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "errorCount": len(self.errors),
            "warningCount": len(self.warnings),
            "tree": self.tree_dict(),
            "treeCompact": self.tree_dict(compact=True),
            "symbols": self.symbols_dict(),
            "tokens": self.tokens_list(),
        }

    def format_diagnostics(self) -> str:
        if not self.diagnostics:
            return "Sin errores ni advertencias."
        return "\n".join(str(d) for d in self.diagnostics)


def _token_name(token_type: int) -> str:
    """Nombre legible de un tipo de token.

    ANTLR reparte los nombres en dos tablas: ``literalNames`` cubre los tokens
    implícitos de la gramática (``'let'``, ``'{'``, ...) desde el índice 1, y
    ``symbolicNames`` continúa a partir de ahí con los tokens con nombre
    (``Identifier``, ``Literal``, ...). De ahí el desplazamiento.
    """
    literal = CompiscriptLexer.literalNames
    symbolic = CompiscriptLexer.symbolicNames

    if 0 <= token_type < len(literal) and literal[token_type] != "<INVALID>":
        return literal[token_type].strip("'")

    index = token_type - len(literal) + 1
    if 0 <= index < len(symbolic) and symbolic[index] != "<INVALID>":
        return symbolic[index]
    return str(token_type)


def analyze(source: str, filename: str = "<memoria>") -> AnalysisResult:
    """Analiza ``source`` y devuelve el resultado completo del front-end."""
    reporter = ErrorReporter()
    tree, tokens = parse_source(source, reporter)

    result = AnalysisResult(source=source, filename=filename, tree=tree, tokens=tokens)

    # Si la sintaxis no es válida el árbol está incompleto: seguir con el
    # análisis semántico sólo produciría errores derivados sin valor.
    if reporter.has_errors:
        result.semantic_ran = False
        result.diagnostics = reporter.diagnostics
        return result

    checker = SemanticChecker(reporter)
    try:
        checker.visit(tree)
    except Exception as exc:  # pragma: no cover - red de seguridad para el IDE
        reporter.error(
            "E002",
            f"Error interno del analizador: {exc.__class__.__name__}: {exc}",
            1,
            1,
        )
        traceback.print_exc()

    result.checker = checker
    result.symbol_table = checker.table
    result.diagnostics = reporter.diagnostics
    return result


def analyze_source(source: str, filename: str = "<memoria>") -> AnalysisResult:
    """Alias explícito de :func:`analyze`."""
    return analyze(source, filename)


def analyze_file(path: str | Path) -> AnalysisResult:
    """Analiza un archivo ``.cps`` del disco."""
    file_path = Path(path)
    source = file_path.read_text(encoding="utf-8")
    return analyze(source, filename=file_path.name)
