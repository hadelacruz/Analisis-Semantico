"""Ejecución del ensamblador MIPS generado.

Componente de 60 puntos del enunciado. Estos son los tests que demuestran que
el código máquina **funciona**: se compila hasta `.asm`, se ejecuta y se
comprueba el resultado.

El emulador parsea el mismo texto que recibiría MARS, así que lo que se valida
aquí es el artefacto real, no una estructura interna.
"""
import pytest

from conftest import ejecutar_mips, ejecutar_mips_con_fallo

pytestmark = [pytest.mark.mips, pytest.mark.simulador]


# ---------------------------------------------------------------------------
# Aritmetica entera
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("fuente", "esperado"),
    [
        ("print(1 + 2);", "3"),
        ("print(10 - 3 * 2);", "4"),
        ("print((2 + 3) * 4);", "20"),
        ("print(7 / 2);", "3"),
        ("print(-7 / 2);", "-3"),
        ("print(7 % 3);", "1"),
        ("print(-5 + 3);", "-2"),
        ("print(-(3 * 4));", "-12"),
        ("print(2 + 3 * 4 - 6 / 2);", "11"),
        ("print(1000000 * 2);", "2000000"),
    ],
)
def test_aritmetica_entera(fuente, esperado):
    assert ejecutar_mips(fuente) == [esperado]


# ---------------------------------------------------------------------------
# Punto flotante (doble precision)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("fuente", "esperado"),
    [
        ("print(1.5 + 2.5);", "4"),
        ("print(7.0 / 2);", "3.5"),
        ("print(2 * 1.5);", "3"),
        ("print(3.14159);", "3.14159"),
        ("print(-2.5);", "-2.5"),
        ("print(0.1 + 0.2);", "0.3"),
        ("const IVA: float = 0.12; print(100.0 * (1 + IVA));", "112"),
        ("print(1.0 / 3.0);", "0.333333"),
    ],
)
def test_aritmetica_flotante(fuente, esperado):
    assert ejecutar_mips(fuente) == [esperado]


def test_comparaciones_entre_flotantes():
    fuente = "let a: float = 1.5; let b: float = 2.5; print(a < b); print(a > b); print(a == a);"
    assert ejecutar_mips(fuente) == ["true", "false", "true"]


def test_comparacion_entre_entero_y_flotante():
    assert ejecutar_mips("let n: integer = 2; print(n < 2.5);") == ["true"]


# ---------------------------------------------------------------------------
# Logica y comparaciones
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("fuente", "esperado"),
    [
        ("print(1 < 2);", "true"),
        ("print(2 <= 2);", "true"),
        ("print(3 == 4);", "false"),
        ("print(3 != 4);", "true"),
        ("print(true && false);", "false"),
        ("print(true || false);", "true"),
        ("print(!true);", "false"),
        ("print(!(1 > 2));", "true"),
    ],
)
def test_logica(fuente, esperado):
    assert ejecutar_mips(fuente) == [esperado]


def test_el_cortocircuito_se_conserva_en_mips():
    """Si evaluara el segundo operando, el programa abortaria."""
    fuente = 'let n: integer = 0; if (n != 0 && 10 / n > 1) { print("si"); } else { print("no"); }'
    assert ejecutar_mips(fuente) == ["no"]


# ---------------------------------------------------------------------------
# Cadenas
# ---------------------------------------------------------------------------

def test_cadenas_y_concatenacion():
    assert ejecutar_mips('print("hola" + " " + "mundo");') == ["hola mundo"]
    assert ejecutar_mips('let n: integer = 7; print("n = " + n + "!");') == ["n = 7!"]
    assert ejecutar_mips('print("ok = " + true);') == ["ok = true"]
    assert ejecutar_mips('let f: float = 2.5; print("f = " + f);') == ["f = 2.5"]


def test_comparacion_de_cadenas():
    fuente = 'print("abc" == "abc"); print("abc" == "abd"); print("abc" < "abd"); print("b" > "a");'
    assert ejecutar_mips(fuente) == ["true", "false", "true", "true"]


def test_una_cadena_nula_se_imprime_como_null():
    assert ejecutar_mips("let s: string = null; print(s);") == ["null"]
    assert ejecutar_mips('let s: string = null; print("v=" + s);') == ["v=null"]


def test_concatenacion_larga():
    fuente = 'let s: string = ""; for (let i: integer = 0; i < 5; i = i + 1) { s = s + i; } print(s);'
    assert ejecutar_mips(fuente) == ["01234"]


# ---------------------------------------------------------------------------
# Control de flujo
# ---------------------------------------------------------------------------

def test_if_else():
    assert ejecutar_mips('let a: integer = 1; if (a > 0) { print("pos"); } else { print("neg"); }') == ["pos"]
    assert ejecutar_mips('let a: integer = -1; if (a > 0) { print("pos"); } else { print("neg"); }') == ["neg"]


