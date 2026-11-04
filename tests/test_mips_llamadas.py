"""Secuencias de llamada y de retorno de procedimientos.

Componente de 20 puntos del enunciado: saltar a una rutina y volver **sin
perder el estado de la memoria**. Se comprueba la forma del prólogo y del
epílogo, y después se verifica ejecutando que el estado sobrevive de verdad.
"""
import pytest

from conftest import compilar_mips, ejecutar_mips, mips_de, rutina_mips

from compiscript.symbols import (
    CONTROL_LINK_OFFSET,
    PARAM_BASE_OFFSET,
    RETURN_ADDRESS_OFFSET,
)

pytestmark = pytest.mark.mips

SENCILLO = """
function suma(a: integer, b: integer): integer {
  let total: integer = a + b;
  return total;
}
print(suma(3, 4));
"""


# ---------------------------------------------------------------------------
# Prologo
# ---------------------------------------------------------------------------

def test_el_prologo_guarda_el_retorno_y_el_marco_anterior():
    cuerpo = rutina_mips(mips_de(SENCILLO), "func_suma")
    assert cuerpo[0] == "addiu $sp, $sp, -8"
    assert cuerpo[1] == f"sw $ra, {RETURN_ADDRESS_OFFSET}($sp)"
    assert cuerpo[2] == f"sw $fp, {CONTROL_LINK_OFFSET}($sp)"
    assert cuerpo[3] == "move $fp, $sp"


def test_el_prologo_reserva_sitio_para_locales_y_temporales():
    cuerpo = rutina_mips(mips_de(SENCILLO), "func_suma")
    reserva = next(i for i in cuerpo[4:] if i.startswith("addiu $sp"))
    bytes_reservados = -int(reserva.split(",")[-1])
    assert bytes_reservados >= 4          # al menos el enlace de acceso
    assert bytes_reservados % 4 == 0


def test_solo_las_rutinas_anidadas_guardan_el_enlace_de_acceso():
    asm = mips_de(
        "function externa(a: integer): integer {"
        "  function interna(x: integer): integer { return a + x; }"
        "  return interna(1); }"
        "print(externa(1));"
    )
    anidada = rutina_mips(asm, "func_externa__interna")
    externa = rutina_mips(asm, "func_externa")
    assert any("sw $t8, -4($fp)" in i for i in anidada)
    assert not any("sw $t8" in i for i in externa)


# ---------------------------------------------------------------------------
# Epilogo
# ---------------------------------------------------------------------------

def test_el_epilogo_restaura_el_marco_y_vuelve():
    cuerpo = rutina_mips(mips_de(SENCILLO), "func_suma")
    final = cuerpo[-5:]
    assert final == [
        "move $sp, $fp",
        f"lw $ra, {RETURN_ADDRESS_OFFSET}($sp)",
        f"lw $fp, {CONTROL_LINK_OFFSET}($sp)",
        "addiu $sp, $sp, 8",
        "jr $ra",
    ]


def test_main_termina_con_la_llamada_de_salida():
    cuerpo = rutina_mips(mips_de("print(1);"), "main")
    assert cuerpo[-2:] == ["li $v0, 10", "syscall"]


def test_el_valor_de_retorno_viaja_en_v0():
    cuerpo = rutina_mips(mips_de(SENCILLO), "func_suma")
    assert any(i.startswith("move $v0,") for i in cuerpo)


def test_un_retorno_flotante_viaja_en_f0():
    cuerpo = rutina_mips(
        mips_de("function f(): float { return 1.5; } print(f());"), "func_f"
    )
    assert any(i.startswith("mov.d $f0,") for i in cuerpo)


# ---------------------------------------------------------------------------
# Lado del llamador
# ---------------------------------------------------------------------------

def test_el_llamador_reserva_la_zona_de_argumentos_y_la_retira():
    cuerpo = rutina_mips(mips_de(SENCILLO), "main")
    reservas = [i for i in cuerpo if i == "addiu $sp, $sp, -8"]
    retiradas = [i for i in cuerpo if i == "addiu $sp, $sp, 8"]
    # Una del prologo y una de los argumentos; igual de retiradas.
    assert len(reservas) == 2 and len(retiradas) >= 1


