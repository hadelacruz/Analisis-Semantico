"""Ejecución del código intermedio en la máquina virtual.

Estos son los tests que de verdad demuestran que la traducción es correcta:
no comprueban que el TAC *se parezca* a lo esperado, sino que **al ejecutarlo
produce el resultado correcto**. Si un desplazamiento, una ranura de la tabla
de métodos o un enlace de acceso estuviera mal calculado, el programa daría
otro número y el test fallaría.
"""
import pytest

from conftest import ejecutar, ejecutar_con_fallo

pytestmark = [pytest.mark.tac, pytest.mark.vm]


# ---------------------------------------------------------------------------
# Expresiones y tipos
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("fuente", "esperado"),
    [
        ("print(1 + 2);", "3"),
        ("print(10 - 3 * 2);", "4"),
        ("print((2 + 3) * 4);", "20"),
        ("print(7 / 2);", "3"),               # division entera
        ("print(7 % 3);", "1"),
        ("print(-5 + 3);", "-2"),
        ("print(2 + 3 * 4 - 6 / 2);", "11"),  # precedencia completa
    ],
)
def test_aritmetica_entera(fuente, esperado):
    assert ejecutar(fuente) == [esperado]


@pytest.mark.parametrize(
    ("fuente", "esperado"),
    [
        ("print(1.5 + 2.5);", "4"),
        ("print(7.0 / 2);", "3.5"),
        ("print(2 * 1.5);", "3"),             # integer se ensancha a float
        ("const IVA: float = 0.12; print(100.0 * (1 + IVA));", "112"),
    ],
)
def test_aritmetica_con_flotantes(fuente, esperado):
    assert ejecutar(fuente) == [esperado]


@pytest.mark.parametrize(
    ("fuente", "esperado"),
    [
        ("print(1 < 2);", "true"),
        ("print(2 <= 2);", "true"),
        ("print(3 == 4);", "false"),
        ("print(3 != 4);", "true"),
        ('print("abc" < "abd");', "true"),
        ("print(true && false);", "false"),
        ("print(true || false);", "true"),
        ("print(!true);", "false"),
    ],
)
def test_comparaciones_y_logica(fuente, esperado):
    assert ejecutar(fuente) == [esperado]


def test_el_cortocircuito_no_evalua_el_segundo_operando():
    """Si evaluara la division, el programa abortaria por division entre cero."""
    fuente = "let n: integer = 0; if (n != 0 && 10 / n > 1) { print(\"si\"); } else { print(\"no\"); }"
    assert ejecutar(fuente) == ["no"]


def test_cadenas_y_concatenacion():
    assert ejecutar('print("hola" + " " + "mundo");') == ["hola mundo"]
    assert ejecutar('let n: integer = 7; print("n = " + n + "!");') == ["n = 7!"]
    assert ejecutar('print("ok = " + true);') == ["ok = true"]
    assert ejecutar('let f: float = 2.5; print("f = " + f);') == ["f = 2.5"]


def test_ternario():
    assert ejecutar('let x: integer = 7; print(x > 5 ? "grande" : "chico");') == ["grande"]
    assert ejecutar('let x: integer = 2; print(x > 5 ? "grande" : "chico");') == ["chico"]


# ---------------------------------------------------------------------------
# Control de flujo
# ---------------------------------------------------------------------------

def test_if_else():
    assert ejecutar('let a: integer = 1; if (a > 0) { print("pos"); } else { print("neg"); }') == ["pos"]
    assert ejecutar('let a: integer = -1; if (a > 0) { print("pos"); } else { print("neg"); }') == ["neg"]


def test_while_acumula():
    assert ejecutar("let s: integer = 0; let i: integer = 1; while (i <= 5) { s = s + i; i = i + 1; } print(s);") == ["15"]


def test_do_while_se_ejecuta_al_menos_una_vez():
    assert ejecutar("let i: integer = 10; do { print(i); i = i + 1; } while (i < 3);") == ["10"]


def test_for_con_break_y_continue():
    fuente = """
    let s: integer = 0;
    for (let i: integer = 0; i < 10; i = i + 1) {
      if (i % 2 == 0) { continue; }
      if (i > 7) { break; }
      s = s + i;
    }
    print(s);
    """
    assert ejecutar(fuente) == ["16"]      # 1 + 3 + 5 + 7


def test_bucles_anidados():
    fuente = """
    let total: integer = 0;
    for (let i: integer = 1; i <= 3; i = i + 1) {
      for (let j: integer = 1; j <= 3; j = j + 1) {
        total = total + i * j;
      }
    }
    print(total);
    """
    assert ejecutar(fuente) == ["36"]      # (1+2+3) * (1+2+3)


