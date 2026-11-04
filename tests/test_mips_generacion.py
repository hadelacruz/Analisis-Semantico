"""Estructura del ensamblador generado y consistencia entre las dos fases.

Aquí se comprueba **cómo se ve** el `.asm`: que tenga las secciones que
espera un simulador, que cada instrucción del código intermedio se traduzca a
la secuencia correcta, y que el resultado de ejecutarlo coincida con el de la
máquina virtual del código intermedio.
"""
import pytest

from conftest import (
    PROGRAMS,
    compilar_mips,
    ejecutar_mips,
    instrucciones_mips,
    mips_de,
    rutina_mips,
)

from compiscript import analyze_file

pytestmark = pytest.mark.mips


# ---------------------------------------------------------------------------
# Forma del archivo
# ---------------------------------------------------------------------------

def test_el_archivo_tiene_las_dos_secciones():
    asm = mips_de("print(1);")
    assert "    .data" in asm
    assert "    .text" in asm
    assert asm.index(".data") < asm.index(".text")


def test_declara_main_como_punto_de_entrada():
    asm = mips_de("print(1);")
    assert "    .globl main" in asm
    assert "\nmain:" in asm


def test_la_biblioteca_de_runtime_va_al_final():
    asm = mips_de("print(1);")
    assert "__print_int:" in asm
    assert "__alloc:" in asm
    assert asm.index("main:") < asm.index("__alloc:")


def test_no_se_emite_ninguna_instruccion_con_operandos_vacios():
    """Regresion: una expansion de shell se habia comido un '$zero'."""
    for instruccion in instrucciones_mips(
        "let a: integer = 6; let b: integer = 3; print(a / b); print(a % b);"
    ):
        partes = instruccion.split(None, 1)
        if len(partes) > 1:
            assert all(arg.strip() for arg in partes[1].split(",")), instruccion


def test_cada_rutina_del_tac_tiene_su_etiqueta_en_el_asm():
    resultado = compilar_mips(
        "function f(): integer { return 1; }"
        "class C { function m(): integer { return 2; } }"
        "print(f() + new C().m());"
    )
    asm = resultado.mips_text()
    for funcion in resultado.tac.functions:
        assert f"\n{funcion.label}:" in asm


# ---------------------------------------------------------------------------
# Seccion de datos
# ---------------------------------------------------------------------------

def test_las_globales_reservan_su_espacio():
    resultado = compilar_mips("let a: integer = 1; let b: integer = 2; print(a + b);")
    asm = resultado.mips_text()
    assert "__globals:" in asm
    reservado = int(asm.split("__globals:")[1].split(".space")[1].split()[0])
    assert reservado >= resultado.symbol_table.global_scope.next_local_offset


def test_los_literales_de_cadena_van_a_datos():
    asm = mips_de('print("hola");')
    assert '.asciiz "hola"' in asm


def test_los_literales_flotantes_van_alineados_a_ocho():
    asm = mips_de("print(3.5);")
    assert ".align 3" in asm
    assert ".double 3.5" in asm


def test_cada_clase_reserva_el_puntero_a_su_tabla_de_metodos():
    asm = mips_de("class A { } class B : A { } let b: B = new B(); print(1);")
    assert "vtable_A:" in asm and "vtable_B:" in asm


def test_un_literal_repetido_se_guarda_una_sola_vez():
    asm = mips_de('print("x"); print("x"); print("x");')
    assert asm.count('.asciiz "x"') == 1


# ---------------------------------------------------------------------------
# Seleccion de instrucciones
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("operador", "instruccion"),
    [("+", "addu"), ("-", "subu"), ("*", "mul"), ("/", "div"), ("%", "rem")],
)
def test_aritmetica_entera_usa_la_instruccion_correcta(operador, instruccion):
    cuerpo = instrucciones_mips(
        f"function f(a: integer, b: integer): integer {{ return a {operador} b; }} print(f(6,3));"
    )
    assert any(i.startswith(instruccion + " ") for i in cuerpo)


@pytest.mark.parametrize(
    ("operador", "instruccion"),
    [("+", "add.d"), ("-", "sub.d"), ("*", "mul.d"), ("/", "div.d")],
)
def test_aritmetica_flotante_usa_el_coprocesador(operador, instruccion):
    cuerpo = instrucciones_mips(
        f"function f(a: float, b: float): float {{ return a {operador} b; }} print(f(6.0,3.0));"
    )
    assert any(i.startswith(instruccion + " ") for i in cuerpo)


def test_un_entero_que_se_mezcla_con_un_doble_se_convierte():
    cuerpo = instrucciones_mips("const IVA: float = 0.1; print(1 + IVA);")
    assert any(i.startswith("mtc1 ") for i in cuerpo)
    assert any(i.startswith("cvt.d.w ") for i in cuerpo)


def test_las_comparaciones_enteras_usan_las_pseudoinstrucciones():
    cuerpo = instrucciones_mips("let a: integer = 1; let b: boolean = a < 2; print(b);")
    assert any(i.startswith("slt ") for i in cuerpo)


