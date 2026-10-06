"""Generación de código intermedio: estructura del TAC producido.

Un test por construcción del lenguaje. Aquí se comprueba **qué instrucciones
se emiten**; que además calculen bien está en ``test_tac_ejecucion.py``.
"""
import pytest

from conftest import compilar, instrucciones, tac_de, tac_texto

from compiscript.tac.quadruple import Op

pytestmark = pytest.mark.tac


def ops(fuente: str) -> list[str]:
    return [q.op.value for q in tac_de(fuente).instructions]


# ---------------------------------------------------------------------------
# Forma general del programa
# ---------------------------------------------------------------------------

def test_todo_programa_tiene_una_rutina_main():
    programa = tac_de("print(1);")
    assert any(f.label == "main" for f in programa.functions)


def test_cada_rutina_esta_delimitada_y_termina_en_return():
    programa = tac_de("function f(): integer { return 1; } print(f());")
    for funcion in programa.functions:
        assert programa.instructions[funcion.start].op is Op.FUNC_BEGIN
        assert programa.instructions[funcion.end].op is Op.FUNC_END
        assert programa.instructions[funcion.end - 1].op is Op.RETURN


def test_las_funciones_se_emiten_despues_del_programa_principal():
    programa = tac_de("function f(): integer { return 1; } print(f());")
    principal = next(f for f in programa.functions if f.label == "main")
    otra = next(f for f in programa.functions if f.label == "func_f")
    assert principal.end < otra.start


def test_no_se_genera_codigo_si_el_programa_tiene_errores():
    from conftest import check

    resultado = check('let x: integer = "mal";')
    assert not resultado.ok
    assert resultado.tac is None


# ---------------------------------------------------------------------------
# Expresiones
# ---------------------------------------------------------------------------

def test_una_expresion_aritmetica_se_aplana_en_tres_direcciones():
    texto = tac_texto("let a: integer = 1; let b: integer = 2; let c: integer = a + b * 2;")
    assert "t0 = b * 2" in texto
    assert "t0 = a + t0" in texto
    assert "c = t0" in texto


def test_cada_cuadrupla_tiene_como_mucho_tres_direcciones():
    programa = tac_de("let a: integer = 1; print(((a + 1) * (a + 2)) - ((a + 3) / (a + 4)));")
    for quad in programa.instructions:
        direcciones = [x for x in (quad.arg1, quad.arg2, quad.result) if x is not None]
        assert len(direcciones) <= 3


def test_la_precedencia_queda_fijada_en_el_orden_de_las_instrucciones():
    texto = tac_texto("let x: integer = 2 + 3 * 4;")
    assert texto.index("* 4") < texto.index("2 +")


@pytest.mark.parametrize("operador", ["+", "-", "*", "/", "%"])
def test_los_operadores_aritmeticos_emiten_una_instruccion_binaria(operador):
    binarias = instrucciones(f"let a: integer = 6; let b: integer = 3; print(a {operador} b);", "binary")
    assert any(q.operator == operador for q in binarias)


def test_el_menos_unario_emite_una_instruccion_unaria():
    unarias = instrucciones("let a: integer = 5; print(-a);", "unary")
    assert len(unarias) == 1 and unarias[0].operator == "-"


def test_el_ternario_se_traduce_con_saltos():
    codigo = ops("let a: integer = 1; let b: string = a > 0 ? \"si\" : \"no\";")
    assert "if_rel_goto" in codigo and "goto" in codigo and "label" in codigo


# ---------------------------------------------------------------------------
# Cortocircuito
# ---------------------------------------------------------------------------

def test_el_and_en_una_condicion_no_materializa_el_booleano():
    """Dentro de un 'if' basta con saltar: no hace falta calcular true/false."""
    texto = tac_texto("let a: integer = 1; if (a > 0 && a < 10) { print(1); }")
    # Se busca la ASIGNACION del booleano; las etiquetas pueden llamarse
    # L_and_false_N y contener la palabra sin que se materialice nada.
    assert "= true" not in texto and "= false" not in texto
    assert texto.count("if ") == 2          # una comparacion por operando


def test_el_or_en_una_condicion_tampoco_lo_materializa():
    texto = tac_texto("let a: integer = 1; if (a < 0 || a > 10) { print(1); }")
    assert "= true" not in texto and "= false" not in texto


def test_el_and_si_se_asigna_produce_un_valor_concreto():
    """Fuera de una condicion el booleano si hay que construirlo."""
    texto = tac_texto("let a: integer = 1; let b: boolean = a > 0 && a < 10;")
    assert "= true" in texto and "= false" in texto


def test_la_negacion_intercambia_los_destinos_del_salto():
    texto = tac_texto("let a: boolean = true; if (!a) { print(1); }")
    assert "if a goto" in texto           # se invierte: salta cuando 'a' es cierta


# ---------------------------------------------------------------------------
# Control de flujo
# ---------------------------------------------------------------------------

def test_el_if_sin_else_usa_una_sola_etiqueta():
    codigo = ops("let a: integer = 1; if (a > 0) { print(1); }")
    assert codigo.count("label") == 1


