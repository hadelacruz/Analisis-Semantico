"""Árbol sintáctico, exportaciones y línea de comandos.

Cubre el requerimiento 2 ("construir un árbol sintáctico con una
representación visual") y el 7 ("cómo ejecutar su compilador").
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import ROOT, check
from compiscript.cli import main
from compiscript.tree_export import count_nodes

PROGRAMA = """
let x: integer = 1 + 2;
function f(n: integer): integer { return n * 2; }
print(f(x));
"""


# ---------------------------------------------------------------------------
# Árbol sintáctico
# ---------------------------------------------------------------------------

def test_el_arbol_se_construye_y_tiene_raiz_program():
    arbol = check(PROGRAMA).tree_dict()
    assert arbol is not None
    assert arbol["label"] == "program"
    assert arbol["children"]


def test_cada_nodo_tiene_identificador_unico():
    arbol = check(PROGRAMA).tree_dict()
    vistos = set()

    def recorrer(node):
        assert node["id"] not in vistos
        vistos.add(node["id"])
        for child in node["children"]:
            recorrer(child)

    recorrer(arbol)
    assert len(vistos) > 20


def test_las_hojas_son_tokens_con_ubicacion():
    arbol = check(PROGRAMA).tree_dict()
    hojas = []

    def recorrer(node):
        if not node["children"]:
            hojas.append(node)
        for child in node["children"]:
            recorrer(child)

    recorrer(arbol)
    assert all(h["kind"] in ("token", "error") for h in hojas)
    assert any(h["label"] == "print" for h in hojas)
    assert all(h["line"] >= 1 for h in hojas)


def test_los_nodos_de_expresion_llevan_el_tipo_inferido():
    arbol = check(PROGRAMA).tree_dict()
    tipos = []

    def recorrer(node):
        if "type" in node:
            tipos.append(node["type"])
        for child in node["children"]:
            recorrer(child)

    recorrer(arbol)
    assert "integer" in tipos


def test_las_alternativas_etiquetadas_aparecen_en_el_arbol():
    """Las alternativas con ``# Etiqueta`` de la gramática se muestran nombradas."""
    arbol = check("class C {} let a: C = new C(); let b: C = a;").tree_dict()
    etiquetas = []

    def recorrer(node):
        etiquetas.append(node["label"])
        for child in node["children"]:
            recorrer(child)

    recorrer(arbol)
    assert any("primaryAtom: IdentifierExpr" == e for e in etiquetas)
    assert any("primaryAtom: NewExpr" == e for e in etiquetas)


def test_exportacion_a_texto_y_a_dot():
    result = check(PROGRAMA)
    texto = result.tree_text()
    assert "program" in texto
    assert "functionDeclaration" in texto

    dot = result.tree_dot()
    assert dot.startswith("digraph AST {")
    assert dot.rstrip().endswith("}")
    assert "->" in dot


def test_el_arbol_se_construye_aunque_haya_errores_semanticos():
    """El IDE debe poder mostrar el árbol de un programa con errores de tipos."""
    result = check('let x: integer = "mal";')
    assert not result.ok
    assert result.tree_dict() is not None


# ---------------------------------------------------------------------------
# Modo compacto: se colapsa la cascada de precedencia de ANTLR
# ---------------------------------------------------------------------------

SUMA = "let x: integer = 5 + 3;"


def _etiquetas(nodo):
    salida = [nodo["label"]]
    for hijo in nodo["children"]:
        salida.extend(_etiquetas(hijo))
    return salida


def _tipos(nodo):
    salida = [nodo["type"]] if "type" in nodo else []
    for hijo in nodo["children"]:
        salida.extend(_tipos(hijo))
    return salida


def test_el_modo_compacto_tiene_menos_nodos_que_el_completo():
    """`5 + 3` gasta siete niveles de precedencia en el modo completo."""
    result = check(SUMA)
    completo = result.tree_dict()
    compacto = result.tree_dict(compact=True)

    assert count_nodes(compacto) < count_nodes(completo)
    # La cascada de precedencia aporta 7 niveles solo para la suma, mas los de
    # cada literal: el colapso tiene que quitar al menos una decena de nodos.
    assert count_nodes(completo) - count_nodes(compacto) >= 10
    assert count_nodes(compacto) <= count_nodes(completo) * 0.6


