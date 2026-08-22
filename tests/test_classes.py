"""Clases y objetos (E5xx) — enunciado, sección 2.5."""
import pytest

from conftest import assert_error, assert_ok, check

pytestmark = pytest.mark.clases

ANIMAL = """
class Animal {
  let nombre: string;
  let patas: integer;

  function constructor(nombre: string, patas: integer) {
    this.nombre = nombre;
    this.patas = patas;
  }

  function describir(): string { return this.nombre; }
}
"""


# ---------------------------------------------------------------------------
# E501 — la clase debe existir
# ---------------------------------------------------------------------------

def test_e501_instanciacion_valida():
    assert_ok(ANIMAL + 'let a: Animal = new Animal("Rex", 4);')


def test_e501_herencia_valida():
    assert_ok(ANIMAL + "class Perro : Animal { } " + 'let p: Perro = new Perro("Rex", 4);')


@pytest.mark.parametrize(
    "source",
    ["let x = new NoExiste();", "class Perro : NoExiste { }"],
)
def test_e501_clase_inexistente(source):
    assert_error(source, "E501")


# ---------------------------------------------------------------------------
# E502 — existencia de atributos y métodos con notación de punto
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        ANIMAL + 'let a: Animal = new Animal("Rex", 4); print(a.nombre);',
        ANIMAL + 'let a: Animal = new Animal("Rex", 4); print(a.describir());',
        ANIMAL + "class Perro : Animal { } "
                 'let p: Perro = new Perro("Rex", 4); print(p.nombre + p.describir());',
        ANIMAL + "class Perro : Animal { function ladrar(): string { return this.nombre; } } "
                 'let p: Perro = new Perro("Rex", 4); print(p.ladrar());',
    ],
)
def test_e502_acceso_valido(source):
    assert_ok(source)


@pytest.mark.parametrize(
    "source",
    [
        ANIMAL + 'let a: Animal = new Animal("Rex", 4); print(a.noExiste);',
        ANIMAL + 'let a: Animal = new Animal("Rex", 4); print(a.volar());',
        ANIMAL + 'let a: Animal = new Animal("Rex", 4); a.noExiste = 1;',
        ANIMAL + 'let a: Animal = new Animal("Rex", 4); a.describir = 1;',  # no se asigna a un metodo
    ],
)
def test_e502_miembro_inexistente(source):
    assert_error(source, "E502")


def test_e502_la_superclase_no_ve_los_miembros_de_la_subclase():
    source = (
        ANIMAL
        + "class Perro : Animal { function ladrar(): string { return \"guau\"; } }"
        + 'let a: Animal = new Perro("Rex", 4); print(a.ladrar());'
    )
    assert_error(source, "E502")


# ---------------------------------------------------------------------------
# E503 — 'this' dentro de un método
# ---------------------------------------------------------------------------

def test_e503_this_valido():
    assert_ok(ANIMAL)


def test_e503_this_en_funcion_anidada_dentro_de_un_metodo():
    assert_ok(
        """
        class C {
          let x: integer;
          function m(): integer {
            function interna(): integer { return 1; }
            return this.x + interna();
          }
        }
        """
    )


@pytest.mark.parametrize(
    "source",
    ["print(this);", "function f(): integer { return 1; } print(this);", "this.x = 1;"],
)
def test_e503_this_fuera_de_una_clase(source):
    assert_error(source, "E503")


# ---------------------------------------------------------------------------
# E504 — llamada correcta al constructor
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        ANIMAL + 'let a: Animal = new Animal("Rex", 4);',
        "class SinCtor { let x: integer; } let s: SinCtor = new SinCtor();",
        ANIMAL + "class Perro : Animal { } " + 'let p: Perro = new Perro("Rex", 4);',
    ],
)
def test_e504_constructor_valido(source):
    assert_ok(source)


@pytest.mark.parametrize(
    "source",
    [
        ANIMAL + "let a: Animal = new Animal();",
        ANIMAL + 'let a: Animal = new Animal("Rex");',
        ANIMAL + 'let a: Animal = new Animal("Rex", 4, 1);',
        "class SinCtor { } let s: SinCtor = new SinCtor(1);",
    ],
)
def test_e504_constructor_con_argumentos_incorrectos(source):
    assert_error(source, "E504")


def test_e302_tipos_de_los_argumentos_del_constructor():
    assert_error(ANIMAL + 'let a: Animal = new Animal(4, "Rex");', "E302")