def test_el_if_con_else_usa_dos_etiquetas():
    codigo = ops("let a: integer = 1; if (a > 0) { print(1); } else { print(2); }")
    assert codigo.count("label") == 2


def test_el_while_salta_hacia_atras():
    programa = tac_de("let a: integer = 0; while (a < 3) { a = a + 1; }")
    etiquetas = programa.labels()
    saltos = [q for q in programa.instructions if q.op is Op.GOTO]
    assert any(etiquetas[str(q.arg1)] < programa.instructions.index(q) for q in saltos)


def test_el_do_while_evalua_la_condicion_al_final():
    programa = tac_de("let a: integer = 0; do { a = a + 1; } while (a < 3);")
    indices = [i for i, q in enumerate(programa.instructions) if q.op is Op.IF_REL_GOTO]
    asignaciones = [i for i, q in enumerate(programa.instructions) if q.op is Op.BINARY]
    assert indices and asignaciones and indices[0] > asignaciones[0]


def test_el_for_coloca_la_actualizacion_al_final_del_cuerpo():
    texto = tac_texto("for (let i: integer = 0; i < 3; i = i + 1) { print(i); }")
    assert texto.index("call __print") < texto.index("t0 = i + 1")


def test_continue_salta_a_la_actualizacion_no_al_inicio():
    programa = tac_de(
        "for (let i: integer = 0; i < 3; i = i + 1) { if (i == 1) { continue; } print(i); }"
    )
    texto = programa.text(comments=False)
    assert "L_paso_for" in texto
    saltos = [str(q.arg1) for q in programa.instructions if q.op is Op.GOTO]
    assert any(s.startswith("L_paso_for") for s in saltos)


def test_break_salta_al_final_del_bucle():
    programa = tac_de("while (true) { break; }")
    saltos = [str(q.arg1) for q in programa.instructions if q.op is Op.GOTO]
    assert any(s.startswith("L_fin_while") for s in saltos)


def test_el_foreach_recorre_con_indice_y_longitud():
    texto = tac_texto("let xs: integer[] = [1, 2]; foreach (v in xs) { print(v); }")
    assert "call __length" in texto
    assert "+ 1" in texto            # el indice avanza


def test_el_switch_compara_antes_de_los_cuerpos():
    texto = tac_texto('let n: integer = 1; switch (n) { case 1: print("a"); case 2: print("b"); }')
    assert texto.index("if n == 1") < texto.index("L_case_1:")
    assert texto.index("if n == 2") < texto.index("L_case_1:")


def test_el_switch_cae_al_siguiente_caso_sin_break():
    """Decision de diseno documentada: cascada estilo C."""
    programa = tac_de('let n: integer = 1; switch (n) { case 1: print("a"); case 2: print("b"); }')
    texto = programa.text(comments=False)
    cuerpo = texto[texto.index("L_case_1:"):texto.index("L_case_2:")]
    assert "goto" not in cuerpo       # no hay salto: la ejecucion cae


def test_con_break_el_caso_salta_al_final():
    programa = tac_de('let n: integer = 1; switch (n) { case 1: print("a"); break; case 2: print("b"); }')
    texto = programa.text(comments=False)
    cuerpo = texto[texto.index("L_case_1:"):texto.index("L_case_2:")]
    assert "goto L_fin_switch" in cuerpo


def test_el_try_catch_delimita_un_manejador():
    codigo = ops('try { print(1); } catch (e) { print(e); }')
    assert "push_handler" in codigo and "pop_handler" in codigo


# ---------------------------------------------------------------------------
# Funciones
# ---------------------------------------------------------------------------

def test_los_argumentos_se_apilan_antes_de_la_llamada():
    programa = tac_de(
        "function f(a: integer, b: integer): integer { return a + b; } print(f(1, 2));"
    )
    indices = [i for i, q in enumerate(programa.instructions) if q.op is Op.PARAM]
    llamada = next(
        i for i, q in enumerate(programa.instructions)
        if q.op is Op.CALL and str(q.arg1) == "func_f"
    )
    anteriores = [i for i in indices if i < llamada][-2:]
    assert len(anteriores) == 2 and all(i < llamada for i in anteriores)


def test_la_llamada_declara_cuantos_argumentos_lleva():
    programa = tac_de("function f(a: integer, b: integer): integer { return a; } print(f(1, 2));")
    llamada = next(q for q in programa.instructions if q.op is Op.CALL and str(q.arg1) == "func_f")
    assert int(llamada.arg2.value) == 2


def test_una_funcion_sin_retorno_recibe_un_return_implicito():
    programa = tac_de("function p() { print(1); } p();")
    funcion = next(f for f in programa.functions if f.label == "func_p")
    assert programa.instructions[funcion.end - 1].op is Op.RETURN


def test_la_recursion_no_necesita_nada_especial():
    texto = tac_texto("function f(n: integer): integer { if (n<=1) { return 1; } return n*f(n-1); }")
    assert texto.count("call func_f") == 1


