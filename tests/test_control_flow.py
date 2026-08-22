"""Control de flujo (E4xx) — enunciado, sección 2.4."""
import pytest

from conftest import assert_error, assert_ok, check

pytestmark = pytest.mark.flujo


# ---------------------------------------------------------------------------
# E401 — las condiciones deben ser boolean
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        "if (true) { print(1); }",
        "let n: integer = 1; if (n > 0) { print(1); } else { print(2); }",
        "let n: integer = 0; while (n < 3) { n = n + 1; }",
        "let n: integer = 3; do { n = n - 1; } while (n > 0);",
        "for (let i: integer = 0; i < 3; i = i + 1) { print(i); }",
        "for (let i: integer = 0; ; i = i + 1) { break; }",     # condicion omitida
        "let a: boolean = true; let b: boolean = false; if (a && !b) { print(1); }",
    ],
)
def test_e401_condiciones_validas(source):
    assert_ok(source)


@pytest.mark.parametrize(
    "source",
    [
        "if (1) { print(1); }",
        'if ("x") { print(1); }',
        "while (1) { break; }",
        "let n: integer = 1; do { n = n - 1; } while (n);",
        "for (let i: integer = 0; i; i = i + 1) { break; }",
        "class C {} let c: C = new C(); if (c) { print(1); }",
    ],
)
def test_e401_condiciones_no_booleanas(source):
    assert_error(source, "E401")


# ---------------------------------------------------------------------------
# E402 — 'break' sólo en bucles o switch
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        "while (true) { break; }",
        "let xs: integer[] = [1]; foreach (x in xs) { break; }",
        "for (let i: integer = 0; i < 3; i = i + 1) { break; }",
        "let n: integer = 1; do { break; } while (n > 0);",
        "switch (1) { case 1: break; }",
        "while (true) { if (true) { break; } }",             # anidado en un bloque
    ],
)
def test_e402_break_valido(source):
    assert_ok(source)


@pytest.mark.parametrize(
    "source",
    [
        "break;",
        "{ break; }",
        "if (true) { break; }",
        "function f() { break; }",
        "while (true) { function f() { break; } }",   # no cruza la frontera de la funcion
    ],
)
def test_e402_break_fuera_de_bucle(source):
    assert_error(source, "E402")


# ---------------------------------------------------------------------------
# E403 — 'continue' sólo en bucles
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        "while (true) { continue; }",
        "for (let i: integer = 0; i < 3; i = i + 1) { continue; }",
        "let xs: integer[] = [1]; foreach (x in xs) { continue; }",
    ],
)
def test_e403_continue_valido(source):
    assert_ok(source)


@pytest.mark.parametrize(
    "source",
    [
        "continue;",
        "if (true) { continue; }",
        "switch (1) { case 1: continue; }",   # un switch no es un bucle
        "function f() { continue; }",
    ],
)
def test_e403_continue_fuera_de_bucle(source):
    assert_error(source, "E403")


# ---------------------------------------------------------------------------
# E404 — 'return' sólo dentro de funciones
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        "function f(): integer { return 1; }",
        "function f(): integer { if (true) { return 1; } return 2; }",
        "class C { function m(): integer { return 1; } }",
    ],
)
def test_e404_return_valido(source):
    assert_ok(source)


@pytest.mark.parametrize("source", ["return 1;", "return;", "{ return 1; }", "if (true) { return 1; }"])
def test_e404_return_fuera_de_funcion(source):
    assert_error(source, "E404")


# ---------------------------------------------------------------------------
# E405 — coherencia entre 'switch' y sus 'case'
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        "switch (1) { case 1: print(1); case 2: print(2); default: print(3); }",
        'let s: string = "a"; switch (s) { case "a": print(1); default: print(2); }',
        "switch (1) { case 1: print(1); }",       # sin default
    ],
)
def test_e405_switch_valido(source):
    assert_ok(source)


@pytest.mark.parametrize(
    "source",
    [
        'switch (1) { case "x": print(1); }',
        'let s: string = "a"; switch (s) { case 1: print(1); }',
        "switch (true) { case 1: print(1); }",
    ],
)
def test_e405_case_incompatible(source):
    assert_error(source, "E405")


# ---------------------------------------------------------------------------
# E406 — 'foreach' recorre arreglos
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        "let xs: integer[] = [1, 2]; foreach (x in xs) { print(x + 1); }",
        'let xs: string[] = ["a"]; foreach (x in xs) { print(x + "!"); }',
        "let m: integer[][] = [[1], [2]]; foreach (fila in m) { print(fila[0]); }",
    ],
)
def test_e406_foreach_valido(source):
    assert_ok(source)


@pytest.mark.parametrize(
    "source",
    [
        "foreach (x in 5) { print(x); }",
        'foreach (x in "texto") { print(x); }',
        "class C {} let c: C = new C(); foreach (x in c) { print(1); }",
    ],
)
def test_e406_foreach_sobre_algo_que_no_es_arreglo(source):
    assert_error(source, "E406")


def test_el_tipo_de_la_variable_de_foreach_es_el_del_elemento():
    assert_ok("let xs: string[] = [\"a\"]; foreach (x in xs) { let y: string = x; print(y); }")
    assert_error("let xs: string[] = [\"a\"]; foreach (x in xs) { let y: integer = x; print(y); }", "E105")


# ---------------------------------------------------------------------------
# Anidamiento de bucles
# ---------------------------------------------------------------------------

def test_break_y_continue_en_bucles_anidados():
    assert_ok(
        """
        for (let i: integer = 0; i < 3; i = i + 1) {
          for (let j: integer = 0; j < 3; j = j + 1) {
            if (j == 1) { continue; }
            if (j == 2) { break; }
          }
          if (i == 2) { break; }
        }
        """
    )


def test_el_switch_dentro_de_un_bucle_admite_break_de_ambos():
    assert_ok(
        """
        while (true) {
          switch (1) {
            case 1: break;
            default: print(0);
          }
          break;
        }
        """
    )
