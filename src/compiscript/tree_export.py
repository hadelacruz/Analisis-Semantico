"""Exportación del árbol sintáctico a formatos visualizables.

El requerimiento 2 del enunciado pide "construir un árbol sintáctico, con una
representación visual". El árbol lo construye ANTLR; este módulo lo traduce a
tres formatos:

* :func:`tree_to_dict` — JSON jerárquico que consume el visor interactivo del
  IDE (nodos plegables, con el tipo inferido de cada expresión).
* :func:`tree_to_dot` — grafo en formato Graphviz DOT, para incrustar el árbol
  en la documentación o exportarlo a PNG/SVG.
* :func:`tree_to_text` — árbol en texto plano con guías, útil en la consola.
"""
from __future__ import annotations

from typing import Optional, Sequence

from antlr4 import ParserRuleContext
from antlr4.tree.Tree import ErrorNode, TerminalNode


def _rule_label(node: ParserRuleContext, rule_names: Sequence[str]) -> str:
    """Nombre de la regla, con la alternativa etiquetada si la tiene.

    Por ejemplo ``assignmentExpr`` con la alternativa ``# AssignExpr`` se
    muestra como ``assignmentExpr: AssignExpr``.
    """
    name = rule_names[node.getRuleIndex()]
    class_name = type(node).__name__
    if class_name.endswith("Context"):
        alternative = class_name[: -len("Context")]
        normalized = alternative[0].lower() + alternative[1:]
        if normalized != name:
            return f"{name}: {alternative}"
    return name


def tree_to_dict(
    node,
    rule_names: Sequence[str],
    *,
    node_types: Optional[dict[int, str]] = None,
    _counter: Optional[list[int]] = None,
) -> dict:
    """Convierte el parse tree en un diccionario anidado listo para JSON."""
    if _counter is None:
        _counter = [0]
    node_id = _counter[0]
    _counter[0] += 1

    if isinstance(node, ErrorNode):
        token = node.getSymbol()
        return {
            "id": node_id,
            "kind": "error",
            "label": token.text,
            "line": token.line,
            "column": token.column + 1,
            "children": [],
        }

    if isinstance(node, TerminalNode):
        token = node.getSymbol()
        return {
            "id": node_id,
            "kind": "token",
            "label": token.text,
            "line": token.line,
            "column": token.column + 1,
            "children": [],
        }

    entry: dict = {
        "id": node_id,
        "kind": "rule",
        "label": _rule_label(node, rule_names),
        "line": node.start.line if node.start else 0,
        "column": (node.start.column + 1) if node.start else 0,
        "children": [],
    }
    if node_types:
        inferred = node_types.get(id(node))
        if inferred:
            entry["type"] = inferred

    for index in range(node.getChildCount()):
        entry["children"].append(
            tree_to_dict(
                node.getChild(index), rule_names, node_types=node_types, _counter=_counter
            )
        )
    return entry


def tree_to_text(node, rule_names: Sequence[str], prefix: str = "", is_last: bool = True) -> str:
    """Árbol en texto plano con guías tipo ``tree``."""
    if isinstance(node, TerminalNode):
        label = f"'{node.getSymbol().text}'"
    else:
        label = _rule_label(node, rule_names)

    connector = "" if not prefix and is_last else ("└── " if is_last else "├── ")
    lines = [f"{prefix}{connector}{label}"]

    if isinstance(node, ParserRuleContext):
        child_prefix = prefix + ("" if not prefix and is_last else ("    " if is_last else "│   "))
        count = node.getChildCount()
        for index in range(count):
            lines.append(
                tree_to_text(node.getChild(index), rule_names, child_prefix, index == count - 1)
            )
    return "\n".join(lines)


def tree_to_dot(node, rule_names: Sequence[str], *, title: str = "Compiscript") -> str:
    """Grafo del árbol sintáctico en formato Graphviz DOT."""
    lines: list[str] = [
        "digraph AST {",
        f'  label="Arbol sintactico - {title}";',
        "  labelloc=t;",
        '  fontname="Helvetica";',
        '  node [fontname="Helvetica", shape=box, style="rounded,filled"];',
        '  edge [color="#888888"];',
    ]
    counter = [0]

    def escape(text: str) -> str:
        return text.replace("\\", "\\\\").replace('"', '\\"')

    def emit(current) -> int:
        node_id = counter[0]
        counter[0] += 1
        if isinstance(current, TerminalNode):
            label = escape(current.getSymbol().text)
            lines.append(f'  n{node_id} [label="{label}", fillcolor="#fde68a"];')
        else:
            label = escape(_rule_label(current, rule_names))
            lines.append(f'  n{node_id} [label="{label}", fillcolor="#dbeafe"];')
            for index in range(current.getChildCount()):
                child_id = emit(current.getChild(index))
                lines.append(f"  n{node_id} -> n{child_id};")
        return node_id

    emit(node)
    lines.append("}")
    return "\n".join(lines)