def test_una_funcion_anidada_recibe_el_enlace_de_acceso():
    texto = tac_texto(
        "function e(a: integer): integer {"
        "  function i(x: integer): integer { return a + x; }"
        "  return i(1); }"
    )
    assert "set_access_link fp" in texto


def test_una_variable_capturada_se_lee_subiendo_por_el_enlace():
    texto = tac_texto(
        "function e(a: integer): integer {"
        "  function i(x: integer): integer { return a + x; }"
        "  return i(1); }"
    )
    assert "fp[-4]" in texto        # enlace de acceso -> marco del padre


# ---------------------------------------------------------------------------
# Clases y objetos
# ---------------------------------------------------------------------------

CLASES = """
class Animal {
  let nombre: string;
  function constructor(n: string) { this.nombre = n; }
  function hablar(): string { return this.nombre; }
}
class Perro : Animal {
  function hablar(): string { return "guau"; }
}
"""


def test_se_construye_una_tabla_de_metodos_por_clase():
    programa = tac_de(CLASES + 'let p: Animal = new Perro("Rex"); print(p.hablar());')
    assert programa.vtables == {"Animal": "vtable_Animal", "Perro": "vtable_Perro"}


def test_new_reserva_memoria_y_enlaza_la_tabla():
    texto = tac_texto(CLASES + 'let p: Perro = new Perro("Rex");')
    assert "call __alloc" in texto
    assert "[0] = vtable_Perro" in texto


def test_new_llama_al_constructor_pasando_this():
    programa = tac_de(CLASES + 'let p: Perro = new Perro("Rex");')
    llamada = next(
        q for q in programa.instructions
        if q.op is Op.CALL and str(q.arg1) == "Animal_constructor"
    )
    assert int(llamada.arg2.value) == 2      # this + 1 argumento


def test_una_llamada_a_metodo_usa_despacho_dinamico():
    texto = tac_texto(CLASES + 'let p: Animal = new Perro("Rex"); print(p.hablar());')
    assert "= p[0]" in texto          # se carga el puntero a la tabla
    assert "call *" in texto          # llamada indirecta


def test_una_subclase_conserva_la_ranura_del_metodo_que_sobrescribe():
    resultado = compilar(CLASES + 'let p: Perro = new Perro("Rex");')
    animal = resultado.symbol_table.global_scope.resolve_local("Animal")
    perro = resultado.symbol_table.global_scope.resolve_local("Perro")
    assert animal.vtable_slots["hablar"] == perro.vtable_slots["hablar"]
    assert perro.vtable["hablar"] == "Perro_hablar"


def test_un_atributo_se_lee_por_su_desplazamiento():
    resultado = compilar(CLASES + 'let p: Perro = new Perro("Rex"); print(p.nombre);')
    animal = resultado.symbol_table.global_scope.resolve_local("Animal")
    desplazamiento = animal.fields["nombre"].offset
    assert f"[{desplazamiento}]" in resultado.tac_text(comments=False)


# ---------------------------------------------------------------------------
# Arreglos
# ---------------------------------------------------------------------------

def test_un_literal_de_arreglo_reserva_y_rellena():
    texto = tac_texto("let xs: integer[] = [1, 2, 3];")
    assert "call __array_new" in texto
    assert texto.count("] = ") >= 3


def test_indexar_escala_por_el_tamano_del_elemento_y_salta_la_cabecera():
    texto = tac_texto("let xs: integer[] = [1, 2]; let i: integer = 0; print(xs[i]);")
    assert "* 4" in texto      # tamano de un integer
    assert "+ 4" in texto      # cabecera con la longitud


def test_un_arreglo_de_float_escala_por_ocho():
    texto = tac_texto("let xs: float[] = [1.5, 2.5]; let i: integer = 0; print(xs[i]);")
    assert "* 8" in texto


def test_por_defecto_se_comprueba_el_rango():
    texto = tac_texto("let xs: integer[] = [1]; let i: integer = 0; print(xs[i]);")
    assert "call __check_bounds" in texto


def test_se_pueden_omitir_las_comprobaciones_de_rango():
    from compiscript import analyze

    resultado = analyze("let xs: integer[] = [1]; let i: integer = 0; print(xs[i]);",
                        bounds_checks=False)
    assert "__check_bounds" not in resultado.tac_text()


# ---------------------------------------------------------------------------
# Cadenas
# ---------------------------------------------------------------------------

def test_concatenar_dos_cadenas_llama_al_runtime():
    texto = tac_texto('let s: string = "a" + "b";')
    assert "call __concat" in texto


def test_concatenar_con_un_numero_lo_convierte_antes():
    texto = tac_texto('let n: integer = 1; let s: string = "n=" + n;')
    assert "call __to_string" in texto
    assert texto.index("__to_string") < texto.index("__concat")


def test_sumar_dos_numeros_no_llama_al_runtime():
    texto = tac_texto("let a: integer = 1; let b: integer = 2; let c: integer = a + b;")
    assert "__concat" not in texto and "__to_string" not in texto
