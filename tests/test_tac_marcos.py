"""Registros de activación y ampliaciones de la tabla de símbolos.

Corresponde al requerimiento de esta fase: "editar la implementación de la
tabla de símbolos para soportar los ambientes y entornos en tiempo de
ejecución, utilizando registros de activación" y "complementarla con los datos
necesarios para la generación de código".
"""
import pytest

from conftest import compilar, ejecutar

from compiscript.symbols import (
    ACCESS_LINK_OFFSET,
    CONTROL_LINK_OFFSET,
    LOCAL_BASE_OFFSET,
    PARAM_BASE_OFFSET,
    RETURN_ADDRESS_OFFSET,
    ActivationRecord,
)
from compiscript.types import OBJECT_HEADER_SIZE, VTABLE_POINTER_OFFSET

pytestmark = [pytest.mark.tac, pytest.mark.tabla]


# ---------------------------------------------------------------------------
# El registro de activacion en aislamiento
# ---------------------------------------------------------------------------

def test_la_distribucion_del_marco_es_la_documentada():
    registro = ActivationRecord("f", "func_f", param_size=8, local_size=12, temp_count=2)
    assert registro.links_size == 8                 # control + acceso
    assert registro.temp_size == 8                  # 2 temporales de 4 bytes
    assert registro.size == 8 + 12 + 8              # enlaces + locales + temporales


def test_las_direcciones_son_relativas_al_puntero_de_marco():
    registro = ActivationRecord("f", "func_f", param_size=8, local_size=8)
    assert registro.param_address(0) == f"fp+{PARAM_BASE_OFFSET}"
    assert registro.param_address(4) == f"fp+{PARAM_BASE_OFFSET + 4}"
    assert registro.local_address(0) == f"fp{LOCAL_BASE_OFFSET}"
    assert registro.local_address(4) == f"fp{LOCAL_BASE_OFFSET - 4}"


def test_los_temporales_van_despues_de_las_locales():
    registro = ActivationRecord("f", "func_f", local_size=8, temp_count=2)
    assert registro.temp_address(0) == f"fp{LOCAL_BASE_OFFSET - 8}"
    assert registro.temp_address(1) == f"fp{LOCAL_BASE_OFFSET - 12}"


def test_el_layout_se_describe_de_la_direccion_alta_a_la_baja():
    registro = ActivationRecord(
        "f", "func_f", local_size=4, temp_count=1, needs_access_link=True
    )
    desplazamientos = [fila["offset"] for fila in registro.layout()]
    assert desplazamientos == sorted(desplazamientos, reverse=True)
    assert RETURN_ADDRESS_OFFSET in desplazamientos
    assert CONTROL_LINK_OFFSET in desplazamientos
    assert ACCESS_LINK_OFFSET in desplazamientos


def test_una_rutina_global_no_necesita_enlace_de_acceso():
    registro = ActivationRecord("f", "func_f", needs_access_link=False)
    assert ACCESS_LINK_OFFSET not in [fila["offset"] for fila in registro.layout()]


def test_el_registro_se_serializa_para_el_ide():
    registro = ActivationRecord("f", "func_f", param_size=4, local_size=4, temp_count=1)
    datos = registro.to_dict()
    assert datos["size"] == registro.size
    assert isinstance(datos["layout"], list)


# ---------------------------------------------------------------------------
# El generador rellena el registro de cada rutina
# ---------------------------------------------------------------------------

PROGRAMA = """
function simple(a: integer, b: integer): integer {
  let suma: integer = a + b;
  return suma * 2;
}

function externa(base: integer): integer {
  let extra: integer = 1;
  function interna(x: integer): integer { return base + extra + x; }
  return interna(1);
}

class Punto {
  let x: integer;
  let y: integer;
  function constructor(x: integer, y: integer) { this.x = x; this.y = y; }
  function norma(): integer { return this.x * this.x + this.y * this.y; }
}

let p: Punto = new Punto(3, 4);
print(simple(1, 2) + externa(1) + p.norma());
"""


@pytest.fixture(scope="module")
def compilado():
    return compilar(PROGRAMA)


def test_cada_rutina_tiene_su_registro_de_activacion(compilado):
    global_scope = compilado.symbol_table.global_scope
    for nombre in ("simple", "externa"):
        simbolo = global_scope.resolve_local(nombre)
        assert simbolo.activation_record is not None
        assert simbolo.activation_record.label == simbolo.label


def test_el_tamano_del_marco_cuadra_con_sus_partes(compilado):
    simbolo = compilado.symbol_table.global_scope.resolve_local("simple")
    registro = simbolo.activation_record
    assert registro.local_size == simbolo.frame_size
    assert registro.param_size == simbolo.param_size
    assert registro.size == registro.links_size + registro.local_size + registro.temp_size


def test_solo_las_rutinas_anidadas_piden_enlace_de_acceso(compilado):
    externa = compilado.symbol_table.global_scope.resolve_local("externa")
    interna = externa.body_scope.resolve_local("interna")
    assert externa.activation_record.needs_access_link is False
    assert interna.activation_record.needs_access_link is True
    assert interna.activation_record.nesting_level == 1


def test_el_conteo_de_temporales_llega_a_la_tabla_de_simbolos(compilado):
    simbolo = compilado.symbol_table.global_scope.resolve_local("simple")
    assert simbolo.temp_count == simbolo.activation_record.temp_count
    assert simbolo.temp_count >= 1