def test_las_condiciones_se_traducen_a_saltos():
    cuerpo = instrucciones_mips("let a: integer = 1; if (a > 0) { print(1); }")
    assert any(i.split()[0] in ("ble", "blt", "bge", "bgt", "beq", "bne") for i in cuerpo)


def test_el_acceso_a_un_atributo_es_un_desplazamiento():
    resultado = compilar_mips(
        "class C { let x: integer; let y: integer;"
        " function constructor(x: integer, y: integer) { this.x = x; this.y = y; } }"
        "print(new C(1, 2).y);"
    )
    clase = resultado.symbol_table.global_scope.resolve_local("C")
    desplazamiento = clase.fields["y"].offset
    assert any(f"{desplazamiento}(" in i for i in instrucciones_mips(
        "class C { let x: integer; let y: integer;"
        " function constructor(x: integer, y: integer) { this.x = x; this.y = y; } }"
        "print(new C(1, 2).y);"
    ))


def test_la_division_comprueba_el_divisor():
    cuerpo = instrucciones_mips("let n: integer = 2; print(10 / n);")
    assert any("__div_zero" in i for i in cuerpo)


def test_una_division_entre_constante_no_gasta_la_comprobacion():
    cuerpo = instrucciones_mips("print(10 / 2);")
    assert not any("__div_zero" in i for i in cuerpo)


def test_el_try_instala_y_retira_el_manejador():
    cuerpo = instrucciones_mips('try { print(1); } catch (e) { print(e); }')
    assert any("jal __handler_push" in i for i in cuerpo)
    assert any("jal __handler_pop" in i for i in cuerpo)


def test_el_enlace_de_acceso_viaja_en_t8():
    cuerpo = rutina_mips(
        mips_de(
            "function e(a: integer): integer {"
            "  function i(x: integer): integer { return a + x; }"
            "  return i(1); }"
            "print(e(1));"
        ),
        "func_e",
    )
    assert any(i.startswith("move $t8,") for i in cuerpo)


# ---------------------------------------------------------------------------
# Las dos fases dan el mismo resultado
# ---------------------------------------------------------------------------

#: ``print`` de un arreglo imprime su direccion, que depende del runtime.
#: Son las unicas lineas que no pueden coincidir entre los dos backends.
LINEAS_CON_DIRECCION = {"06_listas_y_matrices.cps": {22}}

PROGRAMAS = sorted((PROGRAMS / "valid").glob("*.cps"))


@pytest.mark.parametrize("ruta", PROGRAMAS, ids=[p.name for p in PROGRAMAS])
def test_el_mips_da_el_mismo_resultado_que_la_maquina_virtual(ruta):
    resultado = analyze_file(ruta)
    assert resultado.ok and resultado.mips is not None

    salida_vm, fallo_vm = resultado.run()
    salida_mips, fallo_mips = resultado.run_mips()
    assert fallo_vm is None, fallo_vm
    assert fallo_mips is None, fallo_mips
    assert len(salida_vm) == len(salida_mips)

    saltar = LINEAS_CON_DIRECCION.get(ruta.name, set())
    for indice, (vm, mips) in enumerate(zip(salida_vm, salida_mips)):
        if indice in saltar:
            continue
        assert vm == mips, f"linea {indice}: TAC={vm!r} MIPS={mips!r}"


def test_el_ejemplo_del_curso_se_ejecuta_en_mips():
    curso = PROGRAMS.parent.parent / "compiscript" / "program" / "program.cps"
    if not curso.is_file():  # pragma: no cover
        pytest.skip("no esta el ejemplo del curso")
    resultado = analyze_file(curso)
    salida_vm, _ = resultado.run()
    salida_mips, fallo = resultado.run_mips()
    assert fallo is None
    assert salida_vm == salida_mips


# ---------------------------------------------------------------------------
# Opciones del generador
# ---------------------------------------------------------------------------

def test_se_puede_generar_sin_comentarios():
    from compiscript import analyze
    from compiscript.mips import MipsGenerator

    resultado = analyze("let a: integer = 1; print(a);")
    asm = MipsGenerator(resultado.tac, resultado.symbol_table, comments=False).generate().render()
    # Lo que se suprime son los comentarios que el compilador aniade a cada
    # instruccion; los de la biblioteca de runtime se conservan porque
    # documentan sus rutinas y van como texto literal.
    cuerpo = asm.split(".text")[1].split("Biblioteca de apoyo")[0]
    con_nota = [l for l in cuerpo.splitlines() if "#" in l and not l.strip().startswith("#")]
    assert con_nota == []


def test_no_se_genera_codigo_maquina_si_hay_errores():
    from compiscript import analyze

    resultado = analyze('let x: integer = "mal";')
    assert not resultado.ok
    assert resultado.mips is None
    assert resultado.mips_text() == ""


def test_el_resultado_se_serializa_para_el_ide():
    datos = compilar_mips("print(1);").to_dict()["mips"]
    assert set(datos) == {"text", "lines", "instructions", "stats"}
    assert datos["instructions"] > 0
