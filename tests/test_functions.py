"""Funciones y procedimientos (E3xx) — enunciado, sección 2.3."""
import pytest

from conftest import assert_error, assert_ok, check

pytestmark = pytest.mark.funciones


# ---------------------------------------------------------------------------
# E301 — número de argumentos
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        "function f(a: integer, b: integer): integer { return a + b; } print(f(1, 2));",
        "function g(): integer { return 1; } print(g());",
        "function h(a: integer) { print(a); } h(1);",
    ],
)
def test_e301_aridad_valida(source):
    assert_ok(source)


@pytest.mark.parametrize(
    "source",
    [
        "function f(a: integer, b: integer): integer { return a + b; } print(f(1));",
        "function f(a: integer): integer { return a; } print(f(1, 2, 3));",
        "function g(): integer { return 1; } print(g(1));",
    ],
)
def test_e301_aridad_invalida(source):
    assert_error(source, "E301")


# ---------------------------------------------------------------------------
# E302 — tipos de los argumentos (coincidencia posicional)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        'function f(a: string, b: integer): integer { return b; } print(f("x", 1));',
        "function f(a: float): float { return a; } print(f(1));",   # ensanchamiento
        "class A {} class B : A {} function f(a: A): integer { return 1; } print(f(new B()));",
        "function f(a: integer[]): integer { return a[0]; } print(f([1, 2]));",
    ],
)
def test_e302_tipos_de_argumento_validos(source):
    assert_ok(source)


@pytest.mark.parametrize(
    "source",
    [
        'function f(a: string): integer { return 1; } print(f(5));',
        "function f(a: integer): integer { return a; } print(f(1.5));",
        "function f(a: integer, b: string): integer { return a; } print(f(1, 2));",
        "class A {} class B : A {} function f(a: B): integer { return 1; } print(f(new A()));",
    ],
)
def test_e302_tipos_de_argumento_invalidos(source):
    assert_error(source, "E302")


# ---------------------------------------------------------------------------
# E303 — sólo se invoca lo invocable
# ---------------------------------------------------------------------------

def test_e303_llamada_valida():
    assert_ok("function f(): integer { return 1; } print(f());")


@pytest.mark.parametrize(
    "source",
    ["let x: integer = 1; print(x());", 'let s: string = "a"; print(s(1));'],
)
def test_e303_invocar_algo_que_no_es_funcion(source):
    assert_error(source, "E303")


# ---------------------------------------------------------------------------
# E304 / E305 / E308 — tipo de retorno
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        "function f(): integer { return 1; }",
        'function f(): string { return "x"; }',
        "function f(): float { return 1; }",                      # ensanchamiento
        "function f() { return; }",                               # procedimiento
        "function f() { print(1); }",                             # sin return
        "function f(n: integer): integer { if (n > 0) { return 1; } else { return 2; } }",
        "function f(): integer[] { let a: integer[] = [1]; return a; }",
        "class A {} class B : A {} function f(): A { return new B(); }",
    ],
)
def test_e304_retorno_valido(source):
    assert_ok(source)


@pytest.mark.parametrize(
    "source",
    [
        'function f(): integer { return "x"; }',
        "function f(): boolean { return 1; }",
        "function f(): integer { return 1.5; }",
        "class A {} class B : A {} function f(): B { return new A(); }",
    ],
)
def test_e304_retorno_de_tipo_incorrecto(source):
    assert_error(source, "E304")


@pytest.mark.parametrize(
    "source",
    [
        "function f() { return 5; }",                      # void con valor
        "function f(): integer { return; }",               # con tipo pero sin valor
        "class C { function constructor() { return 1; } }",
    ],
)
def test_e305_return_incompatible_con_la_firma(source):
    assert_error(source, "E305")


@pytest.mark.parametrize(
    "source",
    [
        "function f(): integer { print(1); }",
        "function f(n: integer): integer { if (n > 0) { return 1; } }",   # falta el else
        "function f(n: integer): integer { while (n > 0) { return 1; } }",
    ],
)
def test_e308_no_todos_los_caminos_retornan(source):
    assert_error(source, "E308")


def test_e308_todos_los_caminos_retornan():
    assert_ok(
        """
        function clasificar(n: integer): string {
          if (n < 0) {
            return "negativo";
          } else {
            if (n == 0) { return "cero"; } else { return "positivo"; }
          }
        }
        """
    )


# ---------------------------------------------------------------------------
# E306 — no hay sobrecarga
# ---------------------------------------------------------------------------