def test_el_tac_declara_el_tamano_del_marco_de_cada_rutina(compilado):
    for funcion in compilado.tac.functions:
        cabecera = compilado.tac.instructions[funcion.start]
        assert int(cabecera.arg2.value) == funcion.frame_size


def test_los_parametros_ocupan_desplazamientos_distintos(compilado):
    simbolo = compilado.symbol_table.global_scope.resolve_local("simple")
    desplazamientos = [p.offset for p in simbolo.params]
    assert len(set(desplazamientos)) == len(desplazamientos)


# ---------------------------------------------------------------------------
# Layout de los objetos y tabla de metodos
# ---------------------------------------------------------------------------

def test_todo_objeto_reserva_la_cabecera_de_la_tabla_de_metodos(compilado):
    punto = compilado.symbol_table.global_scope.resolve_local("Punto")
    assert punto.fields["x"].offset == OBJECT_HEADER_SIZE
    assert punto.instance_size == OBJECT_HEADER_SIZE + 8
    assert VTABLE_POINTER_OFFSET == 0


def test_cada_clase_tiene_etiqueta_y_ranuras_de_tabla(compilado):
    punto = compilado.symbol_table.global_scope.resolve_local("Punto")
    assert punto.vtable_label == "vtable_Punto"
    assert punto.vtable_slots == {"constructor": 0, "norma": 4}


def test_una_subclase_hereda_las_ranuras_y_solo_anade_las_nuevas():
    resultado = compilar(
        """
        class A { function f(): integer { return 1; } function g(): integer { return 2; } }
        class B : A { function f(): integer { return 3; } function h(): integer { return 4; } }
        let b: B = new B(); print(b.f());
        """
    )
    a = resultado.symbol_table.global_scope.resolve_local("A")
    b = resultado.symbol_table.global_scope.resolve_local("B")
    assert a.vtable_slots["f"] == b.vtable_slots["f"]     # la misma ranura
    assert a.vtable_slots["g"] == b.vtable_slots["g"]
    assert b.vtable_slots["h"] not in (a.vtable_slots["f"], a.vtable_slots["g"])
    assert b.vtable["f"] == "B_f" and b.vtable["g"] == "A_g"


def test_los_atributos_heredados_conservan_su_desplazamiento():
    """Es lo que permite tratar un objeto de la subclase como uno de la base."""
    resultado = compilar(
        """
        class Base { let a: integer; let b: integer; }
        class Derivada : Base { let c: integer; }
        let d: Derivada = new Derivada(); print(1);
        """
    )
    base = resultado.symbol_table.global_scope.resolve_local("Base")
    derivada = resultado.symbol_table.global_scope.resolve_local("Derivada")
    assert derivada.lookup_field("a").offset == base.fields["a"].offset
    assert derivada.fields["c"].offset == base.instance_size


# ---------------------------------------------------------------------------
# Los desplazamientos se usan de verdad
# ---------------------------------------------------------------------------

def test_los_desplazamientos_de_los_atributos_funcionan_al_ejecutar():
    """Si un offset estuviera mal, el programa imprimiria otro numero."""
    fuente = """
    class Caja { let a: integer; let b: integer; let c: integer;
      function constructor(a: integer, b: integer, c: integer) {
        this.a = a; this.b = b; this.c = c; }
      function leer(): string { return this.a + "," + this.b + "," + this.c; } }
    let k: Caja = new Caja(1, 2, 3); print(k.leer());
    """
    assert ejecutar(fuente) == ["1,2,3"]


def test_los_desplazamientos_de_los_parametros_funcionan_al_ejecutar():
    fuente = """
    function seis(a: integer, b: integer, c: integer,
                  d: integer, e: integer, f: integer): string {
      return a + "," + b + "," + c + "," + d + "," + e + "," + f;
    }
    print(seis(1, 2, 3, 4, 5, 6));
    """
    assert ejecutar(fuente) == ["1,2,3,4,5,6"]


def test_los_marcos_de_llamadas_anidadas_no_se_pisan():
    fuente = """
    function externa(a: integer): integer {
      let local: integer = a * 10;
      let devuelto: integer = interna(a);
      return local + devuelto;
    }
    function interna(b: integer): integer {
      let local: integer = b * 100;
      return local;
    }
    print(externa(2));
    """
    assert ejecutar(fuente) == ["220"]      # 20 + 200


def test_la_recursion_profunda_mantiene_un_marco_por_llamada():
    fuente = """
    function suma(n: integer): integer {
      if (n == 0) { return 0; }
      return n + suma(n - 1);
    }
    print(suma(100));
    """
    assert ejecutar(fuente) == ["5050"]


def test_una_constante_de_clase_se_almacena_como_atributo():
    """Regresion: antes recibia almacenamiento de global y perdia su offset."""
    from compiscript.symbols import StorageKind

    resultado = compilar("class C { let x: integer; const K: integer = 5; } print(new C().K);")
    clase = resultado.symbol_table.global_scope.resolve_local("C")
    constante = clase.fields["K"]
    assert constante.storage is StorageKind.FIELD
    assert constante.offset == OBJECT_HEADER_SIZE + 4     # detras de 'x'
    assert clase.instance_size == OBJECT_HEADER_SIZE + 8
