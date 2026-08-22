"""Sistema de tipos (E1xx) — enunciado, sección 2.1.

Cada regla tiene un test de **caso exitoso** y otro de **caso fallido**.
"""
import pytest

from conftest import assert_error, assert_ok, check

pytestmark = pytest.mark.tipos


# ---------------------------------------------------------------------------
# E101 — aritmética sobre operandos numéricos
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        "let a: integer = 2 + 3;",
        "let a: integer = 10 - 4 * 2;",
        "let a: float = 1.5 * 2.0;",
        "let a: float = 3 / 1.5;",          # integer se ensancha a float
        'let a: string = "x" + 1;',         # concatenacion
        'let a: string = "x" + 1.5 + true;',
        "let a: integer = (1 + 2) * 3;",
    ],
)
def test_e101_aritmetica_valida(source):
    assert_ok(source)


@pytest.mark.parametrize(
    "source",
    [
        "let a = 1 + true;",
        "let a = 1 - \"dos\";",
        "let a = true * false;",
        "let a = null / 2;",
        "class C {} let c: C = new C(); let a = c + 1;",
    ],
)
def test_e101_aritmetica_invalida(source):
    assert_error(source, "E101")


# ---------------------------------------------------------------------------
# E102 — operadores lógicos sobre boolean
# ---------------------------------------------------------------------------

def test_e102_logica_valida():
    assert_ok("let a: boolean = true && false || (1 < 2);")


@pytest.mark.parametrize("source", ["let a = 1 && true;", 'let a = "x" || false;'])
def test_e102_logica_invalida(source):
    assert_error(source, "E102")


# ---------------------------------------------------------------------------
# E103 — igualdad entre tipos compatibles
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        "let a: boolean = 1 == 2;",
        'let a: boolean = "x" != "y";',
        "let a: boolean = 1 == 1.5;",
        "class C {} let c: C = new C(); let a: boolean = c == null;",
    ],
)
def test_e103_igualdad_valida(source):
    assert_ok(source)


@pytest.mark.parametrize("source", ['let a = 1 == "x";', "let a = true != 3;"])
def test_e103_igualdad_invalida(source):
    assert_error(source, "E103")


# ---------------------------------------------------------------------------
# E104 — comparaciones relacionales sobre tipos ordenables
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    ["let a: boolean = 1 < 2;", "let a: boolean = 1.5 >= 2;", 'let a: boolean = "a" < "b";'],
)
def test_e104_relacional_valida(source):
    assert_ok(source)


@pytest.mark.parametrize("source", ["let a = true < false;", 'let a = "x" > 1;'])
def test_e104_relacional_invalida(source):
    assert_error(source, "E104")


# ---------------------------------------------------------------------------
# E105 — asignación compatible con el tipo declarado
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        'let a: string = "hola"; a = "adios";',
        "let a: float = 1; a = 2.5;",              # integer -> float
        "let a: integer[] = [1, 2, 3];",
        "class A {} class B : A {} let a: A = new B();",   # subclase -> superclase
        "class A {} let a: A = null;",
    ],
)
def test_e105_asignacion_valida(source):
    assert_ok(source)


@pytest.mark.parametrize(
    "source",
    [
        'let a: integer = "hola";',
        "let a: integer = 1.5;",                    # float -> integer no ensancha
        "let a: boolean = 1;",
        "let a: integer; a = true;",
        "let a: integer[] = [1, 2]; a = [1.5];",
        "class A {} class B : A {} let b: B = new A();",  # superclase -> subclase
    ],
)
def test_e105_asignacion_invalida(source):
    assert_error(source, "E105")


# ---------------------------------------------------------------------------
# E106 / E107 — constantes
# ---------------------------------------------------------------------------

def test_e106_constante_con_inicializador_valida():
    assert_ok("const PI: float = 3.14;")


def test_e106_constante_sin_inicializador_es_rechazada():
    """La gramática ya obliga al '=' en 'const', así que se rechaza como E002."""
    result = check("const PI: integer;")
    assert not result.ok
    assert "E002" in result.codes()


def test_e107_constante_no_se_reasigna_valida():
    assert_ok("const K: integer = 1; let copia: integer = K + 1;")