def test_e306_nombres_distintos_validos():
    assert_ok(
        "function f(a: integer): integer { return a; } "
        "function g(a: string): integer { return 1; }"
    )


@pytest.mark.parametrize(
    "source",
    [
        "function f(): integer { return 1; } function f(): integer { return 2; }",
        "function f(a: integer): integer { return a; } "
        "function f(a: string): integer { return 1; }",   # misma firma distinta: sigue sin valer
    ],
)
def test_e306_funcion_duplicada(source):
    assert_error(source, "E306")


def test_e306_funciones_homonimas_en_ambitos_distintos_son_validas():
    assert_ok(
        """
        function externa(): integer {
          function interna(): integer { return 1; }
          return interna();
        }
        function interna(): integer { return 2; }
        """
    )


# ---------------------------------------------------------------------------
# E307 / E310 — parámetros
# ---------------------------------------------------------------------------

def test_e307_parametros_distintos_validos():
    assert_ok("function f(a: integer, b: integer): integer { return a + b; }")


def test_e307_parametro_duplicado():
    assert_error("function f(a: integer, a: integer): integer { return a; }", "E307")


def test_e310_parametro_con_tipo_valido():
    assert_ok("function f(a: integer): integer { return a; }")


def test_e310_parametro_sin_tipo():
    assert_error("function f(a): integer { return 1; }", "E310")


# ---------------------------------------------------------------------------
# E309 — una función no es un valor
# ---------------------------------------------------------------------------

def test_e309_funcion_invocada_correctamente():
    assert_ok("function f(): integer { return 1; } let x: integer = f();")


@pytest.mark.parametrize(
    "source",
    [
        "function f(): integer { return 1; } let x = f;",
        "function f(): integer { return 1; } let x = f * 2;",
        "function f(): integer { return 1; } print(f);",
    ],
)
def test_e309_funcion_usada_como_valor(source):
    assert_error(source, "E309")


# ---------------------------------------------------------------------------
# Recursión
# ---------------------------------------------------------------------------

def test_recursion_directa_permitida_y_detectada():
    result = assert_ok(
        """
        function factorial(n: integer): integer {
          if (n <= 1) { return 1; }
          return n * factorial(n - 1);
        }
        """
    )
    factorial = result.symbol_table.global_scope.resolve_local("factorial")
    assert factorial.is_recursive is True


def test_recursion_mutua_permitida():
    assert_ok(
        """
        function esPar(n: integer): boolean {
          if (n == 0) { return true; }
          return esImpar(n - 1);
        }
        function esImpar(n: integer): boolean {
          if (n == 0) { return false; }
          return esPar(n - 1);
        }
        """
    )


# ---------------------------------------------------------------------------
# Funciones anidadas y closures
# ---------------------------------------------------------------------------

def test_funcion_anidada_ve_el_entorno_donde_se_define():
    assert_ok(
        """
        function externa(inicio: integer): integer {
          let base: integer = inicio * 10;
          function interna(paso: integer): integer { return base + paso + inicio; }
          return interna(1);
        }
        """
    )


def test_las_variables_capturadas_quedan_registradas():
    result = assert_ok(
        """
        function externa(a: integer): integer {
          let b: integer = 1;
          function interna(c: integer): integer { return a + b + c; }
          return interna(2);
        }
        """
    )
    externa = result.symbol_table.global_scope.resolve_local("externa")
    interna = externa.body_scope.resolve_local("interna")
    assert set(interna.captures) == {"a", "b"}
    assert externa.body_scope.resolve_local("a").captured is True
    assert externa.body_scope.resolve_local("b").captured is True


def test_captura_a_traves_de_dos_niveles_de_anidamiento():
    result = assert_ok(
        """
        function nivel1(a: integer): integer {
          function nivel2(b: integer): integer {
            function nivel3(c: integer): integer { return a + b + c; }
            return nivel3(3);
          }
          return nivel2(2);
        }
        """
    )
    nivel1 = result.symbol_table.global_scope.resolve_local("nivel1")
    nivel2 = nivel1.body_scope.resolve_local("nivel2")
    nivel3 = nivel2.body_scope.resolve_local("nivel3")
    assert set(nivel3.captures) == {"a", "b"}
    assert set(nivel2.captures) == {"a"}


def test_la_funcion_anidada_no_es_visible_desde_fuera():
    assert_error(
        "function externa(): integer { function interna(): integer { return 1; } "
        "return interna(); } print(interna());",
        "E201",
    )