def test_el_switch_cae_al_siguiente_caso():
    fuente = 'let n: integer = 1; switch (n) { case 1: print("uno"); case 2: print("dos"); default: print("otro"); }'
    assert ejecutar(fuente) == ["uno", "dos", "otro"]


def test_el_break_corta_la_cascada_del_switch():
    fuente = 'let n: integer = 1; switch (n) { case 1: print("uno"); break; case 2: print("dos"); }'
    assert ejecutar(fuente) == ["uno"]


def test_el_switch_usa_default_cuando_nada_coincide():
    fuente = 'let n: integer = 9; switch (n) { case 1: print("uno"); break; default: print("otro"); }'
    assert ejecutar(fuente) == ["otro"]


# ---------------------------------------------------------------------------
# Funciones
# ---------------------------------------------------------------------------

def test_factorial_recursivo():
    fuente = "function f(n: integer): integer { if (n <= 1) { return 1; } return n * f(n - 1); } print(f(5));"
    assert ejecutar(fuente) == ["120"]


def test_fibonacci_recursivo():
    fuente = "function fib(n: integer): integer { if (n < 2) { return n; } return fib(n-1) + fib(n-2); } print(fib(10));"
    assert ejecutar(fuente) == ["55"]


def test_recursion_mutua():
    fuente = """
    function par(n: integer): boolean { if (n == 0) { return true; } return impar(n - 1); }
    function impar(n: integer): boolean { if (n == 0) { return false; } return par(n - 1); }
    print(par(10)); print(impar(10));
    """
    assert ejecutar(fuente) == ["true", "false"]


def test_los_parametros_no_se_pisan_entre_llamadas():
    """Cada llamada usa su propio registro de activacion."""
    fuente = """
    function suma(a: integer, b: integer): integer { return a + b; }
    print(suma(suma(1, 2), suma(3, 4)));
    """
    assert ejecutar(fuente) == ["10"]


def test_procedimiento_sin_retorno():
    assert ejecutar('function saluda(q: string) { print("hola " + q); } saluda("mundo");') == ["hola mundo"]


def test_funcion_que_devuelve_un_arreglo():
    fuente = """
    function crear(n: integer): integer[] { let r: integer[] = [n, n * 2, n * 3]; return r; }
    let xs: integer[] = crear(2);
    print(xs[0] + xs[1] + xs[2]);
    """
    assert ejecutar(fuente) == ["12"]


# ---------------------------------------------------------------------------
# Closures
# ---------------------------------------------------------------------------

def test_una_funcion_anidada_lee_el_entorno_donde_se_definio():
    fuente = """
    function externa(base: integer): integer {
      let extra: integer = 5;
      function interna(x: integer): integer { return base + extra + x; }
      return interna(1);
    }
    print(externa(10));
    """
    assert ejecutar(fuente) == ["16"]


def test_el_closure_ve_el_valor_actualizado_de_lo_que_captura():
    fuente = """
    function contador(): integer {
      let n: integer = 0;
      function sumar(): integer { n = n + 1; return n; }
      sumar(); sumar();
      return sumar();
    }
    print(contador());
    """
    assert ejecutar(fuente) == ["3"]


def test_captura_a_traves_de_tres_niveles():
    fuente = """
    function n1(a: integer): integer {
      function n2(b: integer): integer {
        function n3(c: integer): integer { return a + b + c; }
        return n3(3);
      }
      return n2(2);
    }
    print(n1(1));
    """
    assert ejecutar(fuente) == ["6"]


def test_varias_llamadas_al_closure_con_el_mismo_entorno():
    fuente = """
    function acumulador(inicial: integer): integer {
      let acumulado: integer = inicial;
      function agregar(c: integer): integer { return acumulado + c + inicial; }
      return agregar(10) + agregar(20);
    }
    print(acumulador(1));
    """
    assert ejecutar(fuente) == ["34"]


# ---------------------------------------------------------------------------
# Clases, herencia y despacho dinámico
# ---------------------------------------------------------------------------

JERARQUIA = """
class Animal {
  let nombre: string;
  let patas: integer;
  function constructor(nombre: string, patas: integer) {
    this.nombre = nombre;
    this.patas = patas;
  }
  function describir(): string { return this.nombre + " con " + this.patas + " patas"; }
  function sonido(): string { return "..."; }
}
class Perro : Animal {
  function sonido(): string { return "guau"; }
}
class Cachorro : Perro {
  function sonido(): string { return "yip"; }
}
"""


def test_atributos_y_metodos_propios():
    fuente = JERARQUIA + 'let a: Animal = new Animal("gato", 4); print(a.describir());'
    assert ejecutar(fuente) == ["gato con 4 patas"]