def test_while():
    fuente = "let s: integer = 0; let i: integer = 1; while (i <= 10) { s = s + i; i = i + 1; } print(s);"
    assert ejecutar_mips(fuente) == ["55"]


def test_do_while_se_ejecuta_al_menos_una_vez():
    assert ejecutar_mips("let i: integer = 10; do { print(i); i = i + 1; } while (i < 3);") == ["10"]


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
    assert ejecutar_mips(fuente) == ["16"]


def test_bucles_anidados():
    fuente = """
    let total: integer = 0;
    for (let i: integer = 1; i <= 3; i = i + 1) {
      for (let j: integer = 1; j <= 3; j = j + 1) { total = total + i * j; }
    }
    print(total);
    """
    assert ejecutar_mips(fuente) == ["36"]


def test_switch_con_cascada():
    fuente = 'let n: integer = 1; switch (n) { case 1: print("uno"); case 2: print("dos"); default: print("otro"); }'
    assert ejecutar_mips(fuente) == ["uno", "dos", "otro"]


def test_switch_con_break():
    fuente = 'let n: integer = 1; switch (n) { case 1: print("uno"); break; case 2: print("dos"); }'
    assert ejecutar_mips(fuente) == ["uno"]


def test_ternario():
    assert ejecutar_mips('let x: integer = 7; print(x > 5 ? "grande" : "chico");') == ["grande"]


# ---------------------------------------------------------------------------
# Funciones
# ---------------------------------------------------------------------------

def test_factorial():
    fuente = "function f(n: integer): integer { if (n <= 1) { return 1; } return n * f(n - 1); } print(f(10));"
    assert ejecutar_mips(fuente) == ["3628800"]


def test_fibonacci():
    fuente = "function fib(n: integer): integer { if (n < 2) { return n; } return fib(n-1) + fib(n-2); } print(fib(15));"
    assert ejecutar_mips(fuente) == ["610"]


def test_procedimiento_sin_retorno():
    assert ejecutar_mips('function saluda(q: string) { print("hola " + q); } saluda("mundo");') == ["hola mundo"]


def test_funcion_que_devuelve_un_arreglo():
    fuente = """
    function crear(n: integer): integer[] { let r: integer[] = [n, n * 2, n * 3]; return r; }
    let xs: integer[] = crear(2);
    print(xs[0] + xs[1] + xs[2]);
    """
    assert ejecutar_mips(fuente) == ["12"]


# ---------------------------------------------------------------------------
# Closures
# ---------------------------------------------------------------------------

def test_closure_lee_el_entorno_exterior():
    fuente = """
    function externa(base: integer): integer {
      let extra: integer = 5;
      function interna(x: integer): integer { return base + extra + x; }
      return interna(1);
    }
    print(externa(10));
    """
    assert ejecutar_mips(fuente) == ["16"]


def test_closure_escribe_en_el_entorno_exterior():
    fuente = """
    function contador(): integer {
      let n: integer = 0;
      function sumar(): integer { n = n + 1; return n; }
      sumar(); sumar();
      return sumar();
    }
    print(contador());
    """
    assert ejecutar_mips(fuente) == ["3"]


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
    assert ejecutar_mips(fuente) == ["6"]