@pytest.mark.parametrize(
    "source",
    [
        "const K: integer = 1; K = 2;",
        "class C { const K: integer = 1; } let c: C = new C(); c.K = 5;",
    ],
)
def test_e107_constante_no_se_reasigna_invalida(source):
    assert_error(source, "E107")


# ---------------------------------------------------------------------------
# E108 / E109 — operadores unarios
# ---------------------------------------------------------------------------

def test_e108_negacion_numerica_valida():
    assert_ok("let a: integer = -5; let b: float = -1.5;")


@pytest.mark.parametrize("source", ['let a = -"x";', "let a = -true;"])
def test_e108_negacion_numerica_invalida(source):
    assert_error(source, "E108")


def test_e109_negacion_logica_valida():
    assert_ok("let a: boolean = !true; let b: boolean = !(1 < 2);")


@pytest.mark.parametrize("source", ["let a = !5;", 'let a = !"x";'])
def test_e109_negacion_logica_invalida(source):
    assert_error(source, "E109")


# ---------------------------------------------------------------------------
# E110 — anotaciones de tipo conocidas
# ---------------------------------------------------------------------------

def test_e110_tipo_conocido_valido():
    assert_ok("class Persona {} let p: Persona = new Persona(); let n: integer = 1;")


@pytest.mark.parametrize(
    "source",
    ["let a: Inexistente = null;", "function f(x: NoExiste): integer { return 1; }"],
)
def test_e110_tipo_desconocido_invalido(source):
    assert_error(source, "E110")


# ---------------------------------------------------------------------------
# E111 — homogeneidad de los literales de arreglo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        "let a: integer[] = [1, 2, 3];",
        "let a: float[] = [1, 2.5];",                     # se unifica a float
        "let a: integer[][] = [[1], [2, 3]];",
        "class A {} class B : A {} let a: A[] = [new A(), new B()];",
    ],
)
def test_e111_arreglo_homogeneo_valido(source):
    assert_ok(source)


@pytest.mark.parametrize(
    "source",
    ['let a = [1, "dos"];', "let a = [true, 1];", 'let a = [[1], ["x"]];'],
)
def test_e111_arreglo_heterogeneo_invalido(source):
    assert_error(source, "E111")


# ---------------------------------------------------------------------------
# E112 — el tipo debe poder inferirse
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    ["let a: integer;", "let a = 5;", "let a: integer[] = [];"],
)
def test_e112_tipo_inferible_valido(source):
    assert_ok(source)


@pytest.mark.parametrize(
    "source",
    [
        "let a;",                                  # ni tipo ni valor
        "let a = [];",                             # arreglo vacio sin anotacion
        "function p() { } let a = p();",           # void no produce valor
    ],
)
def test_e112_tipo_no_inferible_invalido(source):
    assert_error(source, "E112")


# ---------------------------------------------------------------------------
# E113 / E114 — operador ternario
# ---------------------------------------------------------------------------

def test_e113_e114_ternario_valido():
    assert_ok('let a: string = 1 < 2 ? "si" : "no"; let b: float = true ? 1 : 2.5;')


def test_e113_ternario_condicion_invalida():
    assert_error("let a = 5 ? 1 : 2;", "E113")


def test_e114_ternario_ramas_invalidas():
    assert_error('let a = true ? 1 : "x";', "E114")


# ---------------------------------------------------------------------------
# E115 — el módulo sólo opera sobre enteros
# ---------------------------------------------------------------------------

def test_e115_modulo_valido():
    assert_ok("let a: integer = 7 % 2;")


@pytest.mark.parametrize("source", ["let a = 7 % 2.5;", 'let a = "x" % 2;'])
def test_e115_modulo_invalido(source):
    assert_error(source, "E115")


# ---------------------------------------------------------------------------
# Ensanchamiento numérico y null
# ---------------------------------------------------------------------------

def test_promocion_integer_a_float():
    result = assert_ok("let a: float = 2; let b: float = 1 + 0.5; let c: integer = 1 + 2;")
    tabla = result.symbol_table
    assert str(tabla.global_scope.resolve_local("b").type) == "float"
    assert str(tabla.global_scope.resolve_local("c").type) == "integer"


def test_null_solo_para_tipos_por_referencia():
    assert_ok("let s: string = null; let a: integer[] = null;")
    assert_error("let n: integer = null;", "E105")
    assert_error("let b: boolean = null;", "E105")