def test_el_despacho_es_dinamico_no_estatico():
    """La variable es de tipo Animal pero el objeto es un Perro."""
    fuente = JERARQUIA + 'let a: Animal = new Perro("Rex", 4); print(a.sonido());'
    assert ejecutar(fuente) == ["guau"]


def test_el_despacho_funciona_en_toda_la_cadena_de_herencia():
    fuente = JERARQUIA + """
    let a: Animal = new Animal("x", 4);
    let p: Animal = new Perro("y", 4);
    let c: Animal = new Cachorro("z", 4);
    print(a.sonido()); print(p.sonido()); print(c.sonido());
    """
    assert ejecutar(fuente) == ["...", "guau", "yip"]


def test_un_metodo_heredado_se_ejecuta_sobre_la_subclase():
    fuente = JERARQUIA + 'let c: Cachorro = new Cachorro("Toby", 4); print(c.describir());'
    assert ejecutar(fuente) == ["Toby con 4 patas"]


def test_se_puede_escribir_un_atributo():
    fuente = JERARQUIA + """
    let p: Perro = new Perro("Rex", 4);
    p.patas = 3;
    print(p.describir());
    """
    assert ejecutar(fuente) == ["Rex con 3 patas"]


def test_arreglo_de_objetos_con_despacho_dinamico():
    fuente = JERARQUIA + """
    let zoo: Animal[] = [new Animal("a", 4), new Perro("b", 4), new Cachorro("c", 4)];
    foreach (bicho in zoo) { print(bicho.sonido()); }
    """
    assert ejecutar(fuente) == ["...", "guau", "yip"]


def test_los_objetos_son_independientes():
    fuente = JERARQUIA + """
    let uno: Perro = new Perro("uno", 4);
    let dos: Perro = new Perro("dos", 2);
    print(uno.nombre + "/" + uno.patas + " " + dos.nombre + "/" + dos.patas);
    """
    assert ejecutar(fuente) == ["uno/4 dos/2"]


def test_un_metodo_puede_llamar_a_otro_de_la_misma_clase():
    fuente = """
    class C {
      let n: integer;
      function constructor(n: integer) { this.n = n; }
      function doble(): integer { return this.n * 2; }
      function cuadruple(): integer { return this.doble() * 2; }
    }
    let c: C = new C(3); print(c.cuadruple());
    """
    assert ejecutar(fuente) == ["12"]


# ---------------------------------------------------------------------------
# Arreglos
# ---------------------------------------------------------------------------

def test_lectura_y_escritura_de_elementos():
    fuente = "let xs: integer[] = [10, 20, 30]; xs[1] = 99; print(xs[0] + xs[1] + xs[2]);"
    assert ejecutar(fuente) == ["139"]      # 10 + 99 + 30


def test_indice_calculado():
    fuente = "let xs: integer[] = [5, 6, 7]; let i: integer = 1; print(xs[i] + xs[i + 1]);"
    assert ejecutar(fuente) == ["13"]


def test_matrices():
    fuente = "let m: integer[][] = [[1, 2], [3, 4]]; print(m[1][0]); m[0][1] = 9; print(m[0][1]);"
    assert ejecutar(fuente) == ["3", "9"]


def test_foreach_recorre_en_orden():
    assert ejecutar("let xs: integer[] = [1, 2, 3]; foreach (v in xs) { print(v * 10); }") == ["10", "20", "30"]


def test_foreach_sobre_una_matriz():
    fuente = "let m: integer[][] = [[1, 2], [3, 4]]; foreach (fila in m) { print(fila[0]); }"
    assert ejecutar(fuente) == ["1", "3"]


def test_arreglo_de_cadenas():
    fuente = 'let xs: string[] = ["a", "b"]; foreach (s in xs) { print(s + "!"); }'
    assert ejecutar(fuente) == ["a!", "b!"]


def test_arreglo_de_flotantes_usa_ocho_bytes_por_elemento():
    fuente = "let xs: float[] = [1.5, 2.5, 3.5]; print(xs[0] + xs[2]);"
    assert ejecutar(fuente) == ["5"]


# ---------------------------------------------------------------------------
# Excepciones
# ---------------------------------------------------------------------------

def test_un_indice_fuera_de_rango_se_atrapa():
    fuente = 'let xs: integer[] = [1, 2]; try { print(xs[9]); } catch (e) { print("error: " + e); }'
    salida = ejecutar(fuente)
    assert len(salida) == 1 and salida[0].startswith("error: indice 9 fuera del rango")


def test_la_division_entre_cero_se_atrapa():
    fuente = 'let n: integer = 0; try { print(10 / n); } catch (e) { print(e); }'
    assert ejecutar(fuente) == ["division entre cero"]