def test_los_argumentos_se_escriben_en_orden():
    cuerpo = rutina_mips(mips_de(SENCILLO), "main")
    escrituras = [i for i in cuerpo if i.startswith("sw ") and "($sp)" in i]
    desplazamientos = [int(i.split(",")[1].split("(")[0]) for i in escrituras]
    assert 0 in desplazamientos and 4 in desplazamientos


def test_el_primer_parametro_queda_donde_dice_la_tabla_de_simbolos():
    resultado = compilar_mips(SENCILLO)
    simbolo = resultado.symbol_table.global_scope.resolve_local("suma")
    assert simbolo.params[0].offset == 0
    cuerpo = rutina_mips(resultado.mips_text(), "func_suma")
    assert any(f"{PARAM_BASE_OFFSET}($fp)" in i for i in cuerpo)


def test_un_metodo_recibe_this_como_primer_argumento():
    asm = mips_de(
        "class C { let x: integer;"
        " function constructor(x: integer) { this.x = x; }"
        " function leer(): integer { return this.x; } }"
        "print(new C(5).leer());"
    )
    cuerpo = rutina_mips(asm, "C_leer")
    # 'this' esta en fp+8 y el atributo se lee por su desplazamiento.
    assert any(f"lw $t0, {PARAM_BASE_OFFSET}($fp)" in i or "8($fp)" in i for i in cuerpo)


def test_el_despacho_dinamico_usa_jalr():
    asm = mips_de(
        "class A { function h(): integer { return 1; } }"
        "class B : A { function h(): integer { return 2; } }"
        "let o: A = new B(); print(o.h());"
    )
    assert any(i.startswith("jalr ") for i in rutina_mips(asm, "main"))


# ---------------------------------------------------------------------------
# El estado sobrevive: se comprueba ejecutando
# ---------------------------------------------------------------------------

def test_las_locales_del_llamador_sobreviven_a_la_llamada():
    fuente = """
    function interna(b: integer): integer { let suya: integer = b * 100; return suya; }
    function externa(a: integer): integer {
      let mia: integer = a * 10;
      let devuelto: integer = interna(a);
      return mia + devuelto;
    }
    print(externa(2));
    """
    assert ejecutar_mips(fuente) == ["220"]


def test_cada_llamada_tiene_su_propio_marco():
    fuente = """
    function suma(a: integer, b: integer): integer { return a + b; }
    print(suma(suma(1, 2), suma(3, 4)));
    """
    assert ejecutar_mips(fuente) == ["10"]


def test_la_recursion_profunda_no_pierde_el_estado():
    fuente = """
    function acumular(n: integer): integer {
      if (n == 0) { return 0; }
      return n + acumular(n - 1);
    }
    print(acumular(100));
    """
    assert ejecutar_mips(fuente) == ["5050"]


def test_la_recursion_mutua_tambien():
    fuente = """
    function par(n: integer): boolean { if (n == 0) { return true; } return impar(n - 1); }
    function impar(n: integer): boolean { if (n == 0) { return false; } return par(n - 1); }
    print(par(20)); print(impar(20));
    """
    assert ejecutar_mips(fuente) == ["true", "false"]


def test_seis_parametros_llegan_en_orden():
    fuente = """
    function seis(a: integer, b: integer, c: integer,
                  d: integer, e: integer, f: integer): string {
      return a + "," + b + "," + c + "," + d + "," + e + "," + f;
    }
    print(seis(1, 2, 3, 4, 5, 6));
    """
    assert ejecutar_mips(fuente) == ["1,2,3,4,5,6"]


def test_parametros_de_tipos_mezclados():
    fuente = """
    function mezcla(n: integer, f: float, s: string, b: boolean): string {
      return n + "/" + f + "/" + s + "/" + b;
    }
    print(mezcla(1, 2.5, "x", true));
    """
    assert ejecutar_mips(fuente) == ["1/2.5/x/true"]


def test_el_enlace_de_acceso_sobrevive_a_llamadas_intermedias():
    fuente = """
    function externa(base: integer): integer {
      let extra: integer = 5;
      function interna(x: integer): integer { return base + extra + x; }
      return interna(1) + interna(2);
    }
    print(externa(10));
    """
    assert ejecutar_mips(fuente) == ["33"]


def test_el_valor_devuelto_por_una_funcion_alimenta_a_otra():
    fuente = """
    function doble(n: integer): integer { return n * 2; }
    function triple(n: integer): integer { return n * 3; }
    print(doble(triple(doble(1))));
    """
    assert ejecutar_mips(fuente) == ["12"]
