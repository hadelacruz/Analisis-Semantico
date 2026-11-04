"""Asignación de registros: la función ``getReg()``.

Componente de 20 puntos del enunciado. Se prueba el algoritmo en aislamiento
—con dos bancos de juguete para forzar el *spilling*— y después se comprueba
que el generador realmente lo aprovecha.
"""
import pytest

from conftest import compilar_mips

from compiscript.mips.registers import (
    REGISTROS_ENTEROS,
    REGISTROS_FLOTANTES,
    RegisterAllocator,
)

pytestmark = pytest.mark.mips


@pytest.fixture
def banco():
    """Asignador con tres registros enteros y dos flotantes.

    Tan pocos obligan a expulsar enseguida, que es justo lo que interesa
    comprobar.
    """
    registro = {"cargas": [], "volcados": []}
    allocator = RegisterAllocator(
        lambda reg, clave: registro["cargas"].append((reg, clave)),
        lambda reg, clave: registro["volcados"].append((reg, clave)),
        enteros=["$t0", "$t1", "$t2"],
        flotantes=["$f4", "$f6"],
    )
    return allocator, registro


# ---------------------------------------------------------------------------
# Comportamiento basico
# ---------------------------------------------------------------------------

def test_un_valor_nuevo_se_carga_de_memoria(banco):
    allocator, registro = banco
    assert allocator.get_reg("a") == "$t0"
    assert registro["cargas"] == [("$t0", "a")]


def test_un_valor_ya_cargado_no_se_vuelve_a_leer(banco):
    allocator, registro = banco
    primero = allocator.get_reg("a")
    allocator.soltar_todos()
    segundo = allocator.get_reg("a")
    assert primero == segundo
    assert len(registro["cargas"]) == 1
    assert allocator.reutilizaciones == 1


def test_un_destino_no_carga_nada(banco):
    allocator, registro = banco
    allocator.destino("x")
    assert registro["cargas"] == []


def test_valores_distintos_ocupan_registros_distintos(banco):
    allocator, _ = banco
    registros = {allocator.get_reg(c) for c in ("a", "b", "c")}
    assert registros == {"$t0", "$t1", "$t2"}


def test_los_bancos_entero_y_flotante_son_independientes(banco):
    allocator, _ = banco
    assert allocator.get_reg("n") in REGISTROS_ENTEROS[:3] or allocator.get_reg("n") == "$t0"
    assert allocator.get_reg("f", flotante=True) == "$f4"


# ---------------------------------------------------------------------------
# Spilling
# ---------------------------------------------------------------------------

def test_cuando_no_quedan_registros_se_expulsa_el_menos_usado(banco):
    allocator, registro = banco
    allocator.destino("a")
    allocator.destino("b")
    allocator.destino("c")
    allocator.soltar_todos()
    allocator.get_reg("a")          # 'a' pasa a ser el mas reciente
    allocator.soltar_todos()

    allocator.get_reg("d")          # no hay sitio: cae la victima menos usada
    assert registro["volcados"], "deberia haberse volcado alguno"
    assert registro["volcados"][0][1] == "b"


def test_un_registro_limpio_se_expulsa_sin_escribir(banco):
    allocator, registro = banco
    for clave in ("a", "b", "c"):
        allocator.get_reg(clave)    # cargados, no sucios
        allocator.soltar_todos()
    allocator.get_reg("d")
    assert registro["volcados"] == []


def test_un_registro_fijado_no_se_expulsa(banco):
    """El generador suelta los fijados tras cada instruccion; aqui se simula."""
    allocator, _ = banco
    protegido = allocator.destino("a")
    for clave in ("b", "c", "d"):
        allocator.soltar_todos()
        allocator.fijar(protegido)   # 'a' sigue protegido en cada paso
        allocator.destino(clave)
    assert allocator.esta_en_registro("a") == protegido


def test_si_todo_esta_fijado_se_avisa_en_vez_de_corromper(banco):
    allocator, _ = banco
    for clave in ("a", "b", "c"):
        allocator.fijar(allocator.destino(clave))
    with pytest.raises(RuntimeError, match="no quedan registros"):
        allocator.destino("d")


# ---------------------------------------------------------------------------
# Bordes de bloque basico
# ---------------------------------------------------------------------------