def test_el_modo_compacto_elimina_los_eslabones_de_precedencia():
    compacto = check(SUMA).tree_dict(compact=True)
    etiquetas = _etiquetas(compacto)

    # Los eslabones que solo existen por la precedencia desaparecen...
    for relleno in (
        "assignmentExpr: ExprNoAssign",
        "conditionalExpr: TernaryExpr",
        "logicalOrExpr",
        "logicalAndExpr",
        "equalityExpr",
        "relationalExpr",
        "multiplicativeExpr",
        "unaryExpr",
        "primaryExpr",
    ):
        assert relleno not in etiquetas, f"'{relleno}' no deberia sobrevivir al colapso"

    # ...y el nodo con contenido real (la suma) se conserva.
    assert "additiveExpr" in etiquetas
    assert "program" in etiquetas
    assert "variableDeclaration" in etiquetas


def test_el_colapso_conserva_las_hojas_del_programa():
    """Ningún token puede perderse al colapsar."""
    result = check(SUMA)
    hojas_completo = [n for n in _etiquetas(result.tree_dict()) if n in ("5", "3", "+", "let", "x")]
    hojas_compacto = [
        n for n in _etiquetas(result.tree_dict(compact=True)) if n in ("5", "3", "+", "let", "x")
    ]
    assert sorted(hojas_completo) == sorted(hojas_compacto)


def test_el_tipo_inferido_sobrevive_al_colapso():
    """El requisito clave: colapsar no puede perder la anotación de tipo."""
    result = check(SUMA)
    assert "integer" in _tipos(result.tree_dict())
    assert "integer" in _tipos(result.tree_dict(compact=True))

    # Y concretamente sobre el nodo que sobrevive a la cadena.
    compacto = result.tree_dict(compact=True)

    def buscar(nodo, etiqueta):
        if nodo["label"] == etiqueta:
            return nodo
        for hijo in nodo["children"]:
            encontrado = buscar(hijo, etiqueta)
            if encontrado:
                return encontrado
        return None

    suma = buscar(compacto, "additiveExpr")
    assert suma is not None
    assert suma["type"] == "integer"


def test_el_nodo_colapsado_recuerda_las_reglas_que_absorbio():
    compacto = check(SUMA).tree_dict(compact=True)

    def buscar(nodo, etiqueta):
        if nodo["label"] == etiqueta:
            return nodo
        for hijo in nodo["children"]:
            encontrado = buscar(hijo, etiqueta)
            if encontrado:
                return encontrado
        return None

    suma = buscar(compacto, "additiveExpr")
    assert suma["collapsed"], "el nodo deberia listar las reglas colapsadas"
    assert "logicalOrExpr" in suma["collapsed"]
    assert "conditionalExpr: TernaryExpr" in suma["collapsed"]


def test_el_modo_compacto_no_altera_el_modo_completo():
    """Los dos modos conviven: pedir uno no degrada al otro."""
    result = check(SUMA)
    antes = count_nodes(result.tree_dict())
    result.tree_dict(compact=True)
    assert count_nodes(result.tree_dict()) == antes
    assert "logicalOrExpr" in _etiquetas(result.tree_dict())


def test_los_identificadores_siguen_siendo_unicos_en_modo_compacto():
    compacto = check(PROGRAMA).tree_dict(compact=True)
    vistos = set()

    def recorrer(node):
        assert node["id"] not in vistos
        vistos.add(node["id"])
        for child in node["children"]:
            recorrer(child)

    recorrer(compacto)


def test_el_colapso_reduce_un_programa_real():
    """Sobre el programa de ejemplo del curso el ahorro debe ser sustancial."""
    result = check(PROGRAMA)
    completo = count_nodes(result.tree_dict())
    compacto = count_nodes(result.tree_dict(compact=True))
    assert compacto < completo * 0.65


def test_el_texto_y_el_dot_tambien_tienen_modo_compacto():
    result = check(SUMA)
    assert "logicalOrExpr" in result.tree_text()
    assert "logicalOrExpr" not in result.tree_text(compact=True)
    assert "additiveExpr" in result.tree_text(compact=True)

    assert "logicalOrExpr" in result.tree_dot()
    assert "logicalOrExpr" not in result.tree_dot(compact=True)
    assert result.tree_dot(compact=True).startswith("digraph AST {")


def test_la_respuesta_del_ide_trae_los_dos_arboles():
    """El IDE cambia de modo sin volver a pedir el analisis."""
    data = check(SUMA).to_dict()
    assert data["tree"] is not None
    assert data["treeCompact"] is not None
    assert count_nodes(data["treeCompact"]) < count_nodes(data["tree"])
    json.dumps(data)  # sigue siendo serializable


