"""Tabla de símbolos y manejo de entornos — enunciado, requerimiento 5.

Verifica que la tabla no sólo resuelva nombres, sino que almacene la
información que necesitarán las fases posteriores (almacenamiento,
desplazamientos, tamaños, etiquetas y capturas de closures).
"""
import pytest

from conftest import assert_ok, check

from compiscript.scope import ScopeKind
from compiscript.symbols import StorageKind, SymbolCategory

pytestmark = pytest.mark.tabla


PROGRAMA = """
const MAX: integer = 100;
let contador: integer = 0;
let nombres: string[] = ["a", "b"];

class Punto {
  let x: integer;
  let y: integer;
  function constructor(x: integer, y: integer) { this.x = x; this.y = y; }
  function norma(): integer { return this.x * this.x + this.y * this.y; }
}

function acumular(inicio: integer, paso: float): float {
  let total: float = inicio;
  function sumar(veces: integer): float { return total + paso * veces; }
  return sumar(3);
}

let p: Punto = new Punto(1, 2);
print(p.norma() + acumular(MAX, 1.5) + contador + nombres[0]);
"""


@pytest.fixture(scope="module")
def tabla():
    result = assert_ok(PROGRAMA)
    return result.symbol_table


# ---------------------------------------------------------------------------
# Estructura de entornos
# ---------------------------------------------------------------------------

def test_existe_un_ambito_global_raiz(tabla):
    assert tabla.global_scope.kind is ScopeKind.GLOBAL
    assert tabla.global_scope.parent is None
    assert tabla.global_scope.depth == 0


def test_los_ambitos_forman_un_arbol(tabla):
    for scope in tabla.all_scopes():
        for child in scope.children:
            assert child.parent is scope
            assert child.depth == scope.depth + 1


def test_hay_un_ambito_por_funcion_clase_y_bloque(tabla):
    nombres = {s.name for s in tabla.all_scopes()}
    assert "clase Punto" in nombres
    assert "metodo Punto.constructor" in nombres
    assert "metodo Punto.norma" in nombres
    assert "funcion acumular" in nombres
    assert "funcion sumar" in nombres


def test_la_ruta_del_ambito_refleja_el_anidamiento(tabla):
    sumar = next(s for s in tabla.all_scopes() if s.name == "funcion sumar")
    assert sumar.path() == "global > funcion acumular > funcion sumar"


# ---------------------------------------------------------------------------
# Contenido de los símbolos
# ---------------------------------------------------------------------------

def test_las_categorias_son_correctas(tabla):
    g = tabla.global_scope
    assert g.resolve_local("MAX").category is SymbolCategory.CONSTANT
    assert g.resolve_local("contador").category is SymbolCategory.VARIABLE
    assert g.resolve_local("acumular").category is SymbolCategory.FUNCTION
    assert g.resolve_local("Punto").category is SymbolCategory.CLASS

    punto = g.resolve_local("Punto")
    assert punto.fields["x"].category is SymbolCategory.FIELD
    assert punto.methods["norma"].category is SymbolCategory.METHOD
    assert punto.methods["norma"].params == []
    assert punto.methods["constructor"].params[0].category is SymbolCategory.PARAMETER


def test_cada_simbolo_guarda_su_ubicacion(tabla):
    contador = tabla.global_scope.resolve_local("contador")
    assert contador.line == 3
    assert contador.column > 0


def test_los_tipos_quedan_registrados(tabla):
    g = tabla.global_scope
    assert str(g.resolve_local("MAX").type) == "integer"
    assert str(g.resolve_local("nombres").type) == "string[]"
    assert str(g.resolve_local("p").type) == "Punto"
    assert str(g.resolve_local("acumular").type) == "(integer, float) -> float"


# ---------------------------------------------------------------------------
# Información para las fases posteriores (TAC / MIPS)
# ---------------------------------------------------------------------------

