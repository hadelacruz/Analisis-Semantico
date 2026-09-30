"""Exportación del árbol sintáctico a formatos visualizables.

El requerimiento 2 del enunciado pide "construir un árbol sintáctico, con una
representación visual". El árbol lo construye ANTLR; este módulo lo traduce a
tres formatos:

* :func:`tree_to_dict` — JSON jerárquico que consume el visor interactivo del
  IDE (nodos plegables y vista gráfica, con el tipo inferido de cada expresión).
* :func:`tree_to_dot` — grafo en formato Graphviz DOT, para incrustar el árbol
  en la documentación o exportarlo a PNG/SVG.
* :func:`tree_to_text` — árbol en texto plano con guías, útil en la consola.

Modo compacto
-------------
La gramática codifica la precedencia de operadores como una **cascada de
reglas** (``expression`` -> ``assignmentExpr`` -> ``conditionalExpr`` ->
``logicalOrExpr`` -> ... -> ``primaryExpr``). Cuando una expresión no usa un
nivel, ese nivel aparece igual en el árbol como un nodo con **un solo hijo**.
Para ``5 + 3`` eso significa siete nodos de relleno antes de llegar a la suma,
y en un programa real el panel del IDE se vuelve ilegible.

El **modo compacto** (``compact=True``) colapsa esas cadenas: de cada secuencia
de nodos-regla con exactamente un hijo que también es un nodo-regla se conserva
**el más profundo**, que es el que tiene contenido real. El nodo superviviente
recuerda en ``collapsed`` los nombres de las reglas que absorbió y hereda el
**tipo inferido** de cualquier eslabón de la cadena que lo tuviera, de modo que
no se pierde información: sólo deja de ocupar siete líneas.

El modo completo se conserva intacto (``compact=False``, valor por defecto de
todas las funciones) porque es el que demuestra que la gramática y la
precedencia están bien construidas.
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


def _is_chain_link(node) -> bool:
    """¿Es ``node`` un nodo-regla cuyo único hijo es también un nodo-regla?

    Ésos son exactamente los eslabones de relleno de la cascada de precedencia.
    Un nodo-regla con un único hijo **terminal** (``literalExpr`` -> ``'5'``) no
    lo es: su hijo es contenido real y hay que conservarlo.
    """
    return (
        isinstance(node, ParserRuleContext)
        and node.getChildCount() == 1
        and isinstance(node.getChild(0), ParserRuleContext)
        and not isinstance(node.getChild(0), ErrorNode)
    )


def collapse_chain(
    node, rule_names: Sequence[str], node_types: Optional[dict[int, str]] = None
) -> tuple[object, list[str], Optional[str]]:
    """Recorre una cadena de nodos de un solo hijo y devuelve su resumen.

    Devuelve ``(nodo_superviviente, reglas_absorbidas, tipo_heredado)``:

    * **nodo_superviviente** — el más profundo de la cadena; el que tiene
      contenido real (varios hijos, o un hijo terminal, o ninguno).
    * **reglas_absorbidas** — nombres de las reglas que se saltaron, de arriba
      hacia abajo. El visor las muestra como pista al pasar el ratón.
    * **tipo_heredado** — el tipo inferido más profundo que hubiera en la
      cadena, o ``None``. Así el colapso nunca pierde la anotación de tipo.
    """
    absorbed: list[str] = []
    types: list[Optional[str]] = []
    current = node

    while True:
        if node_types is not None:
            types.append(node_types.get(id(current)))
        if not _is_chain_link(current):
            break
        absorbed.append(_rule_label(current, rule_names))
        current = current.getChild(0)

    # El tipo más profundo gana: si el superviviente no tiene tipo propio se
    # hereda el del eslabón más cercano que sí lo tuviera.
    inherited: Optional[str] = None
    for value in reversed(types):
        if value:
            inherited = value
            break

    return current, absorbed, inherited


def tree_to_dict(
    node,
    rule_names: Sequence[str],
    *,
    node_types: Optional[dict[int, str]] = None,
    compact: bool = False,
    _counter: Optional[list[int]] = None,
) -> dict:
    """Convierte el parse tree en un diccionario anidado listo para JSON.

    Con ``compact=True`` se colapsan las cadenas de precedencia (ver el
    docstring del módulo).
    """
    if _counter is None:
        _counter = [0]

    absorbed: list[str] = []
    inherited: Optional[str] = None
    if compact:
        node, absorbed, inherited = collapse_chain(node, rule_names, node_types)

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
        # El tipo propio manda; si no hay, se hereda el de la cadena colapsada.
        inferred = node_types.get(id(node)) or inherited
        if inferred:
            entry["type"] = inferred
    if absorbed:
        entry["collapsed"] = absorbed

    for index in range(node.getChildCount()):
        entry["children"].append(
            tree_to_dict(
                node.getChild(index),
                rule_names,
                node_types=node_types,
                compact=compact,
                _counter=_counter,
            )
        )
    return entry


def tree_to_text(
    node,
    rule_names: Sequence[str],
    prefix: str = "",
    is_last: bool = True,
    *,
    node_types: Optional[dict[int, str]] = None,
    compact: bool = False,
) -> str:
    """Árbol en texto plano con guías tipo ``tree``."""
    absorbed: list[str] = []
    inherited: Optional[str] = None
    if compact:
        node, absorbed, inherited = collapse_chain(node, rule_names, node_types)

    if isinstance(node, TerminalNode):
        label = f"'{node.getSymbol().text}'"
    else:
        label = _rule_label(node, rule_names)
        if node_types:
            inferred = node_types.get(id(node)) or inherited
            if inferred:
                label = f"{label} : {inferred}"
        if absorbed:
            label = f"{label}  [+{len(absorbed)}]"

    connector = "" if not prefix and is_last else ("└── " if is_last else "├── ")
    lines = [f"{prefix}{connector}{label}"]

    if isinstance(node, ParserRuleContext):
        child_prefix = prefix + (
            "" if not prefix and is_last else ("    " if is_last else "│   ")
        )
        count = node.getChildCount()
        for index in range(count):
            lines.append(
                tree_to_text(
                    node.getChild(index),
                    rule_names,
                    child_prefix,
                    index == count - 1,
                    node_types=node_types,
                    compact=compact,
                )
            )
    return "\n".join(lines)


def tree_to_dot(
    node,
    rule_names: Sequence[str],
    *,
    title: str = "Compiscript",
    node_types: Optional[dict[int, str]] = None,
    compact: bool = False,
) -> str:
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
        inherited: Optional[str] = None
        if compact:
            current, _absorbed, inherited = collapse_chain(current, rule_names, node_types)

        node_id = counter[0]
        counter[0] += 1
        if isinstance(current, TerminalNode):
            label = escape(current.getSymbol().text)
            lines.append(f'  n{node_id} [label="{label}", fillcolor="#fde68a"];')
        else:
            label = escape(_rule_label(current, rule_names))
            if node_types:
                inferred = node_types.get(id(current)) or inherited
                if inferred:
                    label = label + "\\n: " + escape(inferred)
            lines.append(f'  n{node_id} [label="{label}", fillcolor="#dbeafe"];')
            for index in range(current.getChildCount()):
                child_id = emit(current.getChild(index))
                lines.append(f"  n{node_id} -> n{child_id};")
        return node_id

    emit(node)
    lines.append("}")
    return "\n".join(lines)


def count_nodes(tree: Optional[dict]) -> int:
    """Número de nodos de un árbol ya exportado a diccionario."""
    if tree is None:
        return 0
    return 1 + sum(count_nodes(child) for child in tree["children"])