# ---------------------------------------------------------------------------
# Volcado de tokens
# ---------------------------------------------------------------------------

def test_volcado_de_tokens():
    tokens = check("let x: integer = 42;").tokens_list()
    textos = [t["text"] for t in tokens]
    assert textos == ["let", "x", ":", "integer", "=", "42", ";"]
    assert tokens[0]["type"] == "let"           # token implicito de la gramatica
    assert tokens[1]["type"] == "Identifier"    # token con nombre
    assert tokens[5]["type"] == "Literal"


def test_los_comentarios_y_espacios_no_llegan_al_parser():
    tokens = check("// comentario\nlet x: integer = 1; /* otro */").tokens_list()
    assert [t["text"] for t in tokens] == ["let", "x", ":", "integer", "=", "1", ";"]


# ---------------------------------------------------------------------------
# Serialización completa para el IDE
# ---------------------------------------------------------------------------

def test_la_respuesta_json_del_ide_es_serializable():
    data = check(PROGRAMA).to_dict()
    texto = json.dumps(data)          # no debe lanzar
    assert len(texto) > 100
    assert set(data) >= {
        "ok", "diagnostics", "tree", "symbols", "tokens", "errorCount", "warningCount"
    }


def test_los_diagnosticos_traen_rango_para_subrayar():
    data = check('let x: integer = "mal";').to_dict()
    diagnostico = data["diagnostics"][0]
    assert diagnostico["line"] >= 1
    assert diagnostico["column"] >= 1
    assert diagnostico["endColumn"] > diagnostico["column"]
    assert diagnostico["severity"] == "error"
    assert diagnostico["category"] == "Tipos"


# ---------------------------------------------------------------------------
# Línea de comandos
# ---------------------------------------------------------------------------

VALIDO = ROOT / "tests" / "programs" / "valid" / "01_tipos_y_operadores.cps"
INVALIDO = ROOT / "tests" / "programs" / "invalid" / "01_tipos.cps"


def test_cli_codigo_de_salida_cero_en_programa_valido(capsys):
    assert main([str(VALIDO), "--no-color"]) == 0
    assert "valido" in capsys.readouterr().out


def test_cli_codigo_de_salida_uno_en_programa_invalido(capsys):
    assert main([str(INVALIDO), "--no-color"]) == 1
    assert "E101" in capsys.readouterr().out


def test_cli_archivo_inexistente():
    assert main(["no_existe.cps"]) == 2


def test_cli_muestra_tabla_de_simbolos(capsys):
    main([str(VALIDO), "--symbols", "--no-color"])
    salida = capsys.readouterr().out
    assert "TABLA DE SIMBOLOS" in salida
    assert "AMBITO" in salida


def test_cli_muestra_el_arbol(capsys):
    main([str(VALIDO), "--tree", "--no-color"])
    assert "ARBOL SINTACTICO" in capsys.readouterr().out


def test_cli_tree_es_compacto_por_defecto(capsys):
    main([str(VALIDO), "--tree", "--no-color"])
    salida = capsys.readouterr().out
    assert "(compacto)" in salida
    assert "logicalOrExpr" not in salida


def test_cli_tree_completo_muestra_toda_la_cascada(capsys):
    main([str(VALIDO), "--tree-completo", "--no-color"])
    salida = capsys.readouterr().out
    assert "(completo)" in salida
    assert "logicalOrExpr" in salida


def test_cli_el_arbol_compacto_es_mas_corto(capsys):
    main([str(VALIDO), "--tree", "--no-color"])
    compacto = len(capsys.readouterr().out.splitlines())
    main([str(VALIDO), "--tree-completo", "--no-color"])
    completo = len(capsys.readouterr().out.splitlines())
    assert compacto < completo


def test_cli_emite_json(capsys):
    main([str(VALIDO), "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True


def test_cli_escribe_el_dot(tmp_path, capsys):
    destino = tmp_path / "arbol.dot"
    main([str(VALIDO), "--dot", str(destino), "--quiet"])
    assert destino.read_text(encoding="utf-8").startswith("digraph AST {")


def test_el_modulo_es_ejecutable_como_programa():
    """``python -m compiscript archivo.cps`` debe funcionar."""
    proceso = subprocess.run(
        [sys.executable, "-m", "compiscript", str(VALIDO), "--no-color"],
        cwd=ROOT,
        env={**dict(__import__("os").environ), "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
    )
    assert proceso.returncode == 0, proceso.stderr
    assert "valido" in proceso.stdout
