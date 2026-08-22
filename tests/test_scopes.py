"""Manejo de ámbito (E2xx) — enunciado, sección 2.2."""
import pytest

from conftest import assert_error, assert_ok, check

pytestmark = pytest.mark.ambito


# ---------------------------------------------------------------------------
# E201 — uso de identificadores no declarados
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        "let x: integer = 1; print(x);",
        "function f(): integer { let y: integer = 2; return y; }",
        "let x: integer = 1; { print(x); }",                     # el bloque ve el exterior
        "print(f(1)); function f(n: integer): integer { return n; }",  # hoisting
    ],
)
def test_e201_resolucion_valida(source):
    assert_ok(source)


@pytest.mark.parametrize(
    "source",
    [
        "print(noExiste);",
        "noExiste = 5;",
        "{ let interna: integer = 1; } print(interna);",         # fuera del bloque
        "function f(): integer { let a: integer = 1; return a; } print(a);",
    ],
)
def test_e201_identificador_no_declarado(source):
    assert_error(source, "E201")


# ---------------------------------------------------------------------------
# E202 — redeclaración en el mismo ámbito
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        "let x: integer = 1; { let x: string = \"a\"; print(x); } print(x);",  # sombreado
        "function f(): integer { let x: integer = 1; return x; } "
        "function g(): integer { let x: integer = 2; return x; }",
        "class A { let x: integer = 1; } class B { let x: integer = 2; }",
    ],
)
def test_e202_sombreado_valido(source):
    assert_ok(source)


@pytest.mark.parametrize(
    "source",
    [
        "let x: integer = 1; let x: integer = 2;",
        "let x: integer = 1; const x: integer = 2;",
        "{ let y: integer = 1; let y: integer = 2; }",
        "class C {} let C: integer = 1;",
        "function f(n: integer): integer { let n: integer = 2; return n; }",  # local vs parametro
    ],
)
def test_e202_redeclaracion_invalida(source):
    assert_error(source, "E202")


# ---------------------------------------------------------------------------
# E203 — el identificador no designa un valor
# ---------------------------------------------------------------------------

def test_e203_clase_instanciada_correctamente():
    assert_ok("class C {} let c: C = new C();")


@pytest.mark.parametrize(
    "source",
    [
        "class C {} let x = C;",              # una clase no es un valor
        "class C {} C = 5;",
        "function f(): integer { return 1; } f = 3;",
    ],
)
def test_e203_uso_invalido_de_un_nombre(source):
    assert_error(source, "E203")


# ---------------------------------------------------------------------------
# Creación de entornos: un ámbito nuevo por función, clase y bloque
# ---------------------------------------------------------------------------

def test_se_crea_un_ambito_por_cada_construccion():
    source = """
    let g: integer = 0;
    function f(p: integer): integer {
      let local: integer = p;
      { let anidada: integer = 1; local = local + anidada; }
      return local;
    }
    class C { let campo: integer = 1; }
    while (g < 1) { let enBucle: integer = 1; g = g + enBucle; }
    """
    result = assert_ok(source)
    clases = {s.kind.value for s in result.symbol_table.all_scopes()}
    assert clases == {"global", "funcion", "clase", "bloque"}

    nombres = [s.name for s in result.symbol_table.all_scopes()]
    assert "global" in nombres
    assert "funcion f" in nombres
    assert "clase C" in nombres
    assert any(n.startswith("bloque while") for n in nombres)


def test_los_bloques_anidados_ven_hacia_afuera_pero_no_al_reves():
    assert_ok("let a: integer = 1; { { { print(a); } } }")
    assert_error("{ { let profundo: integer = 1; } print(profundo); }", "E201")


def test_el_for_declara_su_variable_en_un_ambito_propio():
    assert_ok("for (let i: integer = 0; i < 3; i = i + 1) { print(i); }")
    assert_error("for (let i: integer = 0; i < 3; i = i + 1) { print(i); } print(i);", "E201")


def test_foreach_declara_la_variable_de_iteracion():
    assert_ok("let xs: integer[] = [1, 2]; foreach (x in xs) { print(x + 1); }")
    assert_error("let xs: integer[] = [1, 2]; foreach (x in xs) { print(x); } print(x);", "E201")


def test_catch_declara_su_variable_de_error():
    assert_ok('try { print(1); } catch (err) { print("fallo: " + err); }')
    assert_error("try { print(1); } catch (err) { print(1); } print(err);", "E201")
