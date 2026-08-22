"""Listas y estructuras de datos (E6xx, W903) — enunciado, sección 2.6."""
import pytest

from conftest import assert_error, assert_ok, check

pytestmark = pytest.mark.listas


# ---------------------------------------------------------------------------
# E601 — el índice debe ser integer
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        "let xs: integer[] = [1, 2, 3]; print(xs[0]);",
        "let xs: integer[] = [1, 2, 3]; let i: integer = 1; print(xs[i]);",
        "let xs: integer[] = [1, 2, 3]; print(xs[1 + 1]);",
        "let m: integer[][] = [[1, 2], [3, 4]]; print(m[0][1]);",
    ],
)
def test_e601_indice_valido(source):
    assert_ok(source)


@pytest.mark.parametrize(
    "source",
    [
        'let xs: integer[] = [1]; print(xs["a"]);',
        "let xs: integer[] = [1]; print(xs[true]);",
        "let xs: integer[] = [1]; print(xs[1.5]);",
    ],
)
def test_e601_indice_no_entero(source):
    assert_error(source, "E601")


# ---------------------------------------------------------------------------
# E602 — sólo se indexan arreglos
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        "let n: integer = 1; print(n[0]);",
        'let s: string = "hola"; print(s[0]);',
        "class C {} let c: C = new C(); print(c[0]);",
        "let m: integer[] = [1]; print(m[0][0]);",   # integer no es indexable
    ],
)
def test_e602_indexar_algo_que_no_es_arreglo(source):
    assert_error(source, "E602")


# ---------------------------------------------------------------------------
# Tipado de los elementos
# ---------------------------------------------------------------------------

def test_el_tipo_del_elemento_es_el_del_arreglo():
    assert_ok("let xs: integer[] = [1, 2]; let a: integer = xs[0];")
    assert_error('let xs: integer[] = [1, 2]; let a: string = xs[0];', "E105")


def test_arreglos_multidimensionales():
    assert_ok(
        """
        let m: integer[][] = [[1, 2], [3, 4]];
        let fila: integer[] = m[0];
        let valor: integer = m[1][1];
        print(fila[0] + valor);
        """
    )
    assert_error("let m: integer[][] = [[1, 2]]; let fila: integer = m[0];", "E105")


def test_asignacion_a_un_elemento_del_arreglo():
    assert_ok("let xs: integer[] = [1, 2]; xs[0] = 99;")
    assert_error('let xs: integer[] = [1, 2]; xs[0] = "x";', "E105")


def test_arreglos_de_objetos():
    assert_ok(
        """
        class P { let n: integer; function constructor(n: integer) { this.n = n; } }
        let ps: P[] = [new P(1), new P(2)];
        print(ps[0].n);
        """
    )


def test_arreglo_como_parametro_y_como_retorno():
    assert_ok(
        """
        function suma(xs: integer[]): integer { return xs[0] + xs[1]; }
        function crear(n: integer): integer[] { let r: integer[] = [n, n]; return r; }
        print(suma(crear(2)));
        """
    )


# ---------------------------------------------------------------------------
# W903 — índice constante fuera del rango conocido
# ---------------------------------------------------------------------------

def test_w903_indice_dentro_de_rango_no_avisa():
    result = check("let xs: integer[] = [1, 2, 3]; print(xs[2]);")
    assert "W903" not in result.codes()


@pytest.mark.parametrize(
    "source",
    [
        "let xs: integer[] = [1, 2, 3]; print(xs[3]);",
        "let xs: integer[] = [1, 2, 3]; print(xs[99]);",
        "let xs: integer[] = [1]; print(xs[-1]);",
        "let xs: integer[] = []; print(xs[0]);",
    ],
)
def test_w903_indice_fuera_de_rango(source):
    result = check(source)
    assert "W903" in result.codes()
    # Es sólo una advertencia: el programa sigue siendo compilable.
    assert result.ok


def test_w903_no_avisa_si_la_longitud_no_se_conoce():
    source = """
    function traer(): integer[] { let r: integer[] = [1]; return r; }
    print(traer()[100]);
    """
    assert "W903" not in check(source).codes()
