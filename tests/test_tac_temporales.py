"""Asignación y reciclaje de variables temporales.

El enunciado de esta fase pide explícitamente "un algoritmo para asignación y
reciclaje de variables temporales durante la transformación de expresiones
aritméticas". Estos tests comprueban el algoritmo en aislamiento y luego
verifican que el generador realmente lo aprovecha.
"""
import pytest

from conftest import compilar, tac_de

from compiscript.tac.temporaries import LabelFactory, TempPool
from compiscript.types import INTEGER

pytestmark = pytest.mark.tac


# ---------------------------------------------------------------------------
# El pool en aislamiento
# ---------------------------------------------------------------------------

def test_los_temporales_se_numeran_en_orden():
    pool = TempPool()
    assert [str(pool.alloc().value) for _ in range(3)] == ["t0", "t1", "t2"]
    assert pool.created == 3


def test_un_temporal_liberado_se_reutiliza():
    pool = TempPool()
    primero = pool.alloc()
    pool.free(primero)
    segundo = pool.alloc()
    assert str(segundo.value) == "t0"      # se reutiliza, no se inventa t1
    assert pool.created == 1


def test_la_lista_de_libres_es_una_pila():
    """Reutilizar el ultimo liberado mantiene los numeros bajos y agrupados."""
    pool = TempPool()
    a, b, c = pool.alloc(), pool.alloc(), pool.alloc()
    pool.free(a)
    pool.free(b)
    assert str(pool.alloc().value) == "t1"   # el ultimo liberado
    assert str(pool.alloc().value) == "t0"
    assert str(c.value) == "t2"


def test_el_pico_cuenta_los_vivos_simultaneos():
    pool = TempPool()
    a, b, c = pool.alloc(), pool.alloc(), pool.alloc()
    assert pool.peak == 3
    pool.free(a)
    pool.free(b)
    pool.free(c)
    pool.alloc()
    assert pool.peak == 3          # el pico no baja
    assert pool.live_count == 1


def test_liberar_algo_que_no_es_temporal_no_rompe():
    from compiscript.tac.quadruple import Operand

    pool = TempPool()
    pool.free(None)
    pool.free(Operand.const(5, INTEGER))
    pool.free(Operand.label("L1"))
    assert pool.live_count == 0


def test_liberar_dos_veces_el_mismo_temporal_es_inofensivo():
    pool = TempPool()
    temporal = pool.alloc()
    pool.free(temporal)
    pool.free(temporal)
    assert len(pool.live) == 0
    assert str(pool.alloc().value) == "t0"


def test_reset_devuelve_el_pool_a_su_estado_inicial():
    pool = TempPool()
    pool.alloc()
    pool.alloc()
    pool.reset()
    assert pool.created == 0 and pool.peak == 0 and not pool.has_leaks()
    assert str(pool.alloc().value) == "t0"


def test_has_leaks_detecta_los_temporales_sin_liberar():
    pool = TempPool()
    temporal = pool.alloc()
    assert pool.has_leaks()
    pool.free(temporal)
    assert not pool.has_leaks()


# ---------------------------------------------------------------------------
# Etiquetas
# ---------------------------------------------------------------------------

def test_las_etiquetas_son_unicas_y_descriptivas():
    fabrica = LabelFactory()
    etiquetas = [fabrica.new("while"), fabrica.new("while"), fabrica.new("fin_if")]
    assert len(set(etiquetas)) == 3
    assert etiquetas[0].startswith("L_while_")
    assert etiquetas[2].startswith("L_fin_if_")


def test_se_pueden_pedir_varias_etiquetas_a_la_vez():
    fabrica = LabelFactory()
    verdadero, falso, fin = fabrica.many("si", "no", "fin")
    assert len({verdadero, falso, fin}) == 3
    assert fabrica.count == 3


# ---------------------------------------------------------------------------
# El generador aprovecha el reciclaje
# ---------------------------------------------------------------------------

def test_una_expresion_grande_no_desperdicia_temporales():
    """Sin reciclaje esta expresion gastaria 7 temporales; con el, 3."""
    programa = tac_de(
        "let a: integer = 1; let b: integer = 2; let c: integer = 3; let d: integer = 4;"
        "let e: integer = 5; let f: integer = 6; let g: integer = 7; let h: integer = 8;"
        "print((a + b) * (c + d) - (e + f) * (g + h));"
    )
    assert programa.temps_peak <= 3


def test_las_expresiones_encadenadas_reutilizan_el_mismo_temporal():
    programa = tac_de("let x: integer = 1; print(x + 1 + 2 + 3 + 4 + 5);")
    assert programa.temps_peak == 1


@pytest.mark.parametrize(
    ("fuente", "maximo"),
    [
        ("let a: integer = 1; print(a);", 1),
        ("let a: integer = 1; print(a + 1);", 1),
        ("let a: integer = 1; print((a + 1) * (a + 2));", 2),
        ("let a: integer = 1; print(((a + 1) * (a + 2)) + ((a + 3) * (a + 4)));", 3),
    ],
)
def test_el_pico_crece_con_la_profundidad_no_con_el_tamano(fuente, maximo):
    assert tac_de(fuente).temps_peak <= maximo


def test_cada_rutina_recicla_por_separado():
    """Los temporales viven en el marco de su rutina: los nombres se repiten."""
    programa = tac_de(
        "function f(): integer { return 1 + 2; }"
        "function g(): integer { return 3 + 4; }"
        "print(f() + g());"
    )
    for funcion in programa.functions:
        if funcion.label.startswith("func_"):
            assert funcion.temp_count <= 1


def test_el_pico_de_temporales_dimensiona_el_marco():
    """El marco reserva exactamente los temporales que hicieron falta."""
    resultado = compilar(
        "function f(a: integer, b: integer): integer { return (a + b) * (a - b); }"
        "print(f(3, 4));"
    )
    simbolo = resultado.symbol_table.global_scope.resolve_local("f")
    registro = simbolo.activation_record
    assert registro is not None
    assert registro.temp_count == simbolo.temp_count
    assert registro.temp_size == registro.temp_count * 4
    # enlaces (8) + locales + temporales
    assert registro.size == 8 + registro.local_size + registro.temp_size


def test_no_quedan_temporales_sin_liberar_al_terminar_una_rutina():
    """Una fuga desperdiciaria ranuras del marco en cada llamada."""
    from compiscript.tac.generator import TACGenerator

    resultado = compilar(
        """
        function calcular(n: integer): integer {
          let acumulado: integer = 0;
          for (let i: integer = 0; i < n; i = i + 1) {
            acumulado = acumulado + i * 2;
          }
          return acumulado;
        }
        print(calcular(5));
        """
    )
    generador = TACGenerator(
        resultado.symbol_table,
        resultado.checker.annotations,
        resultado.checker.collector,
    )
    generador.generate(resultado.tree)
    assert not generador.temps.has_leaks(), (
        f"quedaron temporales vivos: {sorted(generador.temps.live)}"
    )