# ---------------------------------------------------------------------------
# E505 — herencia cíclica
# ---------------------------------------------------------------------------

def test_e505_jerarquia_lineal_valida():
    assert_ok("class A { } class B : A { } class C : B { }")


@pytest.mark.parametrize(
    "source",
    ["class A : B { } class B : A { }", "class A : B { } class B : C { } class C : A { }"],
)
def test_e505_herencia_ciclica(source):
    assert_error(source, "E505")


# ---------------------------------------------------------------------------
# E506 — miembros duplicados
# ---------------------------------------------------------------------------

def test_e506_miembros_distintos_validos():
    assert_ok("class C { let a: integer; let b: integer; function m(): integer { return 1; } }")


@pytest.mark.parametrize(
    "source",
    [
        "class C { let x: integer; let x: integer; }",
        "class C { function m(): integer { return 1; } function m(): integer { return 2; } }",
        "class C { let x: integer; function x(): integer { return 1; } }",
        "class A { let x: integer; } class B : A { let x: integer; }",   # oculta al heredado
    ],
)
def test_e506_miembro_duplicado(source):
    assert_error(source, "E506")


# ---------------------------------------------------------------------------
# E507 — el '.' sólo se aplica a objetos
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        "let n: integer = 1; print(n.algo);",
        'let s: string = "x"; print(s.length);',
        "let xs: integer[] = [1]; print(xs.size);",
        "let n: integer = 1; n.algo = 2;",
    ],
)
def test_e507_punto_sobre_algo_que_no_es_objeto(source):
    assert_error(source, "E507")


# ---------------------------------------------------------------------------
# E508 — sobrescritura compatible
# ---------------------------------------------------------------------------

def test_e508_sobrescritura_valida():
    assert_ok(
        """
        class Base { function f(a: integer): string { return "base"; } }
        class Derivada : Base { function f(a: integer): string { return "derivada"; } }
        """
    )


@pytest.mark.parametrize(
    "source",
    [
        "class Base { function f(a: integer): integer { return a; } } "
        "class Derivada : Base { function f(a: string): integer { return 1; } }",
        "class Base { function f(): integer { return 1; } } "
        "class Derivada : Base { function f(): string { return \"x\"; } }",
        "class Base { function f(a: integer): integer { return a; } } "
        "class Derivada : Base { function f(): integer { return 1; } }",
    ],
)
def test_e508_sobrescritura_con_firma_distinta(source):
    assert_error(source, "E508")


# ---------------------------------------------------------------------------
# Tipos de los atributos, herencia y layout de la instancia
# ---------------------------------------------------------------------------

def test_asignacion_a_atributo_respeta_su_tipo():
    assert_ok(ANIMAL + 'let a: Animal = new Animal("Rex", 4); a.patas = 2;')
    assert_error(ANIMAL + 'let a: Animal = new Animal("Rex", 4); a.patas = "dos";', "E105")


def test_this_respeta_el_tipo_del_atributo():
    assert_error(
        "class C { let x: integer; function m() { this.x = \"texto\"; } }",
        "E105",
    )


def test_layout_de_la_instancia_con_herencia():
    result = assert_ok(
        """
        class Base { let a: integer; let b: integer; }
        class Derivada : Base { let c: integer; }
        """
    )
    base = result.symbol_table.global_scope.resolve_local("Base")
    derivada = result.symbol_table.global_scope.resolve_local("Derivada")

    assert base.fields["a"].offset == 0
    assert base.fields["b"].offset == 4
    assert base.instance_size == 8
    # Los atributos propios continúan tras los heredados.
    assert derivada.fields["c"].offset == 8
    assert derivada.instance_size == 12


def test_la_vtable_registra_los_metodos_heredados_y_sobrescritos():
    result = assert_ok(
        """
        class Base { function f(): integer { return 1; } function g(): integer { return 2; } }
        class Derivada : Base { function f(): integer { return 3; } }
        """
    )
    derivada = result.symbol_table.global_scope.resolve_local("Derivada")
    assert derivada.vtable["f"] == "Derivada_f"   # sobrescrito
    assert derivada.vtable["g"] == "Base_g"       # heredado


def test_metodo_llamado_sin_this_dentro_de_la_clase():
    assert_ok(
        """
        class C {
          let x: integer;
          function ayuda(): integer { return 1; }
          function m(): integer { return ayuda() + x; }
        }
        """
    )