def test_almacenamiento_segun_el_tipo_de_simbolo(tabla):
    g = tabla.global_scope
    assert g.resolve_local("contador").storage is StorageKind.GLOBAL
    assert g.resolve_local("acumular").storage is StorageKind.CODE
    assert g.resolve_local("Punto").storage is StorageKind.CODE
    assert g.resolve_local("Punto").fields["x"].storage is StorageKind.FIELD

    acumular = g.resolve_local("acumular")
    assert acumular.params[0].storage is StorageKind.PARAM
    assert acumular.body_scope.resolve_local("total").storage is StorageKind.LOCAL


def test_los_globales_reciben_desplazamientos_consecutivos(tabla):
    g = tabla.global_scope
    offsets = [g.resolve_local(n).offset for n in ("MAX", "contador", "nombres")]
    assert offsets == [0, 4, 8]


def test_los_parametros_y_locales_viven_en_el_marco_de_su_funcion(tabla):
    acumular = tabla.global_scope.resolve_local("acumular")
    assert [p.offset for p in acumular.params] == [0, 4]
    assert acumular.body_scope.resolve_local("total").offset == 0
    assert acumular.param_size == 12   # integer(4) + float(8), alineados
    assert acumular.frame_size == 8    # el float local


def test_los_tamanos_corresponden_al_tipo(tabla):
    g = tabla.global_scope
    assert g.resolve_local("MAX").size == 4          # integer
    assert g.resolve_local("nombres").size == 4      # puntero al arreglo
    acumular = g.resolve_local("acumular")
    assert acumular.params[1].size == 8              # float


def test_las_funciones_y_metodos_tienen_etiqueta(tabla):
    g = tabla.global_scope
    assert g.resolve_local("acumular").label == "func_acumular"
    assert g.resolve_local("Punto").methods["norma"].label == "Punto_norma"
    sumar = g.resolve_local("acumular").body_scope.resolve_local("sumar")
    assert sumar.label == "func_acumular__sumar"


def test_las_clases_conocen_el_layout_de_sus_instancias(tabla):
    punto = tabla.global_scope.resolve_local("Punto")
    assert punto.fields["x"].offset == 0
    assert punto.fields["y"].offset == 4
    assert punto.instance_size == 8
    assert punto.vtable == {"constructor": "Punto_constructor", "norma": "Punto_norma"}


def test_los_closures_registran_sus_capturas(tabla):
    acumular = tabla.global_scope.resolve_local("acumular")
    sumar = acumular.body_scope.resolve_local("sumar")
    assert set(sumar.captures) == {"total", "paso"}
    assert sumar.nesting_level == 1
    assert acumular.body_scope.resolve_local("total").captured is True


def test_el_nivel_de_anidamiento_lexico(tabla):
    acumular = tabla.global_scope.resolve_local("acumular")
    assert acumular.nesting_level == 0
    assert acumular.body_scope.resolve_local("sumar").nesting_level == 1


# ---------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------

def test_exportacion_a_texto(tabla):
    texto = tabla.to_text()
    assert "AMBITO" in texto
    assert "acumular" in texto
    assert "closure[paso,total]" in texto


def test_exportacion_a_diccionario(tabla):
    data = tabla.to_dict()
    assert data["kind"] == "global"
    assert any(s["name"] == "MAX" for s in data["symbols"])
    assert data["children"], "el ambito global debe tener ambitos hijos"

    def buscar(node, nombre):
        if node["name"] == nombre:
            return node
        for child in node["children"]:
            found = buscar(child, nombre)
            if found:
                return found
        return None

    punto = buscar(data, "clase Punto")
    assert punto is not None
    assert punto["kind"] == "clase"


def test_la_tabla_se_reinicia_entre_analisis():
    """Cada análisis parte de una tabla limpia (importa para el IDE)."""
    primero = check("let a: integer = 1;")
    segundo = check("let b: integer = 2;")
    assert primero.symbol_table.global_scope.resolve_local("b") is None
    assert segundo.symbol_table.global_scope.resolve_local("a") is None