def test_volcar_todo_escribe_solo_los_sucios(banco):
    allocator, registro = banco
    allocator.destino("sucio")
    allocator.soltar_todos()
    allocator.get_reg("limpio")
    allocator.volcar_todo()
    assert [clave for _, clave in registro["volcados"]] == ["sucio"]


def test_tras_volcar_no_se_supone_nada_de_los_registros(banco):
    allocator, _ = banco
    allocator.get_reg("a")
    allocator.volcar_todo()
    assert allocator.esta_en_registro("a") is None


def test_invalidar_olvida_sin_escribir(banco):
    allocator, registro = banco
    allocator.destino("a")
    allocator.invalidar()
    assert registro["volcados"] == []
    assert allocator.esta_en_registro("a") is None


def test_olvidar_libera_el_registro_de_un_valor_muerto(banco):
    allocator, registro = banco
    allocator.destino("temporal")
    allocator.olvidar("temporal")
    assert allocator.esta_en_registro("temporal") is None
    assert registro["volcados"] == []


# ---------------------------------------------------------------------------
# Cambio de banco: los temporales del TAC se reciclan entre tipos
# ---------------------------------------------------------------------------

def test_un_temporal_que_cambia_de_tipo_cambia_de_banco(banco):
    """Regresion: 't0' puede ser un doble y luego un entero."""
    allocator, _ = banco
    flotante = allocator.destino("t:t0", flotante=True)
    allocator.soltar_todos()
    entero = allocator.destino("t:t0", flotante=False)
    assert flotante in REGISTROS_FLOTANTES or flotante.startswith("$f")
    assert not entero.startswith("$f")


# ---------------------------------------------------------------------------
# El generador lo aprovecha
# ---------------------------------------------------------------------------

def test_los_resultados_intermedios_no_tocan_memoria():
    """Dentro de una expresion, los parciales viven en registros.

    Se mira una funcion y no el programa principal porque las variables
    globales si se escriben en memoria en cada borde de bloque: ahi viven.
    """
    from conftest import rutina_mips

    resultado = compilar_mips(
        "function f(a: integer, b: integer, c: integer): integer { return a + b * c - a; }"
        "print(f(1, 2, 3));"
    )
    cuerpo = rutina_mips(resultado.mips_text(), "func_f")
    # Un 'sw' con desplazamiento negativo sobre $fp seria volcar un temporal
    # a la zona de la pila. La funcion no tiene locales, asi que no deberia
    # haber ninguno: los parciales viven en registros de principio a fin.
    volcados = [i for i in cuerpo if i.startswith("sw ") and "($fp)" in i]
    assert volcados == [], cuerpo
    assert any(i.startswith("mul ") for i in cuerpo)
    # Cada parametro se lee una sola vez.
    lecturas = [i for i in cuerpo if i.startswith("lw ") and "($fp)" in i]
    assert len(lecturas) == 3, cuerpo


def test_la_mayoria_de_los_accesos_se_sirven_desde_registros():
    resultado = compilar_mips(
        """
        function calcular(n: integer): integer {
          let total: integer = 0;
          for (let i: integer = 0; i < n; i = i + 1) { total = total + i * 2; }
          return total;
        }
        print(calcular(10));
        """
    )
    assert resultado.mips_stats["aciertos"] >= 50.0


def test_las_estadisticas_suman_todas_las_rutinas():
    resultado = compilar_mips(
        "function f(): integer { return 1 + 2; }"
        "function g(): integer { return 3 + 4; }"
        "print(f() + g());"
    )
    datos = resultado.mips_stats
    assert datos["reutilizaciones"] + datos["cargas"] > 0
    assert datos["instrucciones"] > 0


def test_se_usan_los_dos_bancos_de_registros():
    asm = compilar_mips("let f: float = 1.5; let n: integer = 2; print(f * n);").mips_text()
    assert any(f"$t{i}" in asm for i in range(8))
    assert "$f" in asm


def test_los_registros_reservados_no_se_reparten():
    """``$t8`` lleva el enlace de acceso y ``$t9`` es el borrador."""
    assert "$t8" not in REGISTROS_ENTEROS
    assert "$t9" not in REGISTROS_ENTEROS
    assert "$f0" not in REGISTROS_FLOTANTES
    assert "$f2" not in REGISTROS_FLOTANTES


def test_solo_se_reparten_registros_flotantes_pares():
    """La doble precision usa parejas, y la pareja empieza en un registro par."""
    assert all(int(r[2:]) % 2 == 0 for r in REGISTROS_FLOTANTES)