# ---------------------------------------------------------------------------
# Clases, herencia y despacho dinamico
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
class Perro : Animal { function sonido(): string { return "guau"; } }
class Cachorro : Perro { function sonido(): string { return "yip"; } }
"""


def test_atributos_y_metodos():
    assert ejecutar_mips(
        JERARQUIA + 'let a: Animal = new Animal("gato", 4); print(a.describir());'
    ) == ["gato con 4 patas"]


def test_el_despacho_es_dinamico():
    assert ejecutar_mips(JERARQUIA + 'let a: Animal = new Perro("Rex", 4); print(a.sonido());') == ["guau"]


def test_despacho_en_toda_la_cadena():
    fuente = JERARQUIA + """
    let zoo: Animal[] = [new Animal("a", 4), new Perro("b", 4), new Cachorro("c", 4)];
    foreach (bicho in zoo) { print(bicho.sonido()); }
    """
    assert ejecutar_mips(fuente) == ["...", "guau", "yip"]


def test_los_objetos_son_independientes():
    fuente = JERARQUIA + """
    let uno: Perro = new Perro("uno", 4);
    let dos: Perro = new Perro("dos", 2);
    print(uno.nombre + "/" + uno.patas + " " + dos.nombre + "/" + dos.patas);
    """
    assert ejecutar_mips(fuente) == ["uno/4 dos/2"]


def test_escribir_un_atributo():
    fuente = JERARQUIA + 'let p: Perro = new Perro("Rex", 4); p.patas = 3; print(p.describir());'
    assert ejecutar_mips(fuente) == ["Rex con 3 patas"]


def test_un_metodo_llama_a_otro_de_la_misma_clase():
    fuente = """
    class C {
      let n: integer;
      function constructor(n: integer) { this.n = n; }
      function doble(): integer { return this.n * 2; }
      function cuadruple(): integer { return this.doble() * 2; }
    }
    print(new C(3).cuadruple());
    """
    assert ejecutar_mips(fuente) == ["12"]


def test_atributos_con_valor_inicial():
    fuente = """
    class A { let x: integer = 1; }
    class B : A { let y: integer = 2; function suma(): integer { return this.x + this.y; } }
    print(new B().suma());
    """
    assert ejecutar_mips(fuente) == ["3"]


# ---------------------------------------------------------------------------
# Arreglos
# ---------------------------------------------------------------------------

def test_lectura_y_escritura():
    assert ejecutar_mips("let xs: integer[] = [10, 20, 30]; xs[1] = 99; print(xs[0] + xs[1] + xs[2]);") == ["139"]


def test_indice_calculado():
    assert ejecutar_mips("let xs: integer[] = [5, 6, 7]; let i: integer = 1; print(xs[i] + xs[i + 1]);") == ["13"]


def test_matrices():
    assert ejecutar_mips("let m: integer[][] = [[1, 2], [3, 4]]; print(m[1][0]); m[0][1] = 9; print(m[0][1]);") == ["3", "9"]


def test_foreach():
    assert ejecutar_mips("let xs: integer[] = [1, 2, 3]; foreach (v in xs) { print(v * 10); }") == ["10", "20", "30"]


def test_arreglo_de_flotantes():
    assert ejecutar_mips("let xs: float[] = [1.5, 2.5, 3.5]; print(xs[0] + xs[2]);") == ["5"]


def test_arreglo_de_cadenas():
    assert ejecutar_mips('let xs: string[] = ["a", "b"]; foreach (s in xs) { print(s + "!"); }') == ["a!", "b!"]


# ---------------------------------------------------------------------------
# Excepciones
# ---------------------------------------------------------------------------

def test_indice_fuera_de_rango_se_atrapa():
    fuente = 'let xs: integer[] = [1, 2]; try { print(xs[9]); } catch (e) { print("error: " + e); }'
    assert ejecutar_mips(fuente) == ["error: indice 9 fuera del rango del arreglo (0..1)"]


def test_division_entre_cero_se_atrapa():
    assert ejecutar_mips("let n: integer = 0; try { print(10 / n); } catch (e) { print(e); }") == ["division entre cero"]


def test_el_programa_continua_tras_el_catch():
    fuente = """
    let xs: integer[] = [1];
    try { print(xs[5]); } catch (e) { print("atrapado"); }
    print("sigo aqui");
    """
    assert ejecutar_mips(fuente) == ["atrapado", "sigo aqui"]


def test_una_excepcion_dentro_de_una_funcion_llega_al_catch_del_llamador():
    fuente = """
    function riesgosa(xs: integer[]): integer { return xs[100]; }
    let xs: integer[] = [1];
    try { print(riesgosa(xs)); } catch (e) { print("atrapado en el llamador"); }
    """
    assert ejecutar_mips(fuente) == ["atrapado en el llamador"]


def test_una_excepcion_sin_manejador_detiene_el_programa():
    fuente = 'let xs: integer[] = [1]; print("antes"); print(xs[9]);'
    salida = ejecutar_mips(fuente)
    assert salida[0] == "antes"
    assert salida[1].startswith("Excepcion no atrapada:")


# ---------------------------------------------------------------------------
# Casos fallidos
# ---------------------------------------------------------------------------

def test_un_bucle_infinito_se_detiene_en_vez_de_colgar():
    from conftest import compilar_mips

    resultado = compilar_mips("let i: integer = 0; while (i >= 0) { i = i + 1; }")
    _, fallo = resultado.run_mips(max_pasos=5000)
    assert fallo is not None and "limite de pasos" in fallo


def test_el_emulador_rechaza_una_instruccion_que_no_conoce():
    from compiscript.mips.emulator import MipsError, run

    with pytest.raises(MipsError, match="no soportada"):
        run("    .text\nmain:\n    inventada $t0, $t1\n")


def test_el_emulador_detecta_un_salto_a_una_etiqueta_inexistente():
    from compiscript.mips.emulator import MipsError, run

    with pytest.raises(MipsError, match="etiqueta inexistente"):
        run("    .text\nmain:\n    j no_existe\n")


def test_el_emulador_avisa_si_no_hay_punto_de_entrada():
    from compiscript.mips.emulator import MipsError, run

    with pytest.raises(MipsError, match="entrada"):
        run("    .text\notra:\n    li $v0, 10\n    syscall\n")


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
    assert ejecutar_mips(fuente) == ["teclado", "mouse (oferta)", "168"]