def test_el_programa_continua_despues_del_catch():
    fuente = """
    let xs: integer[] = [1];
    try { print(xs[5]); } catch (e) { print("atrapado"); }
    print("sigo aqui");
    """
    assert ejecutar(fuente) == ["atrapado", "sigo aqui"]


def test_sin_error_no_se_entra_al_catch():
    fuente = 'try { print("todo bien"); } catch (e) { print("no deberia"); }'
    assert ejecutar(fuente) == ["todo bien"]


def test_una_excepcion_dentro_de_una_funcion_llega_al_catch_del_llamador():
    fuente = """
    function riesgosa(xs: integer[]): integer { return xs[100]; }
    let xs: integer[] = [1];
    try { print(riesgosa(xs)); } catch (e) { print("atrapado en el llamador"); }
    """
    assert ejecutar(fuente) == ["atrapado en el llamador"]


def test_una_excepcion_sin_manejador_aborta_el_programa():
    salida, fallo = ejecutar_con_fallo('let xs: integer[] = [1]; print("antes"); print(xs[9]);')
    assert salida == ["antes"]
    assert "no atrapada" in fallo


# ---------------------------------------------------------------------------
# Ámbitos
# ---------------------------------------------------------------------------

def test_el_sombreado_en_un_bloque_no_afecta_al_exterior():
    fuente = 'let x: integer = 1; { let x: integer = 99; print(x); } print(x);'
    assert ejecutar(fuente) == ["99", "1"]


def test_una_variable_sin_inicializar_arranca_en_su_valor_neutro():
    assert ejecutar("let n: integer; print(n);") == ["0"]
    assert ejecutar("let b: boolean; print(b);") == ["false"]
    assert ejecutar("let s: string; print(s);") == ["null"]


# ---------------------------------------------------------------------------
# Programa integrador
# ---------------------------------------------------------------------------

def test_programa_completo():
    fuente = """
    const IVA: float = 0.12;

    class Producto {
      let nombre: string;
      let precio: float;
      function constructor(nombre: string, precio: float) {
        this.nombre = nombre;
        this.precio = precio;
      }
      function total(): float { return this.precio * (1 + IVA); }
      function etiqueta(): string { return this.nombre; }
    }

    class Oferta : Producto {
      function total(): float { return this.precio * (1 + IVA) / 2; }
      function etiqueta(): string { return this.nombre + " (oferta)"; }
    }

    function sumar(items: Producto[]): float {
      let acumulado: float = 0.0;
      foreach (item in items) { acumulado = acumulado + item.total(); }
      return acumulado;
    }

    let carrito: Producto[] = [
      new Producto("teclado", 100.0),
      new Oferta("mouse", 100.0)
    ];
    foreach (p in carrito) { print(p.etiqueta()); }
    print(sumar(carrito));
    """
    assert ejecutar(fuente) == ["teclado", "mouse (oferta)", "168"]


# ---------------------------------------------------------------------------
# Inicializadores de atributos
# ---------------------------------------------------------------------------

def test_un_atributo_con_valor_inicial_lo_recibe_al_construirse():
    fuente = """
    class C { let x: integer = 7; function leer(): integer { return this.x; } }
    let c: C = new C(); print(c.leer());
    """
    assert ejecutar(fuente) == ["7"]


def test_una_constante_de_clase_es_un_atributo_mas():
    fuente = """
    class C { const K: integer = 5; function leer(): integer { return this.K; } }
    let c: C = new C(); print(c.leer());
    """
    assert ejecutar(fuente) == ["5"]


def test_los_valores_iniciales_conviven_con_el_constructor():
    fuente = """
    class C {
      let a: integer = 1;
      let b: integer;
      function constructor(b: integer) { this.b = b; }
      function suma(): integer { return this.a + this.b; }
    }
    let c: C = new C(10); print(c.suma());
    """
    assert ejecutar(fuente) == ["11"]


def test_los_atributos_heredados_se_inicializan_primero():
    fuente = """
    class A { let x: integer = 1; }
    class B : A { let y: integer = 2; function suma(): integer { return this.x + this.y; } }
    let b: B = new B(); print(b.suma());
    """
    assert ejecutar(fuente) == ["3"]


def test_una_clase_sin_constructor_tambien_inicializa_sus_atributos():
    assert ejecutar('class C { let v: string = "hola"; } let c: C = new C(); print(c.v);') == ["hola"]


def test_el_valor_inicial_puede_ser_una_expresion():
    fuente = 'const BASE: integer = 10; class C { let v: integer = BASE * 2; } print(new C().v);'
    assert ejecutar(fuente) == ["20"]
