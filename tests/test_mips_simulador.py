"""Compatibilidad con un simulador de MIPS externo (MARS o SPIM).

Estas pruebas cubren los requisitos que **MARS impone y un emulador
permisivo deja pasar**. Las tres primeras secciones se comprueban sobre el
texto generado, asi que corren siempre; la ultima solo si hay un simulador
instalado.

Cada caso de aqui nacio de un fallo real que MARS reporto y el emulador no.
"""
import pytest

from conftest import PROGRAMS, compilar_mips, instrucciones_mips, mips_de

from compiscript.mips.simulator import buscar_simulador, ejecutar_en_simulador

pytestmark = pytest.mark.mips

SIMULADOR = buscar_simulador()
necesita_simulador = pytest.mark.skipif(
    SIMULADOR is None, reason="no hay MARS ni SPIM instalado"
)


def _datos(asm: str) -> str:
    """La seccion ``.data`` del ensamblador."""
    return asm.split("    .data")[1].split("    .text")[0]


def _codigo(asm: str) -> list[str]:
    """Las instrucciones de la seccion ``.text``, sin comentarios."""
    cuerpo = asm.split("    .text")[1]
    return [linea.split("#")[0].strip() for linea in cuerpo.splitlines()]


# ---------------------------------------------------------------------------
# Alineacion en la seccion de datos
# ---------------------------------------------------------------------------
# Un '.asciiz' de longitud impar deja el cursor de .data sin alinear. MARS no
# realinea por su cuenta y aborta en el primer acceso de palabra a la etiqueta
# siguiente: "store address not aligned on word boundary".

@pytest.mark.parametrize("etiqueta", ["__globals", "__handlers", "__heap_ptr", "__buf"])
def test_los_bloques_de_palabras_piden_alineacion(etiqueta):
    datos = _datos(mips_de('print("exterior"); print("fallo: ");'))
    antes = datos.split(f"{etiqueta}:")[0]
    directivas = [l.strip() for l in antes.splitlines() if l.strip().startswith(".")]
    assert directivas and directivas[-1] == ".align 2", (
        f"{etiqueta} no viene precedida de '.align 2'"
    )


def test_los_literales_dobles_piden_alineacion_de_ocho():
    datos = _datos(mips_de("print(3.5);"))
    assert ".align 3" in datos.split(".double")[0]


def test_las_cadenas_impares_no_desalinean_la_pila_de_manejadores():
    """Regresion: '__handlers' caia en 0x10010041 y MARS abortaba."""
    datos = _datos(mips_de('print("exterior"); print("fallo: ");'))
    entre = datos.split("__str")[-1].split("__handlers:")[0]
    assert ".align 2" in entre


# ---------------------------------------------------------------------------
# Movimiento de dobles
# ---------------------------------------------------------------------------
# 'l.d'/'s.d' se expanden a 'ldc1'/'sdc1', que exigen una direccion multiplo
# de 8. Los desplazamientos del analisis semantico no lo garantizan y '$sp' no
# llega alineado a 8 en MARS, asi que los dobles se mueven en dos palabras.

#: Un salto obliga a volcar los registros, asi que la global se recarga.
CON_RECARGA = (
    "let x: float = 1.5;"
    "let i: integer = 0;"
    "while (i < 3) { x = x + 1.5; i = i + 1; }"
    "print(x);"
)


def test_los_dobles_en_memoria_se_mueven_en_dos_palabras():
    cuerpo = instrucciones_mips(CON_RECARGA)
    assert any(i.startswith("lwc1 ") for i in cuerpo)
    assert any(i.startswith("swc1 ") for i in cuerpo)


def test_las_dos_mitades_son_registros_consecutivos():
    cuerpo = instrucciones_mips(CON_RECARGA)
    pares = [i for i in cuerpo if i.startswith(("lwc1 ", "swc1 "))]
    assert pares, "no se movio ningun doble"
    for baja, alta in zip(pares[::2], pares[1::2]):
        bajo = baja.split()[1].rstrip(",")
        alto = alta.split()[1].rstrip(",")
        assert int(alto[2:]) == int(bajo[2:]) + 1, (baja, alta)


def test_ningun_acceso_a_doble_usa_un_desplazamiento_arbitrario():
    """Regresion: 'l.d $f4, 44($t9)' abortaba en MARS.

    Solo se admite ``l.d`` sobre la direccion de un literal estatico, que
    lleva ``.align 3`` y se alcanza con el registro de borrador.
    """
    for programa in sorted((PROGRAMS / "valid").glob("*.cps")):
        asm = compilar_mips(programa.read_text(encoding="utf-8")).mips_text()
        for codigo in _codigo(asm):
            if codigo.startswith(("l.d ", "s.d ")):
                assert codigo.endswith("($t9)"), (
                    f"{programa.name}: {codigo} puede caer sin alinear"
                )


# ---------------------------------------------------------------------------
# Modos de redondeo
# ---------------------------------------------------------------------------

def test_no_se_depende_del_modo_de_redondeo_del_fcsr():
    """MARS no implementa el FCSR: 'cvt.w.d' trunca en vez de redondear.

    El texto de un mismo flotante diferia entre simuladores ('3.1416' contra
    '3.141599'), asi que el redondeo se hace explicito: +0.5 y truncar.
    """
    instrucciones = _codigo(mips_de("print(3.1416);"))
    assert not any(i.startswith("cvt.w.d") for i in instrucciones)
    assert any(i.startswith("trunc.w.d") for i in instrucciones)


def test_el_flotante_se_imprime_igual_que_en_la_maquina_virtual():
    resultado = compilar_mips("print(3.1416); print(0.1 + 0.2); print(1.0 / 3.0);")
    vm, _ = resultado.run()
    mips, fallo = resultado.run_mips()
    assert fallo is None
    assert vm == mips == ["3.1416", "0.3", "0.333333"]


# ---------------------------------------------------------------------------
# El emulador es tan estricto como MARS
# ---------------------------------------------------------------------------
# Si el emulador fuera mas permisivo, dejaria pasar ensamblador que el
# simulador externo rechaza, y los demas tests no servirian de nada.

def _emular(fuente: str):
    from compiscript.mips.emulator import MipsEmulator

    return MipsEmulator(fuente)


def test_el_emulador_rechaza_una_palabra_sin_alinear():
    from compiscript.mips.emulator import MipsError

    maquina = _emular(
        """
    .data
    .align 2
__dato:
    .space 8
    .text
    .globl main
main:
    la $t0, __dato
    addiu $t0, $t0, 1
    lwc1 $f4, 0($t0)
    li $v0, 10
    syscall
"""
    )
    with pytest.raises(MipsError, match="no alineada"):
        maquina.run()


def test_el_emulador_rechaza_un_doble_sin_alinear():
    from compiscript.mips.emulator import MipsError

    maquina = _emular(
        """
    .data
    .align 3
__dato:
    .double 1.0
    .text
    .globl main
main:
    la $t0, __dato
    addiu $t0, $t0, 4
    l.d $f4, 0($t0)
    li $v0, 10
    syscall
"""
    )
    with pytest.raises(MipsError, match="no alineada a 8"):
        maquina.run()


# ---------------------------------------------------------------------------
# Ejecucion en el simulador externo
# ---------------------------------------------------------------------------

#: ``print`` de un arreglo imprime su direccion, que depende del runtime.
LINEAS_CON_DIRECCION = {"06_listas_y_matrices.cps": {22}}

PROGRAMAS = sorted((PROGRAMS / "valid").glob("*.cps"))


@necesita_simulador
def test_se_detecta_el_simulador():
    assert SIMULADOR.tipo in ("mars", "spim")


@necesita_simulador
@pytest.mark.parametrize("ruta", PROGRAMAS, ids=[p.name for p in PROGRAMAS])
def test_el_simulador_externo_da_el_mismo_resultado(ruta):
    """La validacion que ni el generador ni el emulador pueden darse solos."""
    from compiscript import analyze_file

    resultado = analyze_file(ruta)
    assert resultado.ok and resultado.mips is not None

    propia, fallo_propio = resultado.run_mips()
    externa, fallo_externo = ejecutar_en_simulador(resultado.mips_text())
    assert fallo_propio is None, fallo_propio
    assert fallo_externo is None, fallo_externo
    assert len(propia) == len(externa), (propia, externa)

    saltar = LINEAS_CON_DIRECCION.get(ruta.name, set())
    for indice, (mia, suya) in enumerate(zip(propia, externa)):
        if indice in saltar:
            continue
        assert mia == suya, (
            f"linea {indice}: emulador={mia!r} {SIMULADOR.nombre}={suya!r}"
        )
